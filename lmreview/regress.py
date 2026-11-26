"""Rule regression: after a rulebook changes, check that its rules still fix what their tests showed.

Users only see the default reviewer, so a rulebook edit (merge, generalize, rewrite) must not silently
break a rule that worked. Each entry keeps its A/B records in "tests" (distill.record_test); the
"corrected" ones are the entry's regression suite. Two layers, cheapest first:

1. text: one coverage call per changed entry. The rewritten text must still explain its evidence
   comments and the comments its tests corrected.
2. replay: re-review each corrected test target with the new rulebook (`reps` runs) and judge it. The
   entry passes a case if, in some run, every tested comment is matched by a finding citing the entry
   (or its principle, or for a principle one of its members).

`lmreview vet` (vet.py) checks a distill result as a whole and uses `replay` for its runs.

The third layer, a whole-book eval on test before promotion, is `lmreview eval` (docs/usage.md).
"""

from __future__ import annotations

import hashlib
import json
import threading

from .budget import capped_map
from .config import Config
from .schema import cites as finding_rules
from .distill import COVERAGE, _ask, _fmt, _id
from .reviewer import load_rules, parse_reviewer, reviewer_context, ruleonly_of, run_reviewer
from .annotate import annotate, cid_of, points
from .settings import get
from .runs import cached as is_cached, run_dir, run_models, save_run
from .score import REPORTS, hkey, load_gold, refuted, score_one
from .workspace import cached_pr, sample_workspace

FIELDS = ("when", "expect", "examples", "paths", "status")
EST_RUN = 1.6  # one review plus its judge, in dollars
EST_RO = 0.6   # one rule-only run (-ro) plus its rule check: ~$0.6 per sample with the full book (cx02, 2026-11-25)


def run_tag(only: set[str] | None) -> str:
    """The cache tag of rule-only runs restricted to the rule ids `only` ("" when not restricted)."""
    return "" if only is None else "#o" + hashlib.sha1(",".join(sorted(only)).encode()).hexdigest()[:8]


def changed(new: list[dict], base: list[dict] | None) -> list[str]:
    """Active entries of `new` that are new or differ from `base` in text, scope or status (all
    active entries when there is no base)."""
    old = {r["id"]: r for r in base or []}
    return [r["id"] for r in new if r.get("status", "active") == "active"
            and (base is None or r["id"] not in old or any(r.get(k) != old[r["id"]].get(k) for k in FIELDS))]


def suite(rules: list[dict], ids: list[str]) -> list[tuple[str, dict]]:
    """(entry id, test) for each corrected test of entries `ids`."""
    by = {r["id"]: r for r in rules}
    return [(i, t) for i in ids for t in by[i].get("tests") or [] if t["result"] == "corrected" and t.get("comments")]


def text_check(rules: list[dict], ids: list[str], cm: dict, cfg: Config, effort: str = "high") -> tuple[dict, float]:
    """Layer 1.

    Returns:
        ({entry id: comment ids it should explain but no longer does}, cost).
    """
    by, lost, cost = {r["id"]: r for r in rules}, {}, 0.0
    for i in ids:
        r = by[i]
        want = list(dict.fromkeys([*(r.get("evidence") or []),
                                   *(c for _, t in suite(rules, [i]) for c in t["comments"])]))
        cs = [cm[c] for c in want if c in cm]
        if not cs:
            continue
        text = f"{i}: when {r.get('when')} -> {r.get('expect')}"
        try:
            res, c = _ask(COVERAGE.format(rules=text, comments="\n\n".join(_fmt(x, False) for x in cs)), effort, cfg)
        except Exception as e:  # a failed check must not sink the replays; count it as all lost, as distill does
            print(f"text check of {i} failed: {e}")
            res, c = None, 0.0
        cost += c
        ok = {_id(x.get("id")) for x in res if isinstance(x, dict) and i in (x.get("rules") or [])} \
            if isinstance(res, list) else set()
        lost[i] = [x["id"] for x in cs if x["id"] not in ok]
    return lost, cost


def cite_ids(by: dict[str, dict], i: str) -> set[str]:
    """Ids whose citation counts for entry `i` of a book (`by`: its entries by id): itself, its principle,
    a principle's members."""
    r = by.get(i, {})
    return {i, *([r["principle"]] if r.get("principle") else []), *(r.get("members") or [])}


def replay(book: str, cases: list[tuple[str, dict]], reps: int, max_cost: float, cfg: Config,
           workers: int = 4, suffix: str = "", only: set[str] | None = None) -> tuple[list[dict], float]:
    """Layer 2: re-review each case's target with `book` (the prompt and effort of the test's rule
    reviewer, plus `suffix`, e.g. "-rc") `reps` times; runs are cached under data/runs, so a rerun costs nothing.

    With a rule-only reviewer (suffix "-ro") the judge sees every point of the sample, as production runs
    are judged, and a run with no findings is scored without a judge call.

    `only` (rule-only reviewers): the rule check sees only these rule ids of `book`; such runs are cached
    apart, under the reviewer name plus "#o<hash of the ids>".

    Returns:
        (one row per case: entry, target, reviewer, per-run pass flags, passed), cost.
    """
    ss, cm = load_gold(cfg)
    spent, lock = [0.0], threading.Condition()  # notified when a running review ends
    reserved, est = [0.0], EST_RO if suffix.startswith("-ro") else EST_RUN * (2 if suffix else 1)  # expected cost of the reviews running now
    tag = run_tag(only)

    def reviewer_of(t: dict) -> str:
        version, _, effort = parse_reviewer(t["with"].split("#")[0])
        return f"{version}+{book}@{effort}{suffix}"

    def one(job: tuple[str, str, int]) -> tuple[tuple[str, str, int, dict | None], float]:
        """Review (unless cached) and judge `target` with reviewer `rv`, run k; None if over the cap."""
        rv, target, k = job
        mine = 0.0
        pr, c = target.split("@")
        key = next((x for x in ss if x[0] == int(pr) and x[1].startswith(c)), None)
        if key is None:
            raise ValueError(f"test target {target} is not a sample in the gold set")
        s, name = ss[key], f"{pr}-{key[1][:8]}.json"
        d = run_dir(cfg, rv + tag, k)
        d.mkdir(parents=True, exist_ok=True)
        # a failed run (unparsable output) is run again, not reused; so is one made with an older model
        cached = is_cached(cfg, rv, d / name, rerun_failed=True)
        if not cached:
            with lock:  # cached runs are always read; a new one waits until it fits with those running
                while spent[0] < max_cost and reserved[0] and spent[0] + reserved[0] + est > max_cost:
                    lock.wait()
                if spent[0] >= max_cost:
                    return (rv, target, k, None), 0.0
                reserved[0] += est
            cost = 0.0
            try:
                with sample_workspace(cfg, s, f"regress{k}", reviewer_context(rv)) as (wt, base):
                    r = run_reviewer(wt, cached_pr(cfg, key[0], s["time"]), rv, only=only)
                cost = float(r.get("cost") or 0.0)
                save_run(cfg, d / name, {"pr": key[0], "commit": key[1], "base": base, **r, "model": run_models(r)})
            finally:  # always release the reservation, or the runs waiting for budget wait forever
                with lock:
                    reserved[0] -= est
                    spent[0] += cost
                    lock.notify_all()
            mine += cost
        run = json.loads((d / name).read_text())
        if run.get("findings") is None:
            return (rv, target, k, {"run": run, "score": None}), mine
        sp = cfg.data / "scores" / d.name / name
        gold = [cm[i] for i in s["gold_ids"]]
        if ruleonly_of(rv):
            ann = annotate(cfg, s, gold, str(get("annotate", "effort")))  # the whole sample, so the cache stays whole
            with lock:
                spent[0] += ann["cost"]
            mine += ann["cost"]
            if sp.exists() and set(json.loads(sp.read_text())["gold_ids"]) != set(s["gold_ids"]):
                sp.unlink()  # judged for some comments only: judge against them all
            if not run["findings"]:  # nothing to match: every point missed, no judge call
                sc = {"human": [p | {"matched_ai": []} for p in points(ann, gold)], "ai": [],
                      "gold_ids": [c["id"] for c in gold]}
                return (rv, target, k, {"run": run, "score": sc, "cached": cached}), mine
        judged = sp.exists()
        sc = score_one(cfg, run, s, gold, sp, str(get("judge", "effort")))
        with lock:
            spent[0] += 0 if judged else sc.get("cost", 0)
        mine += 0 if judged else sc.get("cost", 0)
        return (rv, target, k, {"run": run, "score": sc, "cached": cached}), mine

    jobs = sorted({(reviewer_of(t), t["target"], k) for _, t in cases for k in range(1, reps + 1)})
    res, _ = capped_map(one, jobs, workers, float("inf"),  # one() enforces max_cost itself
                        label=lambda j: f"{book} #{j[1]}" + (f" r{j[2]}" if j[2] > 1 else ""),
                        show=lambda x: "over the cap, not run" if x[3] is None else
                        ("cached" if x[3].get("cached") else "reviewed") + f", {len(x[3]['run'].get('findings') or [])} findings")
    done = {(rv, tg, k): r for rv, tg, k, r in res}

    by = {r["id"]: r for r in load_rules(book)}

    def related(i: str) -> set[str]:
        return cite_ids(by, i)

    rows = []
    for i, t in cases:
        rv, flags, anys, bads, ok_ids, verdicts = reviewer_of(t), [], [], [], related(i), []
        for k in range(1, reps + 1):
            res = done.get((rv, t["target"], k))
            if res is None or res["score"] is None:
                flags.append(None)  # not run (cost cap) or unparsable output
                continue
            cites = {f["id"] for f in res["run"]["findings"] if finding_rules(f) & set(ok_ids)}
            gold = res["score"]["gold_ids"]
            # point keys, plus their comment: a target filed before comments were split is hit by any point
            hit = {x for h in res["score"]["human"] if cites & set(h.get("matched_ai") or [])
                   for x in (hkey(res["score"], h), cid_of(hkey(res["score"], h)))}
            hit_any = {x for h in res["score"]["human"] if h.get("matched_ai")
                       for x in (hkey(res["score"], h), cid_of(hkey(res["score"], h)))}
            invalid = {a["id"] for a in res["score"].get("ai") or [] if refuted(a)}
            bads.append(len(cites & invalid))
            run = res["run"]  # the rule check's own verdict on the entry: why it did or did not fire
            verdicts += [{k2: v.get(k2) for k2 in ("applies", "violated", "why")}
                         for x in [run, *(run.get("runs") or [])] for v in x.get("verdicts") or []
                         if isinstance(v, dict) and v.get("rule") == i]
            flags.append(all(c in hit for c in t["comments"]))
            anys.append(all(c in hit_any for c in t["comments"]))
        ran = [f for f in flags if f is not None]
        rows.append({"entry": i, "target": t["target"], "comments": t["comments"], "reviewer": rv, "runs": flags,
                     "passed": any(ran) if ran else None,  # matched by a finding citing the entry (or linked)
                     "any": any(anys) if anys else None,  # matched by any finding
                     "invalid": min(bads) if bads else None,  # findings citing the entry judged invalid
                     "verdicts": verdicts})  # the rule check's verdicts on the entry, one per run
    return rows, spent[0]


def regress(book: str, base: str | None = None, reps: int = 2, max_cost: float = 10.0,
            cfg: Config | None = None, suffix: str = "") -> str:
    """Check rulebook `book` against `base` (or all its tested entries); see the module docstring.

    Writes reports/regress_<book>.md and returns it. `max_cost` 0 = print the plan only. A case that
    fails in all its runs is a regression; a changed entry that loses a comment in the text check is
    one too.
    """
    cfg = cfg or Config()
    rules = load_rules(book)
    ids = changed(rules, load_rules(base) if base else None)
    cases = suite(rules, ids)
    est = len(ids) * 0.1 + len({t["target"] for _, t in cases}) * reps * EST_RUN
    head = [f"# Regression check of {book}" + (f" against {base}" if base else " (all tested entries)"), "",
            f"- changed entries: {', '.join(ids) or 'none'}",
            f"- corrected tests to replay: {len(cases)} ({reps} runs each); est ${est:.1f}, cap ${max_cost:.1f}", ""]
    if max_cost <= 0:
        return "\n".join(head + ["plan only (max-cost 0)"])
    _, cm = load_gold(cfg)
    lost, cost = text_check(rules, ids, cm, cfg)
    rows, rcost = replay(book, cases, reps, max_cost - cost, cfg, suffix=suffix)
    bad_text = {i: l for i, l in lost.items() if l}
    bad_runs = [r for r in rows if r["passed"] is False]
    unknown = [r for r in rows if r["passed"] is None]
    verdict = "REGRESSED" if bad_text or bad_runs else ("INCOMPLETE" if unknown else "PASS")
    L = head + [f"**{verdict}** · cost ${cost + rcost:.2f}", "", "## Text check (layer 1)", ""]
    L += [f"- {i}: " + (f"no longer explains {l}" if l else "ok") for i, l in lost.items()] or ["- nothing to check"]
    L += ["", "## Replay of corrected tests (layer 2)", "", "| entry | target | reviewer | runs | result |",
          "| --- | --- | --- | --- | --- |"]
    for r in rows:
        runs = " ".join("✓" if f else "✗" if f is False else "?" for f in r["runs"])
        res = {True: "pass", False: "REGRESSED", None: "not run"}[r["passed"]]
        L.append(f"| {r['entry']} | {r['target']} | {r['reviewer']} | {runs} | {res} |")
    (REPORTS / f"regress_{book}{suffix}.md").write_text("\n".join(L) + "\n")
    return "\n".join(L)



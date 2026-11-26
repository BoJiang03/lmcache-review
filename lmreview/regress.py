"""Replay of rule cases for `lmreview vet` (vet.py): re-review each case's target with a rulebook and judge it.

An entry passes a case if, in some run, every tested comment is matched by a finding citing the entry (or
its principle, or for a principle one of its members).
"""

from __future__ import annotations

import hashlib
import json
import threading

from .budget import capped_map
from .config import Config
from .schema import cites as finding_rules
from .reviewer import load_rules, parse_reviewer, reviewer_context, ruleonly_of, run_reviewer
from .annotate import annotate, cid_of, points
from .settings import get
from .runs import cached as is_cached, run_dir, run_models, save_run
from .score import hkey, load_gold, refuted, score_one
from .workspace import cached_pr, sample_workspace

FIELDS = ("when", "expect", "examples", "paths", "status")
EST_RUN = 1.6  # one review plus its judge, in dollars
EST_RO = 0.6   # one rule-only run (-ro) plus its rule check: ~$0.6 per sample with the full book (cx02, 2026-11-25)


def run_tag(only: set[str] | None) -> str:
    """The cache tag of rule-only runs restricted to the rule ids `only` ("" when not restricted)."""
    return "" if only is None else "#o" + hashlib.sha1(",".join(sorted(only)).encode()).hexdigest()[:8]


def cite_ids(by: dict[str, dict], i: str) -> set[str]:
    """Ids whose citation counts for entry `i` of a book (`by`: its entries by id): itself, its principle,
    a principle's members."""
    r = by.get(i, {})
    return {i, *([r["principle"]] if r.get("principle") else []), *(r.get("members") or [])}


def replay(book: str, cases: list[tuple[str, dict]], reps: int, max_cost: float, cfg: Config,
           workers: int = 4, suffix: str = "", only: set[str] | None = None) -> tuple[list[dict], float]:
    """Re-review each case's target with `book` (the prompt and effort of the test's rule
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

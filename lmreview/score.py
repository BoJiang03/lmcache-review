"""Eval: grade reviewer runs against the merged human reviews on the same commit.

For each sample (PR, reviewed commit) in data/runs/<version>/:
  1. Classify each human review comment on that commit (all reviewers merged): change_request | question | nit | praise.
  2. For each change_request/nit, rate its severity and decide which AI finding (if any) raises the
     same issue and asks for a change in the same direction.
  3. Judge whether each AI finding is valid, reading the code.
One judge call per sample, in the SAME workspace the reviewer saw. Results go to
<data>/scores/<version>/<pr>-<commit8>.json and a summary to reports/score_<version>.md.
"""

from __future__ import annotations

import collections as C
import json
import pathlib

from . import llm
from .budget import capped_map
from .progress import note
from .annotate import annotate, point_comments, points
from .config import Config
from .settings import get
from .reviewer import prompt_template, rule_evidence
from .schema import load_findings
from .workspace import TOOLS, cached_pr, pr_meta, sample_workspace

JUDGE = "j4"  # judge prompt version; results of another version are never mixed in (see score_one)
REPORTS = pathlib.Path(__file__).resolve().parent.parent / "reports"

PROMPT = """You are grading an AI code reviewer against human reviewers on LMCache PR #{number}.

Your working directory is exactly what the AI reviewer saw: the repository as of the reviewed
commit, `PR.diff` (the PR's changes) and `PR_HISTORY.md` (review discussion before this review).
Read code there whenever a judgment depends on it. Do not modify any files.

PR title: {title}
PR description:
<<<
{body}
>>>

HUMAN review comments on the commit the AI reviewed, each followed by the points in it that ask for a
change (ids p1, p2, ...). Match the points; the comment is there for context:
{human}

AI findings (id, severity, scope, location, title: body):
{ai}

Tasks:
1. For each POINT, set "matched_ai" to the ids of the AI findings that raise the SAME underlying issue
   AND ask for a change in the same direction; [] if none. Be strict:
   * same file/line or same topic is not enough: the problem must be the same;
   * a finding whose fix goes the other way, or differs in substance, is not a match (e.g. the human
     asks to explain a docstring with a worked example while the AI asks to shorten it; the human asks
     to reuse an existing helper while the AI asks to add a new one);
   * a finding that names the problem but proposes a different but compatible fix IS a match.
   Give the reason in "match_why".
2. For each AI finding, check it against the code and set "valid": true if it is a real, specific
   problem a maintainer would want fixed, false if it is wrong, speculative, or noise. Use "unsure"
   only if the code genuinely cannot settle it (e.g. it depends on runtime behavior or code outside
   this repo). Human silence does not make a finding invalid.

Answer with one JSON block only:
```json
{{"points": [{{"id": "p1", "matched_ai": ["f2"], "match_why": "<=15 words"}}],
  "ai": [{{"id": "f1", "valid": true, "why": "<=12 words"}}]}}
```"""

WANT = ("change_request", "nit")  # the point types a reviewer should raise (and distill learns)

# Second opinion: a negative verdict has consequences (a missed point is distilled into a rule; a rule's
# finding judged invalid is a failure signal against the rule), so it counts only when a second, blind
# call agrees. One call covers both: the points the judge found unmatched, and the findings it judged
# invalid that cite a team rule.
RECHECK = """You are checking an AI code reviewer's findings on LMCache PR #{number} ({title}).

Your working directory is exactly what the reviewer saw: the repository as of the reviewed commit,
`PR.diff` (the PR's changes) and `PR_HISTORY.md`. Read the code to settle each question. Do not modify
any files.

AI findings (id, severity, scope, location, title: body):
{ai}

A. Human review points (with the comment they come from, for context). For each POINT, set
"matched_ai" to the ids of the AI findings above that raise the SAME underlying issue AND ask for a
change in the same direction; [] if none. Same file or topic is not enough; a different but compatible
fix for the same problem IS a match.
{human}

B. For each of these findings: {verify}
check its claim against the code. Quote the lines that settle it, then set "holds": true (the code
does what the finding says, and it is a problem), false (it does not, or it is not a problem), or
"unsure" (the code cannot settle it).

Answer with one JSON block only:
```json
{{"points": [{{"id": "p1", "matched_ai": [], "match_why": "<=15 words"}}],
  "findings": [{{"id": "f3", "quote": "path:line: code", "holds": false, "why": "<=15 words"}}]}}
```"""


def load_gold(cfg: Config) -> tuple[dict, dict]:
    """(samples keyed by (pr, commit), comments keyed by id)."""
    ds = cfg.data / "dataset"
    ss = {(x["pr"], x["commit"]): x for x in map(json.loads, (ds / "samples.jsonl").open())}
    cm = {c["id"]: c for c in map(json.loads, (ds / "comments.jsonl").open())}
    return ss, cm | point_comments(cfg, cm)


def hkey(s: dict, h: dict) -> int | str:
    """The point key of judge entry `h` of score `s` (older scores: the comment id)."""
    return h["key"] if "key" in h else int(s["gold_ids"][h["id"]])


def score_one(cfg: Config, run: dict, sample: dict, gold: list[dict], out: pathlib.Path,
              effort: str) -> dict:
    """Grade one sample's run inside the same workspace the reviewer saw; cached on disk.

    The human comments come annotated (annotate.py: points, type, severity; once per sample). A cached
    score of another judge version is moved to <data>/scores/_<version>/ and judged again."""
    if out.exists():
        res = json.loads(out.read_text())
        if res.get("judge", "j1") != JUDGE:
            old = out.parents[1] / f"_{res.get('judge', 'j1')}" / out.parent.name / out.name
            old.parent.mkdir(parents=True, exist_ok=True)
            out.rename(old)
        elif res.get("effort", "medium") != effort:
            raise ValueError(f"{out} was judged at effort {res.get('effort', 'medium')!r}, not {effort!r}; "
                             "pass that --effort or move the scores aside to re-judge")
        else:
            return res
    ann = annotate(cfg, sample, gold, effort)
    pts = points(ann, gold)
    want = [p for p in pts if p["type"] in WANT]
    local = {f"p{n}": p for n, p in enumerate(want, 1)}
    human = "\n\n".join(
        _fmt_human(i, c) + "".join(f"\n  [{lid}] ({p['type']}) {p['text']}" for lid, p in local.items() if p["id"] == i)
        for i, c in enumerate(gold) if any(p["id"] == i for p in want)) or "(no points asking for a change)"
    ai = "\n".join(f"[{f.id}] ({f.severity}, {f.scope}) {f.where()} {f.title}: {f.body[:800]}"
                   for f in load_findings(run) or []) or "(none)"
    cost = ann["cost"]
    got: dict = {"points": [], "ai": []}
    ctx = prompt_template(run["version"])[1] if run.get("version") else ()
    if want:
        with sample_workspace(cfg, sample, "judge", ctx) as (wt, _):
            r = llm.run(PROMPT.format(human=human, ai=ai, **pr_meta(cached_pr(cfg, run["pr"], sample["time"]))),
                        effort, cwd=str(wt), tools=TOOLS)
        got, cost = llm.extract_json(r["text"]), cost + r["cost"]
    m = {e.get("id"): e for e in got.get("points") or [] if isinstance(e, dict)}
    ai_out = [a for a in got.get("ai") or [] if isinstance(a, dict)]
    fs = {f.id: f for f in load_findings(run) or []}
    missed = {lid: p for lid, p in local.items() if not (m.get(lid) or {}).get("matched_ai")}
    doubt = [a for a in ai_out if a.get("valid") is False and a.get("id") in fs
             and (fs[a["id"]].rule or fs[a["id"]].rules)]
    second: dict = {}
    if get("judge", "second_opinion") and (missed or doubt):
        human2 = "\n\n".join(
            _fmt_human(i, c) + "".join(f"\n  [{lid}] ({p['type']}) {p['text']}" for lid, p in missed.items() if p["id"] == i)
            for i, c in enumerate(gold) if any(p["id"] == i for p in missed.values())) or "(none)"
        with sample_workspace(cfg, sample, "judge2", ctx) as (wt, _):
            r2 = llm.run(RECHECK.format(ai=ai, human=human2, verify=", ".join(a["id"] for a in doubt) or "(none)",
                                        **pr_meta(cached_pr(cfg, run["pr"], sample["time"]))),
                         effort, cwd=str(wt), tools=TOOLS)
        cost += r2["cost"]
        try:
            second = llm.extract_json(r2["text"])
        except ValueError:
            second = {}
        second = second if isinstance(second, dict) else {}
    m2 = {e.get("id"): e for e in second.get("points") or [] if isinstance(e, dict)}
    v2 = {e.get("id"): e for e in second.get("findings") or [] if isinstance(e, dict)}
    for lid in missed:  # a miss stands only if the second opinion finds no match either
        if (m2.get(lid) or {}).get("matched_ai"):
            m[lid] = {**m2[lid], "second": "matched"}
    for a in ai_out:  # refuted: a rule's finding both calls found wrong (the failure signal for the rule)
        if a.get("id") in fs and (fs[a["id"]].rule or fs[a["id"]].rules):
            a["refuted"] = a in doubt and (v2.get(a["id"]) or {}).get("holds") is False
            if a in doubt:
                a["second"] = {k: (v2.get(a["id"]) or {}).get(k) for k in ("holds", "quote", "why")}
    by_point = {id(p): lid for lid, p in local.items()}
    hs = []
    for p in pts:
        e = m.get(by_point.get(id(p)), {})
        hs.append(p | {"matched_ai": [str(x) for x in e.get("matched_ai") or []], "match_why": e.get("match_why", "")})
    res = {"human": hs, "ai": ai_out, "second_opinion": bool(second), "pr": run["pr"], "commit": run["commit"], "cost": cost,
           "effort": effort, "judge": JUDGE, "annotator": ann["annotator"],
           "denials": [], "gold_ids": [c["id"] for c in gold]}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    return res


def refuted(a: dict) -> bool:
    """Whether judge entry `a` (an AI finding) counts as wrong for its rule: both the judge and the second
    opinion found it wrong (older scores: the judge alone)."""
    return a["refuted"] if "refuted" in a else a.get("valid") is False


def _fmt_human(i: int, c: dict) -> str:
    if c["kind"] == "inline":
        return (f"[c{i}] {c['path']}:{c['line_lo']}-{c['line_hi']} by {c['author']}\n"
                f"hunk:\n{(c['diff_hunk'] or '')[-1200:]}\ncomment: {c['body'][:1500]}")
    return f"[c{i}] overall review by {c['author']} ({c['review_state']}):\n{c['body'][:2500]}"


def _normalize(s: dict, run: dict) -> dict:
    """Upgrade judge files written before findings had ids (index-based, scalar matches)."""
    ids = [f.id for f in load_findings(run) or []]
    for h in s["human"]:
        m = h.get("matched_ai")
        m = [] if m is None else m if isinstance(m, list) else [m]
        h["matched_ai"] = [ids[x] if isinstance(x, int) and x < len(ids) else str(x) for x in m]
    for f in s["ai"]:
        if "id" not in f:
            f["id"] = ids[f["idx"]] if f["idx"] < len(ids) else f"f{f['idx'] + 1}"
    return s


EST_COST = 0.4  # $/sample for a judge call; used only for the estimate


def judge(version: str, workers: int = 4, effort: str = "high", max_cost: float = 10.0,
          cfg: Config | None = None) -> tuple[list[dict], list[dict]]:
    """Judge every valid run of `version` not judged yet (stopping at `max_cost`).

    Returns:
        (runs that have a judge result, their normalized judge results), in the same order.
    """
    cfg = cfg or Config()
    ss, cm = load_gold(cfg)
    runs = [json.loads(p.read_text()) for p in sorted((cfg.data / "runs" / version).glob("*.json"))]
    runs = [r for r in runs if r["findings"] is not None]
    stale = [r for r in runs if (r["pr"], r["commit"]) not in ss]
    if stale:  # the dataset was rebuilt and the sample no longer exists (e.g. its commit was corrected)
        note(f"skipping {len(stale)} runs whose sample no longer exists: "
              + ", ".join(f"#{r['pr']}-{r['commit'][:8]}" for r in stale))
        runs = [r for r in runs if (r["pr"], r["commit"]) in ss]
    ev = rule_evidence(version)
    leak = [r for r in runs if ev & set(ss[(r["pr"], r["commit"])]["gold_ids"])]
    if leak:  # see replay: the rulebook was distilled from these samples' own human comments
        note(f"skipping {len(leak)} runs whose sample the rulebook came from")
        runs = [r for r in runs if r not in leak]
    sdir = cfg.data / "scores" / version
    path = lambda r: sdir / f"{r['pr']}-{r['commit'][:8]}.json"  # noqa: E731
    def fresh(r: dict) -> bool:  # judged against the sample's current gold (it changes when the dataset is rebuilt)
        if not path(r).exists():
            return False
        s = json.loads(path(r).read_text())
        return s.get("gold_ids") == ss[(r["pr"], r["commit"])]["gold_ids"] and s.get("judge") == JUDGE
    todo = [r for r in runs if not fresh(r)]
    note(f"judge {version}: {len(runs)} runs, {len(todo)} to judge (est ${len(todo) * EST_COST:.0f}, "
         f"cap ${max_cost:.0f})")

    def one(r: dict) -> tuple[str, float]:
        k = (r["pr"], r["commit"])
        s = score_one(cfg, r, ss[k], [cm[i] for i in ss[k]["gold_ids"]], path(r), effort)
        return "judged", s["cost"]
    capped_map(one, todo, workers, max_cost, label=lambda r: f"#{r['pr']}-{r['commit'][:8]}", est=EST_COST)
    done = [r for r in runs if path(r).exists()]
    res = [score_one(cfg, r, None, None, path(r), effort) for r in done]  # cached reads (effort-checked)
    return done, [_normalize(s, r) for s, r in zip(res, done)]


def score(version: str = "v0", workers: int = 4, effort: str = "high", max_cost: float = 10.0,
          cfg: Config | None = None) -> str:
    """Judge runs of `version`, write reports/score_<version>.md, return its headline."""
    cfg = cfg or Config()
    ss, cm = load_gold(cfg)
    gold = {k: [cm[i] for i in s["gold_ids"]] for k, s in ss.items()}
    runs, res = judge(version, workers, effort, max_cost, cfg)
    types = C.Counter(h["type"] for s in res for h in s["human"])
    want = [h for s in res for h in s["human"] if h["type"] in ("change_request", "nit")]
    cr = [h for s in res for h in s["human"] if h["type"] == "change_request"]
    serious = [h for h in want if h.get("severity") in ("blocker", "major")]
    ai = [f for s in res for f in s["ai"]]
    matched = {(s["pr"], s["commit"], m) for s in res for h in s["human"] for m in h["matched_ai"]}
    ai_only = [(s["pr"], f) for s in res for f in s["ai"] if (s["pr"], s["commit"], f["id"]) not in matched]
    n = lambda xs: sum(1 for x in xs if x["matched_ai"])  # noqa: E731
    v = C.Counter(str(f["valid"]) for f in ai)
    vo = C.Counter(str(f["valid"]) for _, f in ai_only)
    cost = sum(r["cost"] for r in runs) + sum(s["cost"] for s in res)
    L = [f"# Score: reviewer {version}", "",
         f"Samples (PR, reviewed commit): {len(res)} · human review comments: {sum(types.values())} "
         f"({', '.join(f'{k} {c}' for k, c in types.most_common())})", "",
         f"- Recall on change requests: {n(cr)}/{len(cr)} ({n(cr) / max(len(cr), 1):.0%})",
         f"- Recall on change requests + nits: {n(want)}/{len(want)} ({n(want) / max(len(want), 1):.0%})",
         f"- Recall on serious human comments (blocker/major): {n(serious)}/{len(serious)} "
         f"({n(serious) / max(len(serious), 1):.0%})",
         f"- AI findings: {len(ai)} ({len(ai) / max(len(res), 1):.1f}/PR); judged valid: "
         f"{v['True']} ({v['True'] / max(len(ai), 1):.0%}), invalid {v['False']}, unsure {v['unsure']}",
         f"- AI-only findings: {len(ai_only)}; judged valid {vo['True']}, invalid {vo['False']}, unsure {vo['unsure']}",
         f"- Cost (review + grading): ${cost:.2f}", "",
         "## Missed change requests", ""]
    for s in res:
        for h in s["human"]:
            if h["type"] == "change_request" and not h["matched_ai"]:
                c = gold[(s["pr"], s["commit"])][h["id"]]
                L.append(f"- #{s['pr']} `{c.get('path') or 'overall review'}:{c.get('line_lo') or ''}` {c['author']}: "
                         f"{c['body'][:160].replace(chr(10), ' ')} ([link]({c['url']}))")
    (REPORTS / f"score_{version}.md").write_text("\n".join(L) + "\n")
    return "\n".join(L[:9])

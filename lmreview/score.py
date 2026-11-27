"""Judge: grade reviewer runs against the merged human reviews on the same commit.

For each sample (PR, reviewed commit) of a run:
  1. Classify each human review comment on that commit (all reviewers merged): change_request | question | nit | praise.
  2. For each change_request/nit, rate its severity and decide which AI finding (if any) raises the
     same issue and asks for a change in the same direction.
  3. Judge whether each AI finding is valid, reading the code.
One judge call per sample, in the SAME workspace the reviewer saw. Results go to
<data>/scores/<reviewer>/<pr>-<commit8>.json.
"""

from __future__ import annotations

import json
import pathlib

from . import llm
from .progress import note
from .annotate import annotate, point_comments, points
from .config import Config
from .settings import get
from .project import localize_module
from .reviewer import prompt_template
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
    ann = annotate(cfg, sample, gold, str(get("annotate", "effort")))
    pts = points(ann, gold)
    want = [p for p in pts if p["type"] in WANT]
    local = {f"p{n}": p for n, p in enumerate(want, 1)}
    human = "\n\n".join(
        _fmt_human(i, c) + "".join(f"\n  [{lid}] ({p['type']}) {p['text']}" for lid, p in local.items() if p["id"] == i)
        for i, c in enumerate(gold) if any(p["id"] == i for p in want)) or "(no points asking for a change)"
    ai = "\n".join(f"[{f.id}] ({f.severity}, {f.scope}) {f.where()} {f.title}: {f.body[:800]}"
                   for f in load_findings(run) or []) or "(none)"
    cost = ann["cost"]
    usage: dict = {}  # the judge's own calls (annotation is cached and counted in `cost` only)
    got: dict = {"points": [], "ai": []}
    ctx = prompt_template(run["version"])[1] if run.get("version") else ()
    if want:
        with sample_workspace(cfg, sample, "judge", ctx) as (wt, _):
            r = llm.run(PROMPT.format(human=human, ai=ai, **pr_meta(cached_pr(cfg, run["pr"], sample["time"]))),
                        effort, cwd=str(wt), tools=TOOLS)
        got, cost = llm.extract_json(r["text"]), cost + r["cost"]
        usage = llm.add_usage(usage, r.get("usage"))
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
        usage = llm.add_usage(usage, r2.get("usage"))
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
        hs.append(p | {"matched_ai": [str(x) for x in e.get("matched_ai") or []], "match_why": e.get("match_why", "")}
                  | ({"second": e["second"]} if e.get("second") else {}))
    res = {"human": hs, "ai": ai_out, "second_opinion": bool(second), "pr": run["pr"], "commit": run["commit"], "cost": cost, "usage": usage,
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


EST_COST = 0.4  # $/sample for a judge call; used only for the estimate


def judge_runs(cfg: Config, reviewer: str, prs: set[int] | None, split: str, max_cost: float,
               rep: int = 1) -> tuple[list, float]:
    """Judge `reviewer`'s runs on `split` (only `prs`, if given) against the human comments, for the
    ledger (state.judge); already judged runs are read from disk. Runs over the cost cap stay unjudged and are skipped.
    `rep` > 1: the runs of that repeat (<reviewer>#r<rep>, see runs.py).

    Returns:
        ([(run, score)], cost).
    """
    from .progress import note
    from .runs import run_dir
    ss, cm = load_gold(cfg)
    out, cost = [], 0.0
    d = run_dir(cfg, reviewer, rep)
    files = sorted(d.glob("*.json"))
    for f in files:
        run = json.loads(f.read_text())
        s = ss.get((run["pr"], run["commit"]))
        if not s or s.get("split") != split or (prs and run["pr"] not in prs) or run.get("findings") is None:
            continue
        sp = cfg.data / "scores" / d.name / f.name
        was = sp.exists() and json.loads(sp.read_text()).get("judge") == JUDGE  # else judged (again) below
        if not was and cost >= max_cost:
            continue
        sp.parent.mkdir(parents=True, exist_ok=True)
        sc = score_one(cfg, run, s, [cm[i] for i in s["gold_ids"]], sp, str(get("judge", "effort")))
        cost += 0 if was else sc.get("cost", 0)
        out.append((run, sc))
        if not was:
            n = out[-1][1]
            note(f"judged #{run['pr']}@{run['commit'][:8]}: {sum(bool(h['matched_ai']) for h in n['human'])}/{len(n['human'])} "
                 f"human comments found (${sc.get('cost', 0):.2f}, total ${cost:.2f} of ${max_cost:.0f})")
    return out, cost

localize_module(globals())  # the prompts above name the project of [project] (project.py)

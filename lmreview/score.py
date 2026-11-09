"""Eval: grade reviewer runs against the merged human reviews on the same commit.

For each sample (PR, reviewed commit) in data/runs/<version>/:
  1. Classify each human review comment on that commit (all reviewers merged): change_request | question | nit | praise.
  2. For each change_request/nit, decide which AI finding (if any) raises the same issue.
  3. Judge whether each AI finding is valid, reading the code.
One judge call per sample, in the SAME workspace the reviewer saw. Results go to
<data>/scores/<version>/<pr>-<commit8>.json and a summary to reports/score_<version>.md.
"""

from __future__ import annotations

import collections as C
import concurrent.futures as cf
import json
import pathlib

from . import llm
from .config import Config
from .schema import load_findings
from .workspace import TOOLS, cached_pr, pr_meta, sample_workspace

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

HUMAN review comments (all human reviews made on the same commit the AI reviewed; inline ones show\ncode location and hunk, overall reviews may contain several points):
{human}

AI findings (id, severity, scope, location, title: body):
{ai}

Tasks:
1. For each HUMAN comment, set "type":
   - change_request: asks for (or clearly implies) a code/test/doc change
   - question: asks for an explanation; no change implied
   - nit: tiny style/naming/typo suggestion
   - praise: approval or thanks
2. For each HUMAN comment of type change_request or nit, set "matched_ai" to the list of ids of the
   AI findings that raise the SAME underlying issue (same problem, not just the same file/line);
   [] if none. Be strict: a vaguely related finding is not a match. Give the reason in "match_why". For an overall review with several
   points, classify by its main actionable point and match on that.
3. For each AI finding, check it against the code and set "valid": true if it is a real, specific
   problem a maintainer would want fixed, false if it is wrong, speculative, or noise. Use "unsure"
   only if the code genuinely cannot settle it (e.g. it depends on runtime behavior or code outside
   this repo). Human silence does not make a finding invalid.

Answer with one JSON block only:
```json
{{"human": [{{"id": 0, "type": "...", "matched_ai": ["f2"], "match_why": "<=15 words"}}],
  "ai": [{{"id": "f1", "valid": true, "why": "<=12 words"}}]}}
```"""


def load_gold(cfg: Config) -> tuple[dict, dict]:
    """(samples keyed by (pr, commit), comments keyed by id)."""
    ds = cfg.data / "dataset"
    ss = {(x["pr"], x["commit"]): x for x in map(json.loads, (ds / "samples.jsonl").open())}
    cm = {c["id"]: c for c in map(json.loads, (ds / "comments.jsonl").open())}
    return ss, cm


def score_one(cfg: Config, run: dict, sample: dict, gold: list[dict], out: pathlib.Path,
              effort: str) -> dict:
    """Grade one sample's run inside the same workspace the reviewer saw; cached on disk."""
    if out.exists():
        res = json.loads(out.read_text())
        if res.get("effort", "medium") != effort:
            raise ValueError(f"{out} was judged at effort {res.get('effort', 'medium')!r}, not {effort!r}; "
                             "pass that --effort or move the scores aside to re-judge")
        return res
    human = "\n\n".join(
        (f"[{i}] {c['path']}:{c['line_lo']}-{c['line_hi']} by {c['author']}\n"
         f"hunk:\n{(c['diff_hunk'] or '')[-1200:]}\ncomment: {c['body'][:1500]}")
        if c["kind"] == "inline" else
        f"[{i}] overall review by {c['author']} ({c['review_state']}):\n{c['body'][:2500]}"
        for i, c in enumerate(gold))
    ai = "\n".join(f"[{f.id}] ({f.severity}, {f.scope}) {f.where()} {f.title}: {f.body[:800]}"
                   for f in load_findings(run) or []) or "(none)"
    with sample_workspace(cfg, sample, "judge") as (wt, _):
        r = llm.run(PROMPT.format(human=human, ai=ai, **pr_meta(cached_pr(cfg, run["pr"]))), effort,
                    cwd=str(wt), tools=TOOLS)
    res = llm.extract_json(r["text"])
    res.update(pr=run["pr"], commit=run["commit"], cost=r["cost"], effort=effort,
               denials=r["denials"], gold_ids=[c["id"] for c in gold])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    return res


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


def score(version: str = "v0", workers: int = 4, effort: str = "high", cfg: Config | None = None) -> str:
    """Grade every run of `version`, write reports/score_<version>.md, return its headline."""
    cfg = cfg or Config()
    ss, cm = load_gold(cfg)
    gold = {k: [cm[i] for i in s["gold_ids"]] for k, s in ss.items()}
    runs = [json.loads(p.read_text()) for p in sorted((cfg.data / "runs" / version).glob("*.json"))]
    runs = [r for r in runs if r["findings"] is not None]
    sdir = cfg.data / "scores" / version
    with cf.ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda r: score_one(cfg, r, ss[(r["pr"], r["commit"])], gold[(r["pr"], r["commit"])],
                                           sdir / f"{r['pr']}-{r['commit'][:8]}.json", effort), runs))

    res = [_normalize(s, r) for s, r in zip(res, runs)]
    types = C.Counter(h["type"] for s in res for h in s["human"])
    want = [h for s in res for h in s["human"] if h["type"] in ("change_request", "nit")]
    cr = [h for s in res for h in s["human"] if h["type"] == "change_request"]
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

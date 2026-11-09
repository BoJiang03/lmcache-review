"""Classify gold human comments and match them against a reviewer run.

For each sample (PR, reviewed commit) in data/runs/<version>/:
  1. Classify each human review comment on that commit (all reviewers merged): change_request | question | nit | praise.
  2. For each change_request/nit, decide which AI finding (if any) raises the same issue.
One `claude -p` call per sample does both, without tools. Results go to
data/scores/<version>/<pr>-<commit8>.json and a summary to reports/score_<version>.md.

Usage: python3 -I src/score.py --version v0
"""

from __future__ import annotations

import argparse
import collections as C
import concurrent.futures as cf
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import llm  # noqa: E402
from workspace import TOOLS, pr_meta, workspace  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DS = ROOT / "data" / "dataset"

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

AI findings:
{ai}

Tasks:
1. For each HUMAN comment, set "type":
   - change_request: asks for (or clearly implies) a code/test/doc change
   - question: asks for an explanation; no change implied
   - nit: tiny style/naming/typo suggestion
   - praise: approval or thanks
2. For each HUMAN comment of type change_request or nit, set "matched_ai" to the index of the AI
   finding that raises the SAME underlying issue (same problem, not just the same file/line), or
   null. Be strict: a vaguely related finding is not a match. For an overall review with several
   points, classify by its main actionable point and match on that.
3. For each AI finding, check it against the code and set "valid": true if it is a real, specific
   problem a maintainer would want fixed, false if it is wrong, speculative, or noise. Use "unsure"
   only if the code genuinely cannot settle it (e.g. it depends on runtime behavior or code outside
   this repo). Human silence does not make a finding invalid.

Answer with one JSON block only:
```json
{{"human": [{{"id": 0, "type": "...", "matched_ai": null}}],
  "ai": [{{"idx": 0, "valid": true, "why": "<=12 words"}}]}}
```"""


def load_gold() -> tuple[dict, dict]:
    """(samples keyed by (pr, commit), comments keyed by id)."""
    ss = {(x["pr"], x["commit"]): x for x in map(json.loads, (DS / "samples.jsonl").open())}
    cm = {c["id"]: c for c in map(json.loads, (DS / "comments.jsonl").open())}
    return ss, cm


def score_one(run: dict, sample: dict, gold: list[dict], out: pathlib.Path, effort: str) -> dict:
    """Grade one sample's run inside the same workspace the reviewer saw; cached on disk."""
    if out.exists():
        return json.loads(out.read_text())
    human = "\n\n".join(
        (f"[{i}] {c['path']}:{c['line_lo']}-{c['line_hi']} by {c['author']}\n"
         f"hunk:\n{(c['diff_hunk'] or '')[-1200:]}\ncomment: {c['body'][:1500]}")
        if c["kind"] == "inline" else
        f"[{i}] overall review by {c['author']} ({c['review_state']}):\n{c['body'][:2500]}"
        for i, c in enumerate(gold))
    ai = "\n".join(f"[{i}] ({f.get('severity')}) {f.get('path')}:{f.get('line')} "
                   f"{f.get('title')}: {f.get('body', '')[:800]}"
                   for i, f in enumerate(run["findings"] or [])) or "(none)"
    with workspace(sample, "judge") as (wt, _):
        r = llm.run(PROMPT.format(human=human, ai=ai, **pr_meta(run["pr"])), effort,
                    cwd=str(wt), tools=TOOLS)
    res = llm.extract_json(r["text"])
    res.update(pr=run["pr"], commit=run["commit"], cost=r["cost"], effort=effort,
               denials=r["denials"], gold_ids=[c["id"] for c in gold])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    return res


def main() -> None:
    """Score every run of a version and write the summary report."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v0")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--effort", default="medium", help="judge effort")
    a = ap.parse_args()
    ss, cm = load_gold()
    gold = {k: [cm[i] for i in s["gold_ids"]] for k, s in ss.items()}
    runs = [json.loads(p.read_text()) for p in sorted((ROOT / "data" / "runs" / a.version).glob("*.json"))]
    runs = [r for r in runs if r["findings"] is not None]
    sdir = ROOT / "data" / "scores" / a.version
    with cf.ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda r: score_one(r, ss[(r["pr"], r["commit"])], gold[(r["pr"], r["commit"])],
                                           sdir / f"{r['pr']}-{r['commit'][:8]}.json", a.effort), runs))

    types = C.Counter(h["type"] for s in res for h in s["human"])
    want = [h for s in res for h in s["human"] if h["type"] in ("change_request", "nit")]
    cr = [h for s in res for h in s["human"] if h["type"] == "change_request"]
    ai = [f for s in res for f in s["ai"]]
    matched = {(s["pr"], s["commit"], h["matched_ai"]) for s in res for h in s["human"] if h.get("matched_ai") is not None}
    ai_only = [(s["pr"], f) for s in res for f in s["ai"] if (s["pr"], s["commit"], f["idx"]) not in matched]
    n = lambda xs: sum(1 for x in xs if x.get("matched_ai") is not None)  # noqa: E731
    v = C.Counter(str(f["valid"]) for f in ai)
    vo = C.Counter(str(f["valid"]) for _, f in ai_only)
    cost = sum(r["cost"] for r in runs) + sum(s["cost"] for s in res)
    L = [f"# Score: reviewer {a.version}", "",
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
            if h["type"] == "change_request" and h.get("matched_ai") is None:
                c = gold[(s["pr"], s["commit"])][h["id"]]
                L.append(f"- #{s['pr']} `{c.get('path') or 'overall review'}:{c.get('line_lo') or ''}` {c['author']}: "
                         f"{c['body'][:160].replace(chr(10), ' ')} ([link]({c['url']}))")
    (ROOT / "reports" / f"score_{a.version}.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:9]))


if __name__ == "__main__":
    main()

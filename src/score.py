"""Classify gold human comments and match them against a reviewer run.

For each PR in data/runs/<version>/:
  1. Classify each first-review human inline comment: change_request | question | nit | praise.
  2. For each change_request/nit, decide which AI finding (if any) raises the same issue.
One `claude -p` call per PR does both, without tools. Results go to
data/scores/<version>/<pr>.json and a summary to reports/score_<version>.md.

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

ROOT = pathlib.Path(__file__).resolve().parent.parent
DS = ROOT / "data" / "dataset"

PROMPT = """You are grading an AI code reviewer against human reviewers on LMCache PR #{pr}.

HUMAN comments (made on the same commit the AI reviewed), each with its code location and hunk:
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
   null. Be strict: a vaguely related finding is not a match.
3. For each AI finding, set "valid": true if it is a real, specific problem a maintainer would want
   fixed, false if it is wrong, speculative, or noise, "unsure" otherwise. Judge from the code
   shown; human silence does not make a finding invalid.

Answer with one JSON block only:
```json
{{"human": [{{"id": 0, "type": "...", "matched_ai": null}}],
  "ai": [{{"idx": 0, "valid": true, "why": "<=12 words"}}]}}
```"""


def gold_by_pr() -> dict[int, list[dict]]:
    """First-review human inline comments, grouped by PR."""
    g: dict[int, list[dict]] = C.defaultdict(list)
    for l in (DS / "comments.jsonl").open():
        c = json.loads(l)
        if (c["kind"] == "inline" and c["is_first_review_commit"] and not c["is_bot"]
                and not c["is_pr_author"] and c["author"]):
            g[c["pr"]].append(c)
    return g


def score_one(run: dict, gold: list[dict], out: pathlib.Path) -> dict:
    """Grade one PR run; cached on disk."""
    if out.exists():
        return json.loads(out.read_text())
    human = "\n\n".join(
        f"[{i}] {c['path']}:{c['line_lo']}-{c['line_hi']} by {c['author']}\n"
        f"hunk:\n{(c['diff_hunk'] or '')[-1200:]}\ncomment: {c['body'][:1500]}"
        for i, c in enumerate(gold))
    ai = "\n".join(f"[{i}] ({f.get('severity')}) {f.get('path')}:{f.get('line')} "
                   f"{f.get('title')}: {f.get('body', '')[:800]}"
                   for i, f in enumerate(run["findings"] or [])) or "(none)"
    r = llm.run(PROMPT.format(pr=run["pr"], human=human, ai=ai), timeout=900)
    res = llm.extract_json(r["text"])
    res.update(pr=run["pr"], cost=r["cost"], gold_ids=[c["id"] for c in gold])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    return res


def main() -> None:
    """Score every run of a version and write the summary report."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v0")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    gold = gold_by_pr()
    runs = [json.loads(p.read_text()) for p in sorted((ROOT / "data" / "runs" / a.version).glob("*.json"))]
    runs = [r for r in runs if r["findings"] is not None]
    sdir = ROOT / "data" / "scores" / a.version
    with cf.ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda r: score_one(r, gold[r["pr"]], sdir / f"{r['pr']}.json"), runs))

    types = C.Counter(h["type"] for s in res for h in s["human"])
    want = [h for s in res for h in s["human"] if h["type"] in ("change_request", "nit")]
    cr = [h for s in res for h in s["human"] if h["type"] == "change_request"]
    ai = [f for s in res for f in s["ai"]]
    matched = {(s["pr"], h["matched_ai"]) for s in res for h in s["human"] if h.get("matched_ai") is not None}
    ai_only = [(s["pr"], f) for s in res for f in s["ai"] if (s["pr"], f["idx"]) not in matched]
    n = lambda xs: sum(1 for x in xs if x.get("matched_ai") is not None)  # noqa: E731
    v = C.Counter(str(f["valid"]) for f in ai)
    vo = C.Counter(str(f["valid"]) for _, f in ai_only)
    cost = sum(r["cost"] for r in runs) + sum(s["cost"] for s in res)
    L = [f"# Score: reviewer {a.version}", "",
         f"PRs: {len(res)} · human first-review comments: {sum(types.values())} "
         f"({', '.join(f'{k} {c}' for k, c in types.most_common())})", "",
         f"- Recall on change requests: {n(cr)}/{len(cr)} ({n(cr) / max(len(cr), 1):.0%})",
         f"- Recall on change requests + nits: {n(want)}/{len(want)} ({n(want) / max(len(want), 1):.0%})",
         f"- AI findings: {len(ai)} ({len(ai) / max(len(res), 1):.1f}/PR); judged valid: "
         f"{v['True']} ({v['True'] / max(len(ai), 1):.0%}), invalid {v['False']}, unsure {v['unsure']}",
         f"- AI-only findings: {len(ai_only)}; judged valid {vo['True']}, invalid {vo['False']}, unsure {vo['unsure']}",
         f"- Cost (review + grading): ${cost:.2f}", "",
         "## Missed change requests", ""]
    gold = gold_by_pr()
    for s in res:
        for h in s["human"]:
            if h["type"] == "change_request" and h.get("matched_ai") is None:
                c = gold[s["pr"]][h["id"]]
                L.append(f"- #{s['pr']} `{c['path']}:{c['line_lo']}` {c['author']}: "
                         f"{c['body'][:160].replace(chr(10), ' ')} ([link]({c['url']}))")
    (ROOT / "reports" / f"score_{a.version}.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:9]))


if __name__ == "__main__":
    main()

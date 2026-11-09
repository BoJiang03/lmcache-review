"""Build eval samples: one per (PR, commit that a human reviewed).

Gold = every human (non-author, non-bot) review on that commit, merged across reviewers and
reviews: inline thread roots + substantive review bodies. PR conversation comments have no
commit and are left out.

History = the review discussion visible before the first human review on that commit
(inline threads with replies, review bodies, PR comments), so the AI sees what the human saw.

Output: data/dataset/samples.jsonl
"""

from __future__ import annotations

import collections as C
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DS = ROOT / "data" / "dataset"
RAW = ROOT / "data" / "raw" / "pr"
MIN_BODY = 80  # a review body alone counts as gold only if it says something


def history(pr: int, before: str) -> str:
    """Markdown transcript of the PR discussion strictly before `before` (ISO time)."""
    raw = json.loads((RAW / f"{pr}.json").read_text())
    ev = []
    for t in raw["reviewThreads"]["nodes"]:
        cs = [c for c in t["comments"]["nodes"] if c["createdAt"] < before]
        if cs:
            root = cs[0]
            lines = [f"- `{root['path']}` line {root.get('originalLine')} — thread:"]
            lines += [f"  - {(c.get('author') or {}).get('login')}: {c['body'][:1200]}" for c in cs]
            ev.append((root["createdAt"], "\n".join(lines)))
    for r in raw["reviews"]["nodes"]:
        if r.get("submittedAt") and r["submittedAt"] < before and (r.get("body") or "").strip():
            ev.append((r["submittedAt"], f"- review by {(r.get('author') or {}).get('login')} "
                                          f"({r['state']}): {r['body'][:1500]}"))
    for c in raw["comments"]["nodes"]:
        if c["createdAt"] < before:
            ev.append((c["createdAt"], f"- PR comment by {(c.get('author') or {}).get('login')}: "
                                       f"{c['body'][:1500]}"))
    return "\n".join(x for _, x in sorted(ev))


def main() -> None:
    """Write samples.jsonl."""
    prs = {json.loads(l)["pr"]: json.loads(l) for l in (DS / "prs.jsonl").open()}
    cs = [json.loads(l) for l in (DS / "comments.jsonl").open()]
    by: dict[tuple[int, str], list[dict]] = C.defaultdict(list)
    for c in cs:
        if c["is_bot"] or c["is_pr_author"] or not c["author"] or not c.get("commit"):
            continue
        if c["kind"] == "inline" or (c["kind"] == "review_body" and len(c["body"].strip()) >= MIN_BODY):
            by[(c["pr"], c["commit"])].append(c)
    out = []
    for (pr, commit), g in sorted(by.items()):
        t0 = min(c["created"] for c in g)
        out.append({"pr": pr, "commit": commit, "split": prs[pr]["split"], "time": t0,
                    "reviewers": sorted({c["author"] for c in g}),
                    "gold_ids": [c["id"] for c in g], "history": history(pr, t0)})
    (DS / "samples.jsonl").write_text("".join(json.dumps(s) + "\n" for s in out))
    cnt = C.Counter(s["split"] for s in out)
    print(f"samples: {dict(cnt)}; with history: {sum(bool(s['history']) for s in out)}")


if __name__ == "__main__":
    main()

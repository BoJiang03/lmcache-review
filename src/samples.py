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
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lmreview.history import format_history  # noqa: E402

DS = ROOT / "data" / "dataset"
RAW = ROOT / "data" / "raw" / "pr"
MIN_BODY = 80  # a review body alone counts as gold only if it says something


def history(pr: int, before: str) -> str:
    """Discussion of `pr` strictly before `before` (ISO time)."""
    return format_history(json.loads((RAW / f"{pr}.json").read_text()), before)


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

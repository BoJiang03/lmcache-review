"""Build eval samples: one per (PR, commit that a human reviewed).

Gold = every human (non-author, non-bot) review on that commit, merged across reviewers and
reviews: inline thread roots + substantive review bodies. PR conversation comments have no
commit and are left out.

History = the review discussion visible before the first human review on that commit
(inline threads with replies, review bodies, PR comments), so the AI sees what the human saw.

The commit is the PR head the reviewer saw (asof.commit_at): GitHub's commit for a review can be
one pushed after it. Comments whose head cannot be found are left out. A sample whose gold is only
approving review bodies is marked "approval_only" (no change asked; replays skip it by default).

Output: data/dataset/samples.jsonl
"""

from __future__ import annotations

import collections as C
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lmreview.asof import commit_at  # noqa: E402
from lmreview.config import Config  # noqa: E402
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
    repo, raws = str(Config().repo), {}
    by: dict[tuple[int, str], list[dict]] = C.defaultdict(list)
    moved = lost = 0
    for c in cs:
        if c["is_bot"] or c["is_pr_author"] or not c["author"] or not c.get("commit"):
            continue
        if c["kind"] == "inline" or (c["kind"] == "review_body" and len(c["body"].strip()) >= MIN_BODY):
            raw = raws.get(c["pr"]) or raws.setdefault(c["pr"], json.loads((RAW / f"{c['pr']}.json").read_text()))
            seen = commit_at(raw, c["created"], c["commit"], repo)
            if seen is None:
                lost += 1
                continue
            moved += seen != c["commit"]
            by[(c["pr"], seen)].append(c)
    out = []
    for (pr, commit), g in sorted(by.items()):
        t0 = min(c["created"] for c in g)
        out.append({"pr": pr, "commit": commit, "split": prs[pr]["split"], "time": t0,
                    "reviewers": sorted({c["author"] for c in g}),
                    "gold_ids": [c["id"] for c in g], "history": history(pr, t0),
                    "approval_only": all(c["kind"] == "review_body" and c["review_state"] == "APPROVED" for c in g)})
    (DS / "samples.jsonl").write_text("".join(json.dumps(s) + "\n" for s in out))
    cnt = C.Counter(s["split"] for s in out)
    print(f"samples: {dict(cnt)}; with history: {sum(bool(s['history']) for s in out)}; "
          f"approval only: {sum(s['approval_only'] for s in out)}; gold comments moved to the head "
          f"seen at review time: {moved}, left out (head not found): {lost}")


if __name__ == "__main__":
    main()

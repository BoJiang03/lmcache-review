"""Command line: `lmreview review|replay|score`."""

from __future__ import annotations

import argparse
import json
import sys

EFFORTS = ["low", "medium", "high", "xhigh", "max"]


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and dispatch to the library."""
    ap = argparse.ArgumentParser(prog="lmreview", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("review", help="review a PR now (local output only, posts nothing)")
    r.add_argument("pr", type=int)
    r.add_argument("--commit", help="review this commit instead of the PR head")
    r.add_argument("--version", default="v0", help="reviewer prompt version")
    r.add_argument("--effort", default="high", choices=EFFORTS)
    r.add_argument("--format", default="md", choices=["md", "json"])

    p = sub.add_parser("replay", help="eval: replay the reviewer on historical samples (costs LLM quota)")
    p.add_argument("--version", default="v0")
    p.add_argument("--split", default="test", choices=["train", "test", "holdout"])
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--effort", default="high", choices=EFFORTS)

    s = sub.add_parser("score", help="eval: grade replayed runs against human reviews (costs LLM quota)")
    s.add_argument("--version", default="v0")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--effort", default="medium", choices=EFFORTS, help="judge effort")

    a = ap.parse_args(argv)
    if a.cmd == "review":
        from .reviewer import review_pr, to_markdown
        out = review_pr(a.pr, a.commit, a.version, a.effort)
        print(json.dumps(out, indent=1) if a.format == "json" else to_markdown(out))
        if out["findings"] is None:
            sys.exit(1)
    elif a.cmd == "replay":
        from .replay import replay
        replay(a.version, a.split, a.limit, a.workers, a.effort)
    else:
        from .score import score
        print(score(a.version, a.workers, a.effort))


if __name__ == "__main__":
    main()

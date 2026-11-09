"""Command line: `lmreview sync|review|eval|distill`.

A reviewer is named <prompt>[+<rules>][@<effort>], e.g. v0b+r1@high (rules = rules/r1.jsonl).
Paid commands stop starting new LLM calls once --max-cost is reached. Nothing is posted to GitHub.
"""

from __future__ import annotations

import argparse
import json
import sys

from .reviewer import DEFAULT_REVIEWER

EFFORTS = ["low", "medium", "high", "xhigh", "max"]


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and dispatch to the library."""
    ap = argparse.ArgumentParser(prog="lmreview", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sync", help="update the dataset from GitHub (free)").add_argument(
        "--since", help="ISO date/time; default: last sync")

    r = sub.add_parser("review", help="review one PR now, or run a reviewer over a split (paid)")
    r.add_argument("pr", type=int, nargs="?", help="review this PR as it is now (local output only)")
    r.add_argument("--commit", help="with a PR: review this commit instead of the head")
    r.add_argument("--format", default="md", choices=["md", "json"])
    r.add_argument("--reviewer", default=DEFAULT_REVIEWER)
    r.add_argument("--split", default="test", choices=["train", "test", "new"])
    r.add_argument("--limit", type=int, default=10, help="samples (0 = all)")
    r.add_argument("--only-pr", action="append", help="only these samples: PR number (all its commits) or PR:commit")
    r.add_argument("--area", help="only samples whose PR touches this area (e.g. vllm-integration)")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--max-cost", type=float, default=15.0)

    e = sub.add_parser("eval", help="judge + human-only by area + signals (+ flips with --vs) (paid: judge); "
                                   "with --rules: rulebook coverage of held-out human comments (paid, cheap)")
    e.add_argument("--reviewer", default=DEFAULT_REVIEWER)
    e.add_argument("--rules", help="coverage mode: which entries of rules/<name> explain human comments")
    e.add_argument("--split", default="test", choices=["train", "test", "new"], help="coverage mode")
    e.add_argument("--area", help="coverage mode: only comments on PRs that touch this area")
    e.add_argument("--misses-of", help="coverage mode: only comments this reviewer missed")
    e.add_argument("--vs", help="compare against this reviewer")
    e.add_argument("--judge-effort", default="high", choices=EFFORTS)
    e.add_argument("--workers", type=int, default=4)
    e.add_argument("--max-cost", type=float, default=10.0)

    d = sub.add_parser("distill", help="distill train human comments into a new rulebook (paid)")
    d.add_argument("out", help="new rulebook name, e.g. r1")
    d.add_argument("--base", help="rulebook to extend")
    d.add_argument("--misses-of", help="only comments this reviewer missed (needs its eval on train)")
    d.add_argument("--area", help="only comments on PRs that touch this area; usually omit it, so team-wide standards voiced in other areas count too")
    d.add_argument("--limit", type=int, help="at most this many comments")
    d.add_argument("--reuse", help="reuse the attribution of this earlier distill run (same inputs); only re-merge")
    d.add_argument("--keep-unaddressed", action="store_true",
                   help="keep comments whose file never changed again (likely not taken)")
    d.add_argument("--effort", default="high", choices=EFFORTS)
    d.add_argument("--workers", type=int, default=4)
    d.add_argument("--max-cost", type=float, default=5.0, help="0 = print the plan and estimate only")

    a = ap.parse_args(argv)
    if a.cmd == "sync":
        from .sync import sync
        print(sync(a.since))
    elif a.cmd == "review" and a.pr:
        from .reviewer import review_pr, to_markdown
        out = review_pr(a.pr, a.commit, a.reviewer)
        print(json.dumps(out, indent=1) if a.format == "json" else to_markdown(out))
        if out["findings"] is None:
            sys.exit(1)
    elif a.cmd == "review":
        from .replay import replay
        print(f"spent ${replay(a.reviewer, a.split, a.limit or None, a.workers, a.max_cost, a.only_pr, a.area):.2f}")
    elif a.cmd == "eval" and a.rules:
        from .distill import coverage
        print(coverage(a.rules, a.split, a.area, a.misses_of, workers=a.workers, max_cost=a.max_cost))
    elif a.cmd == "eval":
        from .evaluate import evaluate
        print(evaluate(a.reviewer, a.vs, a.workers, a.judge_effort, a.max_cost))
    else:
        from .distill import distill
        print(distill(a.out, a.base, a.misses_of, a.area, a.limit, a.effort, a.workers, a.max_cost, a.reuse,
                      a.keep_unaddressed))


if __name__ == "__main__":
    main()

"""Command line: `lmreview sync|review|eval|distill|audit|regress`.

A reviewer is named <prompt>[+<rules>][@<effort>], e.g. v0b+r1@high (rules = rules/r1.jsonl).
Paid commands stop starting new LLM calls once --max-cost is reached. Nothing is posted to GitHub.
"""

from __future__ import annotations

import argparse
import json
import re
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
    r.add_argument("--parallel", type=int, default=1,
                   help="run the reviewer this many times at once and merge (one more agent run); same as x<n>")
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
    d.add_argument("--no-induce", action="store_true", help="skip step 6: principles over standalone entries")
    d.add_argument("--rewrite", action="store_true",
                   help="let generalize/merge rewrite and retire base entries (default: append-only parents)")
    d.add_argument("--misses-of", help="only comments this reviewer missed (needs its eval on train)")
    d.add_argument("--area", help="only comments on PRs that touch this area; usually omit it, so team-wide standards voiced in other areas count too")
    d.add_argument("--limit", type=int, help="at most this many comments")
    d.add_argument("--reuse", help="reuse the attribution of this earlier distill run (same inputs); only re-merge")
    d.add_argument("--keep-unaddressed", action="store_true",
                   help="keep comments whose file never changed again (likely not taken)")
    d.add_argument("--effort", default="high", choices=EFFORTS)
    d.add_argument("--workers", type=int, default=4)
    d.add_argument("--max-cost", type=float, default=5.0, help="0 = print the plan and estimate only")
    d.add_argument("--n", type=int, default=3, help="abstraction drafts merged per batch (1 = a single draft)")

    sub.add_parser("audit", help="suggest rulebook entries to retire: paths gone, findings judged invalid, "
                                 "contested (free)").add_argument("rules", help="rulebook name")
    v = sub.add_parser("vet", help="check a distill result before using it: generality flags, effect on its "
                                   "source comments, side effects on the base entries (paid; cached runs free)")
    v.add_argument("rules", help="the new rulebook")
    v.add_argument("--base", required=True, help="the rulebook it was built from")
    v.add_argument("--prompt", default="v0c")
    v.add_argument("--effort", default="high")
    v.add_argument("--suffix", default="-rc", help="reviewer suffix ('' for no rule check)")
    v.add_argument("--reps", type=int, default=1)
    v.add_argument("--max-cost", type=float, default=30.0, help="0 = print the plan only")
    v.add_argument("--all", action="store_true", help="replay every base entry, not only the affected ones")
    v.add_argument("--every-sample", action="store_true", help="new comments in every sample of a PR, not one")
    g = sub.add_parser("regress", help="after a rulebook change: check changed entries still explain their "
                                       "evidence and still fix their corrected tests (paid: replays)")
    g.add_argument("rules", help="the changed rulebook")
    g.add_argument("--base", help="the rulebook it was built from (default: check every tested entry)")
    g.add_argument("--reps", type=int, default=2, help="runs per replayed test; a case regresses if all miss")
    g.add_argument("--max-cost", type=float, default=10.0, help="0 = print the plan and estimate only")
    g.add_argument("--suffix", default="", help="appended to the replay reviewer, e.g. -rc for the rule check")

    a = ap.parse_args(argv)
    if getattr(a, "parallel", 1) > 1:
        name, sep, rep = a.reviewer.partition("#")  # keep a repeat tag such as #r2
        a.reviewer = re.sub(r"x\d+$", "", name) + f"x{a.parallel}" + sep + rep
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
    elif a.cmd == "regress":
        from .regress import regress
        print(regress(a.rules, a.base, a.reps, a.max_cost, suffix=a.suffix))
    elif a.cmd == "vet":
        from .vet import vet
        print(vet(a.rules, a.base, a.prompt, a.effort, a.suffix, a.reps, a.max_cost, a.all, a.every_sample))
    elif a.cmd == "audit":
        from .distill import audit
        print(audit(a.rules))
    else:
        from .distill import distill
        print(distill(a.out, a.base, a.misses_of, a.area, a.limit, a.effort, a.workers, a.max_cost, a.reuse,
                      a.keep_unaddressed, n=a.n, append_only=not a.rewrite, do_induce=not a.no_induce))


if __name__ == "__main__":
    main()

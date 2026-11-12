"""Command line. The process (state in lmreview/state/, see state.py):

    review --split train --only-pr ...   review samples with the book in use
    judge                                file the human comments: covered / to_distill
    distill                              to_distill comments -> a candidate book
    vet                                  promote what works as the next version; record what failed
    round PR ...                         all four on these samples, distill + vet until settled
    status | rollback vN | discard       look at / move the state

A reviewer is named <prompt>[+<book>][@<effort>][x<n>][-rc]; the default is the current prompt
(prompts/reviewer.md) with the book in use. Paid commands stop starting new LLM calls once
--max-cost is reached (0 = print the plan). Nothing is posted to GitHub.
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

    sub.add_parser("status", help="book in use, candidate, ledger counts (free)")
    j = sub.add_parser("judge", help="judge the current reviewer's runs and file the comments in the ledger (paid, cached)")
    j.add_argument("--prs", type=int, nargs="+")
    j.add_argument("--max-cost", type=float, default=10.0)
    o = sub.add_parser("round", help="review + judge + distill + vet on these samples (paid)")
    o.add_argument("prs", nargs="+", help="PR numbers or PR:commit")
    o.add_argument("--review-cost", type=float, default=30.0)
    o.add_argument("--judge-cost", type=float, default=10.0)
    o.add_argument("--distill-cost", type=float, default=5.0)
    o.add_argument("--vet-cost", type=float, default=30.0)
    sub.add_parser("rollback", help="make an earlier version the book in use, as a new version").add_argument(
        "version", help="e.g. v0001")
    sub.add_parser("discard", help="drop the candidate without vetting it")
    i = sub.add_parser("init", help="start the state from rules/<book>.jsonl as v0001")
    i.add_argument("book")
    i.add_argument("--note", default="")

    d = sub.add_parser("distill", help="ledger to_distill comments -> candidate book (paid); "
                                       "with OUT: the old named-book mode")
    d.add_argument("out", nargs="?", help="old mode: new rulebook name, e.g. r1")
    d.add_argument("--base", help="rulebook to extend")
    d.add_argument("--no-induce", action="store_true", help="skip step 6: principles over standalone entries")
    d.add_argument("--prs", type=int, nargs="+", help="only these train PRs")
    d.add_argument("--misses-of", metavar="REVIEWER",
                   help="learn from this reviewer's runs (normally <prompt>+BASE@high-rc): its misses and the "
                        "invalid findings citing BASE entries; unjudged runs are judged here (paid, cached)")
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
    v.add_argument("rules", nargs="?", help="old mode: the new rulebook (default: vet the candidate)")
    v.add_argument("--base", help="the rulebook it was built from (default: from rules/RULES.meta.json)")
    v.add_argument("--prompt", help="default: that of the runs distill learned from, else v0f")
    v.add_argument("--effort", help="default: as --prompt, else high")
    v.add_argument("--suffix", help="reviewer suffix, '' for no rule check (default: as --prompt, else -rc)")
    v.add_argument("--reps", type=int, default=1)
    v.add_argument("--max-cost", type=float, default=30.0, help="0 = print the plan only")
    v.add_argument("--all", action="store_true", help="replay every base entry, not only the affected ones")
    v.add_argument("--every-sample", action="store_true", help="new comments in every sample of a PR, not one")
    v.add_argument("--no-retry", action="store_true", help="count a failing case after one run")
    v.add_argument("--write", metavar="OUT", help="write rules/OUT.jsonl: RULES without the changes that failed")
    g = sub.add_parser("regress", help="after a rulebook change: check changed entries still explain their "
                                       "evidence and still fix their corrected tests (paid: replays)")
    g.add_argument("rules", help="the changed rulebook")
    g.add_argument("--base", help="the rulebook it was built from (default: check every tested entry)")
    g.add_argument("--reps", type=int, default=2, help="runs per replayed test; a case regresses if all miss")
    g.add_argument("--max-cost", type=float, default=10.0, help="0 = print the plan and estimate only")
    g.add_argument("--suffix", default="", help="appended to the replay reviewer, e.g. -rc for the rule check")

    a = ap.parse_args(argv)
    if a.cmd in ("judge", "round", "regress", "eval") or (a.cmd in ("review", "distill", "vet") and not (
            a.cmd == "review" and a.pr) and getattr(a, "max_cost", 1) > 0):
        from .config import Config
        from .progress import note, tee
        note(f"lmreview {' '.join(argv if argv is not None else sys.argv[1:])} | log: {tee(a.cmd, Config().data)}")
    if getattr(a, "parallel", 1) > 1:
        name, sep, rep = a.reviewer.partition("#")  # keep a repeat tag such as #r2
        rc = "-rc" if name.endswith("-rc") else ""
        name = re.sub(r"x\d+$", "", name.removesuffix("-rc"))
        a.reviewer = f"{name}x{a.parallel}{rc}" + sep + rep
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
    elif a.cmd in ("status", "judge", "round", "rollback", "discard", "init"):
        from . import state
        if a.cmd == "status":
            print(state.status())
        elif a.cmd == "judge":
            print(state.judge("train", set(a.prs or []) or None, a.max_cost))
        elif a.cmd == "round":
            print(state.round_(a.prs, a.review_cost, a.judge_cost, a.distill_cost, a.vet_cost))
        elif a.cmd == "rollback":
            print(f"book in use: {state.vname(state.rollback(int(a.version.lstrip('v'))))}")
        elif a.cmd == "discard":
            print(state.discard())
        else:
            print(f"book in use: {state.vname(state.init(a.book, a.note))}")
    elif a.cmd == "vet" and not a.rules:
        from .state import vet_step
        print(vet_step(a.max_cost, a.reps, a.all))
    elif a.cmd == "distill" and not a.out:
        from .state import distill_step
        print(distill_step(set(a.prs or []) or None, a.limit, a.effort, a.workers, a.max_cost))
    elif a.cmd == "vet":
        from .vet import vet
        print(vet(a.rules, a.base, a.prompt, a.effort, a.suffix, a.reps, a.max_cost, a.all, a.every_sample,
                  retry=not a.no_retry, write=a.write))
    elif a.cmd == "audit":
        from .distill import audit
        print(audit(a.rules))
    else:
        from .distill import distill
        print(distill(a.out, a.base, a.misses_of, a.area, a.limit, a.effort, a.workers, a.max_cost, a.reuse,
                      a.keep_unaddressed, n=a.n, do_induce=not a.no_induce, prs=a.prs))


if __name__ == "__main__":
    main()

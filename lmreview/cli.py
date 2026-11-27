"""Command line. The process (state in lmreview/state/, see state.py):

    review PR [--commit C]               review one PR as it is now (local output only)
    judge                                file the human comments: covered / to_distill
    distill                              to_distill comments -> a candidate book
    vet                                  promote what works as the next version; record what failed
    compress [--stage S] [--repair]      trim / merge the book in use -> a candidate (then vet)
    round PR ...                         all four on these samples, distill + vet until settled; compress + vet when the book is over [compress] words
    status | rollback vN | discard       look at / move the state
    watch add|set|run|status             follow a GitHub repository: review its open PRs, learn from its reviews

A reviewer is named <prompt>[+<book>][@<effort>][-rc|-ro]; the default is the current prompt
(prompts/reviewer.md) with the book in use. Paid commands stop starting new LLM calls once
--max-cost is reached (0 = print the plan). Nothing is posted to GitHub.
"""

from __future__ import annotations

import argparse
import json
import sys

from .reviewer import DEFAULT_REVIEWER
from .settings import get

EFFORTS = ["low", "medium", "high", "xhigh", "max"]


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and dispatch to the library."""
    ap = argparse.ArgumentParser(prog="lmreview", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sync", help="update the dataset from GitHub (free)").add_argument(
        "--since", help="ISO date/time; default: last sync")

    r = sub.add_parser("review", help="review one PR now (paid)")
    r.add_argument("pr", type=int, help="review this PR as it is now (local output only)")
    r.add_argument("--commit", help="with a PR: review this commit instead of the head")
    r.add_argument("--format", default="md", choices=["md", "json"])
    r.add_argument("--reviewer", default=DEFAULT_REVIEWER)
    r.add_argument("--out", help="also write the review to OUT.json and OUT.md")

    w = sub.add_parser("watch", help="follow GitHub repositories with the gh login: review open PRs when their head "
                                     "changes, learn from human reviews once they settle (paid; see lmreview/watch.py)")
    ws = w.add_subparsers(dest="action", required=True)
    wa = ws.add_parser("add", help="start watching OWNER/NAME: its own home, settings overlay and book (free)")
    wa.add_argument("repo")
    wa.add_argument("--since", help="collect PRs created from this date (YYYY-MM-DD); default today")
    wa.add_argument("--backfill", action="store_true", help="also learn from samples before now (from --since)")
    wa.add_argument("--book", help="rulebook .jsonl to start from (default: with the lmcache prompts, the LMCache "
                    "book in use; else no entries)")
    wa.add_argument("--prompts", default="auto", help="lmcache | generic | DIR with reviewer.md, rulecheck.md, rulepick.md; "
                    "auto (default): lmcache for the LMCache organization's repositories, else generic")
    for p_ in (wa, ws.add_parser("set", help="change the settings of a watched repository")):
        if p_ is not wa:
            p_.add_argument("repo")
        p_.add_argument("--review", action=argparse.BooleanOptionalAction, default=None, help="review open PRs")
        p_.add_argument("--learn", action=argparse.BooleanOptionalAction, default=None, help="learn from human reviews")
        p_.add_argument("--post", action=argparse.BooleanOptionalAction, default=None,
                        help="post each review as a PR comment from the gh account (default: off, local only)")
        p_.add_argument("--drafts", action=argparse.BooleanOptionalAction, default=None, help="also review draft PRs")
        p_.add_argument("--settle-hours", type=float, help="a sample of an open PR is learned once its commit is not the "
                        "head, or no human commented on it for this long (default 24)")
        p_.add_argument("--max-reviews", type=int, help="reviews per cycle per repository (default 5)")
        p_.add_argument("--max-learn", type=int, help="samples per round per cycle (default 3)")
        p_.add_argument("--round-cost", type=float, help="cap ($) for each step of a round (default: round's own)")
        p_.add_argument("--review-since", help="ISO time (e.g. 2026-11-27T21:00:00Z) or 'now': open PRs last updated "
                        "before it are not reviewed, so a backlog of old PRs is left alone")
    wr = ws.add_parser("run", help="cycle: review + learn on every watched repository (or these)")
    wr.add_argument("repos", nargs="*")
    wr.add_argument("--once", action="store_true", help="one cycle, then exit")
    wr.add_argument("--interval", type=int, default=600, help="seconds between cycles (default 600)")
    wr.add_argument("--prs", type=int, nargs="+", help="one cycle that reviews just these PRs (again, if reviewed)")
    wr.add_argument("--dry-run", action="store_true", help="list what would be reviewed and learned; no LLM calls, "
                    "nothing posted (sync still updates the local dataset)")
    wst = ws.add_parser("start", help="run the watcher in the background, detached from the terminal (log: <watch root>/watch.log)")
    wst.add_argument("repos", nargs="*")
    wst.add_argument("--interval", type=int, default=600, help="seconds between cycles (default 600)")
    ws.add_parser("stop", help="stop the background watcher")
    wt = ws.add_parser("retract", help="take back the AI reviews on a PR: delete their inline comments, "
                                       "replace the summary, minimize the review (GitHub cannot delete a submitted review)")
    wt.add_argument("repo")
    wt.add_argument("pr", type=int)
    wt.add_argument("--review", type=int, help="only this review id (default: every AI review on the PR)")
    wp = ws.add_parser("repost", help="post the saved review of a PR's head again, in the current format (no new review)")
    wp.add_argument("repo")
    wp.add_argument("pr", type=int)
    ws.add_parser("status", help="the background watcher, watched repositories and their progress (free)")

    sub.add_parser("status", help="book in use, candidate, ledger counts (free)")
    j = sub.add_parser("judge", help="judge the current reviewer's runs and file the comments in the ledger (paid, cached)")
    j.add_argument("--prs", type=int, nargs="+")
    j.add_argument("--max-cost", type=float, default=get("budget", "judge"))
    rt = sub.add_parser("retain", help="re-review the samples of covered / resolved points with the production reviewer "
                        "([retain] reps runs) and send points not caught every time back to to_distill (paid, cached)")
    rt.add_argument("--prs", type=int, nargs="+")
    rt.add_argument("--samples", nargs="+", help="PR:commit8 (default: every sample of a learned point)")
    rt.add_argument("--reps", type=int, default=get("retain", "reps"))
    rt.add_argument("--covered", action="store_true", help="also check covered points (found without an entry); "
                    "needs a --reviewer with the main review, a rule check alone cannot find them")
    rt.add_argument("--reviewer", help="check with this reviewer's runs instead (same prompt and book; default: the rule check, -ro)")
    rt.add_argument("--max-cost", type=float, default=get("budget", "retain"))
    o = sub.add_parser("round", help="review + judge + distill + vet on these samples, then compress + vet when the book is over [compress] words (paid)")
    o.add_argument("prs", nargs="+", help="PR numbers or PR:commit")
    o.add_argument("--review-cost", type=float, default=get("budget", "round")["review"])
    o.add_argument("--judge-cost", type=float, default=get("budget", "round")["judge"])
    o.add_argument("--confirm-cost", type=float, default=get("budget", "round")["confirm"],
                   help="second run of the samples with new misses, before distill (0 = plan; cached runs still count)")
    o.add_argument("--distill-cost", type=float, default=get("budget", "round")["distill"])
    o.add_argument("--vet-cost", type=float, default=get("budget", "round")["vet"])
    sub.add_parser("rollback", help="make an earlier version the book in use, as a new version").add_argument(
        "version", help="e.g. v0001")
    sub.add_parser("discard", help="drop the candidate without vetting it")
    cp = sub.add_parser("compress", help="make the book in use smaller (trim or merge) as a candidate; "
                                         "`lmreview vet` keeps what loses no proven case (paid)")
    cp.add_argument("--max-cost", type=float, default=get("budget", "compress"), help="drafts, final texts, verify")
    cp.add_argument("--stage", choices=["trim", "merge"], default="merge",
                    help="trim: rewrite long entries shorter; merge: merge or regroup entries")
    cp.add_argument("--repair", action="store_true", help="rewrite only what vet undid on this stage's last candidate")
    i = sub.add_parser("init", help="start the state as v0001 from a rulebook .jsonl (an empty file: no entries)")
    i.add_argument("book")
    i.add_argument("--note", default="")
    i.add_argument("--seeded-from", help="where the book comes from, when it is another repository's "
                   "(e.g. 'LMCache/LMCache v0036'); shown with the reviewer")

    d = sub.add_parser("distill", help="ledger to_distill comments -> candidate book (paid)")
    d.add_argument("--compress", action="store_true", help="run even with nothing to_distill, "
                   "to shrink the book (merge / generalize entries that ask for the same change)")
    d.add_argument("--prs", type=int, nargs="+", help="only these train PRs")
    d.add_argument("--limit", type=int, help="at most this many comments")
    d.add_argument("--effort", default=get("distill", "effort"), choices=EFFORTS)
    d.add_argument("--workers", type=int, default=4)
    d.add_argument("--max-cost", type=float, default=get("budget", "distill"), help="0 = print the plan and estimate only")

    v = sub.add_parser("vet", help="check the candidate before using it: generality flags, effect on its "
                                   "source comments, side effects on the base entries (paid; cached runs free)")
    v.add_argument("--reps", type=int, default=get("vet", "reps"))
    v.add_argument("--max-cost", type=float, default=get("budget", "vet"), help="0 = print the plan only")
    v.add_argument("--all", action="store_true", help="replay every base entry, not only the affected ones")

    a = ap.parse_args(argv)
    if a.cmd in ("judge", "round", "retain") or (a.cmd in ("distill", "vet", "compress") and getattr(a, "max_cost", 1) > 0):
        from .config import Config
        from .progress import note, tee
        note(f"lmreview {' '.join(argv if argv is not None else sys.argv[1:])} | log: {tee(a.cmd, Config().data)}")
    if a.cmd == "watch":
        from . import watch
        keys = ("review", "learn", "post", "drafts", "settle_hours", "max_reviews", "max_learn", "round_cost", "review_since")
        opts = {k: getattr(a, k) for k in keys if getattr(a, k, None) is not None}
        if opts.get("review_since") == "now":
            opts["review_since"] = watch._iso(watch._now())
        if a.action == "add":
            print(watch.add(a.repo, a.since, a.book, a.backfill, a.prompts, **opts))
        elif a.action == "set":
            print(watch.set_(a.repo, **opts))
        elif a.action == "run":
            watch.run(a.repos or None, a.once, a.interval, a.dry_run, set(a.prs or []) or None)
        elif a.action == "start":
            print(watch.start(a.repos or None, a.interval))
        elif a.action == "stop":
            print(watch.stop())
        elif a.action == "retract":
            print(watch.retract(a.repo, a.pr, a.review))
        elif a.action == "repost":
            print(watch.repost(a.repo, a.pr))
        else:
            print(watch.status())
    elif a.cmd == "sync":
        from .sync import sync
        print(sync(a.since))
    elif a.cmd == "review":
        from .reviewer import review_pr, to_markdown
        out = review_pr(a.pr, a.commit, a.reviewer)
        md = to_markdown(out)
        if a.out and out["findings"] is not None:
            import pathlib
            from .reviewer import github_review
            pathlib.Path(a.out + ".json").write_text(json.dumps(out, indent=1))
            pathlib.Path(a.out + ".md").write_text(md)
            for name, inline in ((".ghreview.json", True), (".ghreview-flat.json", False)):  # flat: if GitHub refuses inline
                pathlib.Path(a.out + name).write_text(json.dumps(github_review(out, inline), indent=1))
        print(json.dumps(out, indent=1) if a.format == "json" else md)
        if out["findings"] is None:
            sys.exit(1)
    elif a.cmd in ("status", "judge", "round", "rollback", "discard", "init"):
        from . import state
        if a.cmd == "status":
            print(state.status())
        elif a.cmd == "judge":
            print(state.judge("train", set(a.prs or []) or None, a.max_cost))
        elif a.cmd == "round":
            print(state.round_(a.prs, a.review_cost, a.judge_cost, a.distill_cost, a.vet_cost,
                               confirm_cost=a.confirm_cost))
        elif a.cmd == "rollback":
            print(f"book in use: {state.vname(state.rollback(int(a.version.lstrip('v'))))}")
        elif a.cmd == "discard":
            print(state.discard())
        else:
            print(f"book in use: {state.vname(state.init(a.book, a.note, a.seeded_from))}")
    elif a.cmd == "retain":
        if a.covered and not a.reviewer:
            sys.exit("retain --covered needs --reviewer with the main review: a rule check alone cannot find covered points")
        from .state import retain_step
        print(retain_step(set(a.prs or []) or None, a.max_cost, a.reps, samples=set(a.samples or []) or None, reviewer=a.reviewer,
                          statuses=("covered", "resolved") if a.covered else ("resolved",)))
    elif a.cmd == "compress":
        from .state import compress_step
        print(compress_step(a.max_cost, stage=a.stage, repair=a.repair))
    elif a.cmd == "vet":
        from .state import vet_step
        print(vet_step(a.max_cost, a.reps, a.all))
    else:
        from .state import distill_step
        print(distill_step(set(a.prs or []) or None, a.limit, a.effort, a.workers, a.max_cost,
                           compress=a.compress))


if __name__ == "__main__":
    main()

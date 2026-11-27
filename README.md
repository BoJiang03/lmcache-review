# lmreview

An AI pull-request reviewer for any GitHub repository, and the process that teaches it what that
repository's reviewers ask for. Point it at a repository: it reviews pull requests, and it learns team
rules from the team's own review comments, one rulebook per repository. Every rule a review cites links
to the comments it was learned from.

It runs with your own `gh` login and your own logged-in Claude Code. Two repositories use it today:
[LMCache/LMCache](https://github.com/LMCache/LMCache) (its rulebook is the one in `lmreview/state/`) and
[LMCache/LMCache_inprocess](https://github.com/LMCache/LMCache_inprocess) (followed with `lmreview watch`).
It started with LMCache, so this checkout's defaults
(`lmreview/config.toml`, `lmreview/state/`) are LMCache's, and any other repository gets its own with
`lmreview watch add`.

## Quick start

Needs `claude` (logged in; reviews bill your account), `gh` (`gh auth login`), `git` and Python 3.10+.

```
bin/lmreview watch add OWNER/NAME                     # set the repository up (free): its home, prompts, rulebook
bin/lmreview review https://github.com/OWNER/NAME/pull/123     # review one PR now, locally
bin/lmreview watch run OWNER/NAME --once --dry-run    # what following it would review and learn (free)
bin/lmreview watch set OWNER/NAME --post --review-since now    # post reviews on the PRs updated from now on
bin/lmreview watch start                              # follow it in the background
```

A review takes 5–15 minutes and costs about $0.70 (median of 110 reviews; p90 $1.50), more for large PRs.

## Review a PR

In Claude Code, install the plugin and ask "lmreview <PR link>":

```
/plugin install lmreview --marketplace BoJiang03/lmreview
```

From a checkout: `bin/lmreview review <PR number or link> [--commit C] [--format md|json]`. A PR of a
repository other than this checkout's own (LMCache/LMCache) runs in that repository's home, so it uses
that repository's rules; `lmreview watch add` creates the home. See docs/usage.md.

## Follow a repository

`lmreview watch` follows repositories the `gh` login can read. Each cycle, per repository:

- **review**: every open PR whose head changed is reviewed once (drafts and bots skipped; at most
  `max_reviews` per cycle; `--review-since` leaves an older backlog alone). The review is kept in the
  repository's home and, with `--post`, posted as a GitHub review.
- **learn**: `sync` collects the human reviews; every sample that has settled (PR closed, commit no longer
  the head, or no human comment for `settle_hours`) is learned from with `round`, at most `max_learn` per
  cycle. Only reviews made after `add` are learned from, unless `--backfill`.

```
bin/lmreview watch add OWNER/NAME [--since DATE] [--backfill] [--book B.jsonl] [--prompts auto|lmcache|generic|DIR]
bin/lmreview watch set OWNER/NAME [--post] [--no-learn] [--review-since now] [--max-reviews 3] [--book-repo OWNER/NAME] ...
bin/lmreview watch run [OWNER/NAME ...] [--once] [--prs N ...] [--dry-run]
bin/lmreview watch start [--interval 600] | stop | status     # in the background, detached; log: <watch root>/watch.log
bin/lmreview watch retract OWNER/NAME PR | repost OWNER/NAME PR
```

Every repository has its own home, `~/.cache/lmreview/watch/<owner>__<name>/`: its clone, dataset, runs,
rulebook (numbered from v0001), prompts and logs. Repositories never share a book or a cache.

### What a posted review looks like

One GitHub review (event COMMENT: it neither approves nor blocks): a summary, and an inline comment per
finding on the line of the diff it is about; a finding not on the diff goes in the summary. Each finding
says what it rests on: a **team rule** (linked to the rule) or **general review** (the reviewer's own
judgement). Its suggestion, the rule's text, the comments the rule was learned from, and other places
it involves are folded under it. A mention of another finding links to that finding's comment.

With `--book-repo OWNER/NAME` (a public repository), each rulebook version is published once to its
`rulebooks` branch as `<owner>/<name>/vNNNN.md`, every rule with the review comments it came from, and the
review links there. GitHub cannot delete a submitted review: `watch retract` deletes its inline comments,
replaces its summary and minimizes it. Posted text carries a hidden marker, so the reviewer never learns
from its own comments.

### Another project

`watch add` picks the prompts: the LMCache ones (`lmreview/prompts/`) for repositories of the LMCache
organization, the generic ones (`lmreview/prompts/generic/`) for any other, rendered into the home with the
repository's name and GitHub description; edit them there for the project's conventions. `--book` starts
from another repository's rulebook instead of an empty one (LMCache_inprocess started from LMCache's).
The project's name, description and source file types are `[project]` in the home's `config.toml`; its main
branch and the dates that split train and test samples are `[dataset]`.

## How it learns

The same process for every repository, on its own samples and its own book.

```python
runs     = review(prs, reviewer=(prompt, book))          # AI findings on PRs humans reviewed
new_book = distill(book, runs, human_comments)           # rules for what the book still misses
book     = vet(book, new_book, human_comments)           # keep only what works and breaks nothing
```

```
           ┌──────────── review ────────────┐
           │  prompt + book in use (vNNNN)   │
           └───────────────┬────────────────┘
                           ▼
                judge: each human comment
              ┌────────────┴────────────┐
           covered                 to_distill
                                        │
                                   distill ──► candidate
                                        │
                                       vet
                     ┌──────────────────┼──────────────────┐
                 resolved          not_rulable        failed attempt
              (next version)    (context, not an     (back to to_distill
                                 issue, declined)     with the reason;
                                                      after 3/2/1 by tier: needs_human)
```

- **A sample** is one PR commit a human reviewed. Its human comments are the ground truth.
- **review** runs the reviewer `<prompt>+<book>@<effort>[-rc]`. Runs are cached by that name in
  `data/runs/`, which is how the steps hand data to each other.
- **judge** matches the AI findings against the human comments. The comments are annotated once per
  sample first (split into points, each with a type and severity; cached), so every judge call sees
  them the same way, and each point of a long review is matched and learned on its own. A finding
  that cites a rule and is judged invalid is a failure signal for that rule.
- **distill** turns missed comments into rules in two steps. attribute decides which comments are
  worth learning and what each asked the author to do. write sees the whole book, the failure signals
  and those comments (with the reviewer's words and diff hunk) and decides per comment: evidence for an
  existing entry, generalize or revise one, or add a new one. A comment whose entry already exists and
  still missed it is marked a retry. consolidate then tidies the whole book: several drafts run in
  parallel and only the changes most of them agree on are made (merge entries that ask for the same
  change, rewrite new entries at the wrong level, flag contradictions). Its last sub-step verifies
  every change to an existing entry's text: the entry must act differently on the case that motivated
  the change, or a merge must act exactly as what it replaces. A pure rephrasing, or a difference no
  case asks for, is undone.
- **vet** reviews again with the old and the new book where they differ. The part that works
  becomes the next version. A change that fails is not just reverted: its comments go back to
  distill with the reason, so the next attempt is written differently.

## What a rule must earn

- **A comment of its own.** Every new rule must explain at least one missed human comment that no
  other rule explains. A parent that only groups existing rules is dropped.
- **A reason to change.** A rule is revised or retired only on a failure signal or a human comment
  that asks for the opposite, and the revise must say what it now covers differently. Rewording
  is refused.
- **Principle level.** A rule names a kind of situation, not one PR. It reaches the reviewer as
  when / expect / why only; its examples stay out of the prompt.

## State

A repository's state is one directory: `lmreview/state/` (in git) for this checkout's repository (LMCache/LMCache), `<home>/state/` for a watched one:

| File | What |
|---|---|
| `HEAD.json`, `book.jsonl` | the book in use |
| `history/vNNNN.*` | every version, with how it was made |
| `candidate/` | a distilled or compressed book waiting for vet |
| `ledger.jsonl` | every human comment and its status, keyed by (PR, commit) |
| `prompts/` | snapshots of the reviewer prompts (`lmreview/prompts/reviewer.md`, `rulecheck.md`, `rulepick.md`), by prompt id |
| `log.jsonl` | what each step did |
| `sources.json` | the comments behind rules copied from another repository's book (for provenance links) |

All settings (review and rule-check effort, judge, distill, vet, retain, compress, cost caps, paths) are in
`lmreview/config.toml`, commented. `LMREVIEW_CONFIG=<file>` merges a file with only the keys you change on top.

## Commands

```
bin/lmreview review PR|LINK [--commit C] # review one PR now (local output)
bin/lmreview status                       # book in use, candidate, ledger counts
bin/lmreview round 3359 3461:a58f5c9c     # review + judge + distill + vet on these samples, then compress if big
bin/lmreview judge | distill | vet        # one step at a time
bin/lmreview retain                       # re-check learned points; unstable ones go back to to_distill
bin/lmreview compress [--stage trim|merge] [--repair]   # shrink the book in use into a candidate (then vet)
bin/lmreview init BOOK.jsonl | rollback v0001 | discard        # start / move the state
bin/lmreview sync                         # update the dataset from GitHub (free)
```

A bare PR number in `round` means its commits that still have a missed comment (all of them if none
has been judged yet). Paid commands take a cost cap (default: none in effect, $1000) and stop starting new LLM calls when they
reach it (`--max-cost 0` prints the plan). Every run prints timestamped progress and is logged to `data/logs/`.

## Data

`lmreview sync` collects recently updated PRs from GitHub into `data/raw/pr/`, then runs:

```
src/fetch_commits.py    # recover force-pushed commits into the clone
src/derive.py           # -> data/dataset/{prs,comments}.jsonl
src/samples.py          # -> data/dataset/samples.jsonl
```

`data/` is not tracked: raw data, the dataset, runs, scores, and a clone of the repository (a watched repository's are in its home).

## More

- docs/usage.md: the guide for reviewers and operators
- docs/mechanism.md: the design and why

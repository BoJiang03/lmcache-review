# lmcache-review

An AI first-round reviewer for LMCache pull requests, and the process that teaches it what the
team's reviewers ask for. It runs locally and posts nothing to GitHub.

Proposal: https://claude.ai/artifact/TtFYk2eZWjUi13YxCnf9tt

## Review a PR

In Claude Code:

```
/plugin install lmreview --marketplace BoJiang03/lmcache-review
```

Then ask "lmreview 5876". From a checkout: `bin/lmreview review 5876`. One review costs about
$3–4. Treat the output as a first round: it does not replace a human review. See docs/usage.md.

## How it learns

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
                                                      after 2: needs_human)
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

Everything the process needs is in `lmreview/state/`, in git:

| File | What |
|---|---|
| `HEAD.json`, `book.jsonl` | the book in use |
| `history/vNNNN.*` | every version, with how it was made |
| `candidate/` | a distilled or compressed book waiting for vet |
| `ledger.jsonl` | every human comment and its status, keyed by (PR, commit) |
| `prompts/` | snapshots of the reviewer prompts (`lmreview/prompts/reviewer.md`, `rulecheck.md`, `rulepick.md`), by prompt id |
| `log.jsonl` | what each step did |

All settings (review and rule-check effort, judge, distill, vet, retain, compress, cost caps, paths) are in
`lmreview/config.toml`, commented. `LMREVIEW_CONFIG=<file>` merges a file with only the keys you change on top.

## Commands

```
bin/lmreview review 5876 [--commit C]     # review one PR now (local output only)
bin/lmreview status                       # book in use, candidate, ledger counts
bin/lmreview round 3359 3461:a58f5c9c     # review + judge + distill + vet on these samples, then compress if big
bin/lmreview judge | distill | vet        # one step at a time
bin/lmreview retain                       # re-check learned points; unstable ones go back to to_distill
bin/lmreview compress [--stage trim|merge] [--repair]   # shrink the book in use into a candidate (then vet)
bin/lmreview init BOOK | rollback v0001 | discard        # start / move the state
bin/lmreview sync                         # update the dataset from GitHub (free)
```

A bare PR number in `round` means its commits that still have a missed comment (all of them if none
has been judged yet). Paid commands take a cost cap and stop starting new LLM calls when they reach
it (`--max-cost 0` prints the plan). Every run prints timestamped progress and is logged to `data/logs/`.

## Data

`lmreview sync` collects recently updated PRs from GitHub into `data/raw/pr/`, then runs:

```
src/fetch_commits.py    # recover force-pushed commits into data/LMCache
src/derive.py           # -> data/dataset/{prs,comments}.jsonl
src/samples.py          # -> data/dataset/samples.jsonl
```

`data/` is not tracked: raw data, the dataset, runs, scores, and a full LMCache clone.

## More

- docs/usage.md: the guide for reviewers and operators
- docs/mechanism.md: the design and why

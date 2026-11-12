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
- **judge** matches the AI findings against the human comments. A finding that cites a rule and is
  judged invalid is a failure signal for that rule.
- **distill** turns missed comments into rules (attribute, cluster, abstract, update the book). It
  sees each comment with its diff hunk, and each failure signal with the code it pointed at.
- **vet** reviews again with the old and the new book where they differ. The part that works
  becomes the next version. A change that fails is not just reverted: its comments go back to
  distill with the reason, so the next attempt is written differently.

## What a rule must earn

- **A comment of its own.** Every new rule must explain at least one missed human comment that no
  other rule explains. A parent that only groups existing rules is dropped. (Principle induction
  over the whole book, step 6, made such parents; it is off unless `--induce`.)
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
| `candidate/` | a distilled book waiting for vet |
| `ledger.jsonl` | every human comment and its status, keyed by (PR, commit) |
| `prompts/` | snapshots of the reviewer prompt (`lmreview/prompts/reviewer.md`) |
| `log.jsonl` | what each step did |

The reviewer settings (effort, rule check) are in `lmreview/reviewer.json`.

## Commands

```
bin/lmreview status                       # book in use, candidate, ledger counts
bin/lmreview round 3359 3461:a58f5c9c     # review + judge + distill + vet on these samples
bin/lmreview review|judge|distill|vet     # one step at a time
bin/lmreview rollback v0001 | discard     # move the state
bin/lmreview sync                         # update the dataset from GitHub (free)
bin/lmreview eval | regress | audit       # measurements and checks
```

A bare PR number in `round` means its commits that still have a missed comment. Paid commands take
a cost cap and stop starting new LLM calls when they reach it. Every run prints timestamped
progress and is logged to `data/logs/`.

## Data

```
python3 -I src/collect.py          # GitHub GraphQL -> data/raw/pr/<N>.json
python3 -I src/fetch_commits.py    # recover force-pushed commits into data/LMCache
python3 -I src/derive.py           # -> data/dataset/{prs,comments}.jsonl
python3 -I src/samples.py          # -> data/dataset/samples.jsonl
```

`data/` is not tracked: raw data, the dataset, runs, scores, and a full LMCache clone.

## More

- docs/usage.md: the guide for reviewers and operators
- docs/mechanism.md: the design and why

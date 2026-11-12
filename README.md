# lmcache-review

AI first-round PR review for LMCache: data, evaluation harness, and review process.
Proposal: https://claude.ai/artifact/TtFYk2eZWjUi13YxCnf9tt

## Core design

```python
runs     = review(prs, reviewer=(prompt, effort, old_book))       # AI findings, cached by reviewer name
new_book = distill(old_book, runs, human_comments)                # learn what old_book still misses
next_book, verdict = vet(old_book, new_book, human_comments)      # keep only what works and breaks nothing
```

- **review** runs the reviewer `<prompt>+<book>@<effort>[-rc]` on PRs. Runs are cached under
  `data/runs/<reviewer>/`, so the reviewer name is how the steps hand data to each other.
- **distill** learns from old_book's own runs. It judges them against the human comments: missed
  comments become new rules or evidence, and findings that cite a rule but are judged invalid are
  signals to revise or retire it. It is incremental: comments in `<book>.meta.json` `seen` are skipped.
- **vet** reviews again with both books where they differ, judges against the human comments, and
  gives PASS / FAIL / INCOMPLETE. With `--write`, it writes next_book: the new entries that work,
  with every change that made something worse reverted.
- The next round starts with `review(prs', reviewer=(prompt, effort, next_book))`.
- A rule reaches the reviewer as its principle only (when, expect, why), never its examples.

Commands: `lmreview review`, `lmreview distill`, `lmreview vet` (docs/usage.md). Design notes:
docs/mechanism.md.

## Phases
- P0 dataset: historical PRs, first-review commits, review comments, `addressed` labels
- P1 evaluation harness (finding alignment + metrics), validated on gemini-code-assist history
- P2 reviewer v0 (generic), P3 distilled LMCache process, P4 online shadow, P5 live per area

## P0 pipeline (read-only)
    python3 -I src/collect.py          # GitHub GraphQL -> data/raw/pr/<N>.json
    python3 -I src/fetch_commits.py    # recover force-pushed commits into data/LMCache
    python3 -I src/derive.py           # -> data/dataset/{prs,comments}.jsonl

`data/` is not tracked (raw data + a full LMCache clone with PR refs).

## Usage
Reviewers: `lmreview review <PR>` (local only, posts nothing). Full guide for reviewers and operators: docs/usage.md.

## Tool (pre-launch)
    bin/lmreview sync                                   # update dataset from GitHub (free)
    bin/lmreview review 5876                            # review one PR now (local output only)
    bin/lmreview review --reviewer v0b@high --split test --max-cost 15
    bin/lmreview eval --reviewer v0b@high --vs v0@high  # judge + human-only by area + signals + flips
    bin/lmreview review --reviewer v0f+pk9@high-rc --split train --max-cost 30
    bin/lmreview distill pk10 --base pk9 --misses-of v0f+pk9@high-rc --prs N,...   # --max-cost 0 = plan
    bin/lmreview vet pk10 --base pk9 --write pk10v                                 # --max-cost 0 = plan
    DRY=1 scripts/misses_pipeline.sh vllm-integration 30  # one misses-driven round (dry run)

Reviewer names: `<prompt>[+<rules>][@<effort>][x<n>][-rc]`. Design: docs/mechanism.md.

## Install (reviewers)

In Claude Code:

```
/plugin install lmreview --marketplace BoJiang03/lmcache-review
```

Then ask "lmreview <PR number>". See docs/usage.md.

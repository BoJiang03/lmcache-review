# lmcache-review

AI first-round PR review for LMCache: data, evaluation harness, and review process.
Proposal: https://claude.ai/artifact/TtFYk2eZWjUi13YxCnf9tt

## Phases
- P0 dataset: historical PRs, first-review commits, review comments, `addressed` labels
- P1 evaluation harness (finding alignment + metrics), validated on gemini-code-assist history
- P2 reviewer v0 (generic), P3 distilled LMCache process, P4 online shadow, P5 live per area

## P0 pipeline (read-only)
    python3 -I src/collect.py          # GitHub GraphQL -> data/raw/pr/<N>.json
    python3 -I src/fetch_commits.py    # recover force-pushed commits into data/LMCache
    python3 -I src/derive.py           # -> data/dataset/{prs,comments}.jsonl

`data/` is not tracked (raw data + a full LMCache clone with PR refs).

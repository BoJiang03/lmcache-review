# Eval: v0b@high

## Score (vs human reviews on the same commit)

Samples (PR, reviewed commit): 8 · human review comments: 18 (change_request 13, nit 2, praise 2, question 1)

- Recall on change requests: 8/13 (62%)
- Recall on change requests + nits: 9/15 (60%)
- Recall on serious human comments (blocker/major): 3/5 (60%)
- AI findings: 65 (8.1/PR); judged valid: 57 (88%), invalid 8, unsure 0
- AI-only findings: 57; judged valid 49, invalid 8, unsure 0

## Human-only on change requests (pre-launch target: lower is better)

| split | area | human change requests | human-only (AI missed) | rate |
| --- | --- | --- | --- | --- |
| test | all | 13 | 5 | 38% |
| test | vllm-integration | 5 | 5 | 100% |
| test | mp | 4 | 0 | 0% |
| test | tests | 2 | 0 | 0% |
| test | distributed | 1 | 0 | 0% |
| test | (overall review) | 1 | 0 | 0% |

## Passive signals

Samples: 8 · findings: 65. Signals only support a finding; absence means nothing.

| findings | n | changed later in PR | on merged PRs | changed after merge | later human comment at same place |
| --- | --- | --- | --- | --- | --- |
| all | 65 | 27 | 39 | 2 (1 fix-like) | 5 |
| AI-only | 57 | 21 | 34 | 2 (1 fix-like) | 5 |
| AI-only blocker | 1 | 0 | 0 | 0 (0 fix-like) | 0 |
| AI-only major | 9 | 3 | 4 | 0 (0 fix-like) | 0 |
| AI-only minor | 29 | 15 | 17 | 2 (1 fix-like) | 4 |
| AI-only nit | 18 | 3 | 13 | 0 (0 fix-like) | 1 |

Details: score_v0b@high.md, signals_v0b@high.md

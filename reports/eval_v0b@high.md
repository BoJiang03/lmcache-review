# Eval: v0b@high

## Score (vs human reviews on the same commit)

Samples (PR, reviewed commit): 10 · human review comments: 19 (change_request 12, nit 3, praise 3, question 1)

- Recall on change requests: 8/12 (67%)
- Recall on change requests + nits: 9/15 (60%)
- AI findings: 92 (9.2/PR); judged valid: 72 (78%), invalid 16, unsure 4
- AI-only findings: 84; judged valid 64, invalid 16, unsure 4
- Cost (review + grading): $14.08

## Human-only on change requests (pre-launch target: lower is better)

| split | area | human change requests | human-only (AI missed) | rate |
| --- | --- | --- | --- | --- |
| test | all | 12 | 4 | 33% |
| test | vllm-integration | 5 | 4 | 80% |
| test | mp | 3 | 0 | 0% |
| test | tests | 2 | 0 | 0% |
| test | distributed | 1 | 0 | 0% |
| test | (overall review) | 1 | 0 | 0% |

## Passive signals

Samples: 10 · findings: 92. Signals only support a finding; absence means nothing.

| findings | n | changed later in PR | on merged PRs | changed after merge | later human comment at same place |
| --- | --- | --- | --- | --- | --- |
| all | 92 | 28 | 65 | 6 (3 fix-like) | 5 |
| AI-only | 84 | 23 | 61 | 6 (3 fix-like) | 5 |
| AI-only blocker | 2 | 1 | 0 | 0 (0 fix-like) | 1 |
| AI-only major | 17 | 6 | 9 | 3 (1 fix-like) | 1 |
| AI-only minor | 40 | 12 | 31 | 3 (2 fix-like) | 2 |
| AI-only nit | 25 | 4 | 21 | 0 (0 fix-like) | 1 |

Details: score_v0b@high.md, signals_v0b@high.md

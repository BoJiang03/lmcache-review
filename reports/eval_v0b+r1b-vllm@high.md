# Eval: v0b+r1b-vllm@high

## Score (vs human reviews on the same commit)

Samples (PR, reviewed commit): 10 · human review comments: 19 (change_request 12, nit 3, praise 3, question 1)

- Recall on change requests: 8/12 (67%)
- Recall on change requests + nits: 8/15 (53%)
- AI findings: 92 (9.2/PR); judged valid: 68 (74%), invalid 21, unsure 3
- AI-only findings: 85; judged valid 61, invalid 21, unsure 3
- Cost (review + grading): $14.70

## Human-only on change requests (pre-launch target: lower is better)

| split | area | human change requests | human-only (AI missed) | rate |
| --- | --- | --- | --- | --- |
| test | all | 12 | 4 | 33% |
| test | vllm-integration | 5 | 3 | 60% |
| test | mp | 3 | 1 | 33% |
| test | tests | 2 | 0 | 0% |
| test | distributed | 1 | 0 | 0% |
| test | (overall review) | 1 | 0 | 0% |

## Passive signals

Samples: 10 · findings: 92. Signals only support a finding; absence means nothing.

| findings | n | changed later in PR | on merged PRs | changed after merge | later human comment at same place |
| --- | --- | --- | --- | --- | --- |
| all | 92 | 33 | 61 | 7 (5 fix-like) | 7 |
| AI-only | 85 | 28 | 58 | 7 (5 fix-like) | 6 |
| AI-only blocker | 2 | 1 | 0 | 0 (0 fix-like) | 1 |
| AI-only major | 17 | 8 | 12 | 3 (2 fix-like) | 1 |
| AI-only minor | 43 | 14 | 31 | 3 (2 fix-like) | 3 |
| AI-only nit | 23 | 5 | 15 | 1 (1 fix-like) | 1 |

## Flips vs v0b@high

Samples in both: 10 · findings v0b@high 92, v0b+r1b-vllm@high 92

- fixed (missed by v0b@high, matched by v0b+r1b-vllm@high): 1
- broken (matched by v0b@high, missed by v0b+r1b-vllm@high): 2
- matched by both: 7 · missed by both: 5
- net: -1

Details: score_v0b+r1b-vllm@high.md, signals_v0b+r1b-vllm@high.md, compare_v0b@high_vs_v0b+r1b-vllm@high.md

# Eval: v0@high

## Score (vs human reviews on the same commit)

Samples (PR, reviewed commit): 10 · human review comments: 18 (change_request 13, question 2, praise 2, nit 1)

- Recall on change requests: 7/13 (54%)
- Recall on change requests + nits: 7/14 (50%)
- AI findings: 93 (9.3/PR); judged valid: 75 (81%), invalid 16, unsure 2
- AI-only findings: 86; judged valid 68, invalid 16, unsure 2
- Cost (review + grading): $11.20

## Human-only on change requests (pre-launch target: lower is better)

| split | area | human change requests | human-only (AI missed) | rate |
| --- | --- | --- | --- | --- |
| test | all | 13 | 6 | 46% |
| test | (overall review) | 2 | 1 | 50% |
| test | ci-build | 2 | 1 | 50% |
| test | tests | 2 | 1 | 50% |
| test | cli | 2 | 1 | 50% |
| test | vllm-integration | 2 | 2 | 100% |
| test | distributed | 1 | 0 | 0% |
| test | platform | 1 | 0 | 0% |
| test | docs | 1 | 0 | 0% |

## Passive signals

Samples: 10 · findings: 93. Signals only support a finding; absence means nothing.

| findings | n | changed later in PR | on merged PRs | changed after merge | later human comment at same place |
| --- | --- | --- | --- | --- | --- |
| all | 93 | 22 | 29 | 1 (0 fix-like) | 1 |
| AI-only | 86 | 18 | 27 | 1 (0 fix-like) | 1 |
| AI-only blocker | 3 | 3 | 0 | 0 (0 fix-like) | 1 |
| AI-only major | 13 | 2 | 4 | 0 (0 fix-like) | 0 |
| AI-only minor | 46 | 7 | 15 | 0 (0 fix-like) | 0 |
| AI-only nit | 24 | 6 | 8 | 1 (0 fix-like) | 0 |

## Flips vs v0@medium

Samples in both: 10 · findings v0@medium 90, v0@high 93

- fixed (missed by v0@medium, matched by v0@high): 0
- broken (matched by v0@medium, missed by v0@high): 2
- matched by both: 7 · missed by both: 5
- net: -2

Details: score_v0@high.md, signals_v0@high.md, compare_v0@medium_vs_v0@high.md

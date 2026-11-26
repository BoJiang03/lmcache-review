# Retention E3: retain → distill → vet loop on a state copy (2026-11-25 PT evening)

## Goal
Points the ledger calls learned (covered / resolved) must be caught 2/2 by the production reviewer
`p990f2d2e+<book>@medium-rc`; fix in the workflow only, rules must not spell out one PR's fix.

## Mechanism (commit a5bacb3)
- `lmreview retain` (state.retain_step): re-review the samples of resolved points with the current prompt and
  book, rule check only (`-ro`, default) or a given reviewer's runs; judge against every point; points not caught
  in all runs go back to to_distill with a "not retained" try (h/n, whether the entry fired, what its findings
  said). The try does not count toward max_tries; > max_requeues → needs_human. round runs it after each promote.
- Why -ro is enough: on the pilot baseline the rule check raised the entry behind 49/53 caught resolved points
  (26 of them were credited to the main review only because dedupe kept the main copy).
- Specificity checks wired into distill and compress (`[distill] specificity`): lint + Sonnet check on every new or
  changed entry; one rewrite; else drop (replaced entries come back) or revert.
- replay `learned=True` (retain reviews the samples the book came from); `SC_TAG` keeps copy runs apart.

## E3 on copy data/retention/exp3 (state + data isolated; baseline runs imported as cache)
| step | result | cost |
|---|---|---|
| retain (v0032 baseline runs, lmreview judge) | 49 retained, 16 requeued (same 75.4% as blind judge) | $7.64 |
| distill | 12 learnable (4 revise, 2 add), 4 not_issue → not_rulable; specificity: all pass | $1.92 |
| vet | PARTLY KEPT → v0033: resolved 10, failed 2 (cx08k1-003, 2 new entries dropped) | $8.41 |
| measure pilot, v0033, rc rerun + main reused from v0032, 2 reps | 54/5/6 of 65 | $14.87 |

Retention 75.4% → 83.1% (65 points); on the 61 still rulable 80.3% → 88.5%. Cost/run $0.90 → $0.83.
Remaining misses (v0033): c 8, c-elsewhere 5, a 2, b 2 (point-runs). vet's narrow -ro judge still passed some
points production misses (#3869 cx07k1-009: vet 2/2, production 1/2).

## Next
- E4 = second loop iteration on the copy (retain with the measured v0033 runs → distill → vet → measure).
- Then holdout 15. Budget so far ≈ $83 of $200.

# Retention experiments E1–E3 and the scope of retention (2026-11-26 PT)

## Experiments (12 samples / 54 points, main review reused from cache; base book v0032)
| | base | E1 | E2 | E3 |
|---|---|---|---|---|
| 2/2 retained | 30 | 33 | 40 | 34 |
| hits of 108 | 72 | – | 87 | 79 |
| findings / run | 13.8 | 18.9 | 15.2 | 15.7 |
| invalid share | 20% | 25% | 19% | 19% |
| cost | – | $15.98 | $38.58 | $28.82 |
- E1: rule check "every place" line + recheck of applies-not-violated rules. Not adopted
  (user: "上不了生产就不和这个branch").
- E2: distill splits a missed ask out of a bundled entry; `retain --covered`.
- E3: E2 + tightened specificity (no single proposed remedy, no quoted example; 6-gram quote lint).
  Merged to local main (3023a1b). E2→E3 drop: part specificity (rule -013 quoted its comment),
  part single-run distill randomness.
- User checked the split rules for PR leakage, which led to the E3 tightening.

## Decisions
- Examples are not shown to the reviewer: on the source PR they leak the answer.
- Same-PR retention is an in-sample gate (necessary, not the goal). ~80% is enough; do not push it
  by writing more specific rules.
- User: "泛化我打算通过压缩来实现，泛化这个东西根本没法测。" Generalization comes from compress and
  is not measured; retention + specificity are the gates around distill and compress.

## Open
- Apply on the real state for the 30 pilot+holdout samples: one-time
  `retain --covered --reviewer pdba46ca9+v0032@medium-rc` (cached), then distill + vet (~$15).
- Push of b35c462, 3023a1b and this record needs "push吧".

## Free estimate: union of 2 runs (cached runs only, $0)
Script: jobs tmp union_est.py. Data: pdba46ca9+v0032@medium-rc runs 1–4 (the same runs as p990f2d2e) on pilot+holdout,
101 points (65 with 2 runs, 22 with 3, 14 with 4). 2/2 estimated per point as q² (single: est 78%, observed 76%).
| | per-run hit | est 2/2 | cost / sample |
|---|---|---|---|
| single (production) | 82% | 78% | $0.88 |
| rule check ×2, union | 85% | 82% | +36% |
| whole review ×2, union | 88% | 86% | +100% |
- 14 hard points with 4 runs (direct): 42% → 50% (rc union) / 52% (full union).
- Rule check findings: 32% invalid (main 12%). 39 / 193 hits came only from the rule check.
- Misses are correlated across runs, not coin flips: sampling more buys little. Not worth the cost.

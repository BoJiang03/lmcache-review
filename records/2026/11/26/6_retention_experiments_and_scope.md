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

## Severity tiers (a6b513a), user: "按照重要程度来分别解决以及学习…区别对待"
- Severity comes from the existing a2 annotations (every ledger point and every rule's evidence is annotated;
  the earlier "25 rules unknown" came from reading only judge score files). Not stored in the ledger.
- `annotate.severities / tier / entry_severity`; `lmreview status` lists the ledger by tier; book.md shows each
  entry's severity (highest of its evidence); retain prints and logs retained by tier; retention.py report has by_tier.
- Retention by tier, pdba46ca9+v0032@medium-rc, 2 runs:
  | tier | pilot | holdout | together |
  |---|---|---|---|
  | major+ | 20/21 | 7/7 | 27/28 (96%) |
  | minor | 16/25 | 14/21 | 30/46 (65%) |
  | nit | 13/19 | 7/8 | 20/27 (74%) |
- Active v0032 entries by severity: blocker 5, major 20, minor 15, nit 9.
- Rule check findings invalid share by entry tier (earlier estimate, partial labels): major+ 39%, minor 22%, nit 48%.

## Tier behavior (aa24300), user: "确认这个行为"
[tiers] in config.toml: distill attempts major+ 3 / minor 2 / nit 1; retain needs every run for major+ / minor,
one for nit; retain requeues 2 / 1 / 0, then major+ → needs_human, minor / nit stay learned with "unretained".
tests/test_retain_tiers.py (7 cases); 18/18 tests.

## E4: nit rules held to a higher bar in the rule check (user approved; not adopted)
Branch nit-bar (0212460): rule_lines marks the 9 entries learned only from nits ", nit"; rulecheck.md: raise
a nit rule only when the code plainly does what it warns against. Prompt p06adce4f, state copy data/retention/exp6,
same 12 samples x 2 runs, main review reused from pdba46ca9. Spent $11.74.
| | base pdba46ca9 | E4 p06adce4f |
|---|---|---|
| 2/2 major+ / minor / nit | 6/7, 17/33, 7/14 | 6/7, 16/33, 7/14 |
| nit caught >= 1/2 | 9/14 | 7/14 |
| rc findings from nit rules (2 runs) | 23, 57% invalid | 20, 50% invalid |
| rc findings, all tiers | 111, 37% invalid | 98, 31% invalid |
| rule check cost / run | $0.34 | $0.19 |
Nit findings fell by 3 only; the invalid share fell about as much on major+ / minor rules, which the change
does not touch, so it reads as run-to-run noise. Not adopted. (The rule-check cost gap is not explained by the
change; not chased.)

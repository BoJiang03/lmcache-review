# Retention (learned but not stable) — M0, blocked on quota (2026-11-25 19:30 PT)

/workfor 12h armed 18:53 PT, disarmed early: blocked.

## Done (free)
- scripts/retention.py: fixed sets (data/retention/sets.json, not in git):
  pilot 15 samples / 65 ledger points (incl. #3869 and the 10 learned four-way samples), holdout 15 / 36.
  `run` = skill_compare lmreview arm + blind judge; `report` = per-point hits over repeats, misses a/b/c/c-elsewhere/x.
- skill_compare: SC_REP (repeat k kept as TAG#r<k>; donors per repeat).
- lmreview/specificity.py: lint (principles: no evidence identifiers/paths/PR numbers in when/expect;
  knowledge: PR numbers only) + model check prompt; tests/test_specificity.py (6 pass, run without pytest).
  Current book v0032: 0 of 49 active entries flagged.

## Baseline so far (free, cached run 1 of the 10 four-way samples, p990f2d2e+v0032@medium-rc)
- 46 points complete: 39 caught (84.8%), 7 missed: a 2 (covered by luck), c 3 (rule cited on the same file,
  judge matched nothing), c-elsewhere 2 (rule cited on other files only), b 0. 5 of 7 on #3869.
- First fix to try once runs are allowed: class c, not b — rules do fire; the findings miss the spot.

## Blocked
- 7-day quota 97% used (rule: keep >= 30% left), resets 2026-11-29 19:59 PT; 5-hour 100%.
- Extra usage on: paid runs now bill real money ($196.66 used this month).
- Baseline needs ~$27 (5 new run-1 + 15 run-2 + judge). Needs the user's decision.

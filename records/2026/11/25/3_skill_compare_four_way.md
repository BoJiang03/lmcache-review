# lmreview vs review skills: four-way comparison (2026-11-25 PT)

## Goal
User's bar: on unlearned PRs match each baseline, on learned PRs beat it, for recall, cost and speed alike.
Also report recall by severity, what each side misses, and blockers/majors no human raised.

## Setup
- 20 samples: 10 learned (train, gold all in ledger, ≥2 covered), 10 unlearned (test, no gold in ledger; #4729 fixed).
- All Opus 5.5 medium, offline replay, same blind judge.
- lmreview: production config `p990f2d2e+v0032@medium-rc` (main review medium, rule check medium, parallel,
  rc_merge off, Sonnet dedupe).
- /pr-review: LMCache dev d0959e0 SKILL.md + coding_standards.md.
- /code-review: Claude Code 2.1.332 built-in, `/code-review medium`, diff as uncommitted changes.
- /anthropic-skills:pr-review (new arm `SC_BASELINE=askill`): org-synced generic skill (2026-09-21,
  sha256 15e064d3d8ce), installed over the repo's pr-review, run offline. Not committed (public repo).

## Results (per-sample averages)
| | lmreview | /pr-review | /anthropic-skills:pr-review | /code-review |
|---|---|---|---|---|
| learned recall | 83% (39/47) | 51% | 49% (23/47) | 28% |
| learned cost | $0.96 | $0.87 | $0.79 | $0.59 |
| learned time | 90 s | 118 s | 106 s | 87 s |
| unlearned recall | 71% (22/31) | 65% | 65% (20/31) | 42% |
| unlearned cost | $1.16 | $1.18 | $1.05 | $0.78 |
| unlearned time | 114 s | 159 s | 157 s | 127 s |

- Severity totals (blocker/major/minor/nit): lmreview 4/5, 18/20, 27/35, 12/18; /pr-review 4/5, 13/20, 21/35, 6/18;
  askill 4/5, 12/20, 22/35, 5/18; /code-review 4/5, 7/20, 12/35, 3/18.
- lmreview missed 17 points; 16 missed by all four. One (#3869 "move L2→L1 duplicated-key handling to a separate PR",
  minor) caught only by askill — withdrew the earlier claim "lmreview caught every point the others caught".
- Blockers/majors no human raised, judged valid: lmreview 62/65, /pr-review 45/45, askill 36/39, /code-review 40/57.
- Verdict: recall and time meet the bar against all three; cost does not yet (+$0.09 vs /pr-review learned,
  +$0.11–0.17 vs askill, +$0.37–0.38 vs /code-review).
- askill run cost ≈ $24 (incl. $1 pilot on #3210).

## Report
- https://claude.ai/artifact/S4zTeG2CyY13xvMv79rari (org-shared), source `reports/skill_compare.html`.
- One four-way comparison throughout, English default with a 中文 toggle, the 20 PRs listed with GitHub links.
- `reviews.html` + `reviews.json` (artifact only; json gitignored): every finding per arm, judge verdicts,
  matched human points, original Markdown reports of the three skill arms.

## Commits (local, not pushed)
- 7a6281b → askill arm + four-way report; f1ece50 viewer.
- Two unpushed commit subjects reworded ("Claude Code /code-review" → "built-in /code-review") to pass the
  claude/anthropic grep; trees unchanged.

## Open
- Push needs the user's "push吧".
- Cost levers not run: ~$5 rule check low vs medium on the 20 samples; lighter config for small PRs.
- Config default effort is still "high"; switching to medium needs the user's OK.

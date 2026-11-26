# Retention E4 + holdout (2026-11-25 PT 22:30 – 2026-11-26 PT 00:20)

## Results (production config p990f2d2e+<book>@medium-rc, 2 runs, blind judge; later books: rc rerun, main reused from v0032)
| experiment | change | retention 2/2 (2/2, 1/2, 0/2) | misses a/b/c/c-else | specificity blocked | cost/run | exp cost | keep |
|---|---|---|---|---|---|---|---|
| pilot baseline v0032 | — | 75.4% (49, 8, 8) | 3/5/10/6 | — | $0.90 | $22.5 | — |
| E3 pilot → v0033 | retain (covered+resolved) → distill → vet | 83.1% (54, 5, 6) | 2/2/8/5 | 0 | $0.83 | $18.0 + $14.9 measure | keep |
| E4 pilot → v0034 | 2nd loop iteration (retain on v0033 runs) | 86.2% (56, 3, 6) | 2/1/6/6 | 0 | $0.81 | $15.2 + $14.2 measure | keep |
| holdout baseline v0032 | — | 77.8% (28, 4, 4) | 7/3/1/1 | — | $0.87 | $34.4 | — |
| holdout → v0033h | one loop (retain --covered, vet judge_all on) | 69.4% (25, 6, 5) | 12/2/1/1 | 0 | $0.77 | $28.3 incl. measure | inconclusive |

- Pilot on the points still rulable: 49/60 → 53/60 → 55/60 (81.7% → 91.7%). resolved 2/2: 23 → 27 → 29 of 37.
- Holdout: the loop changed almost nothing (6 requeued: 4 became not_rulable, 2 learnable; vet kept 1 revision), so
  the drop is not from the book: 5 covered points fell although the main review was reused verbatim (e.g. #4548:
  identical final findings, 2/2 → 1/2). It measures judge/dedupe noise: about ±3–5 points on 36.
- Pilot noise check: covered points (main reused) moved up 1 / down 0 across E3, 0/0 across E4; resolved moved
  up 8 / down 2 and up 3 / down 1, so the pilot gain is mostly real, but its size is within ~2× the noise.

## Workflow changes (commits a5bacb3, 4a6b8a0, 1a44ce3)
- `lmreview retain` + round wiring; `--covered`, `--reviewer`, `--samples`.
- specificity enforced in distill and compress: 0 entries blocked in 3 distills (all new texts passed lint + model).
- `[vet] judge_all = true`: vet judges -ro runs against every point (vet passed #3869 / #4687 points 2/2 that
  production caught 1/2). Not measured separately (budget).

## Verdict vs done criteria
- +20pp on pilot: NOT met (+10.8pp; +10.0pp on rulable points).
- specificity: met (every promoted entry passed both checks).
- cost/sample: met (lower, $0.90 → $0.81).
- holdout same direction: NOT shown (loop changed almost nothing there; result is judge noise).

## Spend
≈ $171 of $200 (earlier E1/E2/iso ≈ $46). 7-day quota 100%, running on extra usage.

## Next (needs the user)
- The 2-run blind-judge metric has ~±8pp noise on 36 points: more runs, or a judge vote, before small effects mean anything.
- Remaining pilot misses are c-class on #3869 (42 files) and points attribution now calls not_issue / context
  (5 pilot, 4 holdout moved to not_rulable — check these are not the loop hiding misses).
- Apply to the real state: `lmreview retain` on the real ledger costs ≈ $0.4 × 2 per sample (rule check only).

## Follow-up (2026-11-26 PT ~00:30–01:30): judge vote + split rule check
- Judge vote (retention.py vote; misses re-judged, 2 of 3): pilot v0032 and v0034, $5.98. 0 of the misses turned
  hit: the judge repeats its verdict on the same run. Retention unchanged (75.4% → 86.2%).
  Withdrawn: "holdout drop is judge noise". The noise is in the review runs (rule check + dedupe differ run to
  run even with the main review reused), not in the judge.
- Split rule check for large PRs (`[review] rulecheck_split_files`, prompt p6282fa8a when 20), $12.2:
  pilot #3869 (42 files, 16 points) 2/2 12 → 13; holdout #3630/#4729/#3359 (7 points) 3 → 3, hits 7 → 6.
  Rule-check cost on those PRs ×1.5–2.5 (#3869 $0.42 → $1.08 per run). No clear gain: setting left at 0 (off).
- attribute instability: 9 of 30 re-attributed points (all once judged learnable) were re-judged not_rulable
  (E3 4/16, E4 1/8, holdout 4/6); 3 of them look wrong (#3869 groupby, #3869 keep docstring, #3210 device_path).
- Spend ≈ $189 of $200.

## attribute stability and criteria (2026-11-26 PT ~01:30–02:00, $1.75)
- 30 ledger comments × 3 attributions (old prompt): learnable-vs-not differs on 3/30 (10%; small sample, 2–27%).
  The loop's 30% flip rate comes from selection: requeued points are the ambiguous ones. attribute does not see
  the failure history. Covered points never pass attribute: 6 of 14 sampled covered points look like non-issues.
- New criteria (commit after df3c0cc): a reason evident from the hunk + suggestion counts ("(inferred)" in asks);
  learnable needs both calls; disagreement → "unclear" (not_rulable, note "unclear: ..."), no third call.
  30 × 3 again: 2/30 differ; 2 majorities changed (a docstring-wording nit → learnable 3/3; "LMCache?" → learnable 2/3, debatable).
  The 8 loop-dropped comments, 2 runs: itertools.groupby → learnable 2/2; inline constants → learnable 2/2;
  README promo → context 2/2; #4004 docs questions → unclear 2/2; #3869 "keep docstring" and #3210 → not_issue / unclear.

## covered points through attribute (new criteria, no ledger change; $1.53)
- 141 covered points (110 comments): learnable 120 (85%), unclear 7, context 6, not_issue 4, rejected 3, contested 1.
  Saved in data/retention/covered_attr.json. The earlier "6 of 14 sampled covered look like non-issues" was an
  old-prompt, small-sample estimate: withdrawn.
- Pilot/holdout barely move: pilot drops 1 covered point (75.4→75.0%, v0034 86.2→85.9%); holdout drops 2 (#4548
  README promo): 77.8→79.4%, v0033h 69.4→73.5%.

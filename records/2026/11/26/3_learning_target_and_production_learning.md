# Learning target and learning from production misses (2026-11-26 PT ~00:30–02:30)

## User decisions (quoted)
- Judge vote and split rule check: "这聊个措施都没用那就关了吧" → both off (split `rulecheck_split_files = 0`;
  vote is only a retention.py measurement, never in the workflow).
- Freezing attribute results: "1不做，结论都不对怎么能固定呢？" → not done; measure stability instead.
- Terse but useful asks ("Please check itertools.groupby"): "ok" to a three-level attribute criterion.
- Unclear reasons: learnable needs both calls; disagreement → unclear (for a person).
- Denominator: "值得学，且 reviewer没找到的 才要学。才能做分母。" Agreed with two additions: "not found" is judged
  by the production reviewer in 2 runs (not one learning run); points already caught 2/2 are a guard
  (must not drop), not in the main denominator. "改吧" → implemented.

## Changes (local commits, not pushed)
- cd3531e attribute: a reason evident from the hunk + suggestion counts ("(inferred)" in asks); learnable needs
  both calls; disagreement → "unclear" (not_rulable, note "unclear: ...").
- d25f16a `[learn] production = true`: round reviews with the production reviewer (`p...+<book>@medium-rc`,
  no -ms); distill reads its misses; confirm runs a second time on samples with new misses AND new finds;
  a point found in fewer than all runs goes to to_distill as flaky. Not yet run end to end.

## Measurements
- attribute stability, 30 comments × 3 (old prompt): 3/30 flip learnable-vs-not; new prompt: 2/30.
  The loop's 30% re-attribution flip rate is selection (requeued points are the ambiguous ones).
- 8 loop-dropped comments under the new criteria: itertools.groupby and inline-constants → learnable 2/2;
  README promo → context; #4004 doc questions → unclear 2/2.
- All 141 covered points attributed (new criteria, ledger untouched, data/retention/covered_attr.json):
  learnable 120 (85%), unclear 7, context 6, not_issue 4, rejected 3, contested 1. Effect on retention ≤ 1–2 points.
- Cost per run now: learning reviewer ~$0.8–1.1 (v002x avg $1.12 over 31; v003x 2 runs $0.79), production ~$0.99
  → learning from production 2 runs costs about the same as today's learn run + confirm (≈ $2.0–2.4 vs $2.3/sample).

## Estimates (not measured)
- Points worth learning that never enter learning: ~12–15% before (one learning run decides), ~5–6% after
  (2 production runs must both find it). attribute "unclear" (~10%) and attribute errors are separate.

## Proposed target for the next phase (awaiting X from the user)
- Denominator: points attribute (new criteria, fixed at t0) calls learnable AND the production reviewer did not
  find 2/2 before learning. Main metric: retention 2/2 on that set. Guard: points caught 2/2 before must not drop.
- Rough pilot numbers under this view (resolved points as proxy): 23/37 (62%) → 29/37 (78%); covered guard 26/28 → 27/28.
- Noise: use 4 runs per point or ≥ 30 samples.

## Spend
≈ $193.5 of the $200 approved. A next phase needs a new budget.

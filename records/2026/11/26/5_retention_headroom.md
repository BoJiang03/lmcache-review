# Retention headroom: why the 24 not-retained points are missed (2026-11-26 PT)

## Question
User: how much room is left in the retention rate (production 2/2 on learned points)?

## Setup
- Book v0032, production reviewer pdba46ca9+v0032@medium-rc. Its prompts are byte-identical to
  p990f2d2e; r1/r2 were copied from the p990f2d2e cache and reproduce 49/8/8 and 28/4/4.
- Population: the 24 points that are not 2/2 (pilot 16 of 65, holdout 8 of 36; 77/101 = 76.2% retained).
- r3 ran on the 7 samples holding 0/2 points.
- isolate: a rule-only check limited to the point's own rule, 2 reps, on points still 0/3.
- r4 ran only on the 4 cheapest samples (cap).
- Classes:
  - noise: caught in at least 1 production run;
  - not-triggering: 0 in production, the isolated rule catches it;
  - poorly written: 0 in production and 0 in isolate;
  - not learned: covered, no rule.

## Result
| class | pilot | holdout | total |
|---|---|---|---|
| noise | 10 | 4 | 14 |
| not-triggering | 0 | 0 | 0 |
| poorly written | 5 | 2 | 7 |
| not learned | 1 | 2 | 3 |

- Ceilings:
  - all noise points made 2/2: 90.1% (91/101);
  - not-triggering adds nothing;
  - poorly written + not learned: 9.9% left.
- Of the 7 poorly written:
  - 4 are cited on the right file but the judge matches no point (c);
  - 1 is cited only on other files;
  - 2 are never cited (b): 4107 cx07k1-010, 4729 v0023c1-013.
- 5 of the 7 sit on big PRs (#3869 with 42 files, #4729 with 28, #3630 with 31), yet isolation does not
  rescue them either: the rule, not the PR size, is the problem.
  - This withdraws the earlier claim that "rules are drowned on big PRs".
- Caveat: 6 points on #3869, #4729 and #3630 had only 3 production runs.
  4004:3592469968 was 0 in r1–r3 and in isolate, then hit in r4. Some "poorly written" may be noise.
- Cost: $18.00 (r3 $9.71, isolate $5.21, r4 $3.18).
- Results:
  - data/skill_compare/lmreview/pdba46ca9_v0032_medium-rc{,#r2,#r3,#r4} and ...rciso0of3{,#r2};
  - JSON in the job tmp dir.

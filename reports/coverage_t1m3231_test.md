# Coverage of t1m3231 on test

- comments checked: 667 of 667; explained by some entry: 14 (2%)
- entries used at least once: 1 of 3; cost $2.03

| entry | kind | train PRs | held-out comments explained | rule |
| --- | --- | --- | --- | --- |
| m3231-001 | principle | 1 | 14 | When a change handles a corner case or failure by adding new control mechanism (tunables, thresholds, latched or sticky state flags, grace windows, or layered special-case branches) instead of fixing the semantics that produce the corner case, especially when those branches need long comments to justify them: Ask the author to justify each added knob, flag or special case. Ask them to look first for the mini |

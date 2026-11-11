# Coverage of t1m3231 on train

- comments checked: 1516 of 1517; explained by some entry: 26 (2%)
- entries used at least once: 3 of 3; cost $4.46

| entry | kind | train PRs | held-out comments explained | rule |
| --- | --- | --- | --- | --- |
| m3231-001 | principle | 1 | 24 | When a change handles a corner case or failure by adding new control mechanism (tunables, thresholds, latched or sticky state flags, grace windows, or layered special-case branches) instead of fixing the semantics that produce the corner case, especially when those branches need long comments to justify them: Ask the author to justify each added knob, flag or special case. Ask them to look first for the mini |
| m3231-002 | knowledge | 1 | 1 | When a change touches how the multiprocess server handles a KV-cache registration for an instance ID that is already registered, whether in the registration handler itself or in a re-registration, restart or recovery path: Check that registering an already-registered instance ID is an idempotent no-op that keeps the exist |
| m3231-003 | principle | 1 | 1 | When a design document is added or revised and contains intermediate planning, step-by-step narration of explored alternatives, or 'thought process' text alongside or instead of a description of the resulting design: Ask the author to keep only the final design: what it is, how it works, and the key decisions, with  |

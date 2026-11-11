# Coverage of t1m4736 on train

- comments checked: 1517 of 1517; explained by some entry: 4 (0%)
- entries used at least once: 2 of 2; cost $4.24

| entry | kind | train PRs | held-out comments explained | rule |
| --- | --- | --- | --- | --- |
| m4736-001 | knowledge | 1 | 3 | When a change creates, records, passes or waits on a GPU synchronization event for a KV transfer between LMCache and the serving engine, or merges event creation for different transfer paths into one shared path: Check that the event type is chosen by who drives the transfer. Transfers that LMCache drives across |
| m4736-002 | principle | 1 | 1 | When code that can fall back at runtime to another copy or version of a component it depends on (a vendored, bundled, older or third-party implementation) is changed to call a method or attribute that only the primary or newer copy provides: Every API the changed code calls must exist on every implementation the fallback can select. If one  |

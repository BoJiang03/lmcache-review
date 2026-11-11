# Coverage of t1m3779 on train

- comments checked: 1517 of 1517; explained by some entry: 19 (1%)
- entries used at least once: 1 of 1; cost $4.18

| entry | kind | train PRs | held-out comments explained | rule |
| --- | --- | --- | --- | --- |
| m3779-001 | principle | 1 | 19 | When a value that used to be single (one per model, engine or instance) becomes a set of per-unit values (per group, per layer, per worker), and some APIs, endpoints or consumers that exposed or used the old single value are left on the single-value contract: Find every API, endpoint and consumer of the old single value, including status, reporting, logging  |

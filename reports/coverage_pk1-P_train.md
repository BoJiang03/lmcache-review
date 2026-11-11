# Coverage of pk1-P on train, comments missed by v0b+team-v1@high

- comments checked: 316 of 316; explained by some entry: 57 (18%)
- entries used at least once: 4 of 4; cost $1.19

| entry | kind | train PRs | held-out comments explained | rule |
| --- | --- | --- | --- | --- |
| P1 | principle | None | 44 | When Changes to integration layers, connectors, coordinators, dispatchers, registries, base classes and shared interfaces. Also driver modules that build or consume another module's descriptors, plans or specs.: Move each specific behavior and its docs into its own module behind one generic extension point: a d |
| P2 | principle | None | 9 | When Storing references to engine-owned or other components' objects. In-place writes into memory others may share. Cross-submodule calls inside the MP engine. New APIs, endpoints, snapshot calls or handlers that move state between components.: Pass borrowed resources per call, or keep them only in the owner. Show in the diff where any unavoid |
| P4 | principle | None | 4 | When Calling new APIs on components that have fallbacks. Reconnection and recovery paths. GPU event creation for transfers. LMCache-side workarounds for engine behavior.: Add a feature-detecting compatibility helper, or remove or sync the fallback, at every call site and |
| P3 | principle | None | 1 | When GPU-side temporaries whose size scales with request or data length. Handlers or work placed on single-threaded or shared execution lanes, including liveness and health paths.: Report the worst-case footprint. If it is unbounded or large, chunk the work with a fixed byte cap t |

# Coverage of t1m3631 on train

- comments checked: 810 of 1517; explained by some entry: 3 (0%)
- entries used at least once: 2 of 2; cost $2.29

| entry | kind | train PRs | held-out comments explained | rule |
| --- | --- | --- | --- | --- |
| m3631-002 | knowledge | 1 | 2 | When a change adds or modifies an MP engine submodule, makes one submodule use state or functionality owned by another submodule, or a design doc describes how MP engine submodules collaborate: The MP engine is an ownership tree. The engine context owns the storage manager and every submodule, |
| m3631-001 | knowledge | 1 | 1 | When a change in the multiprocess server adds a request handler, changes which dispatch mode a handler uses, makes an existing SYNC handler do more or slower work, or touches the liveness/health-check path: SYNC handlers all run on the single server-side dispatcher thread, so any slow SYNC handler stalls e |

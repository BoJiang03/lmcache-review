# Passive signals: reviewer v0b@high

Samples: 10 · findings: 92. Signals only support a finding; absence means nothing.

| findings | n | changed later in PR | on merged PRs | changed after merge | later human comment at same place |
| --- | --- | --- | --- | --- | --- |
| all | 92 | 28 | 65 | 6 (3 fix-like) | 5 |
| AI-only | 84 | 23 | 61 | 6 (3 fix-like) | 5 |
| AI-only blocker | 2 | 1 | 0 | 0 (0 fix-like) | 1 |
| AI-only major | 17 | 6 | 9 | 3 (1 fix-like) | 1 |
| AI-only minor | 40 | 12 | 31 | 3 (2 fix-like) | 2 |
| AI-only nit | 25 | 4 | 21 | 0 (0 fix-like) | 1 |

## Severity check

AI severity of findings matched by a human change request: major 3, minor 3, blocker 3

## AI-only blocker/major with a signal

- #5042 [major] Full-prompt LMCache hit resumes at N-1, mid compression group, but the scratch ring is nev (judge: True): after merge: 9a7b6050 +8.1d "[Feat][MP]: Preemption Handling (#5248)"
- #5042 [major] Lazy offload divides by a scratch group's tokens_per_block of 0 (ZeroDivisionError) (judge: True): after merge: 2a34fa82 +31.9d "[Bugfix] Skip scratch groups in lazy offload block estimate (#5818)"
- #5222 [major] Synchronous coordinator HTTP call inside the chunk-size lock, on the ZMQ main loop, makes  (judge: True): after merge: 371108bf +15.9d "[Security][Coordinator] Authenticate coordinator outbound requests usi"
- #5405 [major] Executor infers geometry from kv_cache.shape[1] with no validation; vLLM's native KV layou (judge: True): changed later in PR
- #5405 [major] PR description is out of sync with the code (scope and claimed tests) (judge: True): changed later in PR
- #5514 [major] First use now commits only 64 MB instead of init_size, so allocations fail right after pin (judge: True): changed later in PR
- #5514 [major] Multi-L1: warm_up and pin_status only touch the first L1 manager (judge: True): changed later in PR
- #5938 [blocker] Code still contains the old retrieve-tracking fix; the described store_scheduled/delay_fre (judge: True): changed later in PR; later comments [4516814878, 4516849148]
- #5938 [major] Tests listed in the description do not exist; the single new test covers only one abort or (judge: True): changed later in PR
- #5938 [major] request_finished returns True (delay free) for requests the worker is then told never to r (judge: True): changed later in PR; later comments [4516814878, 4516849148]

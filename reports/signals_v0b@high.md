# Passive signals: reviewer v0b@high

Samples: 12 · findings: 111. Signals only support a finding; absence means nothing.

| findings | n | changed later in PR | on merged PRs | changed after merge | later human comment at same place |
| --- | --- | --- | --- | --- | --- |
| all | 111 | 41 | 78 | 20 (4 fix-like) | 8 |
| AI-only | 97 | 31 | 68 | 20 (4 fix-like) | 8 |
| AI-only blocker | 4 | 1 | 3 | 2 (1 fix-like) | 0 |
| AI-only major | 22 | 6 | 15 | 5 (2 fix-like) | 1 |
| AI-only minor | 47 | 20 | 33 | 11 (1 fix-like) | 6 |
| AI-only nit | 24 | 4 | 17 | 2 (0 fix-like) | 1 |

## Severity check

AI severity of findings matched by a human change request: minor 6, major 5, blocker 3, nit 1

## AI-only blocker/major with a signal

- #3359 [blocker] Worker-side pickle fallback is incompatible with a server that chose SHM: stores silently  (judge: True): changed later in PR
- #3359 [blocker] No abort path for SHM write reservations; leaked/unfinished reservations are later publish (judge: True): after merge: 714bd7a5 +15.1d "rename: GPUTransferModule -> LMCacheDrivenTransferModule, NonGPUTransf"
- #3359 [major] SHM segment naming/cleanup is unsafe: crashed servers leak the whole L1 in /dev/shm, and e (judge: True): after merge: 4bbfd11b +9.7d "[core] Add GDS L1 tier (cuFile DMA) for MP mode (#3589)"
- #3359 [major] Default --transfer-mode silently changed from 'gpu' to 'auto' for all deployments (judge: True): changed later in PR
- #3382 [major] Capped load end (num_computed_tokens + cap) is not chunk-aligned; last partial chunk will  (judge: True): changed later in PR
- #3382 [major] Capping lmcache_cached_tokens also lowers num_saved_tokens, so already-cached chunks beyon (judge: True): after merge: 032e23da +139.5d "[Refactor] Isolate vLLM in-process integration (#5831)"
- #3808 [blocker] Per-request store future is overwritten; out-of-order async stores let vLLM free blocks wh (judge: True): after merge: bbd38f08 +57.3d "fix(mp): make transfer events context-aware (#4854)"
- #3808 [major] Unhealthy path reports async stores as finished and skips the preemption flush while backg (judge: True): after merge: fc8002ca +91.8d "[Bugfix] Prevent vLLM engine crash on multi-group cache-load failure ("
- #3808 [major] shutdown() unregisters from the server before draining async stores (judge: True): after merge: 8dcd94f2 +23.1d "Get query tensor v2 (#4042)"
- #3808 [major] LMCache-driven preemption gap still open; torch_dev.synchronize() in the worker does not w (judge: True): after merge: 38ebdeac +118.7d "fix: guard transfer-context close against in-flight gather/scatter (#4"; later comments [3515617440, 3515618410, 3515797334]
- #3808 [major] Async store turns on automatically, but its correctness depends on vLLM calling handle_pre (judge: True): changed later in PR
- #5405 [major] Executor infers slot geometry from kv_cache.shape[1], which is wrong for vLLM's registered (judge: False): changed later in PR
- #5514 [major] First use now commits only 64 MB instead of init_size, so allocations fail right after pin (judge: True): changed later in PR
- #5514 [major] Multi-L1: warm_up and pin_status only touch the first L1 manager (judge: True): changed later in PR

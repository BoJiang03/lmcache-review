# miss1：第一阶段开发集合（93 个 PR，按漏掉的 major → minor → nit 排序）

| # | PR | major | minor | nit | 标题 |
|---|---|---|---|---|---|
| 1 | #4639 | 3 | 2 | 0 | [feat] coordinator memory pressure api |
| 2 | #3877 | 3 | 0 | 0 | [MP][MUSA]:add stage4-2 MP IPC event support |
| 3 | #4042 | 3 | 0 | 0 | Get query tensor v2 |
| 4 | #3631 | 2 | 2 | 0 | [Feat] Worker-adapter liveness hygiene for MP serv |
| 5 | #4723 | 2 | 2 | 0 | [MP][Coordinator] Discover views and controllers i |
| 6 | #4736 | 2 | 1 | 0 | Route multiprocess IPC events through platform API |
| 7 | #3485 | 1 | 4 | 0 | [Refactor]: break apart `utils.py` into format and |
| 8 | #4079 | 1 | 4 | 0 | [Refactor][MP] Move the shared KV copy helpers to  |
| 9 | #3231 | 1 | 3 | 0 | [Feat] Server-side worker liveness tracking and re |
| 10 | #3779 | 1 | 3 | 0 | [Model Support]: Group layers w/ EngineKVFormat fo |
| 11 | #4468 | 1 | 3 | 0 | [feat][CB] linear hybrid model support  |
| 12 | #3808 | 1 | 2 | 0 | feat(mp): async engine-driven store |
| 13 | #3869 | 1 | 2 | 0 | [Prefetch sliding window 3/3] Prefetching / load o |
| 14 | #3180 | 1 | 0 | 0 | [Bugfix] Forward resolved P/D device to allocator |
| 15 | #3223 | 1 | 0 | 0 | [Core] KV cache store & retrieve using HTTP interf |
| 16 | #3476 | 1 | 0 | 0 | feat: Add MP server autostart for vLLM connector |
| 17 | #3477 | 1 | 0 | 0 | [MP] [Metrics] Add l2_evicted_object, Add cachesal |
| 18 | #4062 | 1 | 0 | 0 | [sglang] Support DSA (DeepSeek-V3.2) pools via a s |
| 19 | #4196 | 1 | 0 | 0 | [Design Doc] add lazy offload design doc |
| 20 | #4218 | 1 | 0 | 0 | Add pd-disaggregation for operator |
| 21 | #4709 | 1 | 0 | 0 | fix(mp): complete missing-registration GPU transfe |
| 22 | #4836 | 1 | 0 | 0 | fix(mp): make remote transfer results authoritativ |
| 23 | #4397 | 0 | 6 | 0 | test: refine tests v1 level1 tests |
| 24 | #3776 | 0 | 4 | 1 | [Prefetching sliding window 2/N] Propagate sliding |
| 25 | #3968 | 0 | 4 | 1 | [MP][Ascend] Ascend NPU multiprocess format suppor |
| 26 | #3193 | 0 | 4 | 0 | Add TurboQuant serde support for LMCache L2 adapte |
| 27 | #3630 | 0 | 4 | 0 | [MP] [Feat] Coordinator L2 Quota, Usage, Eviction  |
| 28 | #3264 | 0 | 3 | 0 | [Feat][MP] Add runtime DAX hotplug http API |
| 29 | #3593 | 0 | 3 | 0 | [MP] Add support for OBJ backend and batched opera |
| 30 | #3820 | 0 | 3 | 0 | Token dropping sdk v3 |
| 31 | #4800 | 0 | 3 | 0 | [MP][Coordinator] Add Key Directory placement metr |
| 32 | #3248 | 0 | 2 | 2 | [MP][feat] Support multi LMCache servers deploymen |
| 33 | #3461 | 0 | 2 | 2 | [Doc] Update README.md |
| 34 | #4015 | 0 | 2 | 2 | fix(mp): reclaim CUDA-IPC-imported KV memory when  |
| 35 | #4404 | 0 | 2 | 1 | [MP][Coordinator] Construct token directory and it |
| 36 | #3227 | 0 | 2 | 0 | [MP]: Add per-operation dedicated worker pools to  |
| 37 | #3274 | 0 | 2 | 0 | Missing io_uring changes and introducing nvme io_u |
| 38 | #3336 | 0 | 2 | 0 | [MP][Bugfix] Fix store/retrieve deadlock by routin |
| 39 | #3391 | 0 | 2 | 0 | [MP][Core] Refactor MPCacheEngine for better exten |
| 40 | #3924 | 0 | 2 | 0 | [platform][refactor] refactor device detection |
| 41 | #4016 | 0 | 2 | 0 | [RawBlock][FDP] Add NVMe FDP discovery and placeme |
| 42 | #4310 | 0 | 2 | 0 | [MP][Coordinator] Route quota accounting through t |
| 43 | #4399 | 0 | 2 | 0 | [Operator] Make hostIPC optional |
| 44 | #4763 | 0 | 2 | 0 | [Ascend][MP] Add NPU pin-memory backend via Ascend |
| 45 | #3359 | 0 | 1 | 3 | feat(mp): SHM-based data transfer path for GPUs/CP |
| 46 | #4075 | 0 | 1 | 3 | refactor(mp):Platform refactor ipc abstraction |
| 47 | #3642 | 0 | 1 | 1 | refactor(build): extract extension build into prof |
| 48 | #4434 | 0 | 1 | 1 | [MP] feat:support lazy offload |
| 49 | #4656 | 0 | 1 | 1 | [Bugfix] storage: skip duplicate puts for resident |
| 50 | #4679 | 0 | 1 | 1 | [Feature] MP mode DCP compatibility |
| 51 | #3221 | 0 | 1 | 0 | [Feat]: HiddenStateStore for hidden-state caching |
| 52 | #3259 | 0 | 1 | 0 | feat(mp): Non-GPU Context by pickle |
| 53 | #3364 | 0 | 1 | 0 | [CB] Blend v3 |
| 54 | #3404 | 0 | 1 | 0 | feat: Integrate native Cloud Bigtable remote stora |
| 55 | #3419 | 0 | 1 | 0 | [Core] add support for hybrid memory allocator |
| 56 | #3458 | 0 | 1 | 0 | Add optional native Aerospike L2 backend (BUILD_AE |
| 57 | #3478 | 0 | 1 | 0 | [Refactor] Consolidate ParallelStrategy constructi |
| 58 | #3528 | 0 | 1 | 0 | feat(bench): server_bench supports --mode cpu and  |
| 59 | #3589 | 0 | 1 | 0 | [core] Add GDS L1 slab-file tier (cuFile DMA) for  |
| 60 | #3612 | 0 | 1 | 0 | [MP][Core][HMA] Implement the interface for multi- |
| 61 | #3756 | 0 | 1 | 0 | feat(musa): add guarded MUSA MP handle wrapper |
| 62 | #3766 | 0 | 1 | 0 | Fix KeyError on lookup_cache re-query after async  |
| 63 | #3827 | 0 | 1 | 0 | [MP][Coordinator] Warm-prefetch KV from L2 into L1 |
| 64 | #3919 | 0 | 1 | 0 | feat(observability): per-tier (L2/L3/remote) cache |
| 65 | #3927 | 0 | 1 | 0 | [Core] Batch store memory allocation in LMCacheEng |
| 66 | #3950 | 0 | 1 | 0 | KVCache SDK: batch and stream interface |
| 67 | #4004 | 0 | 1 | 0 | docs: guide for integrating new non-CUDA devices v |
| 68 | #4011 | 0 | 1 | 0 | chore(mp_coordinator): move type-only imports unde |
| 69 | #4060 | 0 | 1 | 0 | pre-commit: ban cudaHostRegister/Unregister outsid |
| 70 | #4161 | 0 | 1 | 0 | [Core][P2P] Add optional native libibverbs host-L1 |
| 71 | #4177 | 0 | 1 | 0 | Refine k3 tests path filtering |
| 72 | #4191 | 0 | 1 | 0 | feat(cli): Add MLA/TP support for bench-server cli |
| 73 | #4253 | 0 | 1 | 0 | fix(vllm): handle the vLLM 0.26.0 fused KV cache l |
| 74 | #4403 | 0 | 1 | 0 | [observability] wire the missing CB V3 blend event |
| 75 | #4409 | 0 | 1 | 0 | test: refine tests v1 subdir compute, platform, an |
| 76 | #4438 | 0 | 1 | 0 | [Coordinator][CacheBlend] serve fleet blend lookup |
| 77 | #4450 | 0 | 1 | 0 | [Platform][RBLN] Add RBLN device backend for engin |
| 78 | #4474 | 0 | 1 | 0 | [MP][Feat][good-first-issue] Add Phoenix L2 Adapte |
| 79 | #4475 | 0 | 1 | 0 |   feat(platform): add AWS Trainium (Neuron) backen |
| 80 | #4583 | 0 | 1 | 0 | [Coordinator] Add cache-event source abstraction |
| 81 | #4607 | 0 | 1 | 0 | fix(sglang): distinguish single-head MHA from MLA |
| 82 | #4632 | 0 | 1 | 0 | [Platform][MUSA] Add lazy pinned memory support |
| 83 | #4726 | 0 | 1 | 0 | [Platform][RBLN] MLA (NL_X_NB_BS_HS) block transfe |
| 84 | #4729 | 0 | 1 | 0 | [Refactor]: vLLM LBHNC KVLayout metadata |
| 85 | #4760 | 0 | 1 | 0 | [MP][Coordinator] Make controller plugables |
| 86 | #4783 | 0 | 1 | 0 | [Bugfix][vLLM] Different images can share the same |
| 87 | #4805 | 0 | 1 | 0 | mp: VMM CUDA IPC wrapper for cuMemCreate-backed KV |
| 88 | #4850 | 0 | 1 | 0 | [Fix][CB] Decide fused-KV packing per group, not p |
| 89 | #3718 | 0 | 0 | 2 | fix(mp): Eliminate Container PID Namespace Collisi |
| 90 | #3322 | 0 | 0 | 1 | fix: handle full-prompt-hit in MP connector to avo |
| 91 | #3696 | 0 | 0 | 1 | [MP] perf(nixl_store_dynamic): load a request's ch |
| 92 | #3829 | 0 | 0 | 1 | refactor(platform): auto-discover DeviceIPCWrapper |
| 93 | #4298 | 0 | 0 | 1 | test: refine tests v1 multiprocess |

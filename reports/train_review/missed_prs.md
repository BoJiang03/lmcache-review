| PR | 标题 | 漏/CR | major | minor | nit | 模块 |
|---|---|---|---|---|---|---|
| #4639 | [feat] coordinator memory pressure api | 5/5 | 3 | 2 | 0 | core-other,distributed,docs,mp,observability,tests |
| #3877 | [MP][MUSA]:add stage4-2 MP IPC event support | 3/4 | 3 | 0 | 0 | docs,platform,tests |
| #4042 | Get query tensor v2 | 3/3 | 3 | 0 | 0 | core-other,docs,examples,mp,tests,vllm-integration |
| #3631 | [Feat] Worker-adapter liveness hygiene for MP server reaping | 4/4 | 2 | 2 | 0 | core-other,docs,tests,vllm-integration |
| #4723 | [MP][Coordinator] Discover views and controllers instead of  | 4/4 | 2 | 2 | 0 | cli,docs,mp,tests |
| #4736 | Route multiprocess IPC events through platform APIs | 3/7 | 2 | 1 | 0 | cli,core-other,docs,mp,platform,tests,vllm-integration |
| #3485 | [Refactor]: break apart `utils.py` into format and engine ba | 5/6 | 1 | 4 | 0 | docs,gpu-connector,mp,platform,tests |
| #4079 | [Refactor][MP] Move the shared KV copy helpers to object_gro | 5/5 | 1 | 4 | 0 | mp,tests |
| #3231 | [Feat] Server-side worker liveness tracking and reaping | 4/10 | 1 | 3 | 0 | docs,mp,tests,vllm-integration |
| #3779 | [Model Support]: Group layers w/ EngineKVFormat for MiniMax  | 4/4 | 1 | 3 | 0 | core-other,docs,gpu-connector,mp,platform,tests,vllm-integration |
| #4468 | [feat][CB] linear hybrid model support  | 4/5 | 1 | 3 | 0 | core-other,distributed,mp,tests,vllm-integration |
| #3808 | feat(mp): async engine-driven store | 3/3 | 1 | 2 | 0 | docs,mp,tests,vllm-integration |
| #3869 | [Prefetch sliding window 3/3] Prefetching / load only KV cac | 3/5 | 1 | 2 | 0 | core-other,distributed,docs,kernels,mp,observability,platform,tests |
| #3180 | [Bugfix] Forward resolved P/D device to allocator | 1/1 | 1 | 0 | 0 | storage,tests |
| #3223 | [Core] KV cache store & retrieve using HTTP interface | 1/1 | 1 | 0 | 0 | ci-build,core-other,docs,examples,mp,tests |
| #3476 | feat: Add MP server autostart for vLLM connector | 1/9 | 1 | 0 | 0 | ci-build,docs,tests,vllm-integration |
| #3477 | [MP] [Metrics] Add l2_evicted_object, Add cachesalt to exist | 1/1 | 1 | 0 | 0 | distributed,docs,observability,tests |
| #4062 | [sglang] Support DSA (DeepSeek-V3.2) pools via a second kern | 1/2 | 1 | 0 | 0 | gpu-connector,vllm-integration |
| #4196 | [Design Doc] add lazy offload design doc | 1/1 | 1 | 0 | 0 | docs |
| #4218 | Add pd-disaggregation for operator | 1/3 | 1 | 0 | 0 | ci-build,docs,operator |
| #4709 | fix(mp): complete missing-registration GPU transfers | 1/1 | 1 | 0 | 0 | mp,tests,vllm-integration |
| #4836 | fix(mp): make remote transfer results authoritative | 1/1 | 1 | 0 | 0 | mp,tests,vllm-integration |
| #4397 | test: refine tests v1 level1 tests | 6/8 | 0 | 6 | 0 | ci-build,tests |
| #3776 | [Prefetching sliding window 2/N] Propagate sliding-window in | 5/8 | 0 | 4 | 1 | core-other,distributed,docs,mp,observability,platform,tests |
| #3968 | [MP][Ascend] Ascend NPU multiprocess format support + generi | 5/9 | 0 | 4 | 1 | ci-build,core-other,gpu-connector,kernels,mp,platform,tests |
| #3193 | Add TurboQuant serde support for LMCache L2 adapters | 4/8 | 0 | 4 | 0 | distributed,docs,examples,tests |
| #3248 | [MP][feat] Support multi LMCache servers deployment with vll | 4/12 | 0 | 2 | 2 | tests,vllm-integration |
| #3359 | feat(mp): SHM-based data transfer path for GPUs/CPU/Accelera | 4/6 | 0 | 1 | 3 | distributed,docs,memory,mp,tests,vllm-integration |
| #3461 | [Doc] Update README.md | 4/4 | 0 | 2 | 2 | docs,other |
| #3630 | [MP] [Feat] Coordinator L2 Quota, Usage, Eviction  | 4/4 | 0 | 4 | 0 | cli,distributed,docs,mp,tests |
| #4015 | fix(mp): reclaim CUDA-IPC-imported KV memory when an instanc | 4/4 | 0 | 2 | 2 | mp,tests |
| #4075 | refactor(mp):Platform refactor ipc abstraction | 4/8 | 0 | 1 | 3 | docs,mp,platform,tests,vllm-integration |
| #3264 | [Feat][MP] Add runtime DAX hotplug http API | 3/4 | 0 | 3 | 0 | distributed,docs,mp,storage,tests |
| #3593 | [MP] Add support for OBJ backend and batched operations in N | 3/3 | 0 | 3 | 0 | distributed,tests |
| #3820 | Token dropping sdk v3 | 3/3 | 0 | 3 | 0 | core-other,docs,examples,mp |
| #4404 | [MP][Coordinator] Construct token directory and its API base | 3/3 | 0 | 2 | 1 | docs,mp,observability,tests |
| #4800 | [MP][Coordinator] Add Key Directory placement metrics | 3/5 | 0 | 3 | 0 | docs,mp,tests |
| #3227 | [MP]: Add per-operation dedicated worker pools to Mooncake L | 2/2 | 0 | 2 | 0 | distributed,docs,kernels,tests |
| #3274 | Missing io_uring changes and introducing nvme io_uring_cmd ( | 2/10 | 0 | 2 | 0 | distributed,docs,examples,kernels,storage,tests |
| #3336 | [MP][Bugfix] Fix store/retrieve deadlock by routing completi | 2/2 | 0 | 2 | 0 | ci-build,kernels,mp,tests |
| #3391 | [MP][Core] Refactor MPCacheEngine for better extendability | 2/2 | 0 | 2 | 0 | mp,tests |
| #3642 | refactor(build): extract extension build into profile-based  | 2/2 | 0 | 1 | 1 | ci-build |
| #3718 | fix(mp): Eliminate Container PID Namespace Collisions in LMC | 2/2 | 0 | 0 | 2 | tests,vllm-integration |
| #3924 | [platform][refactor] refactor device detection | 2/3 | 0 | 2 | 0 | core-other,kernels,mp,platform,tests |
| #4016 | [RawBlock][FDP] Add NVMe FDP discovery and placement plumbin | 2/3 | 0 | 2 | 0 | distributed,docs,kernels,storage,tests |
| #4310 | [MP][Coordinator] Route quota accounting through the cache-e | 2/2 | 0 | 2 | 0 | distributed,docs,mp,tests |
| #4399 | [Operator] Make hostIPC optional | 2/2 | 0 | 2 | 0 | docs,operator |
| #4434 | [MP] feat:support lazy offload | 2/3 | 0 | 1 | 1 | mp,tests,vllm-integration |
| #4656 | [Bugfix] storage: skip duplicate puts for resident disk keys | 2/3 | 0 | 1 | 1 | storage,tests |
| #4679 | [Feature] MP mode DCP compatibility | 2/3 | 0 | 1 | 1 | cli,core-other,distributed,docs,mp,observability,tests,vllm-integration |
| #4763 | [Ascend][MP] Add NPU pin-memory backend via AscendCL aclrtHo | 2/4 | 0 | 2 | 0 | ci-build,core-other,mp,other,platform,tests,vllm-integration |
| #3221 | [Feat]: HiddenStateStore for hidden-state caching | 1/1 | 0 | 1 | 0 | core-other,docs,inprocess,memory,tests |
| #3259 | feat(mp): Non-GPU Context by pickle | 1/1 | 0 | 1 | 0 | core-other,distributed,docs,mp,tests,vllm-integration |
| #3322 | fix: handle full-prompt-hit in MP connector to avoid schedul | 1/1 | 0 | 0 | 1 | vllm-integration |
| #3364 | [CB] Blend v3 | 1/1 | 0 | 1 | 0 | mp,observability,tests |
| #3404 | feat: Integrate native Cloud Bigtable remote storage connect | 1/1 | 0 | 1 | 0 | ci-build,docs,examples,storage,tests |
| #3419 | [Core] add support for hybrid memory allocator | 1/1 | 0 | 1 | 0 | ci-build,cli,core-other,docs,mp,tests,vllm-integration |
| #3458 | Add optional native Aerospike L2 backend (BUILD_AEROSPIKE) | 1/3 | 0 | 1 | 0 | ci-build,distributed,docs,kernels,other,storage,tests |
| #3478 | [Refactor] Consolidate ParallelStrategy construction in vllm | 1/3 | 0 | 1 | 0 | tests,vllm-integration |
| #3528 | feat(bench): server_bench supports --mode cpu and --transfer | 1/2 | 0 | 1 | 0 | cli,docs,tests |
| #3589 | [core] Add GDS L1 slab-file tier (cuFile DMA) for MP mode | 1/4 | 0 | 1 | 0 | ci-build,distributed,docs,gpu-connector,memory,mp,tests |
| #3612 | [MP][Core][HMA] Implement the interface for multi-object gro | 1/1 | 0 | 1 | 0 | core-other,distributed,mp,tests |
| #3696 | [MP] perf(nixl_store_dynamic): load a request's chunks concu | 1/1 | 0 | 0 | 1 | distributed,tests |
| #3756 | feat(musa): add guarded MUSA MP handle wrapper | 1/1 | 0 | 1 | 0 | docs,mp,platform,tests,vllm-integration |
| #3766 | Fix KeyError on lookup_cache re-query after async lookup tim | 1/1 | 0 | 1 | 0 | core-other |
| #3827 | [MP][Coordinator] Warm-prefetch KV from L2 into L1 | 1/2 | 0 | 1 | 0 | distributed,docs,mp,observability,tests |
| #3829 | refactor(platform): auto-discover DeviceIPCWrapper subclasse | 1/2 | 0 | 0 | 1 | cli,docs,gpu-connector,mp,platform,tests,vllm-integration |
| #3919 | feat(observability): per-tier (L2/L3/remote) cache-hit token | 1/2 | 0 | 1 | 0 | core-other,docs,inprocess,tests |
| #3927 | [Core] Batch store memory allocation in LMCacheEngine | 1/1 | 0 | 1 | 0 | inprocess,tests |
| #3950 | KVCache SDK: batch and stream interface | 1/1 | 0 | 1 | 0 | core-other,docs,examples |
| #4004 | docs: guide for integrating new non-CUDA devices via engine- | 1/1 | 0 | 1 | 0 | docs |
| #4011 | chore(mp_coordinator): move type-only imports under TYPE_CHE | 1/1 | 0 | 1 | 0 | mp |
| #4060 | pre-commit: ban cudaHostRegister/Unregister outside platform | 1/1 | 0 | 1 | 0 | other |
| #4161 | [Core][P2P] Add optional native libibverbs host-L1 transfer  | 1/1 | 0 | 1 | 0 | ci-build,distributed,docs,kernels,mp,tests |
| #4177 | Refine k3 tests path filtering | 1/8 | 0 | 1 | 0 | ci-build,docs |
| #4191 | feat(cli): Add MLA/TP support for bench-server cli tool  | 1/2 | 0 | 1 | 0 | cli,docs,tests |
| #4253 | fix(vllm): handle the vLLM 0.26.0 fused KV cache layout in g | 1/1 | 0 | 1 | 0 | docs,tests,vllm-integration |
| #4298 | test: refine tests v1 multiprocess | 1/6 | 0 | 0 | 1 | ci-build,tests |
| #4403 | [observability] wire the missing CB V3 blend events + metric | 1/3 | 0 | 1 | 0 | docs,mp,observability,tests |
| #4409 | test: refine tests v1 subdir compute, platform, and storage_ | 1/1 | 0 | 1 | 0 | ci-build,docs,tests |
| #4438 | [Coordinator][CacheBlend] serve fleet blend lookup from the  | 1/1 | 0 | 1 | 0 | cli,docs,mp,tests |
| #4450 | [Platform][RBLN] Add RBLN device backend for engine-driven M | 1/3 | 0 | 1 | 0 | core-other,docs,gpu-connector,kernels,platform,tests |
| #4474 | [MP][Feat][good-first-issue] Add Phoenix L2 Adapter — GPU-Di | 1/1 | 0 | 1 | 0 | distributed,docs,memory,mp,tests |
| #4475 |   feat(platform): add AWS Trainium (Neuron) backend support  | 1/2 | 0 | 1 | 0 | docs,other,platform,tests |
| #4583 | [Coordinator] Add cache-event source abstraction | 1/1 | 0 | 1 | 0 | docs,mp,tests |
| #4607 | fix(sglang): distinguish single-head MHA from MLA | 1/1 | 0 | 1 | 0 | gpu-connector,tests,vllm-integration |
| #4632 | [Platform][MUSA] Add lazy pinned memory support | 1/1 | 0 | 1 | 0 | gpu-connector,platform,storage,tests |
| #4726 | [Platform][RBLN] MLA (NL_X_NB_BS_HS) block transfer support | 1/3 | 0 | 1 | 0 | docs,platform,tests |
| #4729 | [Refactor]: vLLM LBHNC KVLayout metadata | 1/1 | 0 | 1 | 0 | core-other,distributed,gpu-connector,kernels,memory,platform,tests,vllm-integration |
| #4760 | [MP][Coordinator] Make controller plugables | 1/1 | 0 | 1 | 0 | cli,docs,mp,tests |
| #4783 | [Bugfix][vLLM] Different images can share the same multimoda | 1/2 | 0 | 1 | 0 | docs,tests,vllm-integration |
| #4805 | mp: VMM CUDA IPC wrapper for cuMemCreate-backed KV caches | 1/1 | 0 | 1 | 0 | docs,platform,tests,vllm-integration |
| #4850 | [Fix][CB] Decide fused-KV packing per group, not per registr | 1/1 | 0 | 1 | 0 | mp,tests |

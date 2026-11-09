# Calibration: AI-only blocker/major findings (reviewer v0, high)

Judge each on the code at the reviewed commit only (PR outcome is irrelevant): is it a real problem a maintainer
would want fixed?  Mark **Y** (real) / **N** (wrong) / **?** (can't tell).

Side evidence, not a criterion (not in the list): v0b draft run on #5685 flagged that `Dockerfile.payload`'s extract stage
can no longer `mkdir /payload` as non-root. It merged unnoticed and was fixed 12 days later in #6056 (bf85b41).

## 1. #5255 [blocker] Late loads in a draining request become L1 objects that can never be evicted (default policy)

- PR: https://github.com/LMCache/LMCache/pull/5255 · code at reviewed commit: [lmcache/v1/distributed/storage_controllers/prefetch_controller.py:1519](https://github.com/LMCache/LMCache/blob/412a0ea86242f01da9df69faedb33052f87f1a5d/lmcache/v1/distributed/storage_controllers/prefetch_controller.py#L1519)
- Judge: valid=False (reserve_write already registers keys with eviction policy; evictable)

> With the default prefetch policy, every L2-loaded key is reserved with is_temporary=True (`plan_l1_retention` returns False). In the drain path, `finish_write` puts the staging entry into `_objects` as resident and unlocked. But `finish_write` only notifies listeners for non-temporary entries (l1_manager.py:584), so `L1EvictionPolicy.on_keys_created` is never called. Eviction is driven by the policy, so these objects are never evicted. They are only freed if a later request happens to `reserve_read` and then `finish_read` the key. Repeated timeouts against a slow L2 fill L1 with entries nothing can evict, and `reserve_write` eventually fails with OOM. The PR description says late loads use `finish_prefetch`, but no such method exists. Fix: on drain, call `finish_write_and_delete` for temporary (non-retained) cells, since no reader is waiting for them. For retained cells, use a dedicated L1 API that admits the object and registers it with eviction but does not trigger a store. Add a test that checks L1 usage and eviction after a drained load completes.

**Your verdict:** 

## 2. #5255 [major] Draining requests hold max_in_flight slots indefinitely; with a hung L2, every request then waits the full budget

- PR: https://github.com/LMCache/LMCache/pull/5255 · code at reviewed commit: [lmcache/v1/distributed/storage_controllers/prefetch_controller.py:1102](https://github.com/LMCache/LMCache/blob/412a0ea86242f01da9df69faedb33052f87f1a5d/lmcache/v1/distributed/storage_controllers/prefetch_controller.py#L1102)
- Judge: valid=True (Draining requests occupy max_in_flight slots until adapters report)

> A request in DRAINING stays in `_in_flight_requests` until its adapter task reports, and the drain has no bound. In the motivating scenario (L2 stuck, #4945), all `max_in_flight` slots (default 8) are taken by drainers after 8 timeouts. From then on, every new LOCK request waits in `_pending_queue` for the full deadline, then gets the L1-only fallback it could have had at submission. NO_LOCK warm requests are never armed, so they wait forever. That is a permanent latency floor equal to the timeout, not 'bounded backpressure'. Either stop counting drainers toward `max_in_flight` (with a separate cap on drainers or drained bytes), or fall back immediately for queued armed requests when every slot is held by a drainer.

**Your verdict:** 

## 3. #5372 [major] Default-on recovery makes servers sharing a base_path without `shared: true` evict each other's files

- PR: https://github.com/LMCache/LMCache/pull/5372 · code at reviewed commit: [lmcache/v1/distributed/l2_adapters/fs_native_l2_adapter.py:122](https://github.com/LMCache/LMCache/blob/b410f8141c5971ff450c61be8d06e77ca5031803/lmcache/v1/distributed/l2_adapters/fs_native_l2_adapter.py#L122)
- Judge: valid=True (Default-on recovery silently evicts files from co-tenant servers after upgrade)

> Before this PR, `shared` only labelled coordinator events: an fs_native server only evicted keys it had stored itself, so several servers (e.g. on one NFS mount, or several models on one cache dir) could share a base_path safely without `shared: true`. With `recover_on_start` defaulting to true, after an upgrade any such server registers every file in the directory on restart, charges it to its own max_capacity_gb, and evicts it oldest first. That deletes files the other live servers are serving, with no error, only cache misses elsewhere. Either default recover_on_start to false for one release, or detect the case (e.g. a lock/owner marker file in base_path held by the live server, refusing or skipping recovery when another holder exists), and add a release-note/upgrade warning that `shared` is now a safety setting for fs_native.

**Your verdict:** 

## 4. #5381 [blocker] Event completion is the wrong retention criterion; completed-but-not-yet-imported handles are swept

- PR: https://github.com/LMCache/LMCache/pull/5381 · code at reviewed commit: [lmcache/v1/platform/base/event_ipc.py:252](https://github.com/LMCache/LMCache/blob/c1ffa08d7337207b0d012cf2c00b286579d0d625/lmcache/v1/platform/base/event_ipc.py#L252)
- Judge: valid=True (Completed-but-unimported events swept; diff lacks min-age grace window)

> Retention must cover the interval until the PEER IMPORTS the handle, not until the GPU work completes. Worker->server: worker_transfer.submit_store/submit_retrieve export an event already recorded on the compute stream that completes almost immediately, while the server under DCP>1 backlog imports it much later; if a sweep runs in between, the event is query()==True, dropped, GC'd, and the server's import_event fails -- the exact failure this PR targets. Server->worker: the server's completion event is imported lazily from get_finished() between engine steps, so a fast transfer can be swept before import (the hipErrorInvalidValue -> EngineDeadError the description says was fixed). The old ring at least kept the last 2048 regardless of completion; this can drop an event at the same export that triggers the sweep. Tie lifetime to the request/response instead (e.g. MessagingFuture.retain_reference(event) as the sglang/TRT/ATOM adapters do, released when the response arrives), or at minimum add the min-age grace window the description promises.

**Your verdict:** 

## 5. #5381 [blocker] Diff does not match the described/validated change; test module breaks on import

- PR: https://github.com/LMCache/LMCache/pull/5381 · code at reviewed commit: [lmcache/v1/platform/base/event_ipc.py:167](https://github.com/LMCache/LMCache/blob/c1ffa08d7337207b0d012cf2c00b286579d0d625/lmcache/v1/platform/base/event_ipc.py#L167)
- Judge: valid=True (Test imports removed constant; diff lacks described min-age/2048)

> The description claims a min-age grace window (_EXPORTED_EVENT_MIN_AGE_S=120s, LMCACHE_EXPORTED_EVENT_MIN_AGE_S override), a sweep every 2048 exports, and an updated tests/v1/platform/test_event_ipc.py. None of that is in the diff: the interval is 4096, there is no age check, and tests are untouched. tests/v1/platform/test_event_ipc.py:14 still imports the removed _EXPORTED_EVENT_RING_SIZE, so the whole module fails collection, and test_exported_event_retention_is_bounded asserts the old ring semantics. Push the actual validated revision and add tests for: in-flight event retained across sweeps, completed event retained within the grace window, completed+old event dropped.

**Your verdict:** 

## 6. #5381 [major] Idle-based expiry has no test coverage

- PR: https://github.com/LMCache/LMCache/pull/5381 · code at reviewed commit: [lmcache/v1/multiprocess/session.py:336](https://github.com/LMCache/LMCache/blob/c1ffa08d7337207b0d012cf2c00b286579d0d625/lmcache/v1/multiprocess/session.py#L336)
- Judge: valid=True (No test for last_active refresh behavior)

> No test verifies that get()/get_or_create() refresh last_active so a touched session survives past ttl, or that an untouched one is still reaped. Existing tests only exercise expiry, which passed under the old created_at rule too. Add a test that touches a session after ttl/2 and asserts cleanup_expired() keeps it, then lets it idle and asserts removal.

**Your verdict:** 

## 7. #5390 [major] Changes the stored-object format for NHD too, with no guard against reading old L2 objects

- PR: https://github.com/LMCache/LMCache/pull/5390 · code at reviewed commit: [lmcache/integration/vllm/kv_cache_group_edits.py:471](https://github.com/LMCache/LMCache/blob/7d89aecbe2c2f2659193d3c337835f56a07ae4cb/lmcache/integration/vllm/kv_cache_group_edits.py#L471)
- Judge: valid=unsure (Format change real; mitigation documented, key-salt is design call)

> Before this PR, an edited rank-4 cache was a rank-5 `[NB,2,BS,1,HS']` view, detected as `NL_X_NB_TWO_BS_NH_HS` (split K/V planes). Now NHD (the common default) emits a fused `[NB,BS,1,CS]`, detected as `NL_X_NB_BS_NH_CS`. The bytes in a memory object for the same chunk are therefore laid out differently. Objects stored in persistent L2 by the previous version will be retrieved into the new view without any error, giving wrong KV and wrong answers. The only mitigation is a note in the PR description. Add a guard: e.g. mix the edited format or an edit-contract version into the object key/model salt, or otherwise reject objects stored under the old contract. At minimum, document the incompatibility in the opaque-page contract section ('Not valid: entries written before this change') and in the release notes.

**Your verdict:** 

## 8. #5685 [major] In-repo CI still mounts HF cache at /root and bind-mounts host dirs not writable by uid 1000

- PR: https://github.com/LMCache/LMCache/pull/5685 · code at reviewed commit: [docker/Dockerfile:119](https://github.com/LMCache/LMCache/blob/e9cbad636c640c9cccf7c91d4e9120a383a5bac7/docker/Dockerfile#L119)
- Judge: valid=True (CI scripts still mount /root HF cache with uid-1000 image)

> `.buildkite/scripts/multiprocessing-test/build-mp-docker-image.sh` builds `--target image-build` (now `USER lmcache`), but `launch-containers.sh` and `test-launch.sh` still mount `~/.cache/huggingface` / `/data1/yihua-model` at `/root/.cache/huggingface`. With HOME=/home/lmcache that mount is silently ignored, so Qwen3-14B is downloaded again into the container layer on every run. `vllm-integration-tests.sh` has the same /root mounts. It also bind-mounts `/tmp/lmcache_internal_api_server/${PORT}`, created by `mkdir -p` on the agent host, and uid 1000 most likely cannot create the socket there. All `.buildkite/k3_tests/*/pipeline.yml` files and `.buildkite/k3_harness/README.md` still use `/root/.cache/huggingface` too. Update these scripts and pipelines in this PR, or pass `--user 0` explicitly, so CI does not regress or silently re-download models.

**Your verdict:** 

## 9. #5685 [major] Operator-managed engines lose access to the 0400 root-owned L2 encryption key Secret

- PR: https://github.com/LMCache/LMCache/pull/5685 · code at reviewed commit: [docker/Dockerfile:148](https://github.com/LMCache/LMCache/blob/e9cbad636c640c9cccf7c91d4e9120a383a5bac7/docker/Dockerfile#L148)
- Judge: valid=True (Secret mode 0400, no fsGroup; uid 1000 can't read)

> The operator's default engine/coordinator/cacheblend image is `lmcache/vllm-openai` (`operator/internal/resources/daemonset.go:92`). The DaemonSet mounts the AES-GCM master key Secret with `DefaultMode: 0o400` and sets no pod `securityContext.fsGroup`/`runAsUser` (daemonset.go:258-276, 384-386). Without fsGroup the projected files are root:root 0400, so an engine running as uid 1000 can no longer read the key and L2 encryption fails at startup. Either update the operator in the same change (set `fsGroup: 1000` or `runAsUser`, or loosen the key mode to 0440 with fsGroup), or keep these images root until the operator is updated. The operator e2e/resources tests should cover this.

**Your verdict:** 

## 10. #5685 [major] Server and clients that share /dev/shm now run as different uids, but SHM files are created 0600

- PR: https://github.com/LMCache/LMCache/pull/5685 · code at reviewed commit: [docker/Dockerfile.standalone:155](https://github.com/LMCache/LMCache/blob/e9cbad636c640c9cccf7c91d4e9120a383a5bac7/docker/Dockerfile.standalone#L155)
- Judge: valid=True (SHM created 0600; mixed-uid pairings break)

> Legacy MP mode shares `/dev/shm` (`--ipc host` or the operator's hostPath mount). PyTorch storage IPC keeps a ref-counter file there, and LMCache's own segments are created with mode 0600 (`posix_shm.py:81`, `SharedMemory` in `mem_alloc.py:159`). The standalone server is now uid 1000, while the documented pairings still use root producers: the README SGLang example (`lmsysorg/sglang`, root) with `lmcache/standalone`, and operator deployments with a root `vllm/vllm-openai` image. uid 1000 cannot open root-owned 0600 files, so CUDA IPC registration fails in that setup. Also, after an upgrade a root-owned stale segment on the shared /dev/shm (sticky dir) makes `alloc_shm_pinned_ptr` raise `PermissionError`, because only `FileNotFoundError` is handled. Document and test mixed-uid pairings, recommend isolated IPC, or create segments with group/other permissions.

**Your verdict:** 

## 11. #5776 [major] Warning assertion is satisfied by the pre-existing abort-cleanup warning, not the new one

- PR: https://github.com/LMCache/LMCache/pull/5776 · code at reviewed commit: [tests/v1/test_v1_adapter_request_finished_scheduler_role.py:295](https://github.com/LMCache/LMCache/blob/37ef9e1d78824b58b3928e85a2775da64c396a28/tests/v1/test_v1_adapter_request_finished_scheduler_role.py#L295)
- Judge: valid=True (Existing abort-cleanup warning already contains request id)

> This test uses `engine=None` with `FINISHED_ABORTED`, so `request_finished` already logs "Skipping abort-time backend cleanup for request req-abort-no-token: lmcache_engine is not initialized ...". That message contains the request id, so `any("req-abort-no-token" in r.getMessage() ...)` passes even if the new first-token warning is deleted or never fires. The test doesn't check the behaviour it claims to cover. Match text unique to the new message, e.g. `"req-abort-no-token" in msg and "output token" in msg`, or `"first-token" in msg`. Or use an engine-initialized connector so the only warning that can carry the id is the new one.

**Your verdict:** 

## 12. #5778 [major] Second, divergent KVEventRecord/KVEventBatch/KV_EVENT_CAPABILITY definitions

- PR: https://github.com/LMCache/LMCache/pull/5778 · code at reviewed commit: [lmcache/v1/multiprocess/kv_event_types.py:68](https://github.com/LMCache/LMCache/blob/d85746d5e0f18981efaed5be50e8abaa12318e33/lmcache/v1/multiprocess/kv_event_types.py#L68)
- Judge: valid=True (Duplicate, divergent KVEventRecord/capability definitions exist in custom_types)

> `custom_types.py` still defines `KV_EVENT_CAPABILITY = "kv_event_stream"` and the live `KVEventRecord`/`KVEventBatch`. Those are what server.py, kv_events.py, transport/base.py, the vLLM adapter and `kv_event_service.proto` use. This file adds same-named types with a different schema (adds block_size/profile_id/world_size/cache_salt; tuples instead of lists; frozen) and a different capability string, `kv_event_native_bindings_v1`. Which one you get depends on the import path; the new tests already mix both (`test_native_kv_event_types` uses the new ones, `test_rpc_errors` the old). The new record also cannot be carried over gRPC, because the proto was not updated. The design doc says this change does not alter the capability or record. Remove these definitions until the consumer change lands, or replace the old ones in one place.

**Your verdict:** 

## 13. #5778 [major] KeyError for bindings whose context has no registered profile; can corrupt state mid-batch

- PR: https://github.com/LMCache/LMCache/pull/5778 · code at reviewed commit: [lmcache/v1/multiprocess/kv_event_residency.py:181](https://github.com/LMCache/LMCache/blob/d85746d5e0f18981efaed5be50e8abaa12318e33/lmcache/v1/multiprocess/kv_event_residency.py#L181)
- Judge: valid=True (_update_chunk indexes _profiles unchecked; can KeyError mid-batch)

> `bind` never checks that `(model, world_size)` has a registered profile, or that `binding.profile_id`/`block_size` match it. `_update_chunk` then indexes `self._profiles[(model, world_size)]` and raises `KeyError`. When this happens inside `_update_owners`, the owners of earlier keys are already mutated and their transitions are lost, so the 'caller serializes, ordered transitions' contract is broken after one bad bind. Validate profile registration and descriptor/profile agreement in `bind` (before mutating anything), and add a test for it.

**Your verdict:** 

## 14. #5778 [major] Profiles can never be released; an engine restart with a new profile is permanently rejected

- PR: https://github.com/LMCache/LMCache/pull/5778 · code at reviewed commit: [lmcache/v1/multiprocess/kv_event_residency.py:71](https://github.com/LMCache/LMCache/blob/d85746d5e0f18981efaed5be50e8abaa12318e33/lmcache/v1/multiprocess/kv_event_residency.py#L71)
- Judge: valid=True (No unregister path; reset keeps profiles, restart mismatch)

> `register_profile` pins `(model_name, world_size)` for the life of the process, and `reset` deliberately keeps profiles. A vLLM/SGLang restart against a long-lived MP server, with a different hash algorithm or seed (so a new `profile_id`) or a different group layout, raises 'mismatch' until the MP server restarts. Add an unregister/drop path tied to context unregistration, or scope profiles to registration lifetime, and test re-registration after unregister.

**Your verdict:** 

## 15. #5827 [major] A single transfer timeout aborts the whole benchmark with no summary

- PR: https://github.com/LMCache/LMCache/pull/5827 · code at reviewed commit: [lmcache/cli/commands/bench/server_bench/client.py:855](https://github.com/LMCache/LMCache/blob/7dc5e35f711d7b8289fc5cb595f13d118d42bca3/lmcache/cli/commands/bench/server_bench/client.py#L855)
- Judge: valid=True (Uncertain flag rejects later ops; baseline aborts, losing metrics)

> After any timeout or worker exception, `_transfer` leaves `_transfer_uncertain=True`, and `_require_started()` then rejects every later operation. In the baseline that includes the `store()` right after a timed-out retrieve (even with token_count==0, because `_check_request_ready` runs before the empty-range early return), `compute_checksums()`, and the next `create_request()`. `BaselineBenchCase.run` only catches KeyboardInterrupt, so `run_server_bench` turns the RuntimeError into `SystemExit(1)` and `_emit_server_bench_metrics` never runs. All metrics from completed sequences are lost. Before this PR a timeout was recorded as a failed `*_succeeded` check and the run continued. Retaining the blocks is enough for safety: quarantine only the affected request's blocks (keep them out of the free pool until close) and let later requests allocate from the rest. Or have the case catch the uncertain state, stop cleanly, and still emit the summary. Add a baseline-level test where a STORE times out and the result/summary is still produced.

**Your verdict:** 

## 16. #5876 [major] Hooks are installed on any attention impl without checking the backend or signature

- PR: https://github.com/LMCache/LMCache/pull/5876 · code at reviewed commit: [lmcache/integration/vllm/experimental/token_drop_adapter.py:161](https://github.com/LMCache/LMCache/blob/011478eb9e73aa9e05e7e2917995499441fe5de1/lmcache/integration/vllm/experimental/token_drop_adapter.py#L161)
- Judge: valid=True (Hooks every impl without checks; MLA/hybrid layers would break)

> Every `no_compile_layers[name].impl` for every layer in `worker._kv_caches` gets wrapped without any check of its type. The wrapper assumes FlashAttention's positional contract `(layer, query, key, value, kv_cache, attn_metadata, ...)`. It also assumes `attn_metadata.num_actual_tokens` exists and that `query` is the unquantized post-RoPE Q. These assumptions fail in several cases. MLA impls take `q, k_c_normed, k_pe` (q may not be the full post-RoPE Q). Mamba/linear-attention layers in `_kv_caches` may not have a compatible `.impl`. Other backends (FlashInfer, Triton, FlexAttention) name metadata fields differently. With fp8 attention, vLLM may quantize the query before calling `impl.forward`. Depending on the case, this either captures the wrong tensor with no error or raises an AttributeError inside the forward pass. Check at install time, before patching anything, that each impl is a supported class (e.g. `FlashAttentionImpl`), that it has no query quantization, and that its metadata type has `num_actual_tokens`. Raise a clear error otherwise.

**Your verdict:** 


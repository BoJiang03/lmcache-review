# Three-way split: reviewer v0 (high), 10 test samples

- Both: 6
- Human only: 8
- AI only: 87
- Human questions/praise (not findings): 4

## Both (human comment ⇔ AI finding)

- #5255-412a0ea8: **0andy**: A question about the `DRAINING` late-success path (from reading the code at `412a0ea`; I haven't run it).  With `RetainPrefetchPolicy`, a late load co
  - AI (major): With the `retain` policy, a drained late load is queued for an L2 store (write-back of data just read from L2)
- #5381-c1ffa08d: **ApostaC**: On nvidia GPUs, setting this to 4096 will cause CUDA OOM, so let's keep this at 2048 if possible
  - AI (major): Sweep interval 4096 contradicts the PR's own OOM warning and doubles retention
- #5390-7d89aecb: **sammshen**: the old text said legacy rank-5 edited groups (0.25 mamba conv-state edit, `hpc_attn`) still resolve block size 1 under HND. still true after this pr,
  - AI (major): Design doc now hides the HND block_size==1 failure for remaining rank-5 edits (Mamba page view)
- #5685-e9cbad63: **ApostaC**: Where will `hf-cache` point to?  Previously, `~/.cache/huggingface` pointed to the folder on the host machine, so people didn't need to download the m
  - AI (minor): Named-volume default contradicts the PR description and drops reuse of the host HF cache
- #5778-d85746d5: **7konigsberg**: Heads up, I think the title and description are still from the extraction step, this diff looks like the event contracts and `CommittedKVResidency` pa
  - AI (blocker): Diff does not implement what the PR title/description claim
- #5876-011478eb: **Zefan-Cai**: This calls with `attn_metadata=None`, which is the one path where the wrapper does nothing, so the test would still pass if install were a no-op. Coul
  - AI (major): The only real-vLLM test covers the no-capture path; positive Q capture against FlashAttentionImpl is untested

## Human only

- #5390-7d89aecb [nit] **sammshen**: nit: `_MambaUnifiedViewEdit.apply` raises on a missing hint, this falls back to the legacy default. not blocking, but the two edits disagreeing on a m
- #5390-7d89aecb [change_request] **sammshen**: fix looks right. synthetic head count is 1, so `[NB, BS, 1, CS]` and `[NB, 1, BS, CS]` are the same bytes, the branch only changes which axis the dete
- #5685-e9cbad63 [change_request] **ApostaC**: Actually after a second look at this file, this is a in-process mode example. Maybe we should remove it.
- #5776-37ef9e1d [change_request] **deng451e**: In-process mode is being deprecated soon, so we probably don’t need to add tests for it.  
- #5827-7dc5e35f [change_request] **maobaolong**: Remove this as it is not used for now.
- #5827-7dc5e35f [change_request] **maobaolong**: Define a data class instead of use tuple of tuple of tuple.
- #5876-011478eb [change_request] **Zefan-Cai**: With the default cudagraph mode, decode batches replay a FULL graph, so this wrapper never runs on decode steps. R-KV's observation window is exactly 
- #5876-011478eb [change_request] **Zefan-Cai**: token-dropping-kv-compaction.md (Query capture section) still says post-RoPE Q comes through `save_kv_layer(..., **kwargs)`. Can we update it to the `

## AI only

| severity | valid | invalid | unsure |
| --- | --- | --- | --- |
| blocker | 2 | 1 | 0 |
| major | 13 | 0 | 1 |
| minor | 35 | 10 | 1 |
| nit | 19 | 5 | 0 |

- #5255-412a0ea8 (blocker, valid=False) Late loads in a draining request become L1 objects that can never be evicted (default policy) — judge: reserve_write already registers keys with eviction policy; evictable
- #5255-412a0ea8 (major, valid=True) Draining requests hold max_in_flight slots indefinitely; with a hung L2, every request then waits the full budget
- #5255-412a0ea8 (minor, valid=True) Aborting a draining request frees staging buffers that a pending adapter may still be writing
- #5255-412a0ea8 (minor, valid=True) Queued-timeout fallback emits L2_PREFETCH_LOOKUP_SUBMITTED although no L2 lookup ran
- #5255-412a0ea8 (minor, valid=True) retained/missed chunk counts are wrong under the `full` fetching policy
- #5255-412a0ea8 (minor, valid=True) Description claims per-KV-group read-lock accounting (#6125), but the code still uses a single scalar num_kv_readers
- #5255-412a0ea8 (minor, valid=True) MP 'deadline' tests never exercise deadline code
- #5255-412a0ea8 (minor, valid=True) Tests only cover DefaultPrefetchPolicy and never check what happens to drained objects
- #5255-412a0ea8 (nit, valid=True) Fixtures are imported across test modules with noqa F811; wall-clock sleeps make the tests slow
- #5255-412a0ea8 (nit, valid=True) Transition tests build the controller with __new__ and assert on the call order of private methods
- #5255-412a0ea8 (nit, valid=True) Expiry sweep rebuilds the pending deque on every loop iteration
- #5372-b410f814 (major, valid=True) Default-on recovery makes servers sharing a base_path without `shared: true` evict each other's files
- #5372-b410f814 (minor, valid=True) Skip warning is logged for adapters that never recover anything
- #5372-b410f814 (minor, valid=True) Whole directory is announced as one L2_KEYS_STORED event
- #5372-b410f814 (minor, valid=True) Directory scan runs under _lifecycle_lock and blocks startup
- #5372-b410f814 (minor, valid=True) External deletes stay counted; the PR records this as an xfail test instead of fixing it
- #5372-b410f814 (minor, valid=True) Orphaned .tmp files from a crash are skipped but never removed
- #5372-b410f814 (minor, valid=True) StorageManager skip and ordering logic only tested when the native extension is built
- #5372-b410f814 (nit, valid=True) Eviction order depends on LRU/ARC inserting batches in reverse
- #5381-c1ffa08d (blocker, valid=True) Event completion is the wrong retention criterion; completed-but-not-yet-imported handles are swept
- #5381-c1ffa08d (blocker, valid=True) Diff does not match the described/validated change; test module breaks on import
- #5381-c1ffa08d (major, valid=True) Idle-based expiry has no test coverage
- #5381-c1ffa08d (minor, valid=True) query() exceptions retain events forever with no log
- #5381-c1ffa08d (minor, valid=False) O(n) driver-query sweep under lock on the export hot path — judge: Amortised cheap query calls; speculative latency concern
- #5381-c1ffa08d (minor, valid=False) Idle TTL removes the absolute backstop and still reaps long single in-flight transfers — judge: Idle-based expiry is intended design; speculative leak
- #5381-c1ffa08d (nit, valid=True) Stale ring-era comment left above new constant
- #5381-c1ffa08d (nit, valid=True) created_at now unused; cleanup_expired docstring stale
- #5390-7d89aecb (major, valid=unsure) Changes the stored-object format for NHD too, with no guard against reading old L2 objects — judge: Format change real; mitigation documented, key-salt is design call
- #5390-7d89aecb (minor, valid=True) BLNHC/BLHNC branches can't be reached; blocks-first layouts always fail the contiguity guard
- #5390-7d89aecb (minor, valid=True) matches() re-fires on the edit's own NHD output; the 'block dim is index 2' invariant no longer holds
- #5390-7d89aecb (minor, valid=False) No-hint test doesn't check edit/detector agreement, despite the PR's 'cannot drift' claim — judge: Shared helper already prevents drift; speculative test hardening
- #5390-7d89aecb (nit, valid=True) Doc still describes the sub-paged edit output as rank 5 for all inputs
- #5390-7d89aecb (nit, valid=True) 'token axis follows NHD/HND' is misleading for HND
- #5390-7d89aecb (nit, valid=False) Function-local imports in test — judge: Local imports likely needed for stub; style noise
- #5685-e9cbad63 (major, valid=True) In-repo CI still mounts HF cache at /root and bind-mounts host dirs not writable by uid 1000
- #5685-e9cbad63 (major, valid=True) Operator-managed engines lose access to the 0400 root-owned L2 encryption key Secret
- #5685-e9cbad63 (major, valid=True) Server and clients that share /dev/shm now run as different uids, but SHM files are created 0600
- #5685-e9cbad63 (minor, valid=True) Image does not work with arbitrary non-root uids (OpenShift, `--user $(id -u)`)
- #5685-e9cbad63 (minor, valid=True) Recommending `chown -R 1000:1000 ~/.cache/huggingface` on the host is invasive
- #5685-e9cbad63 (minor, valid=True) Kubernetes guidance omits fsGroup and the recommended production-stack PVC path
- #5685-e9cbad63 (minor, valid=True) No in-tree test for the non-root image contract
- #5685-e9cbad63 (nit, valid=False) useradd does not pin GID 1000; userdel leaves /home/ubuntu behind — judge: userdel removes ubuntu group; gid 1000 works on default base
- #5776-37ef9e1d (major, valid=True) Warning assertion is satisfied by the pre-existing abort-cleanup warning, not the new one
- #5776-37ef9e1d (minor, valid=unsure) Missing `first_tok` is a new, undocumented case that the in-repo proxy can't handle — judge: Depends on whether engine-aborted responses reach proxy
- #5776-37ef9e1d (minor, valid=False) WARNING on every early client disconnect will be noisy; message lacks request status — judge: Log level preference; matches existing abort warning level
- #5776-37ef9e1d (nit, valid=False) No test for `enable_cache_usage_details_in_response` combined with no first token — judge: Low-value extra test request
- #5776-37ef9e1d (nit, valid=True) Module docstring no longer describes the file's contents
- #5778-d85746d5 (major, valid=True) Second, divergent KVEventRecord/KVEventBatch/KV_EVENT_CAPABILITY definitions
- #5778-d85746d5 (major, valid=True) KeyError for bindings whose context has no registered profile; can corrupt state mid-batch
- #5778-d85746d5 (major, valid=True) Profiles can never be released; an engine restart with a new profile is permanently rejected
- #5778-d85746d5 (minor, valid=True) Owner index mirrors every committed L1 object, including contexts without native events
- #5778-d85746d5 (minor, valid=True) Error envelope misclassifies errors and is inconsistent with gRPC
- #5778-d85746d5 (minor, valid=True) Stream setup error leaves pending_streams entry and a reader that can block forever
- #5778-d85746d5 (minor, valid=False) Server-side default filling assumes all defaulted params are trailing positionals — judge: Client binding prevents it; no such RPC shape exists
- #5778-d85746d5 (minor, valid=True) Bindings not cross-validated against event_profile, and tokens sent twice on STORE
- #5778-d85746d5 (minor, valid=True) Integer identities not range-checked to 64 bits
- #5778-d85746d5 (minor, valid=True) Conflicting duplicates within one bind batch are silently dropped
- #5778-d85746d5 (minor, valid=True) Unexplained duplicate of RegisterKvCacheRequest
- #5778-d85746d5 (nit, valid=True) Quadratic ObjectKey construction per bound chunk commit
- #5778-d85746d5 (nit, valid=True) Design doc describes integration that is not in this PR
- #5805-e78a415b (minor, valid=True) Not every in-tree object-group copy goes through transfer_object_group
- #5805-e78a415b (minor, valid=False) _create_cache_context hook omits model_name/world_size — judge: Speculative future-proofing; no current consumer needs these args
- #5805-e78a415b (minor, valid=False) _make_temp_buffer extension point returns a private type and runs mid-construction — judge: Documentation wish; speculative about override problems
- #5805-e78a415b (minor, valid=True) PR description out of sync with the implemented hook
- #5805-e78a415b (minor, valid=False) Test pins private attributes as extension API — judge: Pinning subclass-read state is intentional; design preference
- #5805-e78a415b (nit, valid=True) Untyped **kwargs hook loses type checking and isn't signature-pinned
- #5805-e78a415b (nit, valid=True) Source-text assertion is brittle
- #5805-e78a415b (nit, valid=True) Hook parameter typed as bare dict
- #5805-e78a415b (nit, valid=True) Function-local import on the per-object-group hot path
- #5827-7dc5e35f (major, valid=True) A single transfer timeout aborts the whole benchmark with no summary
- #5827-7dc5e35f (major, valid=True) PR content contradicts its description and the 4-PR split (concurrency, fill, HTTP removal, explicit IDs, --block-allocation)
- #5827-7dc5e35f (minor, valid=True) Remaining worker futures are abandoned when one raises
- #5827-7dc5e35f (minor, valid=True) Warm-pass miss STORE uploads stale KV from a previous request
- #5827-7dc5e35f (minor, valid=True) Per-worker pools diverge from engine semantics and the stated design
- #5827-7dc5e35f (minor, valid=True) Checksum does one device-to-host copy and sync per tensor per chunk
- #5827-7dc5e35f (minor, valid=False) New GPU-only paths are unvalidated — judge: Asks for process validation, not a concrete code defect
- #5827-7dc5e35f (minor, valid=True) Allocator and uncertain-transfer tests miss key branches
- #5827-7dc5e35f (nit, valid=False) Per-block Python loop for deterministic fill — judge: Minor perf speculation outside timed path
- #5827-7dc5e35f (nit, valid=True) BenchConfig attribute documentation removed
- #5827-7dc5e35f (nit, valid=True) Undocumented LOOKUP read-lock change and helpers re-export seam
- #5876-011478eb (major, valid=True) Hooks are installed on any attention impl without checking the backend or signature
- #5876-011478eb (minor, valid=False) Rollback touches uninstalled layers and is not exception-safe, which can leave stale state — judge: Originals recorded before patching; rollback of unpatched layers is no-op
- #5876-011478eb (minor, valid=True) Undocumented duck-typed worker contract that mutates private attributes; no scoped install/remove
- #5876-011478eb (minor, valid=True) Captured query is a view of a reused buffer, keyed only by layer name
- #5876-011478eb (nit, valid=False) Layer name is taken from the runtime layer instead of the hooked key — judge: layer_name always matches key in vLLM; negligible risk
- #5876-011478eb (nit, valid=True) Hard-coded minimum test count is brittle
- #5876-011478eb (nit, valid=True) Comment refers to unexplained internal step label "S6"

## Human questions / praise

- #5372-b410f814 [question] sahibpreetsingh12: I Tested this on macOS arm64 (CPU-only). Repro details are in #5371. Before this PR, all 16 files were still served after restart but tracked usage wa
- #5805-e78a415b [question] maobaolong: Is it intent to use the lazy import here?
- #5805-e78a415b [praise] maobaolong: LGTM. This PR is a pre-work for doing some extending of https://github.com/LMCache/LMCache-Layerwise/pull/1
- #5876-011478eb [praise] KuntaiDu: I am fine with not enabling prefix caching for the first version.   But prefix caching compatibility needs to be seriously considered in the future --

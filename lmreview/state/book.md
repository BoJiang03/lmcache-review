# Rulebook v0032

49 active entries, 2954 words (when + expect; the reviewer sees these, not why or examples). Generated from book.jsonl; do not edit.

## Principle (40)

### cx05k1-005

**When** A change adds another sibling implementation of a concept loose beside unrelated modules, or a file in one tree (CI folder, scripts directory) references a script or resource inside another tree.

**Expect** Ask to group them in a dedicated folder: sibling implementations into a subpackage for the concept, shared files into one folder every consumer references.

*Why (record only)*: Grouped code is navigable; cross-tree paths break and hide sharing.

<sub>v2 · area ci-build,mp,platform · 3 comments from 3 PRs</sub>

### cx05k1-008

**When** A change splits a batch into groups (by device or backend) and builds results or listener notifications from the per-group passes.

**Expect** Ask that outputs keep input order (placed by original index), tested with items interleaved across groups, and that groups run concurrently (a worker per group), not serially.

*Why (record only)*: Group order reorders outputs; serial shards give no parallelism.

<sub>v2 · area distributed,overall · 2 comments from 1 PRs</sub>

### cx05k1-011

**When** Code wraps calls in threads, executors or async, or loops sleeping to re-check another component's work.

**Expect** Flag by name each wrapped call whose callee does not block (e.g. task submission): call it directly, dropping unneeded async. Ask to replace polling with a status API on the owning component, removing settings only polling needs.

*Why (record only)*: Needless async and polling add complexity, latency and knobs.

<sub>v2 · area mp,overall · 3 comments from 1 PRs</sub>

### cx07k1-002

**When** A change adds tests, CI cases or benchmarks narrower than their place or overlapping existing ones: a file for one backend or variant in a general-purpose folder; tests of straightforward functions; CI cases running one path with different models.

**Expect** Ask to fold them into the existing shared file or case (keeping the most demanding configuration) or remove them, and to keep tests of straightforward functions minimal.

*Why (record only)*: Narrow or overlapping tests fragment folders and cost CI time.

<sub>v3 · area ci-build,examples,overall · 3 comments from 3 PRs</sub>

### cx07k1-004

**When** A change acquires something to release exactly once: in-flight entries (tasks, leases) removed by completion, error or client release; a descriptor or heap object freed per path or held by raw pointer.

**Expect** Ask for one owner releasing it once on every path and client (moving out frees nothing; use an owning type); handles marked released even if release raises; repeated-operation tests asserting return to baseline; a size gauge for pending containers.

*Why (record only)*: Missed releases leak; doubled releases hit reused handles.

<sub>v2 · area distributed,kernels,mp,overall · 7 comments from 4 PRs</sub>

### cx07k1-005

**When** A change adds or keeps code nothing needs: a fallback when an always-needed dependency or requested setting is missing or unsupported; a knob nothing in the repository sets to a non-default value; a check an upstream owner (e.g. the inference engine) already does; logs repeating existing ones, e.g. throttled or periodic logs during a condition whose entry and exit are already logged.

**Expect** Ask why it is needed and to remove it with the counters, flags and branches only it serves; raise an error naming an unsupported value instead of falling back.

*Why (record only)*: Unneeded paths add untested code and hide misconfiguration.

<sub>v2 · area ci-build,memory,mp,overall,vllm-integration · 7 comments from 5 PRs</sub>

### cx07k1-006

**When** A value is optional or special-cased though a real value always makes sense: a parameter defaulting to None that falls back to an ambient default, or a single-item case given as None, a sentinel or a scalar instead of the general structure.

**Expect** Ask to require the real value (a required parameter, the general structure even with one entry) and drop the fallbacks and branches, consistently across related helpers.

*Why (record only)*: Optional forms hide ambient defaults and spread special-case branches.

<sub>v2 · area distributed,mp,platform · 3 comments from 3 PRs</sub>

### cx07k1-007

**When** State depends on a peer or producer: events producers send to a central consumer, or a peer restart detected against a baseline (boot token, epoch) recorded lazily rather than when the dependent state was established.

**Expect** Ask for per-producer sequence numbers the receiver checks for gaps and reordering, and a baseline captured synchronously where the dependent state is created, seeding the detector.

*Why (record only)*: Undetected divergence silently corrupts the consumer's state.

<sub>v2 · area mp,vllm-integration · 2 comments from 2 PRs</sub>

### cx07k1-009

**When** A diff adds or changes a public interface or class without full docstrings or with object or Any types, or deletes or shortens a still-accurate docstring or comment.

**Expect** Require docstrings on every public method describing parameters, return value and errors raised, precise types instead of object or Any, and restoring still-accurate text.

*Why (record only)*: Callers and later readers rely on documented contracts.

<sub>v2 · area core-other,distributed,mp,platform · 5 comments from 3 PRs</sub>

### cx07k1-010

**When** A diff adds or keeps a name or label (identifier, file, setting, enum value) that does not say exactly what the thing does or holds: too generic or narrower than its behavior; missing the qualifier the codebase uses to separate concepts sharing a base word; named after a different kind than its type; readable as more than one quantity; a test file named after an entry point; or an existing label of another feature reused for new data.

**Expect** Ask for a rename with a concrete name (its type's name, the unit tested, the codebase's qualified term), renaming companion types consistently. Ask to split a setting mixing trigger and amount, and to add a dedicated label for new data.

*Why (record only)*: Inaccurate names and labels mislead readers and dispatch.

<sub>v2 · area ci-build,core-other,docs,gpu-connector,mp,overall,vllm-integration · 14 comments from 11 PRs</sub>

### cx08k1-002

**When** Generic-layer or base-type code gains something not inherent to every specialization: a device-type branch, a platform-package import, text naming a vendor or engine, or a base member that some subclasses don't need.

**Expect** Ask to move it to the platform package, the engine integration module or the subclasses that use it, reached through an abstraction, and to phrase generic text vendor- and engine-neutrally.

*Why (record only)*: Specializations in shared layers couple and burden every user.

<sub>v2 · area mp,platform,vllm-integration · 9 comments from 5 PRs</sub>

### cx08k1-003

**When** A doc, comment, name or branch scopes something to modes, paths, vendors or backends: which modes use a component or what a path contains, including text from a deprecated mode; a generic concept framed against one vendor (e.g. 'non-CUDA accelerator', 'CUDA-only'); a claim generalized from one backend; a feature loosely credited to a vendor or hardware generation.

**Expect** Raise each such sentence, proposing wording: every mode using it; only components a path uses; one non-deprecated mode, not a mix; generic concepts by capability, not vendor; claims and branches limited to verified backends, the rest marked 'To be verified'; the precise technical fact, not a vendor label. Known fact: the transfer kernels in a device's ops module serve both engine-driven and LMCache-driven transfer.

*Why (record only)*: Wrong scope misleads backend implementers and hides untested branches.

<sub>v1 · area distributed,docs · 11 comments from 3 PRs</sub>

### cx11k1-001

**When** A change writes persisted data that readers or a restart may load, or changes which fields that data holds.

**Expect** Ask that no partial or incompatible entry loads: write to a temp path, atomically replace() it onto the final path and unlink the temp on failure (the existing pattern); reject or skip old entries missing a field the configuration requires instead of defaulting it.

*Why (record only)*: Partial or stale-format entries otherwise load as valid data.

<sub>v2 · area overall,storage · 2 comments from 2 PRs</sub>

### v0003c1-006

**When** a change extracts a few lines into a new helper function or method that has exactly one call site and no independent reuse

**Expect** Ask the author to inline the code into its single caller, unless the helper provides real reuse or genuinely clarifies the caller.

*Why (record only)*: Trivial single-use helpers add indirection and spread one operation across places without adding reuse.

<sub>v1 · area mp · 2 comments from 1 PRs</sub>

### v0009c5-002

**When** A comment, docstring or message refers outside the file: to PR or plan context (a numbered goal or phase) or to another module or function the code mirrors.

**Expect** Ask to remove the reference and, if it is missing, to state the local reason in terms of the code instead.

*Why (record only)*: Labels from the PR mean nothing to later readers. References to other modules silently go stale when that code changes.

<sub>v3 · area memory,mp · 3 comments from 2 PRs</sub>

### v0009c5-004

**When** A docstring or comment narrates in prose a control flow across components, threads or callbacks.

**Expect** Ask for a call-graph diagram instead (e.g. ASCII) showing the thread or process of each step; if the PR description has one, move it into the code.

*Why (record only)*: A reader cannot reliably rebuild control flow across threads and callbacks from a paragraph. A diagram makes it checkable at a glance.

<sub>v3 · area mp · 1 comments from 1 PRs</sub>

### v0011c1-002

**When** A change sets the thread or dispatch mode of a liveness probe or heartbeat, or puts a slow handler on a path the probe shares.

**Expect** Flag a probe that a slow handler on the same path (e.g. one dispatcher thread) can stall; ask to serve the probe on the normal worker pool.

*Why (record only)*: A probe that a slow unrelated handler can stall reports a healthy server as dead and triggers needless downgrade or reaping.

<sub>v3 · area docs · 1 comments from 1 PRs</sub>

### v0012c3-001

**When** A timing window: (a) a reset of shared state reachable while requests or transfers are in flight; (b) a value from another component or peer (lookup result, health, boot token) used at a later step while its source can change, even before the first observation; (c) lazy run-once side effects in a future or handle several callers may poll.

**Expect** Require a regression test driving the code into the window: (a) reset with a running request, and racing in-flight transfers if asynchronous; (b) the source changing inside it (hit downgraded to zero before allocation, peer restarted before the first check), asserting the code acts on the latest value; repeated identical results do not count; (c) concurrent consumers, one delayed, asserting it runs exactly once.

*Why (record only)*: These failures only appear when a test deliberately drives the code into the window.

<sub>v2 · area mp,overall,vllm-integration · 5 comments from 4 PRs</sub>

### v0012c3-004

**When** A guide to extending the system (new device, backend, connector) lists required APIs incompletely or ungrouped, or mixes required steps with internals or optional features.

**Expect** Ask to list every required API with full signature by category, and to split a basic section with only the steps readers must do from an advanced section for optional features.

*Why (record only)*: Readers need concrete, complete required steps, kept apart from optional depth.

<sub>v3 · area docs · 5 comments from 1 PRs</sub>

### v0015c1-001

**When** A dispatcher or registry calls handlers with a payload in a way that implies their signature (iterating or unpacking it), or registers a type unlike the handler's parameter type.

**Expect** Ask that handlers take one payload passed unchanged and typed Any (wrap multi-argument handlers to take a tuple), and that registered types match the handler parameters.

*Why (record only)*: An implicit or mismatched handler signature works for today's callers but misleads the next one who registers a handler.

<sub>v3 · area mp · 3 comments from 1 PRs</sub>

### v0015c1-003

**When** A registry, cache or map keys values by something that does not determine them (e.g. the registering module), or picks among entries an invariant makes equivalent.

**Expect** Ask to drop that key and its bookkeeping, and to return the first equivalent match.

*Why (record only)*: Keying by an irrelevant dimension adds priority rules and documented ambiguity, and it suggests that entries can differ when they cannot.

<sub>v3 · area mp · 2 comments from 1 PRs</sub>

### v0016c1-002

**When** A change computes, copies or allocates a value unconditionally before a branch, but some branch overwrites, replaces or ignores it.

**Expect** Ask the author to move the computation into the branch or branches that use the value.

*Why (record only)*: Unconditional work that one branch discards costs time and memory on that path and hides which path depends on the value.

<sub>v2 · area inprocess · 1 comments from 1 PRs</sub>

### v0017c2-004

**When** A change uses an object (client, socket, connection) from code that may run on another thread, such as a callback.

**Expect** Ask which thread runs it and to verify the object is thread-safe; zmq sockets are not.

*Why (record only)*: Concurrent use of a non-thread-safe client or socket corrupts messages or crashes intermittently.

<sub>v3 · area mp · 1 comments from 1 PRs</sub>

### v0019c1-006

**When** A change adds an option or parameter meant only for benchmarking, testing or experiments that changes behavior production should not use.

**Expect** Ask to label it non-production in its docstring or help text, e.g. 'benchmark only', wherever it is declared.

*Why (record only)*: An unlabeled option looks like a supported production setting, and users will enable it in production.

<sub>v2 · area distributed,mp · 2 comments from 1 PRs</sub>

### v0019c1-008

**When** A workflow acquires locks, pins or references on items, then later releases some because they were not needed.

**Expect** Ask to simplify the workflow: determine the needed items first and acquire only those.

*Why (record only)*: Acquire/undo sequences are hard to follow and add paths where locks leak, are released twice or are briefly inconsistent.

<sub>v3 · area distributed · 1 comments from 1 PRs</sub>

### v0019c1-010

**When** A change adds state other modules access directly or existing components hold, generalizes vendor-specific or experimental logic (e.g. CUDA-only optimizations), or rewrites working code into a more complex form.

**Expect** Flag each, even if it removes duplication: drop the state, keep that logic concrete until stable, reuse existing functions unchanged (import, duplicate or move to utils): duplicate first, refactor later.

*Why (record only)*: Abstractions designed before the code stabilizes lock in the wrong shape and add complexity. Duplicating first and refactoring later is cheaper and safer than rewriting working code.

<sub>v3 · area overall · 4 comments from 1 PRs</sub>

### v0020c1-001

**When** A change adds or moves definitions out of the layout below, e.g. a private helper between public methods.

**Expect** Ask (nit) to move them into this order: imports; private `_` helpers and classes; public classes (`__init__`, public methods, private `_` methods last); public module-level functions used by other modules.

*Why (record only)*: A predictable layout lets readers find the public surface first and the helpers in one known place.

<sub>v3 · area distributed,platform · 2 comments from 2 PRs</sub>

### v0021c1-001

**When** A diff edits text in a hard-wrapped doc paragraph, leaving any edited line noticeably shorter or longer than the file's wrap width, or whitespace damage (trailing, doubled, broken indentation).

**Expect** Check every edited paragraph; ask, as a nit, to fix the whitespace damage and reflow it to the file's wrap width.

*Why (record only)*: Ragged or damaged wrapping left behind by a rewording makes doc sources inconsistent and harder to read. It also makes later diffs noisy.

<sub>v2 · area docs · 1 comments from 1 PRs</sub>

### v0022c1-001

**When** A test explicitly selects the implementation under test (e.g. imports a fallback backend) yet gates, skips or reroutes cases on device, platform or what another implementation (e.g. compiled ops) supports.

**Expect** Ask to remove that gating and its comments and run the cases unconditionally; keep only guards for a requirement of the selected implementation itself.

*Why (record only)*: Guards tied to a different backend silently drop coverage of the code the test exists to check. They also mislead readers about what the test depends on.

<sub>v2 · area tests · 1 comments from 1 PRs</sub>

### v0023c1-002

**When** A change adds a user-visible feature, component or data format, or changes behavior users observe or docs describe (protocol, recovery, on-disk format).

**Expect** Ask to update every doc describing it, not just one (design docs, configuration reference); add a usage page for a new feature, and a design doc under docs/design per CLAUDE.md and CONTRIBUTING.md for a new component, algorithm or format. Ask separately for each consequence users hit: timing bounds via their controlling setting, state lost and rebuilt after recovery, migration steps like clearing old data.

*Why (record only)*: Features and behavior changes without docs cannot be used, operated or maintained correctly, and existing docs go stale.

<sub>v3 · area distributed,docs,overall · 7 comments from 5 PRs</sub>

### v0023c1-006

**When** A change puts a once-per-deployment action (starting a shared server, global setup) in a path that runs in every worker or rank.

**Expect** Ask to move it to a single-instance role, such as the scheduler, or an elected rank.

*Why (record only)*: Running a singleton action in every replica starts duplicates, races on ports and shared resources, or wastes work.

<sub>v3 · area vllm-integration · 1 comments from 1 PRs</sub>

### v0023c1-008

**When** A change adds behavior seen only when the real engine runs multi-process or multi-rank (launch, per-rank roles, cross-process setup), covered only by unit tests or mocks, or untested.

**Expect** Ask for a case in the existing multi-process end-to-end suite that starts the real engine that way and asserts the feature's outcome.

*Why (record only)*: Multi-process interactions such as duplicate launches or wrong roles are invisible to single-process unit tests and mocks.

<sub>v2 · area overall · 1 comments from 1 PRs</sub>

### v0023c1-010

**When** Code writes in place into a tensor derived from the destination by a transform that may copy (reshape, flatten, permute, contiguous).

**Expect** Ask to write directly into the destination with explicit indices, as sibling branches do, and for a test asserting the destination changed, with every merged dimension >1.

*Why (record only)*: A write into a hidden copy silently leaves the real buffer unchanged, and tests with degenerate shapes still pass.

<sub>v3 · area overall,platform · 3 comments from 1 PRs</sub>

### v0023c1-013

**When** A function returns a tuple or record with a component that echoes a parameter or that no caller uses.

**Expect** Ask to drop that component and update the return type and unpacking.

*Why (record only)*: Echoed or unused return values widen the API and mislead readers into thinking the value is transformed.

<sub>v6 · area gpu-connector · 1 comments from 1 PRs</sub>

### v0023c1-014

**When** A diff adds or fixes, or the review finds, a deterministic boundary or error-path defect that no test in the diff forces. Typical cases: a name, path or buffer built by adding to an input (suffix, prefix, header), so that a valid input can cross a system limit; cleanup in finally/except whose own call can raise; a branch relying on an optional argument that callers may omit.

**Expect** For each such defect, raise a separate point in the same review asking for a focused regression test. The test must force exactly that condition (valid input at the limit plus the addition; the cleanup call made to raise; the argument omitted) and must fail without the fix. Never report the bug or accept its fix without also asking for its test.

*Why (record only)*: Edge-case and error-path fixes regress silently unless a test pins the exact triggering condition.

<sub>v5 · area overall · 1 comments from 1 PRs</sub>

### v0024c1-002

**When** A branch reads a public optional parameter whose default (0, None) is invalid there (division, shape), though validation or the reference requires it only for other branches.

**Expect** Ask to derive the value without that parameter, keeping reference parity, and for a test omitting it.

*Why (record only)*: A documented default that works on the reference path becomes a crash on the new branch, which breaks parity for callers that follow the public contract.

<sub>v4 · area overall,platform · 3 comments from 1 PRs</sub>

### v0026c1-012

**When** Code on a per-request hot path (retrieve, store, transfer) allocates a fresh buffer or tensor every call, e.g. concatenating or stacking results.

**Expect** Ask, as a nit, for a comment there noting the per-call allocation and the reuse option, e.g. a preallocated buffer of maximum size.

*Why (record only)*: Hidden per-call allocations add latency and memory churn, and without a note they are never revisited.

<sub>v2 · area core-other · 1 comments from 1 PRs</sub>

### v0027c1-002

**When** A comment or docstring (code, scripts, config) is long for what it annotates: narrating internals, history or rationale, repeating an explanation given elsewhere, or with no clear purpose there.

**Expect** Ask, as a nit, to cut docstrings to caller-facing behavior and delete other narration; a fact readers truly need becomes a short inline NOTE, with proposed wording.

*Why (record only)*: Long narration buries the one fact a reader needs and goes stale; the team repeatedly asks for it to be removed or reduced to one line.

<sub>v2 · area ci-build,mp,vllm-integration · 8 comments from 2 PRs</sub>

### v0031c1-002

**When** A reset, clear, shutdown or teardown frees resources or drops state that in-flight work, possibly in other participants, may still hold.

**Expect** Ask how it ensures quiescence: drain or reject work across all participants, or keep locked entries and return failure, and never force-free resources in use. If a drain bounded by a timeout ends with work still active, teardown must stay blocked or fail closed instead of logging and proceeding.

*Why (record only)*: Freeing resources under running work corrupts or crashes in-flight transfers.

<sub>v1 · area mp,vllm-integration · 2 comments from 2 PRs</sub>

### v0032c1-001

**When** Deferred, queued or retried work captures an entry, registration or handle, but later resolves its target again by a reusable key (ID, name, slot). This includes a fallback that does a fresh lookup when the capture found nothing.

**Expect** Ask to bind the work to the captured entry or its generation. When that entry is missing or no longer current, the work must fail directly and run its failure cleanup (e.g. releasing held locks), never calling code that looks the key up again. Ask for a separate regression test for each such path. The test removes the entry and re-registers the same key before the work runs, then asserts the work fails without touching the replacement. A test of one path does not cover another.

*Why (record only)*: A reused key can point to a replacement target, so stale work silently runs against the new registration with old events, handles or IDs. Only a test that re-registers inside the window proves that each path is bound.

<sub>v1 · area mp · 3 comments from 1 PRs</sub>

## Knowledge (9)

### cx08k1-001

**When** Code re-implements what the standard library or LMCache already provides: manual grouping, counting or deduplicating loops; logic repeating another function's; an LMCache capability (e.g. eviction, MP server health checks) rebuilt or reached through another channel.

**Expect** Name the library function or existing code and ask to reuse it. Known: eviction policies live in lmcache/v1/distributed/eviction_policy/; MP server health checks and communication go over the ZMQ MessageQueueClient, as in the health-monitoring thread in vllm_multi_process_adapter.py.

*Why (record only)*: Reused code is shorter, familiar and maintained once.

<sub>v2 · area distributed,docs,mp,vllm-integration · 5 comments from 3 PRs</sub>

### v0011c1-003

**When** One MP-engine module calls, holds or receives a sibling module.

**Expect** MPEngineContext owns all submodules and the storage manager. Submodules include the management module, the GPU/CPU transfer modules, blend modules and others. Each module holds a reference only to the context and cannot see its siblings. Ask to call `self._ctx.<method>` instead, letting the context dispatch to the correct module.

*Why (record only)*: Only the context knows which sibling, for example which transfer module, is active. Wiring siblings to each other bypasses the ownership tree and couples the modules.

<sub>v3 · area docs · 1 comments from 1 PRs</sub>

### v0019c1-009

**When** Transfer code needs KV group geometry or block IDs, or adds types holding it.

**Expect** KVLayerGroupsManager (lmcache/v1/kv_layer_groups.py) holds all kernel-group and object-group information for a registered KV cache. It is built during register_kv_cache in a transfer-mode-agnostic way. Require each path to build it and parse block IDs per KV layer group; remove types that re-derive it.

*Why (record only)*: A second representation of group geometry duplicates the source of truth and drifts from it, and paths that do not use KVLayerGroupsManager lack hybrid-model support.

<sub>v3 · area overall · 3 comments from 1 PRs</sub>

### v0023c1-004

**When** A diff keeps an old public name after a rename, or adds or edits a base class with many methods.

**Expect** LMCache provides `@lmcache_deprecate` in `lmcache.utils`. MP-mode code: lmcache/v1/multiprocess/**, lmcache_mp_connector.py, vllm_multi_process_adapter.py. Keep an old name as a `def` wrapper with it, not an alias. Ask base-class docstrings to mark which methods MP mode uses and which only non-MP mode does.

*Why (record only)*: Non-MP mode is deprecated. Its code must warn users and be clearly separable from the MP path so it can be removed later; readers of shared bases must be able to tell which methods the MP path depends on.

<sub>v5 · area gpu-connector,mp · 3 comments from 2 PRs</sub>

### v0023c1-009

**When** Code stores engine KV cache tensors or views on `self` (any class, however short-lived), a closure or a cache.

**Expect** Every reference LMCache holds to the engine's GPU KV tensors must be dropped when the serving engine disconnects or unregisters its KV cache. Ask to keep only derived metadata or pass tensors per call.

*Why (record only)*: Hidden references to GPU KV tensors keep engine memory alive after the engine disconnects.

<sub>v5 · area gpu-connector · 1 comments from 1 PRs</sub>

### v0023c1-012

**When** An added line references `native_storage_ops` (import, string module path, mock.patch target).

**Expect** `lmcache.native_storage_ops` no longer exists; its contents, such as Bitmap, live in `lmcache.lmcache_native`. Note the ModuleNotFoundError at import and suggest `from lmcache.lmcache_native import <name>` or the matching string path.

*Why (record only)*: A stale import of the removed native module breaks module load and every test that imports the module.

<sub>v5 · area distributed · 2 comments from 1 PRs</sub>

### v0026c1-004

**When** Text or names call a block or chunk itself 'physical' or 'logical'.

**Expect** In LMCache a block or chunk always corresponds to a fixed, predefined set of tokens. 'Physical' vs 'logical' qualifies only its size: the tensor dimension vs the number of tokens it logically covers. Ask to qualify the size instead.

*Why (record only)*: Qualifying the block instead of its size implies two kinds of blocks that do not exist and confuses the tensor-size vs token-count distinction.

<sub>v2 · area mp · 1 comments from 1 PRs</sub>

### v0026c1-007

**When** A change adds an MP-server message-queue handler or client call that only returns information, not a KV-cache operation.

**Expect** In the MP server, the message-queue path is reserved for KV-cache operations and their lifecycle, plus liveness checks of that path. Informational queries belong on the server's HTTP endpoints. Ask to serve it over HTTP.

*Why (record only)*: This keeps the KV-cache message path focused on cache traffic and uses HTTP for ad-hoc information queries.

<sub>v2 · area mp · 1 comments from 1 PRs</sub>

### v0026c1-011

**When** Code updates recency (LRU touch, eviction order) for a sequence of chunks, on a hit or store.

**Expect** LMCache convention: touch or insert one sequence's chunks in reverse order, last chunk first, so suffixes are evicted before prefixes. Flag forward-order updates; ask to follow the existing LRU update code.

*Why (record only)*: Evicting a prefix chunk makes every later chunk of that sequence unusable, so suffixes must be evicted first.

<sub>v2 · area core-other · 1 comments from 1 PRs</sub>

## Retired (62)

- cx05k1-002: regrouped
- cx05k1-004: regrouped
- cx05k1-012: regrouped
- cx06k1-001: regrouped
- cx06k1-002: regrouped
- cx06k1-004: regrouped
- v0003c1-001: Group sibling implementations and shared base abstractions into their own subpackage folders
- v0003c1-003: Workers-to-coordinator events carry monotonic sequence numbers
- v0003c1-004: Reuse existing eviction policy implementations instead of writing new ones
- v0003c1-005: Unambiguous config names; separate trigger threshold from action amount
- v0003c1-007: Keep docstrings and comments to the contract; no implementation narration
- v0003c1-008: Public interface methods need docstrings and precise types
- v0003c1-009: Make needed parameters required rather than Optional with None default
- v0003c1-010: Source file ordering convention
- v0003c1-011: Renamed public APIs keep the old name as a deprecated wrapper
- v0004c1-001: Comments must be self-contained, with no PR-local planning labels
- v0006c1-004: Base types hold only inherent/used capabilities; others go in subclasses or opt-in interfaces
- v0008c1-001: Atomic file writes via a temporary file and rename
- v0008c1-002: Reset/clear must not free or discard state that in-flight work still holds
- v0008c1-003: Regression test for reset/clear while work is active
- v0009c5-005: no fallback path for a dependency that is always present where the code runs
- v0009c5-006: extension guides state concrete steps and complete, grouped API signatures
- v0009c5-007: documentation claims must match the current code and describe one mode
- v0009c5-008: vendor-neutral, capability-based framing of device-generic concepts
- v0009c5-009: extension guides: minimal basic path plus a separate opt-in advanced section
- v0010c1-001: names must match the actual scope, action and owner of what they name
- v0011c1-001: regression test for a value changing between observation and use
- v0011c1-004: narrow standalone file in a general-purpose folder
- v0011c1-005: precise, verified scope for claims about hardware/backend behavior
- v0011c1-006: capture change-detection baseline when the dependent state is established
- v0011c1-007: every client path must complete a new lifecycle/release step
- v0011c1-008: concurrent-consumer test for lazy one-time processing
- v0013c2-001: consolidated
- v0014c1-001: consolidated
- v0015c1-004: minimal tests for straightforward functions, in the category's shared test file
- v0015c1-005: user-facing docs for new user-visible support
- v0015c1-006: observability for leak-prone pending-work containers
- v0015c1-007: don't duplicate config validation the owning engine already performs
- v0017c2-001: docs for new or changed user-visible behavior and its consequences
- v0017c2-002: method contracts: docstrings with parameters and return values, precise types on interfaces
- v0017c2-003: reject old-format persisted entries instead of defaulting missing fields
- v0017c2-005: redundant logging and the bookkeeping that serves it
- v0017c2-006: invalidate a handle before or regardless of a failing release
- v0019c1-004: no async or thread offloading for non-blocking calls
- v0019c1-005: status-query API instead of a polling loop
- v0019c1-007: keep still-accurate docstrings
- v0020c1-002: no silent fallbacks; fail clearly
- v0020c1-003: uniform representation instead of special-casing the trivial case
- v0020c1-004: use library utilities instead of hand-written equivalents
- v0023c1-001: names must state exactly what the thing is, without clashing or breaking sibling conventions
- v0023c1-003: reuse LMCache's existing shared implementation or channel instead of a parallel one
- v0023c1-007: new code duplicates logic already present in another function
- v0024c1-001: explicit ownership of heap objects passed as raw owning pointers in C/C++
- v0026c1-002: no vendor or engine specialization inside the generic layer
- v0026c1-005: Shared files reached by path across separate directory trees
- v0026c1-006: Remove configuration knobs never set to a non-default value
- v0026c1-008: grouped or sharded processing must preserve request order in outputs
- v0026c1-009: sharded work must run concurrently
- v0026c1-010: dedicated enum or format value for a new kind of data
- v0026c1-013: merge redundant overlapping CI or end-to-end test variants
- v0027c1-001: Keep vendor/engine specifics out of the generic layer, in code and in its text
- v0031c1-003: deferred work must stay bound to the registration it captured

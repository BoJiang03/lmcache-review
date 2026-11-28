# Rulebook v0043

76 active entries, 5514 words (when + expect; the reviewer sees these, not why or examples). Generated from book.jsonl; do not edit.

## Principle (62)

### cx05k1-005

**When** A change adds another sibling implementation of a concept loose beside unrelated modules, or a file in one tree (CI folder, scripts directory) references a script or resource inside another tree.

**Expect** Ask to group them in a dedicated folder: sibling implementations into a subpackage for the concept, shared files into one folder every consumer references.

*Why (record only)*: Grouped code is navigable; cross-tree paths break and hide sharing.

<sub>v2 · minor severity · area ci-build,mp,platform · 3 comments from 3 PRs</sub>

### cx05k1-008

**When** A change splits a batch into groups (by device, backend, size or another attribute) and builds results or listener notifications from the per-group passes.

**Expect** Where an output is positional, or a named consumer relies on its order, ask that it keep input order (placed by original index), tested with items interleaved across groups. Keyed results and aligned pairs are fine. Where groups do blocking work on independent devices or backends, ask that they run concurrently (a worker per group), not serially.

*Why (record only)*: Grouping silently reorders positional outputs and serializes independent I/O. Keyed outputs and in-memory passes are unaffected.

<sub>v3 · major severity · area distributed,overall · 2 comments from 1 PRs</sub>

### cx05k1-011

**When** Code wraps calls in threads, executors or async, or loops sleeping to re-check another component's work.

**Expect** Flag by name each wrapped call whose callee does not block (e.g. task submission): call it directly, dropping unneeded async. Ask to replace polling with a status API on the owning component, removing settings only polling needs.

*Why (record only)*: Needless async and polling add complexity, latency and knobs.

<sub>v2 · major severity · area mp,overall · 3 comments from 1 PRs</sub>

### cx07k1-002

**When** A change adds benchmarks, CI or end-to-end cases that are narrower than their place or overlap existing ones, or adds tests of straightforward functions to a shared test file. Narrow cases include a file for one backend or variant in a general-purpose folder, or cases running one path with different models.

**Expect** Ask to fold them into the existing shared file or case, keeping the most demanding configuration, or to remove them. Ask to keep tests of straightforward functions minimal. Do not ask to cut, merge or move unit tests of a module's own behavior that sit in their own file.

*Why (record only)*: Duplicated CI cases and benchmarks cost run time and maintenance. Cheap focused unit-test files do not.

<sub>v4 · minor severity · area ci-build,examples,overall · 3 comments from 3 PRs</sub>

### cx07k1-004

**When** A change acquires something to release exactly once: in-flight entries (tasks, leases) removed by completion, error or client release; a descriptor or heap object freed per path or held by raw pointer.

**Expect** Ask for one owner releasing it once on every path and client (moving out frees nothing; use an owning type); handles marked released even if release raises; repeated-operation tests asserting return to baseline; a size gauge for pending containers.

*Why (record only)*: Missed releases leak; doubled releases hit reused handles.

<sub>v2 · blocker severity · area distributed,kernels,mp,overall · 7 comments from 4 PRs</sub>

### cx07k1-005

**When** A change adds or keeps code nothing needs: a fallback when an always-needed dependency or requested setting is missing or unsupported; a knob nothing in the repository sets to a non-default value; a check an upstream owner (e.g. the inference engine) already does; logs repeating existing ones, e.g. throttled or periodic logs during a condition whose entry and exit are already logged.

**Expect** Ask why it is needed and to remove it with the counters, flags and branches only it serves; raise an error naming an unsupported value instead of falling back.

*Why (record only)*: Unneeded paths add untested code and hide misconfiguration.

<sub>v2 · major severity · area ci-build,memory,mp,overall,vllm-integration · 7 comments from 5 PRs</sub>

### cx07k1-006

**When** A value is optional or special-cased though a real value always makes sense: a parameter defaulting to None that falls back to an ambient default, or a single-item case given as None, a sentinel or a scalar instead of the general structure.

**Expect** Ask to require the real value (a required parameter, the general structure even with one entry) and drop the fallbacks and branches, consistently across related helpers.

*Why (record only)*: Optional forms hide ambient defaults and spread special-case branches.

<sub>v2 · minor severity · area distributed,mp,platform · 3 comments from 3 PRs</sub>

### cx07k1-007

**When** State depends on a peer or producer: events producers send to a central consumer, or a peer restart detected against a baseline (boot token, epoch) recorded lazily rather than when the dependent state was established.

**Expect** Ask for per-producer sequence numbers the receiver checks for gaps and reordering, and a baseline captured synchronously where the dependent state is created, seeding the detector.

*Why (record only)*: Undetected divergence silently corrupts the consumer's state.

<sub>v2 · major severity · area mp,vllm-integration · 2 comments from 2 PRs</sub>

### cx07k1-009

**When** A diff adds or changes a public interface or class without full docstrings or with object or Any types, or deletes or shortens a still-accurate docstring or comment.

**Expect** Require docstrings on every public method describing parameters, return value and errors raised, precise types instead of object or Any, and restoring still-accurate text.

*Why (record only)*: Callers and later readers rely on documented contracts.

<sub>v2 · minor severity · area core-other,distributed,mp,platform · 5 comments from 3 PRs</sub>

### cx07k1-010

**When** A diff adds or keeps a name or label (identifier, file, setting, enum value) that does not say exactly what the thing does or holds: too generic or narrower than its behavior; missing the qualifier the codebase uses to separate concepts sharing a base word; named after a different kind than its type; readable as more than one quantity; a test file named after an entry point; or an existing label of another feature reused for new data.

**Expect** Ask for a rename with a concrete name (its type's name, the unit tested, the codebase's qualified term), renaming companion types consistently. Ask to split a setting mixing trigger and amount, and to add a dedicated label for new data.

*Why (record only)*: Inaccurate names and labels mislead readers and dispatch.

<sub>v2 · minor severity · area ci-build,core-other,docs,gpu-connector,mp,overall,vllm-integration · 14 comments from 11 PRs</sub>

### cx08k1-002

**When** Generic-layer or base-type code gains something not inherent to every specialization: a device-type branch, a platform-package import, text naming a vendor or engine, or a base member that some subclasses don't need.

**Expect** Ask to move it to the platform package, the engine integration module or the subclasses that use it, reached through an abstraction, and to phrase generic text vendor- and engine-neutrally.

*Why (record only)*: Specializations in shared layers couple and burden every user.

<sub>v2 · major severity · area mp,platform,vllm-integration · 9 comments from 5 PRs</sub>

### cx08k1-003

**When** A doc, comment, name or branch scopes something to modes, paths, vendors or backends: which modes use a component or what a path contains, including text from a deprecated mode; a generic concept framed against one vendor (e.g. 'non-CUDA accelerator', 'CUDA-only'); a claim generalized from one backend; a feature loosely credited to a vendor or hardware generation.

**Expect** Raise each such sentence, proposing wording: every mode using it; only components a path uses; one non-deprecated mode, not a mix; generic concepts by capability, not vendor; claims and branches limited to verified backends, the rest marked 'To be verified'; the precise technical fact, not a vendor label. Known fact: the transfer kernels in a device's ops module serve both engine-driven and LMCache-driven transfer.

*Why (record only)*: Wrong scope misleads backend implementers and hides untested branches.

<sub>v1 · minor severity · area distributed,docs · 11 comments from 3 PRs</sub>

### cx11k1-001

**When** A change writes persisted data that readers or a restart may load, or changes which fields that data holds.

**Expect** Ask that no partial or incompatible entry loads: write to a temp path, atomically replace() it onto the final path and unlink the temp on failure (the existing pattern); reject or skip old entries missing a field the configuration requires instead of defaulting it.

*Why (record only)*: Partial or stale-format entries otherwise load as valid data.

<sub>v2 · major severity · area overall,storage · 2 comments from 2 PRs</sub>

### v0003c1-006

**When** a change extracts a few lines into a new helper function or method that has exactly one call site and no independent reuse

**Expect** Ask the author to inline the code into its single caller, unless the helper provides real reuse or genuinely clarifies the caller.

*Why (record only)*: Trivial single-use helpers add indirection and spread one operation across places without adding reuse.

<sub>v1 · nit severity · area mp · 2 comments from 1 PRs</sub>

### v0009c5-002

**When** A comment, docstring or message refers outside the file. It points to PR or plan context (a numbered goal or phase), or it justifies the code by another module or function ('same as', 'matching', 'mirrors').

**Expect** Ask to remove the reference and, if the local reason is missing, to state it in terms of the code. Do not flag a pointer to where a contract this code consumes or emulates is defined, such as the producer of a format it decodes or the native layer a test double stands in for.

*Why (record only)*: Readers cannot follow plan context or 'same as X' justifications. A pointer to a contract's owner tells them where the truth lives.

<sub>v4 · nit severity · area memory,mp · 3 comments from 2 PRs</sub>

### v0009c5-004

**When** A docstring or comment narrates in prose a control flow across components, threads or callbacks.

**Expect** Ask for a call-graph diagram instead (e.g. ASCII) showing the thread or process of each step; if the PR description has one, move it into the code.

*Why (record only)*: A reader cannot reliably rebuild control flow across threads and callbacks from a paragraph. A diagram makes it checkable at a glance.

<sub>v3 · nit severity · area mp · 1 comments from 1 PRs</sub>

### v0011c1-002

**When** A change sets the thread or dispatch mode of a liveness probe or heartbeat, or puts a slow handler on a path the probe shares.

**Expect** Flag a probe that a slow handler on the same path (e.g. one dispatcher thread) can stall; ask to serve the probe on the normal worker pool.

*Why (record only)*: A probe that a slow unrelated handler can stall reports a healthy server as dead and triggers needless downgrade or reaping.

<sub>v3 · major severity · area docs · 1 comments from 1 PRs</sub>

### v0012c3-001

**When** A timing window: (a) a reset of shared state reachable while requests or transfers are in flight; (b) a value from another component or peer (lookup result, health, boot token) used at a later step while its source can change, even before the first observation; (c) lazy run-once side effects in a future or handle several callers may poll.

**Expect** Require a regression test driving the code into the window: (a) reset with a running request, and racing in-flight transfers if asynchronous; (b) the source changing inside it (hit downgraded to zero before allocation, peer restarted before the first check), asserting the code acts on the latest value; repeated identical results do not count; (c) concurrent consumers, one delayed, asserting it runs exactly once.

*Why (record only)*: These failures only appear when a test deliberately drives the code into the window.

<sub>v2 · major severity · area mp,overall,vllm-integration · 5 comments from 4 PRs</sub>

### v0012c3-004

**When** A guide to extending the system (new device, backend, connector) lists required APIs incompletely or ungrouped, or mixes required steps with internals or optional features.

**Expect** Ask to list every required API with full signature by category, and to split a basic section with only the steps readers must do from an advanced section for optional features.

*Why (record only)*: Readers need concrete, complete required steps, kept apart from optional depth.

<sub>v3 · major severity · area docs · 5 comments from 1 PRs</sub>

### v0015c1-001

**When** A dispatcher or registry calls handlers with a payload in a way that implies their signature (iterating or unpacking it), or registers a type unlike the handler's parameter type.

**Expect** Ask that handlers take one payload passed unchanged and typed Any (wrap multi-argument handlers to take a tuple), and that registered types match the handler parameters.

*Why (record only)*: An implicit or mismatched handler signature works for today's callers but misleads the next one who registers a handler.

<sub>v3 · minor severity · area mp · 3 comments from 1 PRs</sub>

### v0015c1-003

**When** A registry, cache or map keys values by something that does not determine them (e.g. the registering module), or picks among entries an invariant makes equivalent.

**Expect** Ask to drop that key and its bookkeeping, and to return the first equivalent match.

*Why (record only)*: Keying by an irrelevant dimension adds priority rules and documented ambiguity, and it suggests that entries can differ when they cannot.

<sub>v3 · major severity · area mp · 2 comments from 1 PRs</sub>

### v0016c1-002

**When** A change computes, copies or allocates a value unconditionally before a branch, but some branch overwrites, replaces or ignores it.

**Expect** Ask the author to move the computation into the branch or branches that use the value.

*Why (record only)*: Unconditional work that one branch discards costs time and memory on that path and hides which path depends on the value.

<sub>v2 · nit severity · area inprocess · 1 comments from 1 PRs</sub>

### v0017c2-004

**When** A change uses an object (client, socket, connection) from code that may run on another thread, such as a callback.

**Expect** Ask which thread runs it and to verify the object is thread-safe; zmq sockets are not.

*Why (record only)*: Concurrent use of a non-thread-safe client or socket corrupts messages or crashes intermittently.

<sub>v3 · major severity · area mp · 1 comments from 1 PRs</sub>

### v0019c1-006

**When** A change adds an option or parameter meant only for benchmarking, testing or experiments that changes behavior production should not use.

**Expect** Ask to label it non-production in its docstring or help text, e.g. 'benchmark only', wherever it is declared.

*Why (record only)*: An unlabeled option looks like a supported production setting, and users will enable it in production.

<sub>v2 · nit severity · area distributed,mp · 2 comments from 1 PRs</sub>

### v0019c1-008

**When** A workflow acquires locks, pins or references on items, then later releases some because they were not needed.

**Expect** Ask to simplify the workflow: determine the needed items first and acquire only those.

*Why (record only)*: Acquire/undo sequences are hard to follow and add paths where locks leak, are released twice or are briefly inconsistent.

<sub>v3 · minor severity · area distributed · 1 comments from 1 PRs</sub>

### v0019c1-010

**When** A change adds state other modules access directly or existing components hold, generalizes vendor-specific or experimental logic (e.g. CUDA-only optimizations), or rewrites working code into a more complex form.

**Expect** Flag each, even if it removes duplication: drop the state, keep that logic concrete until stable, reuse existing functions unchanged (import, duplicate or move to utils): duplicate first, refactor later.

*Why (record only)*: Abstractions designed before the code stabilizes lock in the wrong shape and add complexity. Duplicating first and refactoring later is cheaper and safer than rewriting working code.

<sub>v3 · major severity · area overall · 4 comments from 1 PRs</sub>

### v0020c1-001

**When** A change adds definitions to a new module, or to a module or class whose existing definitions already follow the layout below, and places them out of that order (e.g. a private helper between public methods of a class that keeps private methods last).

**Expect** Ask (nit) to move them into this order: imports; private `_` helpers and classes; public classes (`__init__`, public methods, private `_` methods last); public module-level functions used by other modules. Do not flag additions to a file or class that does not already follow this order.

*Why (record only)*: A consistent layout makes the public surface easy to find. Imposing it on files organized differently is noise.

<sub>v4 · nit severity · area distributed,platform · 2 comments from 2 PRs</sub>

### v0021c1-001

**When** A diff edits text in a hard-wrapped doc paragraph, leaving any edited line noticeably shorter or longer than the file's wrap width, or whitespace damage (trailing, doubled, broken indentation).

**Expect** Check every edited paragraph; ask, as a nit, to fix the whitespace damage and reflow it to the file's wrap width.

*Why (record only)*: Ragged or damaged wrapping left behind by a rewording makes doc sources inconsistent and harder to read. It also makes later diffs noisy.

<sub>v2 · nit severity · area docs · 1 comments from 1 PRs</sub>

### v0023c1-002

**When** A change adds a user-visible feature, component or data format, or changes behavior users observe or docs describe (protocol, recovery, on-disk format).

**Expect** Ask to update every doc describing it, not just one (design docs, configuration reference); add a usage page for a new feature, and a design doc under docs/design per CLAUDE.md and CONTRIBUTING.md for a new component, algorithm or format. Ask separately for each consequence users hit: timing bounds via their controlling setting, state lost and rebuilt after recovery, migration steps like clearing old data.

*Why (record only)*: Features and behavior changes without docs cannot be used, operated or maintained correctly, and existing docs go stale.

<sub>v3 · minor severity · area distributed,docs,overall · 7 comments from 5 PRs</sub>

### v0023c1-006

**When** A change puts a once-per-deployment action (starting a shared server, global setup) in a path that runs in every worker or rank.

**Expect** Ask to move it to a single-instance role, such as the scheduler, or an elected rank.

*Why (record only)*: Running a singleton action in every replica starts duplicates, races on ports and shared resources, or wastes work.

<sub>v3 · major severity · area vllm-integration · 1 comments from 1 PRs</sub>

### v0023c1-008

**When** A change adds behavior that exists only when the real engine launches several processes or ranks, such as which process or rank performs an action, or what is spawned or bootstrapped. The behavior is covered only by mocks, or untested.

**Expect** Ask for a case in the existing multi-process end-to-end suite that launches the real engine that way and asserts the outcome. Do not ask for it when tests can drive the logic in-process by building its inputs (rank-carrying keys, mocked peer replies, stubbed configs), even if other processes produce those inputs in production.

*Why (record only)*: Only a real launch shows which process runs what. Logic driven by inputs is covered by cheaper in-process tests.

<sub>v3 · major severity · area overall · 1 comments from 1 PRs</sub>

### v0023c1-010

**When** Code writes in place into a tensor derived from the destination by a transform that may copy (reshape, flatten, permute, contiguous).

**Expect** Ask to write directly into the destination with explicit indices, as sibling branches do, and for a test asserting the destination changed, with every merged dimension >1.

*Why (record only)*: A write into a hidden copy silently leaves the real buffer unchanged, and tests with degenerate shapes still pass.

<sub>v3 · blocker severity · area overall,platform · 3 comments from 1 PRs</sub>

### v0023c1-013

**When** A diff adds or changes a function whose return type is a tuple or record with a component beyond the main result. One sign is a parameter's type reappearing in the returned tuple.

**Expect** Check each extra component against the parameters and the callers. If the component returns a parameter back (even normalized or defaulted), or callers ignore it or already hold it, ask to drop it. Ask to update the return type and every caller's unpacking.

*Why (record only)*: Echoed or unused return components complicate every caller.

<sub>v7 · minor severity · area gpu-connector · 1 comments from 1 PRs</sub>

### v0023c1-014

**When** A diff adds or fixes, or the review finds, a deterministic boundary or error-path defect that no test in the diff forces. Typical cases: a name, path or buffer built by adding to an input (suffix, prefix, header), so that a valid input can cross a system limit; cleanup in finally/except whose own call can raise; a branch relying on an optional argument that callers may omit.

**Expect** For each such defect, raise a separate point in the same review asking for a focused regression test. The test must force exactly that condition (valid input at the limit plus the addition; the cleanup call made to raise; the argument omitted) and must fail without the fix. Never report the bug or accept its fix without also asking for its test.

*Why (record only)*: Edge-case and error-path fixes regress silently unless a test pins the exact triggering condition.

<sub>v5 · minor severity · area overall · 1 comments from 1 PRs</sub>

### v0024c1-002

**When** A branch reads a public optional parameter whose default (0, None) is invalid there (division, shape), though validation or the reference requires it only for other branches.

**Expect** Ask to derive the value without that parameter, keeping reference parity, and for a test omitting it.

*Why (record only)*: A documented default that works on the reference path becomes a crash on the new branch, which breaks parity for callers that follow the public contract.

<sub>v4 · blocker severity · area overall,platform · 3 comments from 1 PRs</sub>

### v0026c1-012

**When** Code on a per-request hot path (retrieve, store, transfer) allocates a fresh buffer or tensor every call, e.g. concatenating or stacking results.

**Expect** Ask, as a nit, for a comment there noting the per-call allocation and the reuse option, e.g. a preallocated buffer of maximum size.

*Why (record only)*: Hidden per-call allocations add latency and memory churn, and without a note they are never revisited.

<sub>v2 · nit severity · area core-other · 1 comments from 1 PRs</sub>

### v0027c1-002

**When** A comment or docstring (code, scripts, config) is long for what it annotates: narrating internals, history or rationale, repeating an explanation given elsewhere, or with no clear purpose there.

**Expect** Ask, as a nit, to cut docstrings to caller-facing behavior and delete other narration; a fact readers truly need becomes a short inline NOTE, with proposed wording.

*Why (record only)*: Long narration buries the one fact a reader needs and goes stale; the team repeatedly asks for it to be removed or reduced to one line.

<sub>v2 · nit severity · area ci-build,mp,vllm-integration · 8 comments from 2 PRs</sub>

### v0031c1-002

**When** A reset, clear, shutdown or teardown frees resources or drops state that in-flight work, possibly in other participants, may still hold.

**Expect** Ask how it ensures quiescence: drain or reject work across all participants, or keep locked entries and return failure, and never force-free resources in use. If a drain bounded by a timeout ends with work still active, teardown must stay blocked or fail closed instead of logging and proceeding.

*Why (record only)*: Freeing resources under running work corrupts or crashes in-flight transfers.

<sub>v1 · blocker severity · area mp,vllm-integration · 2 comments from 2 PRs</sub>

### v0032c1-001

**When** Deferred, queued or retried work captures an entry, registration or handle, but later resolves its target again by a reusable key (ID, name, slot). This includes a fallback that does a fresh lookup when the capture found nothing.

**Expect** Ask to bind the work to the captured entry or its generation. When that entry is missing or no longer current, the work must fail directly and run its failure cleanup (e.g. releasing held locks), never calling code that looks the key up again. Ask for a separate regression test for each such path. The test removes the entry and re-registers the same key before the work runs, then asserts the work fails without touching the replacement. A test of one path does not cover another.

*Why (record only)*: A reused key can point to a replacement target, so stale work silently runs against the new registration with old events, handles or IDs. Only a test that re-registers inside the window proves that each path is bound.

<sub>v1 · major severity · area mp · 3 comments from 1 PRs</sub>

### v0033c1-001

**When** A change adds or renames a setting or parameter whose name admits more than one quantity, e.g. the threshold that triggers an action versus how much the action handles.

**Expect** Raise it as its own point and spell out both readings. Ask to rename it to the quantity meant, and to add a separate setting when both quantities are needed.

*Why (record only)*: Operators misconfigure a knob whose meaning they have to guess.

<sub>v1 · minor severity · area mp · 1 comments from 1 PRs</sub>

### v0033c1-002

**When** Newly added code computes a derived value (a count, range, window, mask) with logic that an existing function elsewhere already performs on the same inputs, even when that function is outside the diff.

**Expect** Raise it at the new code and name the existing function. Ask to reuse it or to extract one shared helper that both call. If the author defers, ask for TODOs at both sites that reference each other.

*Why (record only)*: Two copies of one computation drift apart.

<sub>v1 · minor severity · area mp · 1 comments from 1 PRs</sub>

### v0033c1-003

**When** A diff deletes or shortens a docstring, a section of one, or a comment, on any function, while the code it describes still behaves that way.

**Expect** Raise a separate point at each deletion, quote the removed text, and ask to keep it. If part of the text became false, ask to correct that part instead of deleting the whole.

*Why (record only)*: Accurate documentation removed in passing is rarely rewritten.

<sub>v1 · minor severity · area core-other,distributed · 3 comments from 1 PRs</sub>

### v0033c1-005

**When** A doc lists APIs that an implementer must provide as bare names, several on one line, or without their arguments.

**Expect** Ask to list each required API on its own line with its full signature, arguments included, grouped under category headings. Propose the grouping.

*Why (record only)*: Implementers need an exact checklist of what to provide, organized by purpose.

<sub>v1 · minor severity · area docs · 1 comments from 1 PRs</sub>

### v0033c1-007

**When** A change adds entries to a long-lived pending or in-flight container (keyed tasks, requests, sizes, handles) whose removal depends on another thread, a callback, or an error path running correctly, so a missed removal would grow it silently for the life of the process.

**Expect** Raise the leak risk as its own point and ask for a way to make a stuck or growing container detectable or impossible — such as observability of its size, a bound or expiry, removal guaranteed on every completion and error path, or a test showing entries are removed when work fails or is abandoned. Point out other containers in the same component that follow the same add-here/remove-elsewhere pattern; covering them may be a follow-up.

*Why (record only)*: Entries removed across threads and paths leak silently unless their count is observable.

<sub>v1 · minor severity · area distributed · 1 comments from 1 PRs</sub>

### v0033c1-008

**When** A change adds or alters how a client recovers from a peer's or server's failure or restart (reconnect, re-register, reload).

**Expect** Even when other doc updates are already requested, ask as a separate point that user docs state:
- what recovery does not restore and must be rebuilt (state held by the old process, in-flight work);
- how long detection can take, in terms of its controlling setting.

*Why (record only)*: Users otherwise assume recovery is lossless and immediate.

<sub>v1 · minor severity · area docs · 1 comments from 1 PRs</sub>

### v0033c1-009

**When** A function takes or returns tensors, structured values, or strings or enums with a fixed set of valid values, and its docstring describes them only in prose.

**Expect** Ask the docstring to state, for each argument and the return value:
- the concrete type;
- the shape, with named dimensions;
- the allowed string or enum values;
- which format or enum value is returned.

This applies to private helpers too.

*Why (record only)*: Callers of shape-manipulating code cannot infer shape and value contracts from prose about the algorithm.

<sub>v1 · minor severity · area gpu-connector · 2 comments from 1 PRs</sub>

### v0034c1-003

**When** A change edits shared test data (a fixture or config file several tests load) for one mode or variant, or changes the externally visible value of a field or output (normalized, defaulted, reformatted, removed). Existing tests, possibly outside the diff, load that data or assert the old value.

**Expect** Name each existing test that breaks. Ask to restore what the other consumers need or to split the fixture per variant. Ask to assert the new value, or to keep the original value if the change is not meant to be externally visible.

*Why (record only)*: Edits made for one mode silently break tests that share the data or rely on the old contract, on paths the author did not run.

<sub>v1 · major severity · area overall · 2 comments from 1 PRs</sub>

### v0034c1-004

**When** A change whose purpose is performance replaces a slow path (per-item calls, extra copies, round trips) with a faster one, and its tests would still pass if the code fell back to the slow path.

**Expect** Ask for a small regression test asserting that the fast path is taken and the slow one is not, e.g. a spy or call count showing the per-item operation is never invoked.

*Why (record only)*: A silent fallback keeps results correct while losing the optimization, so only a test that asserts which path runs catches it.

<sub>v1 · minor severity · area overall · 1 comments from 1 PRs</sub>

### v0034c1-005

**When** Code infers a shared item's state from an earlier operation's result, error code or check (e.g. 'cannot lock for write' taken to mean 'present'). It then acts on that inference in a separate, later operation, while concurrent actors (eviction, other requests, threads) can change the item in between.

**Expect** Raise the race as its own point, naming both operations and what can intervene. Ask to close the gap (one atomic operation, or a hold kept across both). Otherwise, ask that a failure of the later operation take the path used when the inferred state is false (e.g. reload from the backing tier). A failure branch that only skips the item or logs does not count as handling it.

*Why (record only)*: State inferred from an earlier outcome can be invalidated before it is acted on. Silently dropping the item turns a hit into a miss or lost work.

<sub>v2 · major severity · area distributed · 1 comments from 1 PRs</sub>

### v0034c1-006

**When** A doc, docstring or help text states a default: what happens 'by default', a default value, mode or backend, or a fallback that applies when nothing is configured.

**Expect** Look up the actual default where the code sets it (config or enum default, selection or routing logic). If the text differs, raise it as its own point, even when other points on the same text are raised. Ask to state the actual default and, if it is an automatic selector, what it resolves to in each case.

*Why (record only)*: Users rely on documented defaults. A wrong default misleads them about behavior they never chose.

<sub>v1 · minor severity · area docs · 1 comments from 1 PRs</sub>

### v0034c1-007

**When** A change adds a boolean field or parameter that selects one variant of a concept (a layout, format or mode) that has, or foreseeably will have, more than two variants.

**Expect** Ask to replace the flag with a single field whose values name each variant explicitly (a closed set of named choices), covering the foreseeable variants the boolean cannot express, so that supporting a new variant means adding a value to that field rather than adding another flag.

*Why (record only)*: Boolean flags multiply and combine ambiguously as variants are added; a named variant field extends cleanly.

<sub>v1 · minor severity · area gpu-connector · 1 comments from 1 PRs</sub>

### v0034c1-008

**When** Code hands another process or an asynchronous consumer a handle to a local object (IPC handle, pointer, exported event). It keeps the object only in a slot a later operation can overwrite or drop, or releases it before the consumer finishes.

**Expect** Ask to tie the object's lifetime to the in-flight operation, retaining it on that operation's future or handle until completion. As a separate point, ask for a test issuing two operations that reuse the slot, asserting the first object stays alive while its operation is in flight.

*Why (record only)*: A consumer that uses a handle to a freed or overwritten object reads or signals invalid memory.

<sub>v1 · major severity · area mp · 2 comments from 1 PRs</sub>

### v0035c1-003

**When** Code exports a handle to a local object to another process or an asynchronous consumer. The change keeps the in-flight operation alive (its future, task or request), but the exported object itself is held only where a later operation can overwrite or drop it.

**Expect** Raise as its own point that retaining the operation does not keep the exported object alive. Ask to attach the object to the retained operation's future or handle until that operation completes. Raise this even when the diff's purpose is fixing the operation's own lifetime.

*Why (record only)*: The consumer uses the exported object through its handle. Retaining the future alone lets an overwrite of the slot free that object mid-operation.

<sub>v1 · major severity · area mp · 1 comments from 1 PRs</sub>

### v0035c1-004

**When** A change adds or fixes the lifetime of a local object whose handle another process or asynchronous consumer uses while an operation is in flight. The object lives in a slot that a later operation for the same key can reuse.

**Expect** Ask, as its own point, for a test that issues two operations reusing the same slot while the first is still in flight. The test must assert that the first operation's exported object itself, not only its future, stays alive and unreleased until that operation completes. A test with one operation, or one checking only futures, does not count.

*Why (record only)*: Only a same-slot overlap reproduces the overwrite. A test that checks futures passes with the bug present.

<sub>v1 · minor severity · area mp · 1 comments from 1 PRs</sub>

### v0036c2-003

**When** A change starts relying on an existing component to handle a kind of input it was not previously exercised or tested with.

**Expect** Ask for a unit test of that component with exactly that input case. The test must assert that the component handles the case correctly, for example that data round-trips intact, and must fail if the component does not support it.

*Why (record only)*: The change's correctness depends on an unverified assumption about another component. If the assumption is wrong, the failure is silent and far from the code the diff touches.

<sub>v1 · major severity · area overall · 1 comments from 1 PRs</sub>

### v0038c1-003

**When** A test gates, skips or reroutes cases on device, platform or capability in a way that does not match what the implementation under test itself requires. One case is gating on what another implementation supports. The other is an ad-hoc or generic condition where the implementation needs a specific device.

**Expect** Ask to gate on exactly that requirement. Remove unneeded gating and its comments, and run those cases unconditionally. Express a real device requirement with the repository's device marker instead of an ad-hoc skip condition.

*Why (record only)*: Gating that misstates the requirement either hides coverage or obscures why a test is skipped.

<sub>v1 · minor severity · area tests · 2 comments from 2 PRs</sub>

### v0038c1-004

**When** A change gives a batched or multi-step operation all-or-nothing or rollback semantics, and its tests inject failure only before the operation starts or only check part of the state.

**Expect** Ask for a test where a fake dependency fails after accepting part of the batch. The test must assert that all state returns to its pre-call value, including in-process bookkeeping (maps, counters, locks, allocations), not only the backing writes.

*Why (record only)*: Partial completion is the case that exercises rollback. A failure before the batch begins tests nothing.

<sub>v1 · major severity · area overall · 1 comments from 1 PRs</sub>

### v0038c1-005

**When** A fix adds a step that must accompany a shared operation (release, teardown, reclaim) at several call sites, as a separate call callers must remember, or as a rule stated in a docstring, although every affected path already goes through one shared routine.

**Expect** Ask to perform the step once inside that shared routine and to remove the per-site calls and the caller obligation. If a constraint prevents that, ask for a single helper in one place with the constraint stated there.

*Why (record only)*: A fix in the common path is smaller, covers every caller, and cannot be forgotten at a new call site.

<sub>v1 · major severity · area overall · 1 comments from 1 PRs</sub>

### v0038c1-007

**When** A change handles a failure or fallback in a per-item state machine whose methods a caller may invoke repeatedly. It does so by clearing or resetting the item's state, or by inferring the condition from other fields, instead of recording it.

**Expect** Ask for an explicit named failed or bypass state that the item enters on the failure. That state must return the same fallback answer on every later call until a defined end of the item's lifecycle, instead of returning to a state that re-triggers the operation.

*Why (record only)*: Resetting or inferring the failure lets a repeated call redo lookups or take resources again after the failure.

<sub>v1 · major severity · area overall · 1 comments from 1 PRs</sub>

### v0039c1-002

**When** A change alters what a method returns or does for an item, and an external driver (scheduler, engine, poller, retrying caller) may call that method again for the same item before the companion call that advances the item's state, for example after a failure, fallback or deferral.

**Expect** As its own point, ask for a regression test that calls the method twice in a row for the same item, with no companion call between them. The test asserts that the second call gives the same answer and repeats no side effects, such as a lookup, a lock acquire or release, or a load submission.

*Why (record only)*: Drivers may re-query before advancing state. Tests that cover only the normal call sequence miss re-lookup, double-release and stale-state bugs.

<sub>v1 · minor severity · area overall · 1 comments from 1 PRs</sub>

### v0041c1-001

**When** A diff removes or replaces a call or other use of a function, method, class or setting defined elsewhere, possibly outside the diff, so it may have no remaining user.

**Expect** Search for remaining users. Unless another is visible, raise it as its own point: name the definition, ask the author to check for other callers and, if none remain, delete it in the same PR along with code only it serves. Ask even without proof that it was the last caller.

*Why (record only)*: A fix that drops the last call silently leaves dead code behind that must still be maintained and reasoned about, unless someone asks about the callee that is no longer called.

<sub>v1 · minor severity · area distributed · 1 comments from 1 PRs</sub>

### v0043c1-002

**When** A change adds, or adds a safeguard to, one pending or in-flight container whose entries are removed elsewhere (another thread, a callback, an error path). Other containers in the same component, possibly untouched by the diff, are filled and drained the same way.

**Expect** Raise a separate point naming each such other container and stating that it has the same silent-growth risk. Ask for the same safeguard on it (size observability, a bound or expiry, removal on every completion and error path). Accept deferring this to a follow-up issue.

*Why (record only)*: A leak pattern found in one container usually recurs in its siblings. Reviewing only the touched container leaves the others unmonitored.

<sub>v1 · minor severity · area distributed · 1 comments from 1 PRs</sub>

## Knowledge (14)

### v0011c1-003

**When** One MP-engine module calls, holds or receives a sibling module.

**Expect** MPEngineContext owns all submodules and the storage manager. Submodules include the management module, the GPU/CPU transfer modules, blend modules and others. Each module holds a reference only to the context and cannot see its siblings. Ask to call `self._ctx.<method>` instead, letting the context dispatch to the correct module.

*Why (record only)*: Only the context knows which sibling, for example which transfer module, is active. Wiring siblings to each other bypasses the ownership tree and couples the modules.

<sub>v3 · major severity · area docs · 1 comments from 1 PRs</sub>

### v0019c1-009

**When** Transfer code needs KV group geometry or block IDs, or adds types holding it.

**Expect** KVLayerGroupsManager (lmcache/v1/kv_layer_groups.py) holds all kernel-group and object-group information for a registered KV cache. It is built during register_kv_cache in a transfer-mode-agnostic way. Require each path to build it and parse block IDs per KV layer group; remove types that re-derive it.

*Why (record only)*: A second representation of group geometry duplicates the source of truth and drifts from it, and paths that do not use KVLayerGroupsManager lack hybrid-model support.

<sub>v3 · major severity · area overall · 3 comments from 1 PRs</sub>

### v0023c1-004

**When** A diff keeps an old public name after a rename, or adds or edits a base class with many methods.

**Expect** LMCache provides `@lmcache_deprecate` in `lmcache.utils`. MP-mode code: lmcache/v1/multiprocess/**, lmcache_mp_connector.py, vllm_multi_process_adapter.py. Keep an old name as a `def` wrapper with it, not an alias. Ask base-class docstrings to mark which methods MP mode uses and which only non-MP mode does.

*Why (record only)*: Non-MP mode is deprecated. Its code must warn users and be clearly separable from the MP path so it can be removed later; readers of shared bases must be able to tell which methods the MP path depends on.

<sub>v5 · minor severity · area gpu-connector,mp · 3 comments from 2 PRs</sub>

### v0023c1-009

**When** Code stores engine KV cache tensors or views on `self` (any class, however short-lived), a closure or a cache.

**Expect** Every reference LMCache holds to the engine's GPU KV tensors must be dropped when the serving engine disconnects or unregisters its KV cache. Ask to keep only derived metadata or pass tensors per call.

*Why (record only)*: Hidden references to GPU KV tensors keep engine memory alive after the engine disconnects.

<sub>v5 · major severity · area gpu-connector · 1 comments from 1 PRs</sub>

### v0023c1-012

**When** An added line references `native_storage_ops` (import, string module path, mock.patch target).

**Expect** `lmcache.native_storage_ops` no longer exists; its contents, such as Bitmap, live in `lmcache.lmcache_native`. Note the ModuleNotFoundError at import and suggest `from lmcache.lmcache_native import <name>` or the matching string path.

*Why (record only)*: A stale import of the removed native module breaks module load and every test that imports the module.

<sub>v5 · blocker severity · area distributed · 2 comments from 1 PRs</sub>

### v0026c1-004

**When** Text or names call a block or chunk itself 'physical' or 'logical'.

**Expect** In LMCache a block or chunk always corresponds to a fixed, predefined set of tokens. 'Physical' vs 'logical' qualifies only its size: the tensor dimension vs the number of tokens it logically covers. Ask to qualify the size instead.

*Why (record only)*: Qualifying the block instead of its size implies two kinds of blocks that do not exist and confuses the tensor-size vs token-count distinction.

<sub>v2 · minor severity · area mp · 1 comments from 1 PRs</sub>

### v0026c1-007

**When** A change adds an MP-server message-queue handler or client call that only returns information, not a KV-cache operation.

**Expect** In the MP server, the message-queue path is reserved for KV-cache operations and their lifecycle, plus liveness checks of that path. Informational queries belong on the server's HTTP endpoints. Ask to serve it over HTTP.

*Why (record only)*: This keeps the KV-cache message path focused on cache traffic and uses HTTP for ad-hoc information queries.

<sub>v2 · major severity · area mp · 1 comments from 1 PRs</sub>

### v0026c1-011

**When** Code updates recency (LRU touch, eviction order) for a sequence of chunks, on a hit or store.

**Expect** LMCache convention: touch or insert one sequence's chunks in reverse order, last chunk first, so suffixes are evicted before prefixes. Flag forward-order updates; ask to follow the existing LRU update code.

*Why (record only)*: Evicting a prefix chunk makes every later chunk of that sequence unusable, so suffixes must be evicted first.

<sub>v2 · minor severity · area core-other · 1 comments from 1 PRs</sub>

### v0035c1-001

**When** Code re-implements what the standard library or LMCache already provides, even when the existing function is outside the diff. This covers manual grouping, counting or deduplicating loops, and logic repeating another function's, including hand-written tensor view, permute or stride manipulation. It also covers an LMCache capability rebuilt or reached through another channel.

**Expect** Name the library function or existing code and ask to reuse it. Known locations:
- eviction policies: lmcache/v1/distributed/eviction_policy/
- MP server health checks and communication: the ZMQ MessageQueueClient, as in the health-monitoring thread in vllm_multi_process_adapter.py
- re-viewing a strided or permuted tensor in memory order: attempt_permute_to_contiguous_view in lmcache/v1/gpu_connector/kv_format/contiguity.py

*Why (record only)*: Duplicated logic drifts from the maintained implementation and bypasses tested helpers.

<sub>v1 · major severity · area distributed,docs,mp,vllm-integration · 6 comments from 4 PRs</sub>

### v0037c1-001

**When** A diff adds or edits tests, as a new file or as cases in an existing file, in a location that does not match their scope. One case is a test folder outside the top-level tests tree, such as one inside the package. Another is platform- or vendor-specific cases in a shared, platform-neutral test file or folder.

**Expect** LMCache keeps all tests under the top-level tests/ tree, mirroring the source path, with platform-specific tests under tests/v1/platform/<device>/. Ask to move the new cases, or the touched file, there. Raise this even when the file or folder existed before the PR, or when sibling cases for other devices follow the same pattern. Deferring the move to a follow-up PR is acceptable.

*Why (record only)*: Tests in stray folders or mixed into shared files are hard to find and to run per platform. An existing misplacement is not a precedent.

<sub>v1 · minor severity · area tests · 2 comments from 2 PRs</sub>

### v0039c1-001

**When** An added or edited line uses a vendor device namespace such as `torch.cuda` directly (a call, a constructor, a type annotation) outside the platform code that implements the device abstraction. This includes engine integration modules and files that already use CUDA.

**Expect** LMCache code reaches device APIs only through the torch_dev device abstraction, which keeps it device-agnostic, and a CQ check enforces this. Flag each direct use and ask for the torch_dev equivalent. Do not exempt a module because it already uses CUDA or targets one engine.

*Why (record only)*: Direct torch.cuda use breaks non-CUDA devices and fails the CQ check that enforces the device abstraction.

<sub>v1 · major severity · area vllm-integration · 1 comments from 1 PRs</sub>

### v0040c1-002

**When** A diff changes code that only a specific CI lane, or no lane, exercises. Examples are native sources or raw-pointer paths also built with HIP for AMD/ROCm, and a mode or transport the CI jobs never select. This also applies when such a PR is rebased.

**Expect** Before approval, ask for a passing run of each lane exercising the changed path on the exact head commit. After any rebase, ask to rerun that lane and the focused tests. Older-commit or failed runs do not count. Where no job exercises the path, ask for a smoke test that does. Known facts: only the AMD lane builds HIP, and the K3 engine-driven jobs force SHM transport.

*Why (record only)*: A fix is unverified on any path that no CI job runs on the head commit.

<sub>v1 · major severity · area overall · 3 comments from 2 PRs</sub>

### v0040c1-003

**When** A test replaces a method on an object or class by plain attribute assignment (e.g. `obj.method = MagicMock(...)`).

**Expect** LMCache's mypy check covers tests and rejects assignment to a method with `Cannot assign to a method [method-assign]`. Flag each such assignment. Ask to use `unittest.mock.patch.object(obj, 'method', ...)` instead, as a context manager, decorator or fixture.

*Why (record only)*: Direct method assignment fails the repository's mypy CQ check.

<sub>v1 · minor severity · area tests · 1 comments from 1 PRs</sub>

### v0042c1-001

**When** A PR adds or changes code, tests or docs used only by LMCache's in-process (non-MP) mode, with no MP-mode counterpart. This covers a fix, feature, unit test or deployment guide.

**Expect** In-process mode is deprecated. New implementation work there is not accepted, and MP mode is the recommended default. Raise it as a PR-level point. Ask to port the work to MP mode, rewrite docs for MP mode, and drop new tests of in-process-only code. A PR entirely in that scope should be closed or redirected to MP, migration/removal or docs work. Do not flag code shared with MP mode. In-process code: lmcache/inprocess/, LMCacheConnectorV1, in-process GPU connectors, cache engine, storage backends, lookup clients, layerwise loading. MP code: lmcache/v1/multiprocess/, lmcache_mp_connector.py, vllm_multi_process_adapter.py.

*Why (record only)*: Maintainers no longer accept new work on in-process mode, whatever its technical correctness, and recommend MP mode for production.

<sub>v1 · blocker severity · area overall,tests · 8 comments from 7 PRs</sub>

## Retired (65)

- cx05k1-002: regrouped
- cx05k1-004: regrouped
- cx05k1-012: regrouped
- cx06k1-001: regrouped
- cx06k1-002: regrouped
- cx06k1-004: regrouped
- cx08k1-001: regrouped
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
- v0022c1-001: tests that pin one implementation gate cases on unrelated device or backend availability
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
- v0038c1-006: AMD/HIP CI result on the exact head for HIP-built code

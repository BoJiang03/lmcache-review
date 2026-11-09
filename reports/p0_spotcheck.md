# P0 spot check: `addressed` label

For each: does the later diff actually respond to the comment?

## 1. PR #4695 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/4695#discussion_r3836137493  
`lmcache/v1/kv_layer_groups.py` lines 418–421 · reviewer Shaoting-Feng · outdated=True resolved=False

Comment:

> Same as L153–166. With the detector reshape, this branch is not needed.

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/v1/kv_layer_groups.py b/lmcache/v1/kv_layer_groups.py
index cbe8f19316..d514ec215c 100644
--- a/lmcache/v1/kv_layer_groups.py
+++ b/lmcache/v1/kv_layer_groups.py
@@ -16,5 +16,5 @@ from lmcache import device_ops
 from lmcache.logging import init_logger
 from lmcache.utils import lmcache_deprecate
-from lmcache.v1.distributed.api import AttnWindowDesc
+from lmcache.v1.distributed.api import AttnWindowDesc, GroupKind
 from lmcache.v1.platform.ops_types import PageBufferShapeDesc
 import lmcache.lmcache_native as lmcache_native
@@ -79,5 +79,4 @@ def group_layers_by_identity(
     engine_kv_formats: "Sequence[lmcache_native.EngineKVFormat]",
     per_layer_engine_group_idx: Sequence[int] | None = None,
-    per_layer_tokens_per_block: Sequence[int] | None = None,
 ) -> list[tuple[LayerGroupIdentity, list[int]]]:
     """Partition layer indices by :data:`LayerGroupIdentity`.
@@ -96,10 +95,4 @@ def group_layers_by_identity(
             ``EXCLUDED_ENGINE_GROUP`` are left out of all groups (e.g. cross-layer
             KV-sharing layers whose KV lives in their target owner's blocks).
-        per_layer_tokens_per_block: Optional per-layer physical block size, only
-            consulted for fused formats (e.g. MLA ``NL_X_NBBS_ONE_HS``) whose
-            tensor folds ``num_blocks * block_size`` into dim-0 and therefore
-            cannot report a block size from its shape. Non-fused layers ignore
-            it and read the block size from the tensor. When a f
…
```

## 2. PR #4882 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/4882#discussion_r3929041906  
`docs/source/getting_started/index.rst` lines 16–16 · reviewer ApostaC · outdated=True resolved=True

Comment:

> I don't think this should be added to `getting_started` section.
> 
> Maybe we should just link to the page in the vLLM-starting-command-related sections, since the user only needs to be aware of this when using `lmcache.mp.host` with vLLM.

Later diff of this file (comment commit → PR head):

```diff
diff --git a/docs/source/getting_started/index.rst b/docs/source/getting_started/index.rst
index 1bb6030001..1f5c76a2eb 100644
--- a/docs/source/getting_started/index.rst
+++ b/docs/source/getting_started/index.rst
@@ -14,5 +14,4 @@ the cache.
    quickstart
    /mp/configuration
-   /mp/request_transport
    benchmarking
    kv_cache_calculator
```

## 3. PR #3336 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/3336#discussion_r3277049751  
`csrc/completion_recorder.cpp` lines 15–15 · reviewer ApostaC · outdated=True resolved=True

Comment:

> I'm concerned about whether std::move(completion) will free the original memory on the heap. It will move the underlying strings to the new object, but the reference to the original `CompletionRecorder` becomes dangling there. We need to free the original pointer to avoid a memory leak.
> 
> An alternative is to directly keep the pointers, and call `delete` during `drain()`.
> Or we can use `std::unique_ptr` to better handle the "move" semantics.

Later diff of this file (comment commit → PR head):

```diff
diff --git a/csrc/completion_recorder.cpp b/csrc/completion_recorder.cpp
index d795d34b71..9f70ecd44b 100644
--- a/csrc/completion_recorder.cpp
+++ b/csrc/completion_recorder.cpp
@@ -10,15 +10,12 @@ CompletionRecorder& CompletionRecorder::instance() {
 }
 
-void CompletionRecorder::push(PendingCompletion* completion) {
-  {
-    std::lock_guard<std::mutex> lock(mutex_);
-    buffer_.push_back(std::move(*completion));
-  }
-  delete completion;
+void CompletionRecorder::push(std::unique_ptr<PendingCompletion> completion) {
+  std::lock_guard<std::mutex> lock(mutex_);
+  buffer_.push_back(std::move(completion));
 }
 
-std::vector<PendingCompletion> CompletionRecorder::drain() {
+std::vector<std::unique_ptr<PendingCompletion>> CompletionRecorder::drain() {
   std::lock_guard<std::mutex> lock(mutex_);
-  std::vector<PendingCompletion> result;
+  std::vector<std::unique_ptr<PendingCompletion>> result;
   result.swap(buffer_);
   return result;
@@ -30,19 +27,23 @@ static void
 #endif
     completion_host_callback(void* data) {
-  auto* completion = static_cast<PendingCompletion*>(data);
-  CompletionRecorder::instance().push(completion);
+  // Adopt the raw pointer back into a unique_ptr.
+  std::unique_ptr<PendingCompletion> completion(
+      static_cast<PendingCompletion*>(data));
+  CompletionRecorder::instance().push(std::move(completion));
 }
 
 void record_completion_on_stream(int64_t cuda_stream_ptr,
-                                 const std::string& kind,
-              
…
```

## 4. PR #4079 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/4079#discussion_r3694439353  
`lmcache/v1/multiprocess/modules/lmcache_driven_transfer.py` lines 279–279 · reviewer hlin99 · outdated=True resolved=True

Comment:

> do we need to change the docstring here?

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/v1/multiprocess/modules/lmcache_driven_transfer.py b/lmcache/v1/multiprocess/modules/lmcache_driven_transfer.py
index ee97a2a0ca..7fa212c79a 100644
--- a/lmcache/v1/multiprocess/modules/lmcache_driven_transfer.py
+++ b/lmcache/v1/multiprocess/modules/lmcache_driven_transfer.py
@@ -4,11 +4,8 @@
 # Standard
 from dataclasses import dataclass
-from typing import Callable, Sequence, cast
+from typing import Any, Sequence
 import threading
 import time
 
-# Third Party
-import torch
-
 # First Party
 from lmcache import torch_dev
@@ -22,13 +19,8 @@ from lmcache.v1.distributed.api import (
     ObjectKey,
 )
-from lmcache.v1.gpu_connector.gpu_ops import (
-    build_staging_copies,
-    lmcache_memcpy_async_d2h,
-    lmcache_memcpy_async_h2d,
-)
 from lmcache.v1.gpu_connector.utils import LayoutHints
-from lmcache.v1.memory_allocators.lazy_memory_allocator import LazyMemoryAllocator
-from lmcache.v1.memory_management import GDSMemoryObject, MemoryObj
-from lmcache.v1.mp_observability.event import Event, EventType
+from lmcache.v1.kv_layer_groups import ObjectGroupInfo
+from lmcache.v1.memory_management import MemoryObj
+from lmcache.v1.mp_observability.event import Event, EventType, next_transfer_key
 from lmcache.v1.multiprocess.custom_types import (
     IPCCacheServerKey,
@@ -36,26 +28,17 @@ from lmcache.v1.multiprocess.custom_types import (
 )
 from lmcache.v1.multiprocess.engine_context import MPCacheServerContext
-from lmcache.v1.multiprocess.engine_modul
…
```

## 5. PR #5674 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/5674#discussion_r4310520043  
`lmcache/v1/platform/devices/xpu/device_ops.py` lines 106–106 · reviewer hlin99 · outdated=False resolved=False

Comment:

> ditto. device level should know the underneath capability very well and clear. if the .so is missing, we should do it in _ini_ and return base class of the whole device ops block.

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/v1/platform/devices/xpu/device_ops.py b/lmcache/v1/platform/devices/xpu/device_ops.py
index 596d2dfb3c..59ff9e8a5d 100644
--- a/lmcache/v1/platform/devices/xpu/device_ops.py
+++ b/lmcache/v1/platform/devices/xpu/device_ops.py
@@ -14,5 +14,5 @@ from __future__ import annotations
 # Standard
 from collections.abc import Callable
-from typing import ClassVar
+from typing import TYPE_CHECKING, ClassVar
 
 # Third Party
@@ -22,5 +22,5 @@ import torch
 from lmcache.logging import init_logger
 from lmcache.v1.platform.base.device_ops import DeviceOps
-from lmcache.v1.platform.native_block_transfer import (
+from lmcache.v1.platform.device_ops_helper import (
     allocate_pinned_chunk,
     transfer_with_address_kernel,
@@ -29,6 +29,14 @@ from lmcache.v1.platform.ops_types import PageBufferShapeDesc
 import lmcache.lmcache_native as lmcache_native
 
+if TYPE_CHECKING:
+    # First Party
+    from lmcache.v1.gpu_connector.kv_format.types import DiscoverableKVCache
+
 logger = init_logger(__name__)
 
+#: Chunks per kernel launch. The SYCL kernel has no per-launch limit; this
+#: matches the CUDA kernel's, and raising it needs validation on XPU hardware.
+MAX_CHUNKS_PER_LAUNCH = 4
+
 
 class XpuDeviceOps(DeviceOps):
@@ -37,6 +45,7 @@ class XpuDeviceOps(DeviceOps):
     def __init__(self) -> None:
         super().__init__()
-        # The compiled address-taking block kernel, or None while the torch
-        # baseline serves block transfers.
+        # The compile
…
```

## 6. PR #5383 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/5383#discussion_r4300053666  
`lmcache/v1/multiprocess/modules/lookup.py` lines 371–382 · reviewer ApostaC · outdated=False resolved=False

Comment:

> Should we do a reverse here so that the keys in the front will be touched at the end?

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/v1/multiprocess/modules/lookup.py b/lmcache/v1/multiprocess/modules/lookup.py
index 74169489a6..a327d29de2 100644
--- a/lmcache/v1/multiprocess/modules/lookup.py
+++ b/lmcache/v1/multiprocess/modules/lookup.py
@@ -222,20 +222,5 @@ class LookupModule(DiscoverableModule):
                 world_size,
             )
-            self._register_prefetch_job(
-                _PrefetchJob(
-                    handle=PrefetchHandle(
-                        prefetch_request_id=-1,
-                        external_request_id=key.request_id,
-                        total_requested_keys=0,
-                        submit_time=time.monotonic(),
-                    ),
-                    row_windows=(),
-                    request_id=key.request_id,
-                    requested_tokens=0,
-                    model_name=model_name,
-                    cache_salt=key.cache_salt,
-                    early_exit_reason="no_gpu_context",
-                )
-            )
+            self._register_empty_prefetch_job(key, early_exit_reason="no_gpu_context")
             return
 
@@ -246,19 +231,6 @@ class LookupModule(DiscoverableModule):
         )
         if not chunk_hashes:
-            self._register_prefetch_job(
-                _PrefetchJob(
-                    handle=PrefetchHandle(
-                        prefetch_request_id=-1,
-                        external_request_id=key.request_id,
-                        total_requested_keys=0,
-           
…
```

## 7. PR #4828 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/4828#discussion_r4078589835  
`lmcache/v1/multiprocess/futures.py` lines 197–197 · reviewer ApostaC · outdated=True resolved=True

Comment:

> change it to a private function if nobody is calling it

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/v1/multiprocess/futures.py b/lmcache/v1/multiprocess/futures.py
index 527fd2b0f7..42de186302 100644
--- a/lmcache/v1/multiprocess/futures.py
+++ b/lmcache/v1/multiprocess/futures.py
@@ -195,5 +195,5 @@ class DeviceMessagingFuture(MessagingFuture[T]):
         self._raw_response_processed = True
 
-    def prepare(self, timeout: Optional[float] = None) -> T:
+    def _prepare(self, timeout: Optional[float] = None) -> T:
         """Import the remote completion event without waiting for it.
 
@@ -244,5 +244,5 @@ class DeviceMessagingFuture(MessagingFuture[T]):
             synchronization.
         """
-        result = self.prepare(timeout)
+        result = self._prepare(timeout)
         if self.event_ is not None:
             self._event_backend.wait_event(self.event_, stream)
```

## 8. PR #4292 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/4292#discussion_r3679513405  
`lmcache/v1/distributed/api.py` lines 40–40 · reviewer ApostaC · outdated=True resolved=True

Comment:

> nit: `L1BackendType`

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/v1/distributed/api.py b/lmcache/v1/distributed/api.py
index 3f76e71b8a..bad9570870 100644
--- a/lmcache/v1/distributed/api.py
+++ b/lmcache/v1/distributed/api.py
@@ -38,10 +38,10 @@ class Tier(str, enum.Enum):
 
 
-class L1Backend(str, enum.Enum):
+class L1BackendType(str, enum.Enum):
     """The storage medium backing the L1 tier (a closed set, unlike L2
     backends, which are an open adapter-type registry).
 
     Subclasses ``str`` so it compares equal to and serializes as the bare
-    wire value (``L1Backend.DRAM == "dram"``).
+    wire value (``L1BackendType.DRAM == "dram"``).
     """
```

## 9. PR #5341 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/5341#discussion_r4214394767  
`lmcache/v1/platform/kv_wrap.py` lines 45–45 · reviewer maobaolong · outdated=True resolved=True

Comment:

> Could we report the dtype for each plane here? Multi-plane KV caches may use mixed dtypes, so `value[0].dtype` can make this log misleading.

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/v1/platform/kv_wrap.py b/lmcache/v1/platform/kv_wrap.py
index 8a073f2b51..b218ae0d8f 100644
--- a/lmcache/v1/platform/kv_wrap.py
+++ b/lmcache/v1/platform/kv_wrap.py
@@ -13,4 +13,5 @@ from __future__ import annotations
 
 # Standard
+from logging import DEBUG
 from typing import Any
 
@@ -20,4 +21,5 @@ import torch
 # First Party
 from lmcache.logging import init_logger
+from lmcache.v1.gpu_connector.utils import get_device
 from lmcache.v1.multiprocess.custom_types import KVCache
 from lmcache.v1.platform import resolve_kv_wrapper_factory
@@ -27,5 +29,5 @@ logger = init_logger(__name__)
 
 def wrap_one_kv_cache(tensor: torch.Tensor) -> Any:
-    """Dispatch by ``tensor.device.type`` via the platform registry.
+    """Dispatch by the layer KVCache's device type via the platform registry.
 
     Concrete factories are supplied by the registered ``DeviceSpec`` objects,
@@ -33,7 +35,4 @@ def wrap_one_kv_cache(tensor: torch.Tensor) -> Any:
     can provide their wrapper from an installed device-plugin wheel.
     """
-    # First Party
-    from lmcache.v1.gpu_connector.utils import get_device
-
     return resolve_kv_wrapper_factory(get_device(tensor).type)(tensor)
 
@@ -43,32 +42,33 @@ def _layer_shape_and_dtype(value: Any) -> tuple[object, str]:
     if isinstance(value, torch.Tensor):
         return tuple(value.shape), str(value.dtype)
-    return tuple(tuple(p.shape) for p in value), str(value[0].dtype)
+    return tuple(tuple(p.shape) for p in value), 
…
```

## 10. PR #4487 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/4487#discussion_r3809343752  
`lmcache/v1/mp_coordinator/persistence/checkpoint.py` lines 114–114 · reviewer ApostaC · outdated=False resolved=True

Comment:

> Move this to the top of this function.
> 
> Double check the logic of "skipping already processed events" in the event consumer.

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/v1/mp_coordinator/persistence/checkpoint.py b/lmcache/v1/mp_coordinator/persistence/checkpoint.py
index 47401e96b4..2693068aa2 100644
--- a/lmcache/v1/mp_coordinator/persistence/checkpoint.py
+++ b/lmcache/v1/mp_coordinator/persistence/checkpoint.py
@@ -80,6 +80,6 @@ def load_checkpoint(
         broadcaster.broadcast(batch)
     for component in components:
-        if component.state_key in sections:
-            component.restore_state(sections[component.state_key])
+        if component.name in sections:
+            component.restore(sections[component.name])
     stats = directory.stats()
     logger.info(
@@ -111,7 +111,9 @@ async def save_checkpoint(
         components: State captured into the trailing sections.
     """
-    snapshot = directory.snapshot()
+    # Cursors first: a gate ahead of the directory would drop the gap as
+    # duplicates on restore.
     cursors = gate.stats()
-    sections = {c.state_key: c.capture_state() for c in components}
+    snapshot = directory.snapshot()
+    sections = {c.name: c.capture() for c in components}
     try:
         await asyncio.to_thread(_write_snapshot, store, snapshot, cursors, sections)
```

## 11. PR #4004 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/4004#discussion_r3567620872  
`docs/design/ARCHITECTURE_MULTI_HARDWARE.md` lines 40–40 · reviewer hlin99 · outdated=True resolved=True

Comment:

> maybe not calling cuda-only anymore, we have other deivces support IPC now. can we call it IPC capable device, or something like this?

Later diff of this file (comment commit → PR head):

```diff
diff --git a/docs/design/ARCHITECTURE_MULTI_HARDWARE.md b/docs/design/ARCHITECTURE_MULTI_HARDWARE.md
index 86404a34c5..8186fcac92 100644
--- a/docs/design/ARCHITECTURE_MULTI_HARDWARE.md
+++ b/docs/design/ARCHITECTURE_MULTI_HARDWARE.md
@@ -1,8 +1,10 @@
-
 # LMCache Multi-Hardware Architecture
 
+This document describes the multi-hardware architecture for LMCache's
+multiprocess (MP) mode. 
+
 ```
 ┌─────────────────────────────────────────────────────────────────┐
-│                 lmcache/v1/platform/__init__.py                │
+│                 lmcache/v1/platform/__init__.py                 │
 │                                                                 │
 │  torch_dev, torch_device_type = _detect_device()                │
@@ -15,5 +17,6 @@
 │                           │                                     │
 │                     torch_dev (unified entry)                   │
-│                  torch_device_type ("cuda"/"xpu"/"hpu"/"cpu")   │
+│              torch_device_type (e.g. "cuda"/"musa"/"xpu"/       │
+│                                 "hpu"/"cpu"; auto-discoverable) │
 │                                                                 │
 │  [Registry Discovery Point]                                     │
@@ -38,7 +41,8 @@
 │                  │ │ .device_     │ │ .Stream()                │
 │                  │ │  count()     │ │                          │
-│                  │ │              │ │ CUDA-only (hasattr):     │
+│                  │ │           
…
```

## 12. PR #5615 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/5615#discussion_r4238902926  
`lmcache/integration/vllm/kv_cache_identity.py` lines 35–35 · reviewer zhengfeihe · outdated=True resolved=False

Comment:

> Thanks for catching the issue!
> 
> But encoding precision settings in the model name is a little hacky.. I'd prefer adding a field to ObjectKey and IPCCacheServerKey for a general solution.

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/integration/vllm/kv_cache_identity.py b/lmcache/integration/vllm/kv_cache_identity.py
index a7ff766c26..52d35ca8fb 100644
--- a/lmcache/integration/vllm/kv_cache_identity.py
+++ b/lmcache/integration/vllm/kv_cache_identity.py
@@ -1,35 +1,27 @@
 # SPDX-License-Identifier: Apache-2.0
-"""Cache identity for vLLM KV encodings copied without dtype conversion."""
+"""Cache identity for vLLM KV encodings."""
 
 # Third Party
 from vllm.config import VllmConfig
-from vllm.config.utils import hash_factors
 
-_KV_DTYPE_NAMESPACE = "##lmcache-kv-dtype-v1-"
+# First Party
+from lmcache.v1.cache_format import KVCacheFormat
 
 
-def get_kv_dtype_decorated_model_name(vllm_config: VllmConfig, model_name: str) -> str:
-    """Namespace the cache model name by raw KV precision settings.
+def get_kv_cache_format(vllm_config: VllmConfig) -> str:
+    """Project raw vLLM KV precision settings into LMCache's format schema.
 
     Args:
-        vllm_config: Initialized vLLM configuration shared by scheduler/worker.
-        model_name: Cache model name, including any DCP layout decoration.
+        vllm_config: Initialized configuration shared by scheduler and worker.
 
     Returns:
-        Cache model name with a dtype identifier. New clients miss legacy
-        objects; model loading and the public served name are unaffected.
-
-    Note:
-        Raw settings remain distinct even when they resolve to equivalent
-        encodings (e.g. auto and bfloat16). This isolates c
…
```

## 13. PR #3679 — label addressed=True (file-deleted)
https://github.com/LMCache/LMCache/pull/3679#discussion_r3411098117  
`docs/source/mp/architecture.rst` lines 441–441 · reviewer hlin99 · outdated=True resolved=True

Comment:

> lmcache driven -> gpu
> engine driven -> non gpu

Later diff of this file (comment commit → PR head):

```diff
diff --git a/docs/source/mp/architecture.rst b/docs/source/mp/architecture.rst
deleted file mode 100644
index 291d59b3fd..0000000000
--- a/docs/source/mp/architecture.rst
+++ /dev/null
@@ -1,484 +0,0 @@
-Architecture & Developer Guide
-===============================
-
-This page describes the internal architecture of LMCache multiprocess mode.
-It is aimed at developers who want to understand, debug, or extend the system.
-
-.. contents::
-   :local:
-   :depth: 2
-
-High-Level Architecture
------------------------
-
-.. code-block:: text
-
-    vLLM Instance(s)
-         |
-         | ZMQ (tcp)
-         v
-    MessageQueueServer (mq.py)
-         |
-         | dispatch by RequestType
-         v
-    MPCacheServer (server.py)
-         |
-         |--- TokenHasher / SessionManager
-         |
-         v
-    StorageManager (distributed/storage_manager.py)
-         |
-         |--- L1Manager (l1_manager.py)
-         |       |--- L1MemoryManager (CPU DRAM) or
-         |       |    GDSL1MemoryManager (NVMe slab via cuFile)
-         |       |--- TTLLock per object (read/write)
-         |
-         |--- StoreController  -----> L2 Adapter(s) (async L1->L2 push)
-         |--- PrefetchController ---> L2 Adapter(s) (async L2->L1 load)
-         |--- EvictionController ----> L1Manager (watermark-triggered eviction)
-         |
-         v
-    EventBus + OTel providers (observability)
-
-Server Variants
----------------
-
-All server entry points share the same ``MPCacheServe
…
```

## 14. PR #4177 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/4177#discussion_r3868289182  
`.buildkite/k3_tests/common_scripts/path-filter.sh` lines 120–120 · reviewer hlin99 · outdated=True resolved=True

Comment:

> ditto

Later diff of this file (comment commit → PR head):

```diff
diff --git a/.buildkite/k3_tests/common_scripts/path-filter.sh b/.buildkite/k3_tests/common_scripts/path-filter.sh
index 3a6fbaa2a2..e5864c1198 100755
--- a/.buildkite/k3_tests/common_scripts/path-filter.sh
+++ b/.buildkite/k3_tests/common_scripts/path-filter.sh
@@ -20,4 +20,8 @@
 #     to that suite, while shared harness changes under .buildkite/k3_harness/
 #     are classified by the harness file they touch.
+#   - Special-case platform tests are treated as unrelated for the unit
+#     pipeline: tests/v1/platform/{musa,rbln,xpu} do not trigger unit. The xpu
+#     pipeline also treats these platform paths as non-targets while allowing
+#     tests/platform/* to remain relevant.
 #
 # Opt-out: add a "force-ci" label to the PR on GitHub. Buildkite exposes
@@ -50,149 +54,224 @@ _path_filter_is_trivial() {
 }
 
-_path_filter_is_runtime_surface() {
-    case "$1" in
-        lmcache/*) return 0 ;;
-        csrc/*) return 0 ;;
-        requirements/*) return 0 ;;
-        pyproject.toml|pyproject_cli.toml|setup.py|hatch_build.py|conftest.py) return 0 ;;
-        CMakeLists.txt|MANIFEST.in|Cargo.toml|rust-toolchain.toml) return 0 ;;
-        .buildkite/k3_harness/*) return 0 ;;
-        .buildkite/k3_tests/common_scripts/*) return 0 ;;
-    esac
-    return 1
-}
-
-_path_filter_is_unit_surface() {
-    case "$1" in
-        .buildkite/k3_tests/unit/*) return 0 ;;
-        tests/v1/platform/musa/*|tests/v1/platform/rbln/*|tests/v1/platform/xpu/*)
-            return 1
-          
…
```

## 15. PR #3679 — label addressed=True (file-deleted)
https://github.com/LMCache/LMCache/pull/3679#discussion_r3411099628  
`docs/source/mp/architecture.rst` lines 442–442 · reviewer hlin99 · outdated=True resolved=True

Comment:

> the same

Later diff of this file (comment commit → PR head):

```diff
diff --git a/docs/source/mp/architecture.rst b/docs/source/mp/architecture.rst
deleted file mode 100644
index 291d59b3fd..0000000000
--- a/docs/source/mp/architecture.rst
+++ /dev/null
@@ -1,484 +0,0 @@
-Architecture & Developer Guide
-===============================
-
-This page describes the internal architecture of LMCache multiprocess mode.
-It is aimed at developers who want to understand, debug, or extend the system.
-
-.. contents::
-   :local:
-   :depth: 2
-
-High-Level Architecture
------------------------
-
-.. code-block:: text
-
-    vLLM Instance(s)
-         |
-         | ZMQ (tcp)
-         v
-    MessageQueueServer (mq.py)
-         |
-         | dispatch by RequestType
-         v
-    MPCacheServer (server.py)
-         |
-         |--- TokenHasher / SessionManager
-         |
-         v
-    StorageManager (distributed/storage_manager.py)
-         |
-         |--- L1Manager (l1_manager.py)
-         |       |--- L1MemoryManager (CPU DRAM) or
-         |       |    GDSL1MemoryManager (NVMe slab via cuFile)
-         |       |--- TTLLock per object (read/write)
-         |
-         |--- StoreController  -----> L2 Adapter(s) (async L1->L2 push)
-         |--- PrefetchController ---> L2 Adapter(s) (async L2->L1 load)
-         |--- EvictionController ----> L1Manager (watermark-triggered eviction)
-         |
-         v
-    EventBus + OTel providers (observability)
-
-Server Variants
----------------
-
-All server entry points share the same ``MPCacheServe
…
```

## 16. PR #3491 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/3491#discussion_r3343969828  
`lmcache/v1/distributed/storage_controllers/prefetch_controller.py` lines 347–347 · reviewer ApostaC · outdated=True resolved=False

Comment:

> nit: "Query the keys that are found during the lookup for a specific request".

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/v1/distributed/storage_controllers/prefetch_controller.py b/lmcache/v1/distributed/storage_controllers/prefetch_controller.py
index 9e2c8f0450..4efc68f20b 100644
--- a/lmcache/v1/distributed/storage_controllers/prefetch_controller.py
+++ b/lmcache/v1/distributed/storage_controllers/prefetch_controller.py
@@ -24,5 +24,5 @@ import threading
 from lmcache.logging import init_logger
 from lmcache.native_storage_ops import Bitmap
-from lmcache.v1.distributed.api import MemoryLayoutDesc, ObjectKey
+from lmcache.v1.distributed.api import MemoryLayoutDesc, ObjectKey, TrimPolicy
 from lmcache.v1.distributed.error import L1Error
 from lmcache.v1.distributed.l1_manager import L1Manager
@@ -60,32 +60,20 @@ def merge_bitmaps(bitmaps: Iterable[Bitmap], num_keys: int) -> Bitmap:
 
 
-class TrimPolicy(enum.Enum):
-    """How to pick the retained subset of found keys for a prefetch.
-
-    PREFIX retains the longest contiguous run from index 0; SEGMENTED_PREFIX
-    retains a caller-supplied set of key indices (a segment mask).
-    """
-
-    PREFIX = enum.auto()
-    SEGMENTED_PREFIX = enum.auto()
-
-
-def retained_mask(
+def build_trim_mask(
     found: Bitmap,
     num_keys: int,
     policy: TrimPolicy = TrimPolicy.PREFIX,
-    segments: Bitmap | None = None,
 ) -> Bitmap:
     """Subset of ``found`` to keep (load + read-lock + report); the rest is
     released.
 
-    PREFIX = the leading contiguous run; SEGMENTED_PREFIX = the intersection
-    with ``segments``.
+
…
```

## 17. PR #4077 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/4077#discussion_r3557133176  
`lmcache/v1/platform/base_device_ops.py` lines 37–37 · reviewer maobaolong · outdated=True resolved=True

Comment:

> Are you trying to make these following to be the methods of `DeviceOps` ?

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/v1/platform/base_device_ops.py b/lmcache/v1/platform/base_device_ops.py
index 12b22a5a2f..def1a9886f 100644
--- a/lmcache/v1/platform/base_device_ops.py
+++ b/lmcache/v1/platform/base_device_ops.py
@@ -2,12 +2,8 @@
 """The unified per-device ops abstraction (the ``lmcache.c_ops`` surface).
 
-:class:`DeviceOps` owns the full op contract (:data:`OPS`) with a
-device-agnostic torch baseline from :mod:`lmcache.v1.platform._torch_ops`.
-Each op is a real ``staticmethod`` on the class, resolved via normal MRO.
-Accelerator subclasses override individual ops or call :func:`bind_native`
-(usually via :meth:`_ensure_native`) to bulk-bind a compiled ``.so``.
-
-:func:`bind_native` is a class-decorator factory: ``bind_native(module)(cls)``
-overwrites every OPS-listed staticmethod found in *module* onto *cls*.
+:class:`DeviceOps` is a strategy base class whose every op is an instance
+method delegating to :mod:`lmcache.v1.platform.torch_ops`.  Accelerator
+subclasses override individual methods with native kernels via normal OO
+polymorphism, or bulk-rebind via :meth:`DeviceOps.bind_native`.
 """
 
@@ -16,215 +12,231 @@ from __future__ import annotations
 
 # Standard
-from typing import ClassVar
+from typing import TYPE_CHECKING, ClassVar
+
+if TYPE_CHECKING:
+    # Third Party
+    import torch
 
 # First Party
-from lmcache.v1.platform import _torch_ops
+from lmcache.logging import init_logger
+from lmcache.v1.platform import ops_types, torch_ops
 from lmcache.v
…
```

## 18. PR #5836 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/5836#discussion_r4319940512  
`examples/observability/grafana/provisioning/dashboards/lmcache.json` lines 1537–1551 · reviewer ApostaC · outdated=True resolved=False

Comment:

> 2 changes:
> - drop "engine prefix-cache hit rate" because we don't need to expose that to users
> - change lmcache hit rate's denominator to be the total prompt tokens

Later diff of this file (comment commit → PR head):

```diff
diff --git a/examples/observability/grafana/provisioning/dashboards/lmcache.json b/examples/observability/grafana/provisioning/dashboards/lmcache.json
index 5f39b1d4b0..a59075b207 100644
--- a/examples/observability/grafana/provisioning/dashboards/lmcache.json
+++ b/examples/observability/grafana/provisioning/dashboards/lmcache.json
@@ -1317,5 +1317,5 @@
         "uid": "prometheus"
       },
-      "description": "Chunks loaded into the engine, and lookup token counts. Lookup-level: requested vs hit (the range LMCache was asked for) and the engine-covered prefix it skipped. Request-level: whole prompt, the engine's own prefix-cache hit, and the prefix served by either cache.",
+      "description": "Chunks loaded into the engine, and lookup token counts: requested vs hit (the range LMCache was asked for, past the prefix the engine already held), the whole prompt, and the request-level prefix served by the engine's prefix cache or LMCache.",
       "fieldConfig": {
         "defaults": {
@@ -1406,10 +1406,4 @@
           "refId": "B"
         },
-        {
-          "editorMode": "code",
-          "expr": "rate(lmcache_mp_lookup_apc_covered_tokens_total[$__rate_interval])",
-          "legendFormat": "engine-covered tokens/s [{{service_instance_id}}]",
-          "refId": "D"
-        },
         {
           "editorMode": "code",
@@ -1418,10 +1412,4 @@
           "refId": "E"
         },
-        {
-          "editorMode": "code",
-          "expr": "rate(lmcache_mp_lookup
…
```

## 19. PR #3702 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/3702#discussion_r3418327014  
`lmcache/v1/multiprocess/server.py` lines 119–119 · reviewer hlin99 · outdated=True resolved=True

Comment:

> shall we rename function name to cache_context if it's reused by gpu/cpu?

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/v1/multiprocess/server.py b/lmcache/v1/multiprocess/server.py
index fd40164d6a..d88a59ae8a 100644
--- a/lmcache/v1/multiprocess/server.py
+++ b/lmcache/v1/multiprocess/server.py
@@ -117,5 +117,5 @@ class MPCacheServer:
 
     @property
-    def gpu_contexts(self) -> dict[int, BaseCacheContext] | None:
+    def cache_contexts(self) -> dict[int, BaseCacheContext] | None:
         """Used by ``/kvcache/check``; unwraps :class:`ContextEntry`."""
         for module in self._modules:
```

## 20. PR #4302 — label addressed=True (lines-changed)
https://github.com/LMCache/LMCache/pull/4302#discussion_r3680124960  
`.buildkite/k3_tests/xpu/run.sh` lines 58–58 · reviewer hlin99 · outdated=True resolved=True

Comment:

> is it also tests in sub-folders?

Later diff of this file (comment commit → PR head):

```diff
diff --git a/.buildkite/k3_tests/xpu/run.sh b/.buildkite/k3_tests/xpu/run.sh
index 0c046dcfaa..64e9f776f0 100755
--- a/.buildkite/k3_tests/xpu/run.sh
+++ b/.buildkite/k3_tests/xpu/run.sh
@@ -56,5 +56,5 @@ allowlist = {
   "tests/disagg/test_*.py",
   "tests/v1/multiprocess/test_engine_driven_transfer.py",
-  "tests/v1/distributed/test_*.py",
+  "tests/v1/distributed/**/test_*.py",
   "tests/v1/test_xpu_connector.py",
   "tests/v1/test_torch_ops.py",
```

## 21. PR #3391 — label addressed=False (no-later-commits)
https://github.com/LMCache/LMCache/pull/3391#discussion_r3302119297  
`lmcache/v1/multiprocess/modules/gpu_transfer.py` lines 254–254 · reviewer maobaolong · outdated=False resolved=False

Comment:

> Ref to https://github.com/LMCache/LMCache/pull/3352/changes#diff-e02d00dbea27ffec36f8fa559186d06b4bf8bcbd9c82be453f208d9ab7db2832L300
> 
> for server-side shm based copy Cpu only case, it may not be `GPUCacheContext`, it can be `CpuCacheContext` too. 

Later diff of this file (comment commit → PR head):

```diff
(no change to this file)
```

## 22. PR #5877 — label addressed=False (no-later-commits)
https://github.com/LMCache/LMCache/pull/5877#discussion_r4507675629  
`tests/v1/test_token_drop_worker_adapter.py` lines 12–12 · reviewer Zefan-Cai · outdated=False resolved=False

Comment:

> With the module-level `importorskip("vllm")` this file only runs where vLLM is installed, but it isn't in the token-drop job (the only one pinned to vLLM 0.25.1), and the GPU unit-test pipeline doesn't install vLLM. So I don't think any of these tests run in CI right now. Could we add it to the `token_drop` filter and the pytest line in that job?

Later diff of this file (comment commit → PR head):

```diff
(no change to this file)
```

## 23. PR #3302 — label addressed=False (file-changed-elsewhere)
https://github.com/LMCache/LMCache/pull/3302#discussion_r3257575953  
`setup.py` lines 224–224 · reviewer maobaolong · outdated=False resolved=True

Comment:

> @ApostaC Do you still remember the dead-lock issue we encountered? The way you fixed that issue is by introduced native `event_recorder`, but how about non-cuda case?

Later diff of this file (comment commit → PR head):

```diff
diff --git a/setup.py b/setup.py
index a4d6b48e04..836cf6148a 100644
--- a/setup.py
+++ b/setup.py
@@ -194,4 +194,5 @@ def _common_cpp_extensions(
         ),
     ]
+    # Mooncake extension is optional.
     ext_modules.extend(
         _mooncake_extension(cpp_extension, mooncake_sources, extra_cxx_flags)
```

## 24. PR #5615 — label addressed=False (file-unchanged)
https://github.com/LMCache/LMCache/pull/5615#discussion_r4252978957  
`lmcache/v1/storage_backend/raw_block/key_codec.py` lines 74–77 · reviewer KuntaiDu · outdated=False resolved=False

Comment:

> Just double check --- does this mean that not all code paths use `cache_format`?

Later diff of this file (comment commit → PR head):

```diff
(no change to this file)
```

## 25. PR #4178 — label addressed=False (file-changed-elsewhere)
https://github.com/LMCache/LMCache/pull/4178#discussion_r3629813463  
`lmcache/v1/distributed/l2_adapters/fs_l2_adapter.py` lines 673–673 · reviewer maobaolong · outdated=False resolved=False

Comment:

> It looks like there is special handling for the case with only a single element. Does this actually lead to a significant performance boost, or is it more of a maintenance overhead?
> 
> If there is no real benefit, wouldn't introducing this extra branch negatively impact code read ability?

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/v1/distributed/l2_adapters/fs_l2_adapter.py b/lmcache/v1/distributed/l2_adapters/fs_l2_adapter.py
index 7da873c93d..15def555cb 100644
--- a/lmcache/v1/distributed/l2_adapters/fs_l2_adapter.py
+++ b/lmcache/v1/distributed/l2_adapters/fs_l2_adapter.py
@@ -265,4 +265,6 @@ class FSL2Adapter(L2AdapterInterface):
     """
 
+    _DELETE_CONCURRENCY = 64
+
     def __init__(self, config: FSL2AdapterConfig):
         super().__init__()
@@ -388,6 +390,6 @@ class FSL2Adapter(L2AdapterInterface):
 
     def submit_unlock(self, keys: list[ObjectKey]) -> None:
-        # No-op: FS adapter has no eviction, so locking
-        # between lookup and load is unnecessary.
+        # No-op: the FS adapter tracks no per-key locks — a delete
+        # racing the lookup→load window degrades the load to a miss.
         pass
 
@@ -433,12 +435,34 @@ class FSL2Adapter(L2AdapterInterface):
 
     def delete(self, keys: list[ObjectKey]) -> None:
-        # Not implemented for the filesystem adapter.
-        pass
+        """Delete each key's backing file and notify listeners.
+
+        Args:
+            keys: The object keys to delete.
 
-    # ``get_usage()`` is inherited from ``L2AdapterInterface``. The FS
-    # adapter declares no max capacity (default 0) so ``supports_global_eviction``
-    # returns ``False`` and ``usage_fraction == -1.0`` — the eviction
-    # controller treats this as "no eviction signal" and skips the
-    # adapter entirely.
+        Note:
+           
…
```

## 26. PR #4706 — label addressed=False (no-later-commits)
https://github.com/LMCache/LMCache/pull/4706#discussion_r3961126935  
`lmcache/v1/multiprocess/http_server.py` lines 146–151 · reviewer ruizhang0101 · outdated=False resolved=False

Comment:

> Is there a reason to change the logic here? 

Later diff of this file (comment commit → PR head):

```diff
(no change to this file)
```

## 27. PR #5105 — label addressed=False (file-changed-elsewhere)
https://github.com/LMCache/LMCache/pull/5105#discussion_r4057234979  
`docs/design/v1/shared_devdax_l1.md` lines 123–123 · reviewer zhengfeihe · outdated=False resolved=False

Comment:

> Curious about your visibility `.so`, not a blocker comment (
> 
> How is it implemented on your setup? From the design doc (64-byte granularity,
> `software_fenced`) I'm guessing it's mostly a per-range cache-line flush + fence?
> 
> Asking because the cross-host coherence problem reminds me of the Beluga paper:
> https://arxiv.org/abs/2511.20172
> 
> It claims that by marking the CXL range uncacheable (MTRR) and turning DDIO off,
> the GPU's DMA traffic never lands in the CPU's LLC, so there's nothing to flush
> per object. They report this as noticeably faster. Caveat: that was on Intel Xeon,
> and DDIO is Intel-specific.
> 
> Do you have any plan to look at that direction later, or did you already try it?
> 

Later diff of this file (comment commit → PR head):

```diff
diff --git a/docs/design/v1/shared_devdax_l1.md b/docs/design/v1/shared_devdax_l1.md
index 52aeb20a93..fa73e90e13 100644
--- a/docs/design/v1/shared_devdax_l1.md
+++ b/docs/design/v1/shared_devdax_l1.md
@@ -69,4 +69,10 @@ ABSENT --reserve--> WRITING --D2H complete, publish, finish--> VALID
    unmapping; they are not distributed read pins.
 
+Shared L1 uses the common `PrefetchController` and configured `PrefetchPolicy`,
+not a separate lookup/retention path in `StorageManager`. Each hit's layout is
+checked against its request row before policy planning. Grouped hit results,
+prefix/window retention, and `NO_LOCK` release follow the common contract.
+L2 adapters remain unsupported for shared L1.
+
 Canonical object keys include the chunk hash, model, KV rank, object group, and
 cache salt. The coordinator stores immutable, validated keys directly in its
@@ -94,4 +100,11 @@ full key listing. Shared capacity events prevent each mounting MP from reporting
 the same pool as private capacity.
 
+When a new batch does not fit, reservation fails atomically with `OutOfSpaceError`
+(HTTP 507). This does not fence the client. Existing committed objects remain
+readable while the coordinator is available. MP reports `OUT_OF_MEMORY` for
+ungranted keys and skips storing those chunks; cache misses must be computed by
+the serving engine. Safe eviction would need a lifetime protocol covering remote
+readers and in-flight GPU writes, not just a metadata-delete API.
+
 This version supports
…
```

## 28. PR #3391 — label addressed=False (no-later-commits)
https://github.com/LMCache/LMCache/pull/3391#discussion_r3302309860  
`lmcache/v1/multiprocess/modules/lookup.py` lines 89–89 · reviewer maobaolong · outdated=False resolved=False

Comment:

> Why these sub classes didn't inherit `EngineModule` class?

Later diff of this file (comment commit → PR head):

```diff
(no change to this file)
```

## 29. PR #4246 — label addressed=False (no-later-commits)
https://github.com/LMCache/LMCache/pull/4246#discussion_r3876736597  
`lmcache/v1/multiprocess/transport/grpc_impl/typed_rpc.py` lines 21–21 · reviewer ApostaC · outdated=False resolved=False

Comment:

> We should avoid use pickle due to security issues. Let's use msgspec for serialize & deserialize.

Later diff of this file (comment commit → PR head):

```diff
(no change to this file)
```

## 30. PR #4551 — label addressed=False (file-changed-elsewhere)
https://github.com/LMCache/LMCache/pull/4551#discussion_r3816656892  
`lmcache/v1/platform/cuda/timeline_semaphore_event_ipc.py` lines 180–183 · reviewer ApostaC · outdated=False resolved=True

Comment:

> How many local buffers will we have? Is it the same as the number of devices?

Later diff of this file (comment commit → PR head):

```diff
diff --git a/lmcache/v1/platform/cuda/timeline_semaphore_event_ipc.py b/lmcache/v1/platform/cuda/timeline_semaphore_event_ipc.py
index 16a2dbb420..cc80ea8332 100644
--- a/lmcache/v1/platform/cuda/timeline_semaphore_event_ipc.py
+++ b/lmcache/v1/platform/cuda/timeline_semaphore_event_ipc.py
@@ -129,5 +129,5 @@ class _TimelineSemaphoreBuffer:
         base_ptr: Device pointer of the buffer.
         handle_bytes: ``cudaIpcMemHandle`` bytes exported at allocation.
-        host_ops_stream: Dedicated non-blocking stream for host-initiated
+        buffer_ops_stream: Dedicated non-blocking stream for host-initiated
             slot reads/writes, so they never synchronize with (possibly
             blocked) caller streams.
@@ -142,5 +142,5 @@ class _TimelineSemaphoreBuffer:
     base_ptr: int
     handle_bytes: bytes
-    host_ops_stream: object
+    buffer_ops_stream: object
     lock: threading.Lock = field(default_factory=threading.Lock)
     slot_by_stream: dict[cudaStream_t, int] = field(default_factory=dict)
@@ -253,5 +253,5 @@ class TimelineSemaphoreEventIPCBackend:
             probe_ptr: int = buffer.base_ptr + _PROBE_SLOT_OFFSET
             stream_hdl: cudaStream_t = _raw_stream_handle(
-                buffer.host_ops_stream, device_index
+                buffer.buffer_ops_stream, device_index
             )
             with torch.cuda.device(device_index):
@@ -275,5 +275,5 @@ class TimelineSemaphoreEventIPCBackend:
                 )
                 _CHECK_CUDA(
- 
…
```


# Compare v0-medium vs v0

Samples in both: 10 · findings v0-medium 90, v0 93

- fixed (missed by v0-medium, matched by v0): 0
- broken (matched by v0-medium, missed by v0): 2
- matched by both: 7 · missed by both: 5
- net: -2

## fixed


## broken

- #5390 (nit) `lmcache/integration/vllm/kv_cache_group_edits.py:424` sammshen: nit: `_MambaUnifiedViewEdit.apply` raises on a missing hint, this falls back to the legacy default. not blocking, but the two edits disagreeing on a m
- #5876 (change_request) `lmcache/integration/vllm/experimental/token_drop_adapter.py:182` Zefan-Cai: With the default cudagraph mode, decode batches replay a FULL graph, so this wrapper never runs on decode steps. R-KV's observation window is exactly 

## neither

- #5390 (change_request) `overall review` sammshen: fix looks right. synthetic head count is 1, so `[NB, BS, 1, CS]` and `[NB, 1, BS, CS]` are the same bytes, the branch only changes which axis the dete
- #5685 (change_request) `docker/example_run.sh:None` ApostaC: Actually after a second look at this file, this is a in-process mode example. Maybe we should remove it.
- #5776 (change_request) `tests/inprocess/integration/vllm/test_v1_adapter_request_finished_scheduler_role.py:None` deng451e: In-process mode is being deprecated soon, so we probably don’t need to add tests for it.  
- #5827 (change_request) `lmcache/cli/commands/bench/server_bench/allocator.py:8` maobaolong: Define a data class instead of use tuple of tuple of tuple.
- #5876 (change_request) `lmcache/integration/vllm/experimental/token_drop_adapter.py:153` Zefan-Cai: token-dropping-kv-compaction.md (Query capture section) still says post-RoPE Q comes through `save_kv_layer(..., **kwargs)`. Can we update it to the `


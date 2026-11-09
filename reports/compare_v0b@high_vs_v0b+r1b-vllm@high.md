# Compare v0b@high vs v0b+r1b-vllm@high

Samples in both: 10 · findings v0b@high 92, v0b+r1b-vllm@high 92

- fixed (missed by v0b@high, matched by v0b+r1b-vllm@high): 1
- broken (matched by v0b@high, missed by v0b+r1b-vllm@high): 2
- matched by both: 7 · missed by both: 5
- net: -1

## fixed

- #5004 (change_request) `lmcache/integration/vllm/lmcache_mp_metadata.py:145` ApostaC: I think we can replace this text description with an example to keep the docstring more self-contained and easier to understand.  A quick example coul

## broken

- #5222 (change_request) `lmcache/v1/multiprocess/config.py:37` zhengfeihe: We also need to update mp_coordinator. Both TokenHasher in create_app() and the BlendIndex created by directory.enable_blend_lookup() use config.chunk
- #5736 (nit) `lmcache/integration/vllm/experimental/token_drop.py:34` KuntaiDu: Maybe `NotImplementedError`

## neither

- #5004 (change_request) `lmcache/integration/vllm/lmcache_mp_connector.py:616` chunxiaozheng: hi, @zhengfeihe, #5249 has also add `mamba_cache_mode`, may be we can rebase the latest `dev` branch and reuse it.
- #5042 (nit) `overall review` deng451e: I ran the local tests and verified both the output correctness and the TTFT speedup. Thanks for your work! Before the final merge, @maobaolong, could 
- #5150 (nit) `lmcache/v1/multiprocess/transport/grpc_impl/protos/common.proto:22` chunxiaozheng: @BoJiang03 We should define the var in order, otherwise, it will be difficult to maintain in the future.
- #5222 (change_request) `lmcache/integration/vllm/vllm_multi_process_adapter.py:1488` zhengfeihe: We should re-negotiate and verify the previously agreed chunk size during recovery, before re-registering KV.  If LMCache restarts while vLLM remains 
- #5405 (change_request) `lmcache/integration/vllm/experimental/kv_compaction.py:104` Zefan-Cai: When this is wired into the worker, what happens if a destination block is shared through prefix caching? Writing into it would change another request


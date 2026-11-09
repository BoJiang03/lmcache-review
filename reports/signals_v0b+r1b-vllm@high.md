# Passive signals: reviewer v0b+r1b-vllm@high

Samples: 10 · findings: 92. Signals only support a finding; absence means nothing.

| findings | n | changed later in PR | on merged PRs | changed after merge | later human comment at same place |
| --- | --- | --- | --- | --- | --- |
| all | 92 | 33 | 61 | 7 (5 fix-like) | 7 |
| AI-only | 85 | 28 | 58 | 7 (5 fix-like) | 6 |
| AI-only blocker | 2 | 1 | 0 | 0 (0 fix-like) | 1 |
| AI-only major | 17 | 8 | 12 | 3 (2 fix-like) | 1 |
| AI-only minor | 43 | 14 | 31 | 3 (2 fix-like) | 3 |
| AI-only nit | 23 | 5 | 15 | 1 (1 fix-like) | 1 |

## Severity check

AI severity of findings matched by a human change request: major 4, blocker 3, nit 1, minor 1

## AI-only blocker/major with a signal

- #5042 [major] Lazy offload divides by tokens_per_block, which is now 0 for scratch groups (ZeroDivisionE (judge: True): after merge: 2a34fa82 +31.9d "[Bugfix] Skip scratch groups in lazy offload block estimate (#5818)"
- #5042 [major] Full-prompt hit resumes at N-1, mid compression group, which breaks the doc's correctness  (judge: True): after merge: a0ff4701 +35.2d "[Fix][MP] Keep a full-prompt hit inside vLLM's allocation under SWA pr"
- #5150 [major] Old gRPC clients are silently served zero chunks instead of being rejected; description sa (judge: True): changed later in PR
- #5222 [major] Coordinator chunk-size bind is a blocking, fail-hard HTTP call on the MP server's SYNC mai (judge: True): after merge: 371108bf +15.9d "[Security][Coordinator] Authenticate coordinator outbound requests usi"
- #5222 [major] Negotiation rejection never reaches the client on ZMQ; vLLM fails after mq_timeout with a  (judge: True): changed later in PR
- #5222 [major] New connector cannot start against an older MP server (unknown op → silent timeout → 'unre (judge: True): changed later in PR
- #5222 [major] Resize guard only checks active sessions; registered KV layouts and stored data keep the o (judge: True): changed later in PR
- #5405 [major] Executor assumes dim 1 is the slot dimension; vLLM layouts such as FlashInfer `[num_blocks (judge: True): changed later in PR
- #5405 [major] Copy tensor is never validated: wrong shape, dtype, device, out-of-range or duplicate slot (judge: True): changed later in PR
- #5514 [major] warm_up / pin_status only cover the first L1 manager (judge: True): changed later in PR
- #5938 [blocker] Head commit doesn't implement the described store_scheduled design; ApostaC's change reque (judge: True): changed later in PR; later comments [4516814878, 4516849148]
- #5938 [major] Connector calls a new worker-adapter method that vLLM's vendored adapter fallback doesn't  (judge: False): changed later in PR; later comments [4516814878, 4516849148]

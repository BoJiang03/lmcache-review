# Coverage of t1m3485 on train

- comments checked: 1517 of 1517; explained by some entry: 4 (0%)
- entries used at least once: 2 of 2; cost $4.27

| entry | kind | train PRs | held-out comments explained | rule |
| --- | --- | --- | --- | --- |
| m3485-002 | knowledge | 1 | 2 | When a change adds, refactors or touches code that is used only by the legacy non-MP (non-multiprocess) mode, or adds or modifies a base class or interface whose methods are split between MP-mode use and non-MP-only use: Ask the author to mark non-MP-only code paths with the project's deprecation annotation so they emit |
| m3485-001 | knowledge | 1 | 2 | When a change makes any object other than the single owner that is cleared on engine disconnect retain a reference to the serving engine's GPU KV cache tensors, or to views, wrappers or containers of them, beyond a single call. This covers an attribute on a helper, descriptor, adapter or spec, a cache or registry entry, a closure, and module-level state.: Ask the author to pass the engine KV tensors into each call that needs them, or to keep them only in |

# Refactor to the core workflow, proven by tape replay (2026-11-26 PT)

## Goal
User: cut repo complexity and keep only the core. Old experiments need not stay reproducible (git history
has them). Hard requirement: no workflow performance regression. $100 approved for verification.

## What changed (branch `refactor-core`, local, not pushed)
- 099afb8..6a6a801: deletion only.
  - CLI eval / audit / regress / stability and the named-book distill / vet modes.
  - Config-off experiments: -sh, -ms, x<n> + LLM merge, split files, dedupe places, select, induce,
    precision gate, trim2.
  - Legacy compatibility: named prompts, tool-using rule check, LEGACY_PARAMS, `_normalize`.
  - Modules: evaluate, compare, signals, selection.
  - One-off scripts, old rulebooks, state archive, old reports.
  - Docs rewritten to the kept workflow.
- f80798d: bug fix. vet (regress.replay) hung near the cost cap: float residue in `reserved` kept the
  waiters asleep forever. Hit during the recording (1h stuck).
- 9bb0cd5: `vet()` (325 lines) split into _plan, _plan_lines, _first_pass, _classify, _sequential, _report.
  Expressions moved unchanged.
- 97d4e6e, b86ebaf, 1bfed14: record / replay tape in llm.run.
  - LMREVIEW_TAPE and LMREVIEW_TAPE_MODE select the tape and the mode.
  - Matching falls back to reordered prompts (LMREVIEW_TAPE_LOGS) and to near prompts
    (LMREVIEW_TAPE_FUZZY); every such hit is noted.
  - Replay progress is kept across commands.
- Size: lmreview 8219 → 6948 lines (including about 150 of tape tooling).
  4f141f7..HEAD: 152 files, +619 / −9954.
- Prompt id p990f2d2e → pdba46ca9. It now hashes only reviewer.md, rulecheck.md, rulepick.md and
  rulecheck_effort / stage_words. The rendered prompts are unchanged.

## Verification
1. Recording: old code (97d4e6e) in a pinned worktree on state copy A. Spent $53.09 in 353 calls.
   - `round 3340 3880 4273 4800`: covered review, judge, confirm, distill, vet and retain. Cost $8.00,
     result v0033.
   - `compress`: merge, $4.38.
   - `vet`: NONE KEPT, then promote v0034. It ran twice: the first run hung, the second ran with cap $40.
2. Replay: refactor-core HEAD on copy B from the same snapshot, the same commands, every call answered
   from the tape. Result:
   - 353 / 353 recorded calls used; 0 misses; 0 near matches.
   - 1 reordered prompt: parallel distill drafts joined in finish order, which old code does too.
   - Byte-identical modulo the prompt id: ledger, book, outcomes, compress.jsonl, every history book.
   - Remaining differences: timestamps, the removed config keys in the meta settings snapshot, and vet
     cost / log lines from the split recording. B ran vet in one command and hit the $40 cap on the
     last run, so it is followed by vet at $60. The verdicts and entries match.
3. Tests: 17/17 (importlib runner; pytest not installed).
4. Skipped: the optional 20-sample paid re-review. Replay already proves the review prompts are
   byte-identical.

## Pitfalls found while building the replay (old-code nondeterminism, not refactor bugs)
- Parallel drafts are joined in finish order, so a prompt's draft order varies.
- Identical-input calls run in parallel (annotate twice for one sample; r1/r2/r3 of a -ro run) get
  different answers, and which one lands where depends on timing.
- Logged prompts hold `\r\n`: read them as bytes, not with read_text.
- Tape consumption must persist across CLI commands.

## Files
- data/refactor/: s0 (snapshot), A (record), B (replay), tape.jsonl, rec*.sh / repall.sh,
  A_*.log / B_*.log, A_reports / B_reports.

## Open
- Push needs "push吧" (branch refactor-core, 12 commits on top of 4f141f7).
- Mechanism-level reductions need paid A/B and the user's call:
  - distill write chain: n drafts + consolidate + verify;
  - compress: 4 stages, never auto-triggered at about 3k words.

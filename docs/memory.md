# memory

*Design, 2026-11-23. Status: proposed; nothing moved yet.*

A store of learned entries for an agent, changed only through checked operations. An application
tells memory what was observed, how to quote its evidence, and how to test a book; memory decides how
the book changes and keeps every change accountable to the cases it was learned from.

```
 application                                 memory
 ───────────                                 ──────
 observations ─────────────▶ write ─────────▶ candidate book
 (what should have been done,                    │
  with evidence ids)                        consolidate (+ blind verify)
                                                 │
 evaluate(book, cases) ◀──────── vet ◀───────────┘
 (did the agent do it?)            │
                                   ├─ pass → new version; effect recorded on entries
                                   └─ fail → undone; observation tries + 1
 outcomes ─────────────────▶ record (helpful / harmful per entry)
 situation ────────────────▶ retrieve ──────▶ entries to load
```

## Entry

| Field | Meaning |
|---|---|
| `id`, `version`, `history`, `status` | Identity; text changes bump the version and keep the old text |
| `kind` | `principle` (applies anywhere) or `knowledge` (where a principle bites in this domain) |
| `when` | The situation the entry is about: a kind of situation, not an instance |
| `expect` | What the agent should do in it |
| `examples` | Short instances, optional |
| `scope` | Tags limiting where it can apply; empty = anywhere |
| `links` | `principle`, `members`, `replaces` |
| `evidence` | Ids of the observations it was learned from (opaque to memory) |
| `tests` | Effect records: case, control, result (`corrected`, `both-hit`, `both-miss`, ...) |
| `counters` | Helpful / harmful outcomes since it was written |
| `extra` | Anything the application wants to keep on the entry |

## What an application provides

| Method | Returns |
|---|---|
| `describe()` | A few paragraphs added to every memory prompt: what the agent does, what an entry is for, what a case is |
| `quote(ids)` | The text of evidence ids, for prompts |
| `evaluate(book, cases)` | Per case (a situation + the observation ids it should satisfy): satisfied or not, which entries the agent used, harmful uses |
| `scope(situation)` | Scope tags of a situation, for retrieval |

## Operations

| Operation | Does |
|---|---|
| `write(book, observations, signals)` | Sees the whole book and every observation; per observation: add evidence to an entry, generalize, add, revise (only on harmful signals or a repeated miss), skip. Several drafts, merged. |
| `consolidate(book)` | Whole-book tidy: absorb (keep one entry word for word), merge (shorter, acts as the union), rewrite new entries at the wrong level, flag conflicts. Drafts voted in code; every text change of an existing entry is verified blind (acts differently only where a case asks for it). |
| `vet(candidate, base, evaluate)` | Replays the cases tied to what changed: new entries on their evidence, revisions on their trigger, merged / retired entries on what they were proven to do. Keeps the changes that pass, writes their effect into `tests`. |
| `record(book, outcomes)` | Adds helpful / harmful counts to entries |
| `retire(book, ids, why)` | Retires entries; their evidence goes back to the ledger as open |
| `retrieve(book, situation, stage)` | Stage 1: `when` lines of the entries in scope; stage 2: full entries the agent picked |

## Store

Versioned books (`history/vNNNN`), `HEAD`, at most one candidate, rollback. A ledger of observations
by id: `open | resolved (by entry) | not_learnable | needs_human`, with tries and notes. The
application adds observations and marks the ones its agent handled; memory resolves them.

## Rules memory keeps

- Every entry is tied to the observations it must satisfy; every change keeps that link.
- A change is kept only if `evaluate` shows it works and loses nothing an entry was proven to do.
- Existing text changes only on evidence (harmful signals, a repeated miss) or to merge.
- Effects are assumed local: only the cases tied to changed entries are replayed.

## Open research questions

Studied on memory alone, with cheap synthetic applications first.

- Growth: what keeps the book from growing with every observation, without a size cap.
- Merge pressure: how to reward fewer words for the same proven cases without losing detail.
- Retirement: sparse rewards; retire on harmful evidence only?
- Retrieval: staged loading so a large book costs little per situation.

## Design lessons from lmreview (proposal, not settled)

Written 2026-11-24 from what lmreview ran into. Not agreed: some points are disputed, and several
hold only in lmreview's setting. They are sorted below by how far they seem to carry; that sorting is
itself a guess.

Possibly general:
- **Gated writes.** An entry is admitted only after evidence that it helps; "the model thought it was
  worth remembering" is not enough. Repeated, unchecked self-writes can degrade a memory rather than
  improve it.
- **Small entries with provenance.** Each entry is a short unit (situation, expectation, reason)
  linked to the observations it came from, so a change knows what to re-check and a person can trace
  it.
- **Outcome accounting.** Each use records whether it helped or hurt; that record, not age or size,
  is what revises or retires an entry.
- **Versions and rollback.** Every change is a new version; any version can be restored; a model
  upgrade re-checks what was proven.

Specific to lmreview's setting:
- **How a write is checked.** Majority votes on "worth learning", writing at the level of the
  reviewer's stated principle, and replay before admission all rely on human review comments as
  ground truth and on a PR commit as a replayable input.
- **Forced per-entry use.** A separate checker gives a verdict on every applicable entry, because
  entries in one long prompt crowded each other out. This fits a checklist-like task (does this diff
  break the rule?), not memory used for recall.
- **Local replay.** Re-checking only the changed entries' cases assumes entries compose and their
  effect is predictable (docs/mechanism.md). Untested, and only meaningful where cases replay.
- **People at policy points only.** People settle what the machine cannot decide twice and which kinds
  of feedback to learn from, not individual entries. Depends on having ground truth for the rest.

## Example application: lmreview

| Memory concept | lmreview |
|---|---|
| Agent | The PR reviewer (main review + rule check) |
| Observation | A human review point the reviewer missed, after attribute says it is learnable |
| Situation / case | A PR at one commit |
| `evaluate` | Rule-check replay of the PR plus a judge against the human comments |
| `scope` | Changed file paths |
| Harmful outcome | A finding citing an entry that the judge refutes |

Moving the current code: entry and store code out of state.py / reviewer.py, write / consolidate /
verify out of distill.py (their prompts reworded through `describe` and `quote`), vet's decision
logic out of vet.py. Code-only moves are checked for free against data on disk (same vet plans and
verdicts, same prompts byte for byte); the reworded prompts with a 10-observation pilot, old vs new
(about $5).

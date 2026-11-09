# P0 spot check verdicts (30 samples, manual read of comment + diff + thread)

| label | n | really addressed | not addressed | no change needed |
| --- | --- | --- | --- | --- |
| True | 20 | 18 | 1 | 1 |
| False | 10 | 0 | 3 | 7 |

- `addressed=True` precision ~90%; ~5 of the 18 are "lucky" (whole-file rewrite/move or file deleted by a base merge).
- `addressed=False` is mostly *no change needed* (questions, curiosity, author explained), not ignored requests.
- Failure modes: unrelated nearby edits or base merges mark lines as changed; reply-only resolutions and
  "deferred to follow-up PR" are invisible to a diff-only label.

Decisions for P1:
1. Classify each human comment first (change request / question / praise-nit) with an LLM; the recall
   gold set is change requests only.
2. Keep the diff-based label as a secondary signal; restricting the diff to the PR's own commits
   (excluding base merges) is deferred — it affects ~1/20 samples.

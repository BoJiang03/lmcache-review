# Coverage of t1m4468 on test

- comments checked: 667 of 667; explained by some entry: 7 (1%)
- entries used at least once: 2 of 4; cost $2.01

| entry | kind | train PRs | held-out comments explained | rule |
| --- | --- | --- | --- | --- |
| m4468-002 | principle | 1 | 6 | When a PR bundles defensive fixes or behavior changes (new validation, newly raised errors, altered fallbacks) in components unrelated to its stated purpose: Ask the author to move the unrelated change into a separate PR, verified and tested on its own, or t |
| m4468-003 | principle | 1 | 1 | When a change adds a new kind of entry (auxiliary, extra or special-purpose) to an ordered collection that existing consumers address by position or walk without knowing about the new kind: Require the new entries to come after all regular entries, enforced in the code that builds the coll |

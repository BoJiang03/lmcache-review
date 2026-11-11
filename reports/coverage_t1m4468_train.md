# Coverage of t1m4468 on train

- comments checked: 1517 of 1517; explained by some entry: 15 (1%)
- entries used at least once: 4 of 4; cost $4.45

| entry | kind | train PRs | held-out comments explained | rule |
| --- | --- | --- | --- | --- |
| m4468-002 | principle | 1 | 10 | When a PR bundles defensive fixes or behavior changes (new validation, newly raised errors, altered fallbacks) in components unrelated to its stated purpose: Ask the author to move the unrelated change into a separate PR, verified and tested on its own, or t |
| m4468-003 | principle | 1 | 2 | When a change adds a new kind of entry (auxiliary, extra or special-purpose) to an ordered collection that existing consumers address by position or walk without knowing about the new kind: Require the new entries to come after all regular entries, enforced in the code that builds the coll |
| m4468-001 | principle | 1 | 2 | When a change adds a new category or variant to a shared metadata or descriptor type by introducing a field (a boolean or any other single-case flag) that only distinguishes the one case the PR needs: Ask the author to replace the one-off flag with a generalized classification field, such as an enum  |
| m4468-004 | principle | 1 | 1 | When a change synthesizes groups, partitions or allocations for a set of items by creating one per item, while items can share the property (layout, geometry, configuration) that determines how a group behaves: Ask the author to key the grouping on that defining property and merge items that share it into one  |

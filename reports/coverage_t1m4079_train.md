# Coverage of t1m4079 on train

- comments checked: 1516 of 1517; explained by some entry: 23 (2%)
- entries used at least once: 1 of 1; cost $4.31

| entry | kind | train PRs | held-out comments explained | rule |
| --- | --- | --- | --- | --- |
| m4079-001 | principle | 1 | 23 | When A change adds or keeps logic in an orchestrating/driver module that builds, derives inputs for, or reads into the internals of a data structure owned by another module, such as a descriptor, plan or spec that the driver hands to another component. This includes exposing that structure's sub-builders or internal types as public functions, and changes where adding a field or parameter to the structure forces edits in the driver.: Ask the author to move the construction and derivation helpers into the module that owns the structu |

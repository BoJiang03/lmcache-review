# Coverage of t1m12to22 on test

- comments checked: 665 of 667; explained by some entry: 10 (2%)
- entries used at least once: 2 of 8; cost $2.17

| entry | kind | train PRs | held-out comments explained | rule |
| --- | --- | --- | --- | --- |
| m4836-x8 | principle | 1 | 6 | When An asynchronous request hands another process a handle to a locally owned resource, such as an exported IPC handle of a device event or buffer, and the local reference to that resource is kept somewhere a later submission can overwrite or free, such as a per-request or per-key slot.: Ask for the resource's lifetime to be tied to the submission's own completion object, so that the fu |
| m3869-x4 | principle | 1 | 4 | When A docstring describes what a function computes in terse set-algebra or shorthand phrasing that the reader has to decode, or the function acquires locks, pins or references that are released somewhere other than inside the function.: Ask for the docstring to state in plain words what the function computes and from which inputs. For  |

# Passive signals: reviewer v0

Samples: 10 · findings: 93. Signals only support a finding; absence means nothing.

| findings | n | changed later in PR | on merged PRs | changed after merge | later human comment at same place |
| --- | --- | --- | --- | --- | --- |
| all | 93 | 22 | 29 | 1 (0 fix-like) | 1 |
| AI-only | 86 | 18 | 27 | 1 (0 fix-like) | 1 |
| AI-only blocker | 3 | 3 | 0 | 0 (0 fix-like) | 1 |
| AI-only major | 13 | 2 | 4 | 0 (0 fix-like) | 0 |
| AI-only minor | 46 | 7 | 15 | 0 (0 fix-like) | 0 |
| AI-only nit | 24 | 6 | 8 | 1 (0 fix-like) | 0 |

## Severity check

AI severity of findings matched by a human change request: major 5, minor 1, blocker 1

## AI-only blocker/major with a signal

- #5255 [blocker] Late loads in a draining request become L1 objects that can never be evicted (default poli (judge: False): changed later in PR; later comments [4278604132]
- #5255 [major] Draining requests hold max_in_flight slots indefinitely; with a hung L2, every request the (judge: True): changed later in PR
- #5381 [blocker] Event completion is the wrong retention criterion; completed-but-not-yet-imported handles  (judge: True): changed later in PR
- #5381 [blocker] Diff does not match the described/validated change; test module breaks on import (judge: True): changed later in PR
- #5776 [major] Warning assertion is satisfied by the pre-existing abort-cleanup warning, not the new one (judge: True): changed later in PR

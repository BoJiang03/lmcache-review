# Passive signals: reviewer v0b-draft

Samples: 1 · findings: 10. Signals only support a finding; absence means nothing.

| findings | n | changed later in PR | on merged PRs | changed after merge | later human comment at same place |
| --- | --- | --- | --- | --- | --- |
| all | 10 | 1 | 10 | 3 (0 fix-like) | 0 |
| AI-only | 9 | 0 | 9 | 3 (0 fix-like) | 0 |
| AI-only blocker | 1 | 0 | 1 | 1 (0 fix-like) | 0 |
| AI-only major | 3 | 0 | 3 | 1 (0 fix-like) | 0 |
| AI-only minor | 3 | 0 | 3 | 0 (0 fix-like) | 0 |
| AI-only nit | 2 | 0 | 2 | 1 (0 fix-like) | 0 |

## Severity check

AI severity of findings matched by a human change request: major 1

## AI-only blocker/major with a signal

- #5685 [blocker] Dockerfile.payload extract stage now runs as lmcache and cannot mkdir /payload (judge: True): after merge: bf85b41f +12.5d "[CI] Stage the payload under /tmp so extraction works as non-root (#60"
- #5685 [major] In-repo CI scripts that build from docker/Dockerfile still mount HF cache under /root (judge: True): after merge: 5b9db86f +23.1d "[Refactor] Remove in-tree InProcess implementation (#6254)"

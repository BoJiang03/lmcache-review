# Regression check of pk2 against miss1-r9

- changed entries: P1, P2, P3, P4, m4639-001
- corrected tests to replay: 3 (2 runs each); est $10.1, cap $12.0

**REGRESSED** · cost $12.07

## Text check (layer 1)

- P1: ok
- P2: ok
- P3: ok
- P4: ok
- m4639-001: ok

## Replay of corrected tests (layer 2)

| entry | target | reviewer | runs | result |
| --- | --- | --- | --- | --- |
| P1 | 4805@0598604d | v0b+pk2@high | ✓ ✓ | pass |
| P1 | 3359@eeeb301f | v0b+pk2@high | ✓ ✓ | pass |
| P2 | 3697@99a66482 | v0b+pk2@high | ✗ ✗ | REGRESSED |

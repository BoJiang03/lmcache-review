# Regression check of pk5 (all tested entries)

- changed entries: P1, P2, P3, P4, m4042-001, m4079-001, m4723-001, m3485-001, team-v1-002, m3631-002, m4639-001, team-v1-001, m3631-001, team-v1-003, team-v1-005, m4736-001, m4736-002, team-v1-004, m3485-002, P5, P6, P7, m3231-001, m3231-005, m3231-006, m3231-002, m3231-004, m3231-003
- corrected tests to replay: 7 (1 runs each); est $9.2, cap $16.0

**REGRESSED** · cost $10.95

## Text check (layer 1)

- P1: ok
- P2: ok
- P3: ok
- P4: ok
- m4042-001: ok
- m4079-001: ok
- m4723-001: ok
- m3485-001: ok
- team-v1-002: ok
- m3631-002: ok
- m4639-001: ok
- team-v1-001: ok
- m3631-001: ok
- team-v1-003: ok
- team-v1-005: ok
- m4736-001: ok
- m4736-002: ok
- team-v1-004: ok
- m3485-002: ok
- P5: ok
- P6: ok
- P7: ok
- m3231-001: ok
- m3231-005: no longer explains [4474442514]
- m3231-006: ok
- m3231-002: ok
- m3231-004: ok
- m3231-003: ok

## Replay of corrected tests (layer 2)

| entry | target | reviewer | runs | result |
| --- | --- | --- | --- | --- |
| P1 | 4805@0598604d | v0b+pk5@high-rc | ✓ | pass |
| P1 | 3359@eeeb301f | v0b+pk5@high-rc | ✓ | pass |
| P2 | 3697@99a66482 | v0b+pk5@high-rc | ✓ | pass |
| m4042-001 | 4805@0598604d | v0b+pk5@high-rc | ✓ | pass |
| m4042-001 | 3359@eeeb301f | v0b+pk5@high-rc | ✓ | pass |
| m3631-002 | 3697@99a66482 | v0b+pk5@high-rc | ✓ | pass |
| m3231-005 | 5886@183c6aa7 | v0b+pk5@high-rc | ✓ | pass |

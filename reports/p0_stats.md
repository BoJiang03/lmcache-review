# P0 dataset stats

## PRs

| split | PRs | merged | with human review | human changes requested |
| --- | --- | --- | --- | --- |
| train | 1351 | 742 | 882 | 97 |
| test | 1096 | 485 | 585 | 33 |
| holdout | 142 | 52 | 65 | 1 |

PRs with merge commits (addressed label less reliable): 795
PRs with truncated connections: 21

## Human review comments (not by PR author)

| kind | train | test | holdout |
| --- | --- | --- | --- |
| inline | 1232 | 490 | 27 |
| review_body | 1725 | 757 | 60 |
| pr_comment | 878 | 452 | 37 |

Top inline reviewers: ApostaC 688, maobaolong 246, hlin99 190, KuntaiDu 96, DongDongJu 93, chunxiaozheng 78, sammshen 62, zhengfeihe 47, deng451e 38, ruizhang0101 36

## `addressed` label (human inline roots)

| addressed | count | share | thread outdated | thread resolved |
| --- | --- | --- | --- | --- |
| True | 1174 | 67% | 87% | 55% |
| False | 418 | 24% | 6% | 34% |
| None | 157 | 9% | 31% | 49% |

Reasons: lines-changed 1094, file-changed-elsewhere 186, file-unchanged 119, no-line 116, no-later-commits 113, file-deleted 80, side=LEFT 41

Agreement of `addressed` with GitHub `isOutdated`: 1413/1592 (89%)

## By area (human inline roots)

| area | comments | addressed |
| --- | --- | --- |
| mp | 403 | 70% |
| vllm-integration | 253 | 73% |
| distributed | 202 | 65% |
| docs | 158 | 72% |
| platform | 131 | 69% |
| tests | 123 | 53% |
| ci-build | 110 | 58% |
| core-other | 78 | 73% |
| kernels | 75 | 64% |
| gpu-connector | 53 | 60% |
| cli | 49 | 78% |
| storage | 33 | 48% |
| memory | 25 | 60% |
| operator | 17 | 65% |
| observability | 16 | 81% |
| examples | 15 | 60% |
| inprocess | 6 | 50% |
| other | 2 | 50% |

## Bot review comments (baseline material for P1)

| bot | comments | on PRs that also have human review |
| --- | --- | --- |
| gemini-code-assist | 2677 | 1888 |
| github-actions | 466 | 126 |
| copilot-pull-request-reviewer | 94 | 28 |
| cursor | 90 | 87 |
| chatgpt-codex-connector | 45 | 17 |
| github-advanced-security | 24 | 21 |
| dependabot | 7 | 2 |
| copilot-swe-agent | 1 | 1 |

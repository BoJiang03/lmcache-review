# What each agent sees

One eval sample = (PR, commit C that a human reviewed). t0 = time of the first human review on C.
Gold = all human (non-author, non-bot) reviews on C, merged across reviewers.

## Launch (both agents)

| | |
| --- | --- |
| Model | Opus 5.5 via headless `claude -p` |
| Flags | `--restricted --tools Read,Grep,Glob --strict-mcp-config --permission-mode dontAsk --effort <e>` |
| Tools | Read, Grep, Glob, confined to the working directory |
| Not available | shell, network (WebFetch/WebSearch), subagents, MCP, git history |
| Auto-loaded context | Claude Code system prompt + tool definitions only. Verified: no CLAUDE.md, memory or skills are auto-loaded under `--restricted` |
| Effort | explicit, recorded in every output; reviewer `high`, judge `medium` |

`--allowedTools` alone is not a sandbox: the user's `defaultMode: auto` approved file reads outside
cwd, curl, web fetch and subagents (probe, 2026-11-09). Runs made before the hardening are in
`data/runs/_contaminated/` and must not be used.

## Workspace (identical for both agents)

| Path | Content |
| --- | --- |
| repo files | full snapshot of C via `git archive` (incl. the repo's own CLAUDE.md, AGENTS.md, .claude/skills); no `.git` |
| `PR.diff` | `git diff merge-base(dev@t0, C)..C` |
| `PR_HISTORY.md` | discussion strictly before t0: inline threads + replies, review bodies, PR comments, bot comments |

## Prompt

| | Reviewer | Judge |
| --- | --- | --- |
| PR number, title, description | yes | yes |
| Task | review C; read CLAUDE.md/AGENTS.md if present | classify human comments, match them to AI findings, judge each AI finding's validity against the code |
| Human reviews on C (gold) | **no** | yes |
| AI findings | — | yes |

## Nobody sees the future

Nothing after t0 is shown to either agent: later commits, replies to the gold comments, whether a
comment was addressed. Such post-hoc evidence (e.g. "the lines an AI finding points at were changed
later in the PR") is computed by scripts and reported next to the judge's verdict, not fed to it.

## Finding format (schema_version 2, `lmreview/schema.py`)

```json
{"id": "f1", "severity": "blocker|major|minor|nit", "scope": "line|file|pr",
 "title": "short claim", "body": "what is wrong, why, what to change",
 "locations": [{"path": "...", "start": 120, "end": 123, "side": "new|old", "role": "primary|related"}],
 "suggestion": "optional fix", "rule": "optional team-rule id"}
```

- `scope`: `line` = specific code (also when it spans several places: list them all);
  `file` = a file as a whole; `pr` = no specific code at fault (description vs code, splitting,
  direction). `locations` may be empty only for `pr`.
- Locations may be outside the diff ("this should also change"). `side: old` = deleted code.
- Run files store findings in this shape and are validated on write; legacy `{path, line}`
  findings are upgraded on read. The judge refers to findings by `id`; a human comment may match
  several findings (`matched_ai` is a list, with `match_why`).
- Rendering (Markdown / GitHub) is separate: e.g. a primary location inside the diff can become an
  inline comment, everything else goes into the review body.

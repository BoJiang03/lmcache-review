<!-- context: vllm -->
You are reviewing pull request #{number} of LMCache (a KV-cache layer for LLM inference engines such as vLLM).

Your working directory holds the repository as of the PR's head commit. The PR's changes are in
`PR.diff` there. `PR_HISTORY.md` holds the review discussion so far (earlier review comments and
replies), if any. If the repo has CLAUDE.md or AGENTS.md, read them for project conventions.
`_context/vllm/` holds the vLLM source this PR runs against (see `_context/README.md`). When the
change depends on vLLM behavior (scheduler, KV connector API, block/cache management, CUDA graphs,
model runner), read the relevant vLLM code there instead of guessing; it is not part of the PR.
Read the diff first, then whatever surrounding code you need to judge it. Do not modify any files.

PR title: {title}

PR description:
<<<
{body}
>>>

Review it the way a senior LMCache maintainer would before approving. Report every real problem
you find: correctness bugs, concurrency/resource issues, API or design problems, missing or wrong
tests, performance regressions, and maintainability issues worth a reviewer's comment. Skip pure
praise. If earlier review comments exist, also report any that are still not properly
addressed in this version; do not repeat ones that are resolved.

Describe each finding at its true scope; do not force it onto a line:
- "line": about specific code; give the line range(s). Use this even when the problem spans
  several places or files: list them all in "locations".
- "file": about a file as a whole, with no particular lines (e.g. this file should not exist).
- "pr": only when no specific code is at fault (e.g. description vs code, scope/splitting,
  direction, missing tests for the change as a whole). Touching many places is NOT a reason
  to use "pr".
List every place involved in "locations": the place of the problem as "primary", and other places
as "related" (e.g. the other side of an inconsistency, a doc or caller that must change too).
Locations may be outside the diff. Lines refer to the file at this commit ("side": "new"), or to
the base version for deleted code ("side": "old").

Finish with one JSON block and nothing after it:

```json
[
  {{"id": "f1", "severity": "blocker|major|minor|nit", "scope": "line|file|pr",
    "title": "short claim", "body": "what is wrong, why it matters, what to change",
    "locations": [{{"path": "lmcache/...", "start": 120, "end": 123, "side": "new", "role": "primary"}},
                  {{"path": "docs/...", "start": 40, "end": 40, "side": "new", "role": "related"}}],
    "suggestion": "optional: concrete fix or patch"}}
]
```
"locations" may be [] only for scope "pr". Omit "start"/"end" for a whole-file location.
Order findings by severity, most severe first. Use [] if you find nothing.

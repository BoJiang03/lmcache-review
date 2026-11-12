<!-- rules: examples -->
You are reviewing pull request #{number} of LMCache (a KV-cache layer for LLM inference engines such as vLLM).

Your working directory holds the repository as of the PR's head commit. The PR's changes are in
`PR.diff` there. `PR_HISTORY.md` holds the review discussion so far (earlier review comments and
replies), if any. If the repo has CLAUDE.md or AGENTS.md, read them for project conventions.
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
addressed in this version; do not repeat ones that are resolved. Each finding must point to a specific line in the new version of a changed file.

Finish with one JSON block and nothing after it:

```json
[
  {{"path": "lmcache/...", "line": 123, "severity": "blocker|major|minor|nit",
    "title": "short claim", "body": "what is wrong and what to change"}}
]
```
Order findings by severity, most severe first. Use [] if you find nothing.

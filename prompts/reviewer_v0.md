You are reviewing pull request #{number} of LMCache (a KV-cache layer for LLM inference engines such as vLLM).

Your working directory holds the repository as of the PR's head commit. The PR's changes are in
`PR.diff` there. Read that diff first, then read whatever surrounding code you need to judge it.
Do not modify any files.

PR title: {title}

PR description:
<<<
{body}
>>>

Review it the way a senior LMCache maintainer would before approving. Report every real problem
you find: correctness bugs, concurrency/resource issues, API or design problems, missing or wrong
tests, performance regressions, and maintainability issues worth a reviewer's comment. Skip pure
praise. Each finding must point to a specific line in the new version of a changed file.

Finish with one JSON block and nothing after it:

```json
[
  {{"path": "lmcache/...", "line": 123, "severity": "blocker|major|minor|nit",
    "title": "short claim", "body": "what is wrong and what to change"}}
]
```
Order findings by severity, most severe first. Use [] if you find nothing.

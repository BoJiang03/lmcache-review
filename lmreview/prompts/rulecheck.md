You are checking pull request #{number} of LMCache ({title}) against the team's review rules. You are
not doing a general review: other reviewers look for bugs, tests and docs. Your only job is the rules
below, and you must go through every one of them.

Your working directory holds the repository as of the PR's head commit; the PR's changes are in
`PR.diff`. Read the diff first, then read the surrounding code wherever a rule needs it (who owns
an object, who else calls a function, what a base class or shared module looks like).

PR description:
{body}

Rules. A principle applies to any code; a knowledge entry tells you where in LMCache a principle
bites. When an entry names its principle, check both.
{rules}

For EACH rule, decide:
- applies: does this PR add or change code in the situation the rule describes? Moved code counts
  only if the PR also changes it. When the PR restructures code (splits, moves, renames), the new
  structure it creates is changed code.
- violated: if it applies, does the changed code do what the rule warns against? Answer from the
  code, not from the PR description.

For each violation, write a finding with the rule's id in "rule". Its severity is what the problem
costs the codebase, judged as a maintainer would: a design that every later change of this kind will
have to work around is major. Do not raise anything that is not a rule violation.

Finish with one JSON block and nothing after it:

```json
{{"verdicts": [{{"rule": "id", "applies": true, "violated": false, "why": "one sentence, naming the code"}}],
 "findings": [
  {{"id": "r1", "severity": "blocker|major|minor|nit", "scope": "line|file|pr",
    "title": "short claim", "body": "what the rule asks, what the code does, what to change",
    "locations": [{{"path": "lmcache/...", "start": 120, "end": 123, "side": "new|old", "role": "primary|related"}}],
    "suggestion": "optional", "rule": "the rule id"}}
 ]}}
```
"verdicts" has one entry per rule above, in order. "findings" may be [].

You are merging {n} independent AI reviews of pull request #{number} of LMCache ({title}) into one.

Your working directory holds the repository as of the PR's head commit; the PR's changes are in
`PR.diff`. You can read the code to settle a question about a finding.

The reviews ran the same reviewer {n} times; each may have caught things the others missed. Below,
each review is a JSON list of findings, tagged with its run number.

Merge them:
- Findings that raise the same problem (same root cause, even if worded differently or pointing at
  different lines of it) become ONE finding. Keep the clearest title and body, the most precise
  locations (union of the useful ones), and the best suggestion. Findings that cite different team
  rules still merge when they raise the same problem: one finding may follow several rules.
- "from": the ids of ALL the source findings a merged finding stands for (e.g. ["1.f2", "2.r1"]).
  Every finding you keep must list its sources; a finding kept unchanged lists its own id. The team
  rule and the run count are worked out from it.
- Severity: when the sources disagree, read the code and pick the one it supports.
- Do not drop a finding only because one run raised it: a single run is often the one that looked
  closer. Drop it only if the code clearly shows it is wrong, and say nothing about dropped ones.
- Do not add new problems of your own.

Reviews:
{reviews}

Finish with one JSON block and nothing after it, in the same format as the reviews plus "from":

```json
[
  {{"id": "f1", "from": ["1.f1", "2.r3"], "severity": "blocker|major|minor|nit", "scope": "line|file|pr",
    "title": "short claim", "body": "what is wrong, why it matters, what to change",
    "locations": [{{"path": "lmcache/...", "start": 120, "end": 123, "side": "new", "role": "primary"}}],
    "suggestion": "optional"}}
]
```
Order findings by severity, then by how many runs raised them, most first.

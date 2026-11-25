You are about to check pull request #{number} of LMCache ({title}) against the team's review rules.
The rulebook is long, so first pick the rules worth checking. The PR's diff, discussion and SYMBOLS
are in the system prompt; below, for each rule, is only the situation it is about ("when").
{shared}

Rules (id: when):
{rules}

Pick every rule whose situation this PR's added or changed code could be in. When unsure, pick it:
a rule left out is never checked, a rule picked costs one more look.

Finish with one JSON block and nothing after it:

```json
{{"picked": ["rule id", "..."]}}
```

---
name: lmreview
description: AI review of a GitHub pull request with lmreview, which reviews with the rules learned from that repository's own reviewers. Use when the user asks lmreview to review a PR (a github.com/<owner>/<repo>/pull/<n> link, or a PR number), e.g. "lmreview https://github.com/LMCache/LMCache/pull/5876", "lmreview 5876", "帮我 review 一下 5876".
---

# lmreview: AI review of a pull request

The plugin bundles the `lmreview` Python package (standard library only, no pip install).
The plugin root is two levels above this skill's base directory (`<base>/../..`); `${CLAUDE_PLUGIN_ROOT}` names the same folder when it is set.

## 1. Preflight (once per session)

Run, and stop with a clear message if any fails:

- `python3 --version` must be 3.10 or newer.
- `claude --version` (the review runs a headless Claude Code; it bills the user's own account).
- `gh auth status` (GitHub read access; lmreview only reads).
- `git --version`.

lmreview reviews each repository with its own rules. A bare PR number means the plugin's own repository
(LMCache/LMCache); a link names its repository. A repository other than that one must be set up once with
`python3 -m lmreview watch add <owner>/<repo>` (free: its clone, prompts and rulebook); if the review stops
with "has no lmreview state yet", tell the user and offer to run it. On first use lmreview clones the
repository (blobless; LMCache: about 20 s and 330 MB). Tell the user once.

## 2. Run the review

Take the PR from the user's request: pass a link as it is, or a number. Optional: a commit (`--commit <sha>`).

```bash
ROOT="${CLAUDE_PLUGIN_ROOT:-<base>/../..}"
PYTHONPATH="$ROOT" python3 -m lmreview review <PR number or link> --format json > <scratch>/lmreview-<n>.json
```

- A review takes 5–15 minutes and costs about $0.70 (median; more for large PRs). Run it in the background and tell the user it is running; do not poll.
- Use `--format md` instead of json if the user just wants the raw report.
- Do not pass `--reviewer` unless the user asks; the default is the current recommended reviewer.

## 3. Report

From the JSON output:

- Show **blocker** and **major** findings in full: location, the problem, the suggested fix.
- Fold **minor** and **nit** into a short list at the end (one line each). Never drop any.
- If the user wants, verify a finding against the code before they act on it: open the file at the commit reviewed and say whether the finding holds.

## 4. Never post on your own

`lmreview review` never writes to GitHub, and neither does this skill on its own initiative.
If the user wants comments on the PR, draft them, show the exact text and target lines, and post only after the user explicitly says to post (e.g. `gh pr review` / `gh api`). Approval to post one batch does not cover the next.

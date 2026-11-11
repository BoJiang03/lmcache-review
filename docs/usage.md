# Using lmreview

Two kinds of users:
- **Reviewers** run an AI first-round review of one PR on their own machine.
- **Operators** run the pre-launch pipeline that evaluates and improves the reviewer.

`lmreview` never posts to GitHub. Everything it produces stays local.

## Reviewers: review a PR

### Setup (once)

1. Install the `claude` CLI and log in. Reviews are billed to your own Claude account.
2. Install the `gh` CLI and run `gh auth login`. lmreview only reads from GitHub.
3. Install `git` and Python 3.10 or newer.
4. Install lmreview as a Claude Code plugin. In Claude Code, type:

```
/plugin install lmreview --marketplace BoJiang03/lmcache-review
```

Answer `y` to add the marketplace, then pick a scope (user is the default). Or just tell Claude Code
"安装这个 plugin: https://github.com/BoJiang03/lmcache-review" and it runs the same two steps
(`claude plugin marketplace add BoJiang03/lmcache-review` and `claude plugin install lmreview@lmcache-review`).
The plugin bundles the Python package (standard library only), so there is no pip step.
Update later with `claude plugin update lmreview@lmcache-review`.

Without the plugin, the CLI also works on its own: `pip install git+<this repo>`, or `bin/lmreview` from a checkout.

On first use, lmreview clones LMCache into `~/.cache/lmreview/`. It clones vLLM there too when the reviewer prompt needs it. The clones are blobless, take about 20 s and about 330 MB.

### Run

In Claude Code: "lmreview 5876" or "review LMCache PR 5876". The skill checks prerequisites, runs the review in the
background, shows blocker/major in full and folds minor/nit, and can verify a finding against the code.
It drafts PR comments only on request and posts nothing without your explicit OK.

From a shell:

```bash
lmreview review 5876                      # review the PR's current head
lmreview review 5876 --commit 1a2b3c4     # review a specific commit
lmreview review 5876 --format json > r.json
```

- A review takes 5–15 minutes and costs about $1–2 of Claude usage.
- **Output** is Markdown on stdout:
  - blocker and major findings are shown in full;
  - minor and nit findings are folded, never dropped;
  - each finding gives its location(s), any related places (which may be outside the diff), and a suggested fix.
- **What the AI sees:**
  - a snapshot of the PR's code;
  - the PR diff against its base;
  - the PR's discussion so far;
  - for some reviewer versions, the vLLM source.
- **What it cannot do:** run shell commands, access the network, or read anything outside that snapshot (see `docs/agent_context.md`).
- `--reviewer` selects a reviewer version. The default is the version that has been validated; you normally don't set it.

### Treat it as a first round

It reports everything it finds, so expect more findings than a human would write. Use blocker and major findings as things to check. Minor and nit findings are suggestions.

## Operators: the pre-launch pipeline

Design: `docs/mechanism.md`.

There are four commands. Reviewers are named `<prompt>[+<rulebook>][@<effort>][x<n>][-rc]`, e.g. `v0b+r2@high`.
`x<n>` runs n reviews in parallel and merges them. `-rc` adds a rule-check run next to the review: one more agent
that must give a verdict (applies, violated, why) on every applicable rule, merged with the review. It keeps a long
rulebook from crowding out specific rules (on #3697, m3631-002 fired 0/2 with pk2 and 2/2 with pk2 `-rc`); it
costs about $1–1.5 more per review.
Paid commands take `--max-cost`. They stop starting new LLM calls once they reach it, and `0` prints the plan only.

| Command | What it does |
| --- | --- |
| `lmreview sync` | Pull recently updated PRs and rebuild the samples (one per PR and human-reviewed commit). Splits: `train` / `test` / `new` (PRs since 2026-11-01). |
| `lmreview review --reviewer R --split S [--area A] [--limit N]` | Run R on samples. Runs are cached in `data/runs/R/`. |
| `lmreview eval --reviewer R [--vs R0]` | Judge R against the human reviews, then report: human-only rate per area, passive signals, and per-comment flips vs R0. Writes `reports/eval_R.md`. |
| `lmreview eval --rules NAME [--misses-of R]` | Check how many held-out human comments the rulebook explains. Cheap. Check this before any A/B run. |
| `lmreview distill OUT --misses-of R` | Build a new rulebook from R's misses on train. Writes `lmreview/rules/OUT.{jsonl,md}`. |

```bash
# daily: hidden runs on new PRs + monitoring (AI output is not shown to anyone)
lmreview sync
lmreview review --reviewer $CUR --split new --limit 0 --max-cost 20
lmreview eval --reviewer $CUR --max-cost 10

# one improvement round: learn from misses, check reuse, then A/B on test
scripts/misses_pipeline.sh vllm-integration 30 $CUR r2     # DRY=1 to see the plan
lmreview review --reviewer v0b+r2@high --split test --area vllm-integration --max-cost 15
lmreview eval --reviewer v0b+r2@high --vs $CUR             # net fixed > 0  ->  new default
```

### Promoting a new reviewer

Promote a reviewer only if it passes the rules in `docs/mechanism.md`: a net gain in per-comment flips on test, and the launch gate on `new`.

To promote it:
- set `DEFAULT_REVIEWER` in `lmreview/reviewer.py`, or `LMREVIEW_REVIEWER` on the deploy machine;
- commit the rulebook (`lmreview/rules/`).

The default rulebook is versioned: `team-v1`, `team-v2`, and so on. To update it, build the next
version from the current one (`lmreview distill team-v2 --base team-v1 ...`) and point the default at
it. Old versions stay, so their runs can be reproduced.

`review` and `eval` skip samples whose human comments are evidence for an entry of the reviewer's
rulebook, because that rule was written from the answer. Rules distilled from test comments therefore
remove those samples from that reviewer's test set.

### Rule lifecycle

```
human-only miss ──distill──> candidate ──A/B on a fair target──> corrected ──promotion gate──> team-vN
                  (add, or merge into an existing entry;          (tests field)
                   merged-away entries are retired, kept)
```

- **Candidate.** A new or changed entry. distill adds it, or merges it into the entry it generalizes.
  `lmreview eval --rules` (coverage) shows which other train comments it explains. A topic match is not
  enough: the rule's condition has to hold.
- **Fair target.** A PR the rule was not distilled from, whose diff *adds* code that meets the
  rule's condition. Moved code does not count. Run the same prompt with the rule and without it
  (the control). The control has to miss.
- **Record the result** with `lmreview.distill.record_test(book, rule, target, control, with_rule,
  result)`. `result` is one of: corrected, both-hit, both-miss, uncited-gain, regressed.
  `lmreview audit` shows corrected/run per entry, and flags active entries that have no corrected test.
- **Working books** (`miss1-r4`, `-r5`, ...) are versions too. Runs name them, so keep them. Only
  promote to `team-vN` through the gate above.

### Keeping rules valid through edits

A merge, generalization or rewrite can break a rule that worked. Users never see this happen, so
every rulebook change is checked before it can be promoted:

| Layer | When | Checks | Cost |
| --- | --- | --- | --- |
| 1. text | inside distill, on every rewrite; again in `regress` | The new text still explains the entry's evidence comments and its corrected test comments. If not, the rewrite is rejected. | ~$0.1 per entry |
| 2. replay | `lmreview regress NEW --base OLD [--suffix=-rc]` | Each corrected test of a changed entry is re-reviewed with NEW (`--reps 2`). Every tested comment must be matched by a finding that cites the entry, in at least one run. | ~$1.6 per run |
| 3. whole book | before promoting to `team-vN` | `lmreview eval` on test: fewer human-only misses and no rise in findings judged invalid. Catches dilution and over-firing that per-rule tests cannot see. | ~$30 |

Tests follow merges: the surviving entry inherits the tests of the entries it absorbed, so they are
replayed under its id. Replays are cached under `data/runs`, so rerunning `regress` costs nothing.
`regress` writes `reports/regress_<book>.md`, with the verdict PASS, REGRESSED or INCOMPLETE (stopped
by the cost cap).

The current default is `v0b+team-v1@high`. `team-v1` holds five rules, each distilled from one
review comment. They were added for out-of-the-box use before passing the promotion gate above.

Reviewers pick up the new version when they upgrade.

### Environment variables

| Variable | Default |
| --- | --- |
| `LMREVIEW_REPO` | the checkout's `data/LMCache`, else `~/.cache/lmreview/LMCache` |
| `LMREVIEW_VLLM` | the same pattern for `vllm` |
| `LMREVIEW_SANDBOX` | `~/.cache/lmreview/sandbox`. Must hold nothing the agent should not see. |
| `LMREVIEW_DATA` | the checkout's `data/`, else `~/.cache/lmreview/data` |
| `LMREVIEW_REVIEWER` | the validated default reviewer |

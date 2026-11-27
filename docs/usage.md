# Using lmreview

lmreview works on any GitHub repository; LMCache/LMCache and LMCache/LMCache_inprocess are the two that use
it today, and the examples below use them. Two kinds of users:
- **Reviewers** run an AI review of one PR on their own machine.
- **Operators** set a repository up, follow it (`lmreview watch`), and run the process that teaches the
  reviewer that repository's rules.

`lmreview review` posts nothing: its output stays local. Only `lmreview watch` with `--post` writes to
GitHub (a review on the PR, and with `--book-repo` the published rulebook).

## Reviewers: review a PR

### Setup (once)

1. Install the `claude` CLI and log in. Reviews are billed to your own Claude account.
2. Install the `gh` CLI and run `gh auth login`. `lmreview review` only reads from GitHub.
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

Each repository is reviewed with its own rules. This checkout's own repository is LMCache/LMCache (its rulebook is
`lmreview/state/`); any other is set up once with `lmreview watch add OWNER/NAME` (free), which creates its home
with its prompts and rulebook. On first use lmreview clones the repository (blobless; LMCache: about 20 s and
330 MB), and vLLM too when a prompt asks for it (the LMCache prompts do).

### Run

In Claude Code: "lmreview https://github.com/LMCache/LMCache/pull/5876" (or a PR number of this checkout's repository).
The skill checks prerequisites, runs the review in the
background, shows blocker/major in full and folds minor/nit, and can verify a finding against the code.
It drafts PR comments only on request and posts nothing without your explicit OK.

From a shell:

```bash
lmreview review https://github.com/OWNER/NAME/pull/123   # review the PR's current head
lmreview review 123 --repo OWNER/NAME                     # the same
lmreview review 5876 --commit 1a2b3c4                     # this checkout's repository, a specific commit
lmreview review 5876 --format json > r.json
```

- A review takes 5–15 minutes and costs about $0.70 of Claude usage (median; p90 $1.50), more for large PRs.
- **Output** is Markdown on stdout:
  - blocker and major findings are shown in full;
  - minor and nit findings are folded, never dropped;
  - each finding gives its location(s), any related places (which may be outside the diff), and a suggested fix.
- **What the AI sees:**
  - a snapshot of the PR's code;
  - the PR diff against its base;
  - the PR's discussion so far;
  - extra context a prompt declares (the LMCache prompts: the vLLM source the PR runs against).
- **What it cannot do:** run shell commands, access the network, or read anything outside that snapshot (see `docs/agent_context.md`).
- `--reviewer` selects a reviewer version. The default is the version that has been validated; you normally don't set it.

### Treat it as a first round

It reports everything it finds, so expect more findings than a human would write. Use blocker and major findings as things to check. Minor and nit findings are suggestions.

## Operators

Design: `docs/mechanism.md`.

### Set a repository up and follow it

```bash
lmreview watch add OWNER/NAME                 # its home: clone, prompts, rulebook v0001, settings (free)
lmreview watch run OWNER/NAME --once --dry-run   # what a cycle would review and learn (free)
lmreview watch set OWNER/NAME --post --review-since now --book-repo YOU/PUBLIC_REPO
lmreview watch start                          # every 10 minutes, in the background; `watch status`, `watch stop`
```

- **Prompts.** A repository of the LMCache organization gets the LMCache prompts (`lmreview/prompts/`); any
  other gets the generic ones (`lmreview/prompts/generic/`), rendered into `<home>/prompts/` with its name
  and GitHub description. Edit them there for the project's conventions (`--prompts DIR` brings your own).
- **Rulebook.** Starts empty, or from another repository's book (`--book`; the LMCache prompts start from
  LMCache's). It is the repository's own from then on and numbered from v0001. The comments behind copied
  rules are kept in `<home>/state/sources.json`, so a review can still link a rule to where it was learned.
- **Settings.** `<home>/config.toml` on top of `lmreview/config.toml`: `[project]` (name, description, source
  file types), `[dataset]` (main branch, the date from which PRs are collected and learned from).
- **Posting.** A GitHub review per PR head: a summary and an inline comment per finding, each saying whether it
  rests on a team rule or is general review. `watch retract OWNER/NAME PR` takes one back (GitHub cannot delete
  a submitted review); `watch repost` posts a saved one again in the current format.

### The learning process

### The process and its state

Per repository: one prompt, one book in use, versions of it, and a ledger of the human comments. Everything
that changes is in its state directory: `lmreview/state/` (in git) for this checkout's repository,
`<home>/state/` for a watched one (see `lmreview/state.py`):

| What | Where | Changed by |
| --- | --- | --- |
| reviewer prompts (main review, rule check, rule pick: one prompt id) | `lmreview/prompts/reviewer.md`, `rulecheck.md`, `rulepick.md` | people (git) |
| settings: review, judge, distill, vet, retain, compress, cost caps, paths | `lmreview/config.toml` (override: `LMREVIEW_CONFIG`) | people (git) |
| book in use / every version | `state/HEAD.json`, `state/book.jsonl` / `state/history/vNNNN.jsonl` (+ `.meta.json`) | `vet`, `rollback`, `init` |
| candidate waiting for vet | `state/candidate/` | `distill`, `compress` |
| one row per human comment point (`<id>`, or `<id>:<k>` when a comment makes several) | `state/ledger.jsonl` | `judge`, `distill`, `vet`, `retain` |
| comment annotations: points, type, severity (cache, once per sample) | `data/annotations/a1/` | `judge` |
| every prompt used, by id | `state/prompts/p<sha8>.*` | automatic |
| what happened | `state/log.jsonl` | every step |
| runs, scores (cache) | `data/runs/<reviewer>/`, `data/scores/...` | `review`, `judge` |

A sample is one PR commit a human reviewed (`#3776@33b257aa`); its human comments are the ground
truth. The ledger files each change-request / nit comment of a judged sample:

```
review ─> judge ─┬─> covered        (the reviewer found it)
                 └─> to_distill ─distill─> candidate ─vet─┬─> resolved     (an entry makes the reviewer find it)
                       ▲     │                            └─> failed attempt ─┐
                       │     └─> not_rulable (context / not an issue / declined)
                       └──────── tries < max_tries ───────────────────────────┤
                                          tries = max_tries ─> needs_human

Severity tiers (`[tiers]`, from the point's annotation): major+ / minor / nit get 3 / 2 / 1 distill attempts.
retain counts a major+ or minor point learned when every run catches it, a nit when one does; a missed point
goes back to distill 2 / 1 / 0 times, then a major+ one goes to a person and a minor / nit one stays
learned, marked `unretained`. vet does not fail a change for losing a nit point (`vet_tolerate`); the
row is marked `unretained` instead. After a compress passes vet, retain re-checks every retained point behind an entry it
merged, retired or rewrote (vet only samples a few of them, once). `lmreview status` and retain report by tier.
```

### Reviewer names

`<prompt>[+<book>][@<effort>][-rc|-ro]`, e.g. `pdba46ca9+v0032@medium-rc`. The prompt id hashes the
three prompt files and the rule-check settings (`[review] rulecheck_effort`, `rulecheck_stage_words`);
the default is the current prompt with the book in use (`lmreview status`).

- `-rc`: the main review plus a rule check, one more agent that gives a verdict (applies, violated, why)
  on every applicable rule. The rule check has no tools: it reads the diff and discussion in its prompt.
  Past `rulecheck_stage_words`, one call first picks the rules worth checking from their "when" lines.
  The findings of both are listed side by side. This is the production reviewer.
- `-ro`: the rule check alone. vet and retain replay with it.

The reviewer sees each rule's id, kind, when, expect and why, never its `examples`.

### Commands

Paid commands take `--max-cost` (`round` takes one per step; the defaults in `[budget]` are $1000, i.e. no
cap in effect). They stop starting new LLM calls once they reach it, and `0` prints the plan only.

| Command | What it does |
| --- | --- |
| `lmreview sync [--since T]` | Pull recently updated PRs and rebuild the samples (one per PR and human-reviewed commit). Free. |
| `lmreview round PR[:commit] ...` | review, judge, confirm new misses with a second run, then distill + vet (with every comment still to_distill from earlier rounds, on any PR) until the comments settle; retain after judge and vet; compress + vet when the book is over `[compress]` words. A bare PR number means its commits with a missed comment. |
| `lmreview judge [--prs N ...]` | Judge the current reviewer's runs and file the comments in the ledger. |
| `lmreview distill [--prs N ...] [--limit N] [--compress]` | `to_distill` comments to a candidate book: attribute, write, consolidate. |
| `lmreview vet [--reps N] [--all]` | Replay where the candidate differs from the book in use; promote what works as the next version, record what failed. `--all` replays every base entry. |
| `lmreview retain [--prs N ...] [--samples PR:c ...] [--reps N] [--covered] [--reviewer R]` | Re-run the rule check on the samples of covered / resolved points; a point not caught often enough for its tier goes back to `to_distill` (see severity tiers). |
| `lmreview compress [--stage trim\|merge] [--repair]` | Make the book in use smaller as a candidate; `vet` keeps what loses no proven case. |
| `lmreview status` | Book in use, candidate, ledger counts. |
| `lmreview init BOOK.jsonl [--note T]` | Start the state from a rulebook file as v0001 (an empty file: no entries). |
| `lmreview rollback vN` / `discard` | Make vN the book in use again as a new version / drop the candidate. |

- `vet` promotes what works and drops or reverts the rest. A failed comment keeps its attempt (book,
  entries, why), and the next `distill` is told to write it differently. Its report goes to
  `reports/vet_<book>.md`.
- A sample is solved when all its comments are resolved.

### Shipping a new version

The default reviewer moves when `vet` promotes a version. For this checkout's repository, commit
`lmreview/state/` to ship it: reviewers pick it up when they upgrade. A watched repository uses its new
version from the next review on; with `--book-repo` the version is published before the first review that
cites it. `LMREVIEW_REVIEWER` overrides the reviewer on a machine.

### Environment variables

| Variable | Default |
| --- | --- |
| `LMREVIEW_GH_REPO` | the repository reviewed and learned from (`OWNER/NAME`); default LMCache/LMCache |
| `LMREVIEW_REPO` | its clone: the checkout's `data/LMCache`, else `~/.cache/lmreview/LMCache` |
| `LMREVIEW_VLLM` | the same pattern for `vllm` |
| `LMREVIEW_SANDBOX` | `~/.cache/lmreview/sandbox`. Must hold nothing the agent should not see. |
| `LMREVIEW_DATA` | the checkout's `data/`, else `~/.cache/lmreview/data` |
| `LMREVIEW_REVIEWER` | the validated default reviewer |
| `LMREVIEW_STATE` | the state directory (book, ledger, history); default `lmreview/state/` |
| `LMREVIEW_CONFIG` | a settings file merged on top of `lmreview/config.toml` |
| `LMREVIEW_PROMPTS` | the prompts directory; default `lmreview/prompts/` |
| `LMREVIEW_WATCH` | where `watch` keeps the homes; default `~/.cache/lmreview/watch/` |

`lmreview watch` sets the first seven for each repository it follows, pointing at its home.

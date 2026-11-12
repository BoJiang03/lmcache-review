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

### The process and its state

One prompt, one book in use, versions of it, and a ledger of the human comments. Everything that
changes is in `lmreview/state/` (in git; see `lmreview/state.py`):

| What | Where | Changed by |
| --- | --- | --- |
| reviewer prompt, effort, rule check on/off | `lmreview/prompts/reviewer.md`, `lmreview/reviewer.json` | people (git) |
| book in use / every version | `state/HEAD.json`, `state/book.jsonl` / `state/history/vNNNN.jsonl` (+ `.meta.json`) | `vet`, `rollback` |
| candidate waiting for vet | `state/candidate/` | `distill` |
| one row per human comment | `state/ledger.jsonl` | `judge`, `distill`, `vet` |
| every prompt used, by hash | `state/prompts/p<sha8>.md` | automatic |
| what happened | `state/log.jsonl` | every step |
| runs, scores (cache) | `data/runs/p<sha8>+vNNNN@high-rc/`, `data/scores/...` | `review`, `judge` |

A sample is one PR commit a human reviewed (`#3776@33b257aa`); its human comments are the ground
truth. The ledger files each change-request / nit comment of a judged sample:

```
review ─> judge ─┬─> covered        (the reviewer found it)
                 └─> to_distill ─distill─> candidate ─vet─┬─> resolved     (an entry makes the reviewer find it)
                       ▲     │                            └─> failed attempt ─┐
                       │     └─> not_rulable (context / not an issue / declined)
                       └──────────── tries < 2 ───────────────────────────────┤
                                                       tries = 2 ─> needs_human
```

- `lmreview round PR[:commit] ...` runs review, judge, then distill + vet until the comments settle.
  The steps also run one by one: `review --split train --only-pr ...`, `judge`, `distill`, `vet`.
- `vet` promotes what works as the next version and drops or reverts the rest. A failed comment keeps
  its attempt (book, entries, why), and the next `distill` is told to write it differently.
- A sample is solved when all its comments are resolved. `lmreview status` prints the counts.
- `rollback vN` makes vN the book in use again as a new version; `discard` drops the candidate.
- The rows from before the ledger (v0001 = pk9) are marked legacy.

The commands below with explicit book names (`distill OUT --base`, `vet BOOK --base`, `regress`) are
the lower-level tools the process uses; use them for experiments, not for the book in use.

There are four commands. Reviewers are named `<prompt>[+<rulebook>][@<effort>][x<n>][-rc]`, e.g. `v0b+r2@high`.

The reviewer sees each rule's id, kind, when, expect and why, never its `examples`. Examples carry the
source PR's particulars (names, values): too specific for the reviewer, and on the source PR they leak
the answer. They stay in the book for people and for distill. The older prompts (v0, v0b, v0c, v0d,
v0t) still show the first example (`<!-- rules: examples -->`), so their cached runs stay valid; v0e and
v0f are v0b and v0c without it.
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

The default reviewer is the current prompt with the book in use (`lmreview status`). It moves
when `vet` promotes a version; commit `lmreview/state/` to ship it. `LMREVIEW_REVIEWER` overrides it
on a machine.

`review` and `eval` skip samples whose human comments are evidence for an entry of the reviewer's
rulebook, because that rule was written from the answer. Rules distilled from test comments therefore
remove those samples from that reviewer's test set.

### Rule lifecycle

```
human-only misses ─┐
failure signals ───┴─distill──> NEW book ──vet NEW --base OLD --write NEXT──> NEXT (the passing part)
 (findings citing   1 judge the runs of OLD    1 generality flags (free)
  an entry, judged  2 attribute                2 effect: source PRs, OLD vs NEW
  invalid)          3 cluster with OLD entries 2b revisions: their trigger is fixed
                    4 abstract (3 drafts)      3 side effects: affected OLD entries' sources
                    5 update: add | evidence | parent principle | revise | retire
                    6 induce (--induce only): standalone entries under principles
                    every new entry needs a comment of its own, else it is dropped
                                              ...later: fair-target A/B, whole-book eval -> team-vN
```

- **review → distill → vet.** review produces runs; distill learns from them; vet decides what to keep.
- **distill** (`lmreview distill OUT --base OLD --misses-of v0f+OLD@high-rc --prs N ...`) does not
  review. First run `lmreview review` with the OLD book on the train PRs to learn from, so the misses
  are OLD's own. distill then:
  - Step 1 judges those runs against the human comments (cached; vet reuses runs and scores). The
    missed comments are what to learn. Findings citing an OLD entry that were judged invalid are its
    failure signals.
  - Additions are the normal case: a new entry, evidence on an existing one, or a parent principle
    above existing entries, which stay as written and are linked by `principle`/`members`.
  - An existing entry is rewritten (`revise`: version + 1, old text in `history`) or `retire`d only
    with evidence that it is wrong: a failure signal (a finding that cited it, judged invalid,
    collected from every judged run on disk) or a human comment asking for the opposite. A revision
    must still explain the entry's evidence and corrected tests. A signal is considered once
    (`signals_seen`).
- **vet** (`lmreview vet NEW --base OLD [--write NEXT] [--prompt v0f] [--max-cost N] [--all]`;
  `--max-cost 0` prints the plan and the generality flags for free). It reviews with
  `<prompt>+<book>@high-rc`:
  - **effect**: each comment new to the book is re-reviewed (one sample per PR) with OLD and NEW. An
    entry works if NEW matches one of its comments with a finding citing it. This leaks (the rule was
    written from that comment), so it shows the reviewer applies the rule, not that it generalizes.
    An existing entry that gained evidence from another PR, and that OLD already cited there, is a
    fair hit.
  - **revisions**: the samples whose invalid findings triggered a revision are re-reviewed; a finding
    citing the entry judged invalid again means it is not fixed.
  - **side effects**: OLD entries whose links, text or neighbours changed, and retired ones (`--all`:
    every entry), are replayed on their own source comments. Caught with a citation under OLD but not
    under NEW (for a retired entry: not caught at all) = regression.
  - A failing case gets one more run before it counts (`--no-retry` to skip). Runs are cached under
    `data/runs/<reviewer>/`, shared with any A/B that used the same names.
  - The verdict is PASS, FAIL or INCOMPLETE (cost cap), written to `reports/vet_<book>.md`.
    `--write NEXT` saves NEW without what failed:
    - entries that never worked are dropped;
    - lost or unfixed entries go back to their OLD version;
    - new entries linked to a lost one are dropped.

- **Learn from the current book's runs.** Misses go stale as the working book grows: pk7 `-rc`
  already caught 3 of the 15 #12–#22 misses that team-v1 had, and pk8 5 of the 24 #23–#27 ones.
- **Candidate.** A new or changed entry. distill adds it, or merges it into the entry it generalizes.
  `lmreview eval --rules` (coverage) shows which other train comments it explains. A topic match is not
  enough: the rule's condition has to hold.
- **Fair target.** A PR the rule was not distilled from, whose diff *adds* code that meets the
  rule's condition. Moved code does not count. Run the same prompt with the rule and without it
  (the control). The control has to miss.
- **Record the result** with `lmreview.distill.record_test(book, rule, target, control, with_rule,
  result)`. `result` is one of: corrected, both-hit, both-miss, uncited-gain, regressed.
  `lmreview audit` shows corrected/run per entry, and flags active entries that have no corrected test.
- **Principles.** distill tends to split one reviewer habit into several one-off rules. Steps 5 and
  6 group them under principles with an operational check and keep the specific rules verbatim as
  members linked by `principle`. P5 fired on a new PR only after this. Since 2026-11-12, step 6 is off
  by default (`--induce`), and any new entry whose evidence all comes from its members is dropped:
  such a parent explains no comment its members don't. In v0001 the induced P1–P7 had matched 3 human
  comments in 34 findings (all rules: 12 in 116), and they made most of vet's side-effect replays. (`scripts/induce_principles.py`
  is the older whole-book, rewriting version.)
- **Working books** (`miss1-r4`, `-r5`, ..., `pk1`–`pk8`) are versions too. Runs name them, so keep
  them. Only promote to `team-vN` through the gate above. The latest is `pk9` (principles plus knowledge), meant to be run with `-rc`. It has not passed the whole-book gate yet.

### Keeping rules valid through edits

A merge, generalization or rewrite can break a rule that worked. Users never see this happen, so
every rulebook change is checked before it can be promoted:

| Layer | When | Checks | Cost |
| --- | --- | --- | --- |
| 1. text | inside distill, on every revision; again in `regress` | The new text still explains the entry's evidence comments and its corrected test comments. If not, the rewrite is rejected. | ~$0.1 per entry |
| 2. replay | `lmreview regress NEW --base OLD [--suffix=-rc]` | Each corrected test of a changed entry is re-reviewed with NEW (`--reps 2`). Every tested comment must be matched by a finding that cites the entry, in at least one run. | ~$1.6 per run |
| 3. whole book | before promoting to `team-vN` | `lmreview eval` on test: fewer human-only misses and no rise in findings judged invalid. Catches dilution and over-firing that per-rule tests cannot see. | ~$380 (292 samples) |

Tests follow merges: the surviving entry inherits the tests of the entries it absorbed, so they are
replayed under its id. Replays are cached under `data/runs`, so rerunning `regress` costs nothing.
`regress` writes `reports/regress_<book>.md`, with the verdict PASS, REGRESSED or INCOMPLETE (stopped
by the cost cap).

The current default is `v0e+team-v1@high`. `team-v1` holds five rules, each distilled from one
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

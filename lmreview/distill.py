"""`lmreview distill`: turn what a reviewer missed into rulebook changes; also the compress steps (trim, merge).

distill neither reviews nor judges: it learns from judged review runs (the ledger's to_distill points;
`lmreview judge` judges runs). Findings citing a base entry that were refuted are its failure signals. Comments whose file never changed again although
the PR got later commits are dropped.
  1. attribute (batches, no tools): learnable | context | not_issue | rejected (declined in the
     thread) | contested; for a learnable one, what the reviewer asked the author to do (a
     description, not a rule)
  2. write (one step, n drafts merged): with the whole rulebook, the failure signals and every
     learnable finding (the reviewer's words and code), decide per finding: evidence | generalize |
     merge | add | revise / retire (only on failure signals, an opposite finding, or a retry) |
     contradict | skip. A finding whose entry already exists and still missed it is marked RETRY.
  3. update the book; a revision must still explain the entry's evidence and corrected tests
  4. consolidate the whole book (n drafts in parallel, voted in code, then one call writes the agreed
     entries): absorb or merge entries that ask for the same change, rewrite new entries at the wrong
     level, flag contradictions. Last, every change to an existing entry's text (from this step or
     from step 2) is verified by blind parallel calls: it must act differently on the case that
     motivated it, or (a merge) act exactly as the entries it replaces; a rephrasing or an unasked-for
     difference is undone. vet then replays every source of a merged entry
Output: the candidate book (state/candidate/book.jsonl, .md readable), <data>/distill/<out>/{attribution,changes}.json.
Whether the result is kept is `lmreview vet`'s call (vet.py).
Never reads test/new samples.
"""

from __future__ import annotations

import collections as C
import datetime as dt
import functools
import json
import re
import pathlib
import subprocess
import tempfile
from collections.abc import Callable

from . import llm
from .budget import capped_map
from .config import Config
from .schema import cites as finding_rules
from .annotate import cid_of, norm
from .settings import get
from .state import book_path
from .ensemble import ensemble
from .progress import note
from .score import load_gold, refuted

BATCH = 30          # comments per attribution / coverage call
WRITE_BATCH = 25    # findings per write call (each call sees the whole rulebook)
EST = {"attribute": 0.17, "write": 0.6, "consolidate": 0.6}  # $/call; estimates only

ATTRIBUTE = """You are distilling the review standards of the LMCache team (a KV-cache layer for LLM
inference engines such as vLLM) from past human review comments.

For each comment below (with its code hunk, what happened to the code afterwards, and the discussion
after it: every reply with who wrote it, and whether the thread was resolved and by whom), decide:
- "learnable": it follows from a standard, a recurring concern, or knowledge of this codebase or the
  engine that a reviewer could apply to FUTURE pull requests. In "asks", say in at most 40 words what
  the reviewer asked the author to do and why, as the reviewer put it (with the principle if they
  stated one). Describe this comment; do not write a rule: rules are written later, from all the
  findings and the whole rulebook together. When the team took only part of the comment (the author
  adopted one ask and argued down another, and no reviewer insisted on it), it is "learnable" and
  "asks" covers only the part that was taken. A comment is "learnable" only if its motivation is clear:
  the comment or its thread states it (what is wrong with the code as written, what it would cause, or
  the standard it breaks), or the hunk and the suggestion together make it evident, so that you can
  name the kind of problem the change fixes (e.g. a hand-written loop next to "use itertools.groupby":
  re-implementing the standard library). Then put that reason in "asks", marked "(inferred)". That the
  author made the change supports this but is not enough alone. When neither the thread nor the code
  shows a reason (a bare preference, a question), it is "not_issue".
  Judge the whole thread: a comment that opens with a question is "learnable" when a later reply
  (the author's explanation, or the reviewer's follow-up) turns it into such an ask. Marking an ask
  "nit" does not make it "not_issue". An author who agrees with the point but defers the change (adds a
  TODO, promises a follow-up, says "not now") accepts the standard: that is "learnable", not
  "rejected" or "contested".
- "context": it needs knowledge outside the code (an offline decision, roadmap, where code should live
  across projects, another PR's state). Decide this before "contested": an author's reply does not make
  a roadmap question a code standard.
- "not_issue": a question, praise, or nothing actionable; also an ask whose motivation the thread does
  not state and the code does not make evident (a bare preference, or a question the thread never
  answers with a problem in the code).
- "rejected": the team took no part of the suggestion: the reviewer (or another reviewer) withdrew it,
  agreed with the author's objection, or resolved the thread with the code left as it was; or the
  file never changed again and nothing in the discussion shows the change was made in other files.
  Also "rejected": the author showed the ask is wrong with a checkable fact (a tool, formatter, spec or
  CI requirement the change would break), and no reviewer disputed it.
- "contested": only the PR author objected on the merits (a design or preference argument, not a
  checkable fact), or resolved the thread without the change, and no reviewer agreed. Whether the team
  stands by the suggestion is unknown; do not decide it.

Comments:
{comments}

Answer with one JSON block only:
```json
[{{"id": 123, "kind": "learnable|context|not_issue|rejected|contested", "asks": "<learnable only>",
   "why": "<=20 words, for every kind but learnable"}}]
```"""

CONSOLIDATE_DRAFTS = int(get("distill", "consolidate_drafts"))  # parallel consolidate drafts, voted
MIN_SIGNAL_PRS = int(get("distill", "min_signal_prs"))  # revise/retire on failure signals alone: they must come from this many PRs

# How general an entry must be; shared by WRITE, MERGE_WRITE and INDUCE (no braces: it goes through str.format).
GENERAL = """How general "when" and "expect" must be:
- "when" names a KIND of situation a reviewer can recognize in any diff (e.g. "a docstring explains in
  prose a process the reader has to simulate in their head"), not the mechanisms, identifiers or
  parameters of the PRs it came from (e.g. not "appending/relocating block ids, nulling slots").
- "expect" names the ACTIONS to ask the author for (bound a temporary, state a precondition, redo the
  whole handshake, add a worked example), as the source comments did. Keep the action checkable
  against a diff; do not soften it into a vague goal ("be careful with memory" is useless). But the
  source PRs' particulars (numbers, identifiers, parameters, orderings, e.g. "128K tokens", "chunk
  size") do not belong in "expect" either: use the general term ("a long request", "every
  negotiated parameter") and put the particulars in "examples".
- Level: read what the reviewer said (quoted under each finding). When the reviewer states the
  principle behind the ask (e.g. "there are two paths for X; use only one", "this is a vendor
  specialization inside the generic layer"), write "when" and "expect" at the level of that stated
  principle, even if the summary of the ask is narrower. The mechanism the PR happened to use (an inline type
  check, an event stream, a snapshot getter) goes to "examples", never into "when" as a condition.
- Length: "when" and "expect" together in at most about 80 words. Sub-cases, mechanisms and instances
  go to "examples" (at most 2). Go longer only when an entry marked RETRY shows the shorter text did
  not make the reviewer raise the point.
- Self-check before answering: for each noun, number or mechanism in "when" and "expect", ask whether
  it still holds for another PR of the same kind. If not, replace it with the general term and move
  the particular to "examples".
- Counterfactual check: imagine two other PRs that break the same principle by a DIFFERENT mechanism
  (e.g. a whole module instead of an inline branch; a polling loop instead of a snapshot API). The
  entry must apply to both word for word; rewrite it until it does. But do not lift it above what the
  reviewer said: no entry so broad that it fits any change ("keep the design clean").
- "paths" limits where the reviewer is shown the entry at all. A "principle" gets [] (anywhere) unless
  the principle itself only makes sense in that code; that the source comments sat in some directory
  is not a reason (a "keep the shared layer feature-agnostic" rule from connector comments applies to
  the server too). A "knowledge" entry is scoped to the code its fact is about."""

WRITE = """You are updating the LMCache review rulebook: the entries an AI reviewer is given when it reviews a
pull request of LMCache (a KV-cache layer for LLM inference engines such as vLLM). Writing the entries
is the step everything depends on: an entry is useful only if an AI reviewer reading a diff will raise
the human's point because of it, on the PR it came from AND on other PRs of the same kind, without
raising points the team would not ask for.

Below are (1) the rulebook as it stands; (2) failure signals: findings of the AI reviewer that cited an
entry and were judged invalid; (3) review findings by human reviewers that the AI reviewer missed, each
with what the reviewer said, the code it was on, and what they asked the author to do.

Decide how the rulebook changes. Every finding key ("c...") and every signal key ("s...") appears in
exactly one decision; several findings that ask for the same change go into ONE decision (one entry
with all of them as evidence). Findings that share a topic but ask for different or opposite changes
are separate decisions (e.g. "shorten docstrings to the contract" and "explain tricky state changes in
a docstring with a worked example" are two entries, though both are about docstrings).
- "evidence": the findings are already instances of an existing entry AS WRITTEN: a reviewer applying
  it to their change would have raised their point. The entry's text stays.
- "generalize": the findings ask for the same kind of change as an existing entry, but its "when" or
  "expect" is too narrow to make a reviewer raise their point. Write the broader entry at the lowest
  level that covers the existing entry AND the findings. It REPLACES the existing entry (which is
  retired), so it must still make a reviewer raise everything the existing entry asked for.
- "add": the findings ask for a different change than every existing entry; write a new entry. Before
  choosing it, find the existing entry closest to the findings ("closest": its id) and say in
  "why_new" (one line) why neither "evidence" nor "generalize" of that entry can make a reviewer raise
  their point. An add without that reason is wrong: generalize instead.
- "revise": an existing entry's text is WRONG as shown by failure signals or by findings that ask for
  the opposite, or it is the entry a finding marked RETRY was written from and it still did not make
  the reviewer raise the point. Rewrite it so it would not have produced those findings (or agrees with
  the reviewers, or now makes the reviewer raise the retried point), while still covering everything
  its examples asked for. List the keys that show it is wrong in "members", and say in "changed" (one
  line) what the new text covers or asks for differently. A rewrite that only rephrases is not a revise.
- "retire": the existing entry is wrong and no rewrite fixes it, or another entry already covers it
  completely ("replaced_by": that id). Same evidence requirement as "revise".
- A failure signal shows the entry's record (citing findings judged valid vs refuted). An entry whose
  citations were mostly valid is revised to stop the wrong findings, not retired; retire one whose
  citations were mostly refuted.
- "contradict": findings ask for the opposite of an existing entry, but it is unclear who is right. Do
  not rewrite it; say why.
- "skip": a finding carries no principle or knowledge a reviewer could apply to other PRs; say why.
- "keep": a failure signal that came from the reviewer misapplying a correct entry (the signal is
  recorded as considered).
This step places each finding in the rulebook; a smaller rulebook that explains the same comments
generalizes better: prefer "evidence", then "generalize", over "add". Do not merge existing entries
with each other: that is a later step. Every replacement is checked later against all the comments the
replaced entries came from; one that loses any of them is undone. "revise" and "retire" need failure
signals from at least @MINPRS@ different PRs, or a finding in "members" (opposite, or RETRY of that entry).

How to write an entry (generalize, merge, add, revise):
- "kind": "principle" (a review principle at the level a reviewer would apply it to other changes) or
  "knowledge" (a fact or invariant about this codebase or the engine, and what a reviewer must
  therefore check when touching that code; scope it with "paths").
- Read the reviewer's own words, not only the summary of what they asked: the reviewer may state the
  principle behind the ask, and the entry belongs at that level.
- Keep what the reviewer asked the author to DO (e.g. "explain multi-step state changes in a docstring
  with a worked example of values before/after", not just "docstrings should be clear").
- A finding marked RETRY already has an entry that did not work: write it so that a reviewer reading
  that diff would recognize the situation (usually the "when" names the situation too abstractly or
  too narrowly), not a paraphrase of the same text. When its earlier attempts quote what the rule
  check said of the entry on that diff, fix exactly that reason: if it judged the entry not to apply,
  the "when" missed the situation; if it applied but judged nothing violated, the "expect" lacks the
  distinction the reviewer drew. Attaching it again as "evidence" of the same unchanged text will fail
  the same way.
- A finding whose earlier attempt says a broader entry was dropped because a replaced entry lost a proven
  case: generalize again, and make the new entry cover that case too (name the situation in "when", put
  it among the "examples"). Adding a narrow entry beside the old one is the fallback only when no single
  entry can ask for both.

""" + GENERAL + """

Fields of a written entry: "kind", "when" (the kind of change it applies to), "expect" (what to check
or require; checkable), "why" (one line), "examples" (1-2 short concrete instances), "paths" (globs,
[] = anywhere).

Rulebook:
@BOOK@

Failure signals:
@SIGNALS@

Findings the AI reviewer missed:
@FINDINGS@

Answer with one JSON block only, one object per decision:
```json
[{"op": "evidence|generalize|add|revise|retire|contradict|skip|keep", "rules": ["<existing id>"],
  "members": ["c123", "s1"], "concern": "short name", "kind": "...", "when": "...", "expect": "...",
  "why": "...", "examples": ["..."], "paths": [], "changed": "<revise only>", "replaced_by": "<id, retire only>",
  "closest": "<id, add only>", "why_new": "<add only>"}]
```"""

# Merge step of an ensemble of WRITE runs: the level of abstraction varies from run to run.
MERGE_WRITE = """Several independent drafts were written of how the LMCache review rulebook changes for the findings
below. They differ by chance, mostly in how general the written entries are and in which findings
they put together. Write the ONE final set of decisions:
- For each finding take the decision most drafts agree on (which existing entry it belongs to, or
  that it needs a new one); put findings together only where most drafts did. Keep an "add" only if
  its "why_new" holds against the "closest" entry; otherwise generalize that entry.
- For a written entry, its level is the one the reviewer's own words support: read the quotes. Prefer
  the draft whose "when" covers every mechanism by which a PR could break that stated principle; take
  the most precise "expect" and the best examples from any draft. Do not go above what the reviewer said.
- Skip a finding only if most drafts skipped it. Every finding and signal key appears in exactly one
  decision.

""" + GENERAL + """

Rulebook:
@BOOK@

Failure signals:
@SIGNALS@

Findings the AI reviewer missed:
@FINDINGS@

Drafts:
@DRAFTS@

Answer with one JSON block only, in the same format as the drafts."""


COVERAGE = """Below is a rulebook of LMCache review rules (id: when -> expect), then human review comments
from pull requests. For each comment, list the ids of the rules it is an INSTANCE of: a reviewer
applying that rule to this change would have raised the same point. Be strict: sharing a topic is
not enough. [] if none.

Rules:
{rules}

Comments:
{comments}

Answer with one JSON block only:
```json
[{{"id": 123, "rules": ["r1-004"]}}]
```"""


MODEL: str | None = None  # the model of distill / trim / compress calls; None = Claude Code's default


def _ask(prompt: str, effort: str, cfg: Config) -> tuple[object, float]:
    """One tool-less LLM call in an empty directory; returns (parsed JSON, cost)."""
    cfg.sandbox.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cfg.sandbox) as d:
        r = llm.run(prompt, effort, cwd=d, tools="", model=MODEL)
    return llm.extract_json(r["text"]), r["cost"]


def _id(x: object) -> object:
    """Comment ids come back from the model as ints or strings."""
    return norm(x) if isinstance(x, (int, str)) else x


def _resolve(x: object, keys: "set | dict") -> object:
    """The key in `keys` an attribution's id names. A point of a split comment has the id
    "<comment>:<k>", which the model sometimes returns as the bare comment id: that resolves to the
    point when the comment has exactly one point among `keys`."""
    x = _id(x)
    if x in keys:
        return x
    hits = [k for k in keys if str(k).split(":")[0] == str(x)]
    return hits[0] if len(hits) == 1 else x


OUTCOME = {"lines-changed": "the commented lines were changed afterwards",
           "file-deleted": "the file was deleted afterwards",
           "file-changed-elsewhere": "the file changed afterwards, but not at these lines",
           "no-later-commits": "no later commits in the PR",
           "file-unchanged": "the PR got later commits, but this file never changed again (taken only if "
                             "the change was made in other files: see the discussion)"}


REPLY_CHARS = 1500  # per reply; a longer one keeps its end (where the conclusion usually is)


@functools.lru_cache(maxsize=256)
def _raw_pr(pr: int) -> dict:
    p = Config().data / "raw" / "pr" / f"{pr}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _who(login: str | None, pr_author: str | None, reviewer: str | None) -> str:
    role = "PR author" if login == pr_author else "the reviewer" if login == reviewer else "another reviewer"
    return f"{login} ({role})"


def _cut(t: str) -> str:
    t = " ".join((t or "").split())
    return t if len(t) <= REPLY_CHARS else "..." + t[-REPLY_CHARS:]


def _discussion(c: dict) -> str:
    """What happened after comment `c`, from the raw PR: an inline comment's whole thread (every reply
    with who wrote it, whether the thread was resolved and by whom); for an overall review, the PR's
    conversation comments after it (not necessarily answers to it)."""
    raw = _raw_pr(int(c["pr"]))
    if not raw:
        return ""
    pr_author = (raw.get("author") or {}).get("login")
    cid = c.get("comment", c["id"])  # a point of a comment: its comment's thread
    if c["kind"] == "inline":
        t = next((t for t in raw.get("reviewThreads", {}).get("nodes") or []
                  if (t["comments"]["nodes"] or [{}])[0].get("databaseId") == cid), None)
        if t is None:
            return ""
        reps = t["comments"]["nodes"][1:]
        lines = [f"reply by {_who((r.get('author') or {}).get('login'), pr_author, c['author'])}: {_cut(r.get('body'))}"
                 for r in reps]
        state = ("resolved by " + _who((t.get("resolvedBy") or {}).get("login"), pr_author, c["author"])
                 if t.get("isResolved") else "not resolved")
        return "\n".join(lines + [f"thread: {len(reps)} replies, {state}"])
    later = [x for x in (raw.get("comments") or {}).get("nodes") or [] if (x.get("createdAt") or "") > (c.get("created") or "")][:5]
    return "\n".join(f"later PR conversation, by {_who((x.get('author') or {}).get('login'), pr_author, c['author'])}: "
                     f"{_cut(x.get('body'))}" for x in later)


def _fmt(c: dict, rich: bool = True) -> str:
    """One comment for a prompt: location, hunk, body; with `rich`, outcome and the discussion after it."""
    if c["kind"] == "inline":
        s = (f"[{c['id']}] {c['path']}:{c['line_lo']} (PR #{c['pr']}, by {c['author']})\n"
             f"hunk:\n{(c['diff_hunk'] or '')[-600:]}\ncomment: {c['body'][:1000]}")
    else:
        s = f"[{c['id']}] overall review of PR #{c['pr']} by {c['author']}:\n{c['body'][:1500]}"
    if rich:
        if c.get("addressed_reason") in OUTCOME:
            s += f"\nafterwards: {OUTCOME[c['addressed_reason']]}"
        d = _discussion(c)
        s += f"\n{d}" if d else ""
    return s


def _entry(r: dict) -> dict:
    """The fields of a rulebook entry the model writes."""
    return {k: r.get(k) for k in ("kind", "when", "expect", "why", "examples", "paths")}


def _uniq(xs: list) -> list:
    return list(dict.fromkeys(xs))


def _regress(rule: dict, old_ev: list[int], cm: dict, effort: str, cfg: Config, spend: list[float]) -> list[int]:
    """Old evidence comments the rewritten `rule` no longer explains (one coverage call; all of them if
    the call fails, so an unverified rewrite is rejected)."""
    cs = [cm[e] for e in old_ev if e in cm]
    if not cs:
        return []
    text = f"{rule['id']}: when {rule.get('when')} -> {rule.get('expect')}"
    try:
        res, cost = _ask(COVERAGE.format(rules=text, comments="\n\n".join(_fmt(c, False) for c in cs)), effort, cfg)
    except (RuntimeError, ValueError) as e:  # unverified: treat as losing everything, so the rewrite is rejected
        print(f"  regression check of {rule['id']} failed: {e}", flush=True)
        return [c["id"] for c in cs]
    spend[0] += cost
    ok = {_id(x.get("id")) for x in res if isinstance(x, dict) and rule["id"] in (x.get("rules") or [])} \
        if isinstance(res, list) else set()
    return [c["id"] for c in cs if c["id"] not in ok]


def _show_entry(r: dict) -> str:
    """An existing entry for the WRITE prompt."""
    return (f"- {r['id']} (v{r.get('version', 1)}, {r.get('kind')}): When {r.get('when')}: {r.get('expect')}"
            f" | examples: {'; '.join(r.get('examples') or [])} | paths {r.get('paths') or []}"
            f" | evidence: {len(r.get('evidence') or [])} comments")


def update_rulebook(base_rules: list[dict], items: dict, evid: dict, out: str, cm: dict,
                    effort: str, cfg: Config, spend: list[float], max_cost: float,
                    workers: int = 4, n: int = 3, signals: dict | None = None,
                    retry: dict | None = None, notes: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Apply the missed findings and the failure signals to a rulebook, in one WRITE step.

    `items`: key -> text: "c<id>" a finding (what the reviewer asked), "s<n>" a failure signal of an
    existing entry (`signals` maps it to its record); `evid`: key -> its comment ids. The model sees
    the whole active rulebook, the signals and the findings (with the reviewer's words and code) and
    decides: evidence | generalize | add | revise | retire | contradict | skip | keep. It runs
    `n` times and MERGE_WRITE merges the drafts (the level of abstraction varies from run to run).
    Findings go in batches of WRITE_BATCH, each with the whole rulebook; the signals go with the
    first batch. `retry`: finding key -> ids of the entries already written from its comment (they
    did not make the reviewer raise it); `notes`: finding key -> what earlier attempts made of it.

    Existing entries change only on evidence that they are wrong: "revise" (rewrite, version + 1, the
    old text kept in "history") and "retire" are accepted only when the decision names failure
    signals from MIN_SIGNAL_PRS PRs or a finding (opposite, or a retry). A revision must still
    explain the entry's old evidence and corrected tests. Generalize adds a replacement that retires
    what it replaces. Merging existing entries is consolidate()'s job. `lmreview vet` then checks every kind of change on the source PRs.

    Returns:
        (the whole rulebook: base entries, changed or not, then new ones; the list of changes)
    """
    today = dt.date.today().isoformat()
    base = {f"b{r['id']}": {**r, "version": r.get("version", 1), "history": list(r.get("history") or [])}
            for r in base_rules}
    added, changes = [], []
    book = "\n".join(_show_entry(r) for r in base.values() if r.get("status", "active") == "active") or "(empty)"

    def finding(k: str) -> str:
        said = "\n".join("    " + _fmt(cm[e], rich=False).replace("\n", "\n    ") for e in evid.get(k, []) if e in cm)
        rt = (retry or {}).get(k)
        return (f"- {k}: asks: {items[k]}"
                + (f"\n  RETRY: entry {', '.join(rt)} was written from this comment, and the reviewer given it still "
                   "missed the point" if rt else "")
                + (f"\n  earlier attempts: {(notes or {})[k]}" if (notes or {}).get(k) else "")
                + f"\n  what the reviewer said:\n{said}")

    skeys = [k for k in items if k.startswith("s")]
    ckeys = [k for k in items if k.startswith("c")]
    batches = [ckeys[i:i + WRITE_BATCH] for i in range(0, len(ckeys), WRITE_BATCH)] or ([[]] if skeys else [])

    def case(k: str) -> str:
        """A key of a decision as a case for verify_changes: a finding with the reviewer's words, or a signal."""
        if k.startswith("s"):
            return items[k]
        said = " / ".join(" ".join(cm[e]["body"].split())[:400] for e in evid.get(k, []) if e in cm)
        return f"missed finding: the reviewer asked: {items[k]} | reviewer said: {said}"

    def fill(t: str, i: int, b: list[str]) -> str:
        sig = "\n".join(f"- {k}: {items[k]}" for k in skeys) if i == 0 and skeys else "(none)"
        return (t.replace("@MINPRS@", str(MIN_SIGNAL_PRS)).replace("@BOOK@", book).replace("@SIGNALS@", sig)
                .replace("@FINDINGS@", "\n\n".join(map(finding, b)) or "(none)"))

    def write(job: tuple[int, list[str]]) -> tuple[object, float]:
        i, b = job

        def merge(ok: list) -> tuple[object, float]:
            drafts = "\n\n".join(f"Draft {j}:\n{json.dumps(d, indent=1)}" for j, (d, _) in enumerate(ok, 1))
            return _ask(fill(MERGE_WRITE, i, b).replace("@DRAFTS@", drafts), effort, cfg)
        e = ensemble(lambda: _ask(fill(WRITE, i, b), effort, cfg), n, merge, ok=lambda r: isinstance(r[0], list),
                     warm=True)
        return e.result[0], sum(c for _, c in e.runs) + (e.merge[1] if e.merge else 0.0)

    res, cost = capped_map(write, list(enumerate(batches)), workers, max(0.0, max_cost - spend[0]),
                           label=lambda j: f"write {len(j[1])} findings")
    spend[0] += cost
    waiting: set[str] = set()  # signals of a refused revise/retire: kept open for a later distill
    replaced: set[str] = set()  # base keys a generalize / merge replaces
    for d in (x for part in res if isinstance(part, list) for x in part):
        if not isinstance(d, dict):
            continue
        g, op = {"concern": str(d.get("concern") or "")}, d.get("op")
        mem = [k for k in d.get("members") or [] if k in items]
        bkeys = [f"b{x}" for x in d.get("rules") or [] if f"b{x}" in base]
        ev = _uniq(e for k in mem for e in evid.get(k, []))
        ch = {"op": op, "rules": [base[b]["id"] for b in bkeys], "members": mem, "concern": g["concern"]}
        if op == "evidence" and bkeys:
            base[bkeys[0]]["evidence"] = _uniq(list(base[bkeys[0]].get("evidence") or []) + ev)
        elif op in ("generalize", "merge") and bkeys and d.get("expect"):
            bkeys = [b for b in bkeys if base[b].get("status", "active") == "active" and b not in replaced]
            olds = [base[b] for b in bkeys]
            if not olds or (op == "merge" and len(olds) < 2):
                continue
            if op == "merge" and _size(d) >= sum(map(_size, olds)):
                ch |= {"op": "merge-refused", "why": f"not shorter ({_size(d)} words vs {sum(map(_size, olds))})"}
                changes.append(ch)
                continue
            # a replacement: the old entries are retired once it has an id; their members move under it
            kids = _uniq([m for r in olds for m in r.get("members") or [] if m not in {o["id"] for o in olds}])
            rep = _entry(d) | {"kind": d.get("kind") or "principle", "replaces": [r["id"] for r in olds],
                               "cases": [case(k) for k in mem],
                               "tests": [{**t, "from": r["id"]} for r in olds for t in r.get("tests") or []]}
            if kids:
                rep["members"] = kids
            added.append((rep, _uniq([e for r in olds for e in r.get("evidence") or []] + ev), g["concern"]))
            replaced |= set(bkeys)
            ch |= {"op": f"{op}-replace", "words": [sum(map(_size, olds)), _size(d)]}
        elif op in ("revise", "retire") and bkeys:
            sig = [k for k in d.get("members") or [] if k in items and k.startswith("s")
                   and (signals or {}).get(k, {}).get("rule") == base[bkeys[0]]["id"]]
            sig_prs = {(signals or {})[k]["target"].split("@")[0] for k in sig}
            if not mem and len(sig_prs) < MIN_SIGNAL_PRS:
                # one PR's invalid finding is weak evidence (and the judge may be wrong): wait for more.
                # These signals stay open, so they count again when another PR shows the same problem.
                ch |= {"op": f"{op}-refused", "why": f"failure signals on {len(sig_prs)} PR(s), need {MIN_SIGNAL_PRS}, "
                       "or a finding"}
                waiting |= set(sig)
                changes.append(ch)
                continue
            r = base[bkeys[0]]
            why = {"signals": [(signals or {})[k] for k in sig], "comments": ev, "why": d.get("why"),
                   "cases": [case(k) for k in d.get("members") or [] if k in items],
                   "retry": any(base[bkeys[0]]["id"] in (retry or {}).get(k, []) for k in mem)}
            if op == "retire":
                r["status"] = "retired"
                r["retired"] = {"date": today, "by": out, "replaced_by": d.get("replaced_by"), **why}
                ch |= {"why": d.get("why"), "replaced_by": d.get("replaced_by")}
            elif not d.get("expect"):
                continue
            elif not (d.get("changed") or "").strip():
                # no stated change of what the entry covers or asks: a rephrasing, which costs the entry
                # its failure signals and a re-vet and fixes nothing
                ch |= {"op": "revise-refused", "why": "no 'changed' given"}
            elif spend[0] >= max_cost:  # no budget left to verify the rewrite: keep the entry as it is
                ch |= {"op": "revise-skipped", "why": "cost cap reached before the text check"}
            else:
                old_ev = list(r.get("evidence") or [])
                tested = _uniq(c for t in r.get("tests") or [] if t["result"] == "corrected" for c in t.get("comments") or [])
                lost = _regress({"id": r["id"], **_entry(d)}, _uniq(old_ev + tested), cm, effort, cfg, spend)
                if lost:  # the rewrite would stop explaining what the entry stood for
                    ch |= {"op": "revise-rejected", "lost": lost}
                else:
                    r["history"].append({"version": r["version"], "until": today, "by": out, "reason": "revise",
                                         **{k: r.get(k) for k in ("when", "expect", "examples", "paths")}})
                    r.update({k: v for k, v in _entry(d).items() if v is not None})
                    r["version"] += 1
                    r["evidence"] = _uniq(old_ev + ev)
                    r["revised"] = {"date": today, "by": out, **why}  # vet re-checks these cases
                    ch |= {"version": r["version"], "when": r["when"], "expect": r["expect"], "changed": d["changed"]}
        elif op == "add" and d.get("expect") and mem:
            ch |= {k: d[k] for k in ("closest", "why_new") if d.get(k)}  # why no existing entry fits
            added.append((_entry(d) | {"kind": d.get("kind") or "principle"}, ev, g["concern"]))
        elif op == "skip" and mem:
            ch["why"] = d.get("why")
        elif op == "contradict" and bkeys:
            base[bkeys[0]]["contested"] = _uniq(list(base[bkeys[0]].get("contested") or []) + ev)
            ch["why"] = d.get("why")
        else:
            continue
        changes.append(ch)

    for k, x in (signals or {}).items():  # considered once: later distills do not reopen them
        b = base.get(f"b{x['rule']}")
        if b is not None and k not in waiting and k in items:
            b["signals_seen"] = list(b.get("signals_seen") or []) + [[x["reviewer"], x["target"], x["finding"]]]

    def finish(r: dict) -> dict:
        ev = [e for e in r.get("evidence") or [] if e in cm]
        return r | {"n_prs": len({cm[e]["pr"] for e in ev}),
                    "area": ",".join(sorted({cm[e].get("area") or "overall" for e in ev}))}
    new = [finish({**e, "concern": concern, "evidence": ev, "status": "active", "version": 1, "history": []})
           for e, ev, concern in added]
    new.sort(key=lambda r: -r["n_prs"])
    used, i = {r["id"] for r in base.values()}, 0
    for r in new:  # never reuse an id of the base (e.g. out == base, or out names an ancestor)
        i += 1
        while f"{out}-{i:03d}" in used:
            i += 1
        r["id"] = f"{out}-{i:03d}"
    by_id = {r["id"]: r for r in base.values()}
    for r in new:  # replacements retire what they replace (vet undoes it if a source comment is lost)
        for o in r.get("replaces") or []:
            by_id[o]["status"] = "retired"
            by_id[o]["retired"] = {"date": today, "by": out, "replaced_by": r["id"], "why": "replaced"}
            by_id[o].pop("members", None)
    for r in new:  # link members to their principle (a member of a replaced entry moves to its replacement)
        for m in r.get("members") or []:
            if m in by_id and (not by_id[m].get("principle")
                               or by_id.get(by_id[m]["principle"], {}).get("status") == "retired"):
                by_id[m]["principle"] = r["id"]
    for ch in changes:  # name new entries in the change log
        if ch["op"] in ("add",) or ch["op"].endswith("-replace"):
            ch["new"] = [r["id"] for r in new if set(r["evidence"]) & {e for k in ch["members"] for e in evid.get(k, [])}]
    return [finish(r) for r in base.values()] + new, changes


CONSOLIDATE = """Below is the whole LMCache review rulebook after this round's updates: the entries an AI reviewer
is given when it reviews a pull request of LMCache (a KV-cache layer for LLM inference engines such
as vLLM). Entries marked NEW were written this round. Each entry shows what the human reviewers said
in the comments it was learned from.

Tidy the rulebook where this round touched it: the NEW entries against the whole book. A rulebook with
overlapping, uneven or redundant entries costs on every review and every later check, and its
entries fire less reliably. Every merge or absorb includes at least one NEW entry; merging existing
entries with each other is left to the periodic whole-book compress. Changes:
- "merge": two or more entries ask for the same kind of change in the same kind of situation, though
  their wording, area or level differ. Write ONE entry that replaces them all: it must make a reviewer
  raise everything each of them asked for (read their reviewers' words), at the lowest level that
  covers them all, and be shorter than they are together. Entries that share a topic but ask for
  different or opposite changes are NOT merged (e.g. "shorten docstrings to the contract" and
  "explain tricky state changes in a docstring with a worked example").
- "rewrite": a NEW entry whose level is wrong: it names one PR's particulars in "when" or "expect",
  or it is so broad that it fits any change. Write it at the level its reviewers' words support.
  Existing (not NEW) entries change only by merge.
- "absorb": one of the entries ("into") already makes a reviewer raise everything the others ask
  for, AS WRITTEN. It stays word for word; the others are retired in its favor. Prefer this to a merge
  whenever it holds: rewording an entry that already works is not tidying.
- "contradict": two entries ask for opposite changes in the same situation. Do not change them; say why.
List only changes; everything else stays as it is. Do not merge just to make the book smaller: every
merge is checked later on all the comments the merged entries came from, and one that loses any of
them is undone.

""" + GENERAL + """

Fields of a written entry (merge, rewrite): "kind" (principle | knowledge), "when", "expect", "why"
(one line), "examples" (1-2 short concrete instances), "paths" (globs, [] = anywhere).

Rulebook:
@BOOK@

Answer with one JSON block only, one object per change ([] if none):
```json
[{"op": "merge|absorb|rewrite|contradict", "rules": ["<id>", "<id>"], "into": "<absorb only>", "reason": "one line", "kind": "...",
  "when": "...", "expect": "...", "why": "...", "examples": ["..."], "paths": []}]
```"""

# Final text of the changes most CONSOLIDATE drafts agreed on (which entries, voted in code).
FINAL_CONSOLIDATE = """Several independent drafts proposed how to tidy the LMCache review rulebook below. The changes
listed under "Agreed changes" are the ones most drafts agreed on (which entries to merge, which NEW
entry to rewrite). For each agreed change write the ONE final entry, using the drafts' versions:
- Its level is the one the reviewers' own words support (shown under each entry). Prefer the draft
  whose "when" covers every mechanism by which a PR could break the stated principle; take the most
  precise "expect" and the best examples from any draft. Do not go above what the reviewers said.
- A merged entry must make a reviewer raise everything each merged entry asked for, and be shorter
  than they are together.

""" + GENERAL + """

Rulebook:
@BOOK@

Agreed changes, with the drafts' versions:
@CHANGES@

Answer with one JSON block only, one object per agreed change:
```json
[{"change": 0, "kind": "...", "when": "...", "expect": "...", "why": "...", "examples": ["..."], "paths": []}]
```"""


def _book_with_quotes(rules: list[dict], new_ids: set[str], cm: dict, quotes: int = 3) -> str:
    """The active entries for CONSOLIDATE: text, then up to `quotes` reviewer comments it came from."""
    out = []
    for r in rules:
        if r.get("status", "active") != "active":
            continue
        tag = "NEW" if r["id"] in new_ids else f"v{r.get('version', 1)}"
        said = [f"    PR #{cm[e]['pr']} {cm[e]['author']}: {' '.join(cm[e]['body'].split())[:300]}"
                for e in (r.get("evidence") or [])[:quotes] if e in cm]
        more = len(r.get("evidence") or []) - len(said)
        out.append(f"- {r['id']} ({tag}, {r.get('kind')}): When {r.get('when')}: {r.get('expect')}\n"
                   f"  examples: {'; '.join(r.get('examples') or [])} | paths {r.get('paths') or []}\n"
                   f"  reviewers said:\n" + "\n".join(said) + (f"\n    (+{more} more comments)" if more > 0 else ""))
    return "\n".join(out)


def _components(edges: set[tuple[str, str]]) -> list[list[str]]:
    """Connected components of an undirected graph given by its edges (sorted, for stable output)."""
    adj: dict[str, set[str]] = C.defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    seen, out = set(), []
    for x in sorted(adj):
        if x in seen:
            continue
        comp, todo = [], [x]
        while todo:
            y = todo.pop()
            if y not in seen:
                seen.add(y)
                comp.append(y)
                todo += adj[y] - seen
        out.append(sorted(comp))
    return out


def consolidate(rules: list[dict], base_rules: list[dict], out: str, cm: dict, effort: str, cfg: Config,
                spend: list[float], max_cost: float, n: int = 3) -> tuple[list[dict], list[dict]]:
    """Tidy the rulebook where this round touched it: merge NEW entries with entries that ask for the same change,
    rewrite NEW entries at the wrong level, flag contradictions; then verify_changes() checks every
    change made to the text of existing entries in this distill (this step's and the write step's).

    `n` CONSOLIDATE drafts run in parallel and are voted on in code: two entries are merged when most
    drafts put them in one merge (merges are the connected components of those pairs); a NEW entry is
    rewritten, and a contradiction flagged, when most drafts say so. One FINAL_CONSOLIDATE call then
    writes the agreed entries from the drafts' versions. A merge replaces its entries: existing ones
    are retired ("replaced_by"; vet replays all their sources and undoes a merge that loses one), NEW
    ones are removed and their evidence moves to the replacement. A merge that is not shorter than
    what it replaces is refused.

    Two entries are absorbed when most drafts put them together and most of those say "absorb" into
    the same entry: no new text is written.

    Returns:
        (the rulebook, change records "consolidate-*" and "verify-*").
    """
    rules, changes = _consolidate(rules, {r["id"] for r in base_rules}, out, cm, effort, cfg, spend, max_cost, n,
                                  incremental=True)
    rules, more = verify_changes(rules, base_rules, out, effort, cfg, spend, max_cost, n)
    base_ids = {r["id"] for r in base_rules}
    return [r for r in rules if r["id"] in base_ids or r.get("status", "active") == "active"], changes + more


def _consolidate(rules: list[dict], base_ids: set[str], out: str, cm: dict, effort: str, cfg: Config,
                 spend: list[float], max_cost: float, n: int, prompt: str = "", book: str = "",
                 absorb_ok: Callable[[str, list[str]], bool] | None = None, blocked: set[frozenset] = frozenset(),
                 shrink: float = 1.0, final_prompt: str = "", incremental: bool = False,
                 union: bool = False, detail: Callable[[list[str]], str] | None = None,
                 forced: list[list[str]] | None = None) -> tuple[list[dict], list[dict]]:
    """The proposing part of consolidate(): drafts, votes, final texts, applied. compress() passes its own
    `prompt` and `book` text, `final_prompt` for the final texts, `shrink` (a merge must have under that share
    of the words it replaces), `absorb_ok(into, others)` (which absorbs may happen) and `blocked` groups
    (merges vet undid twice: not proposed again). `incremental` (consolidate in distill): a merge or absorb
    must include a NEW entry; pairs of existing entries are left to compress. `union` (compress): no vote,
    every draft's merge counts (vet is the only gate); overlapping groups are resolved by taking the group
    most drafts proposed, then the larger one, and skipping groups that share an entry with a taken one.
    `detail(group)`: text shown under each agreed change in the final call (compress: the group's entries
    with their proven comments in full and the budget). `forced`: no drafts; these groups go straight to
    the final call (compress's repair of the groups vet undid)."""
    act = {r["id"]: r for r in rules if r.get("status", "active") == "active"}
    new_ids = {i for i in act if i not in base_ids}
    if len(act) < 2 or spend[0] >= max_cost:
        return rules, []
    book = book or _book_with_quotes(rules, new_ids, cm)
    prompt = prompt or CONSOLIDATE

    def once(_: int) -> tuple[object, float]:
        return _ask(prompt.replace("@BOOK@", book), effort, cfg)
    if forced:
        res = [[{"op": "regroup", "rules": g} for g in forced]]
    else:
        res, cost = capped_map(once, list(range(n)), n, max(0.0, max_cost - spend[0]),
                               label=lambda _: "consolidate draft", warm=True)
        spend[0] += cost
    drafts = [[d for d in r if isinstance(d, dict)] for r in res if isinstance(r, list)]
    if not drafts:
        return rules, []
    need = 1 if union else len(drafts) // 2 + 1
    pair, rew, con, into = C.Counter(), C.Counter(), C.Counter(), C.Counter()
    for dr in drafts:
        mp, rw, ct = set(), set(), set()
        for d in dr:
            ids = sorted({x for x in d.get("rules") or [] if x in act})
            if d.get("op") in ("merge", "absorb") and len(ids) >= 2:
                mp |= {(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]
                       if not incremental or a in new_ids or b in new_ids}
                if d.get("op") == "absorb" and d.get("into") in ids:
                    into[(tuple(ids), d["into"])] += 1
            elif d.get("op") == "rewrite" and len(ids) == 1 and ids[0] in new_ids:
                rw.add(ids[0])
            elif d.get("op") == "contradict" and len(ids) == 2:
                ct.add(tuple(ids))
        pair.update(mp)
        rew.update(rw)
        con.update(ct)
    if union:
        proposed = C.Counter(frozenset(x for x in d.get("rules") or [] if x in act) for dr in drafts for d in dr
                             if d.get("op") in ("merge", "absorb", "regroup"))
        single = {frozenset(x for x in d.get("rules") or [] if x in act) for dr in drafts for d in dr
                  if d.get("op") == "regroup"}  # a regroup may rewrite one entry (1 -> 1, shorter)
        groups, used = [], set()
        for g, _ in sorted(proposed.items(), key=lambda kv: (-kv[1], -len(kv[0]), sorted(kv[0]))):
            if (len(g) >= 2 or g in single) and g and not g & used:
                groups.append(sorted(g))
                used |= g
    else:
        groups = _components({p for p, v in pair.items() if v >= need})
    changes: list[dict] = []
    for g in [g for g in groups if frozenset(g) in blocked]:
        changes.append({"op": "consolidate-blocked", "rules": g, "members": [], "concern": "",
                        "why": "vet undid this group twice"})
    groups = [g for g in groups if frozenset(g) not in blocked]
    absorbed = []
    for g in groups:  # absorb: most drafts say one entry already covers the group: no new text
        votes = C.Counter({t: v for (ids, t), v in into.items() if set(ids) == set(g)})
        # union: an absorb needs most of the drafts that proposed this group, else it is merged (regroup)
        need_a = (proposed[frozenset(g)] // 2 + 1) if union else need
        if votes and votes.most_common(1)[0][1] >= need_a:
            t = votes.most_common(1)[0][0]
            if absorb_ok and not absorb_ok(t, [x for x in g if x != t]):
                changes.append({"op": "consolidate-refused", "rules": g, "members": [], "concern": "",
                                "why": f"absorb into {t}: it is older than an entry it would absorb"})
                if not union:  # union: the group is still merged with a new text
                    absorbed.append(g)
                continue
            for x in g:
                if x != t:
                    act[x]["status"] = "retired"
                    act[x]["retired"] = {"date": dt.date.today().isoformat(), "by": out, "replaced_by": t,
                                         "why": "absorbed"}
                    act[t]["evidence"] = _uniq(list(act[t].get("evidence") or []) + list(act[x].get("evidence") or []))
                    for r in rules:
                        if r.get("principle") == x:
                            r["principle"] = t
            changes.append({"op": "consolidate-absorb", "rules": g, "into": t, "members": [], "concern": ""})
            absorbed.append(g)
    groups = [g for g in groups if g not in absorbed]
    in_group = {i for g in groups for i in g} | {i for g in absorbed for i in g}
    agreed = [("regroup" if union else "merge", g) for g in groups] + [("rewrite", [i]) for i, v in sorted(rew.items())
                                                if v >= need and i not in in_group]
    for (a, b), v in sorted(con.items()):
        if v >= need:
            why = next((d.get("reason") for dr in drafts for d in dr if d.get("op") == "contradict"
                        and sorted(d.get("rules") or []) == [a, b]), "")
            for x, y in ((a, b), (b, a)):
                act[x]["conflicts"] = _uniq(list(act[x].get("conflicts") or []) + [y])
            changes.append({"op": "consolidate-contradict", "rules": [a, b], "members": [], "concern": "", "why": why})
    if not agreed:
        return rules, changes

    def versions(op: str, g: list[str]) -> str:
        ops = ("merge", "regroup") if op == "regroup" else (op,)
        vs = [d for dr in drafts for d in dr if d.get("op") in ops and set(d.get("rules") or []) & set(g)]
        return "\n".join(json.dumps({"rules": d.get("rules"), "entries": d["entries"]} if d.get("entries")
                                    else _entry(d) | {"rules": d.get("rules")}) for d in vs if not forced)
    text = "\n\n".join(f"Change {k}: {op} {', '.join(g)}\n" + (detail(g) + "\nDrafts' versions:\n" if detail else "")
                       + versions(op, g) for k, (op, g) in enumerate(agreed))
    if spend[0] >= max_cost:
        return rules, changes
    final, c2 = _ask((final_prompt or FINAL_CONSOLIDATE).replace("@BOOK@", book).replace("@CHANGES@", text), effort, cfg)
    spend[0] += c2
    fin = {d["change"]: d for d in final if isinstance(d, dict) and isinstance(d.get("change"), int)} \
        if isinstance(final, list) else {}

    today = dt.date.today().isoformat()
    used, k = {r["id"] for r in rules}, 0
    drop: set[str] = set()
    add: list[dict] = []
    for i, (op, g) in enumerate(agreed):
        d = fin.get(i)
        if not d:
            continue
        if op == "regroup":
            ents = [e for e in d.get("entries") or [] if isinstance(e, dict) and e.get("expect")] \
                or ([d | {"from": g}] if d.get("expect") else [])
            why = _regroup_refusal(g, ents, act, shrink)
            if why:
                changes.append({"op": "consolidate-refused", "rules": g, "members": [], "concern": "", "why": why})
                continue
            new = _apply_regroup(rules, act, g, ents, out, used, base_ids, cm, today)
            changes.append({"op": "consolidate-regroup", "rules": g, "new": new, "members": [], "concern": "",
                            "words": [sum(_size(act[x]) for x in g), sum(map(_size, ents))]})
            continue
        if not d.get("expect"):
            continue
        if op == "rewrite":
            act[g[0]].update({kk: v for kk, v in _entry(d).items() if v is not None})
            changes.append({"op": "consolidate-rewrite", "rules": g, "members": [], "concern": "",
                            "when": d.get("when"), "expect": d.get("expect")})
            continue
        olds = [act[x] for x in g]
        if _size(d) >= sum(map(_size, olds)) * shrink:
            changes.append({"op": "consolidate-refused", "rules": g, "members": [], "concern": "",
                            "why": f"not short enough ({_size(d)} words vs {sum(map(_size, olds))}, "
                                   f"limit {shrink:.0%})"})
            continue
        k += 1
        while f"{out}-{k:03d}" in used:
            k += 1
        rid = f"{out}-{k:03d}"
        used.add(rid)
        kids = _uniq([m for r in olds for m in r.get("members") or [] if m not in g])
        ev = _uniq([e for r in olds for e in r.get("evidence") or []])
        rep = _entry(d) | {"id": rid, "kind": d.get("kind") or "principle", "status": "active", "version": 1,
                           "history": [], "evidence": ev, "concern": "consolidated",
                           "replaces": [x for x in g if x in base_ids],
                           "replaces_new": [x for x in g if x not in base_ids],
                           "tests": [{**t, "from": r["id"]} for r in olds for t in r.get("tests") or []],
                           "n_prs": len({cm[e]["pr"] for e in ev if e in cm}),
                           "area": ",".join(sorted({cm[e].get("area") or "overall" for e in ev if e in cm}))}
        if kids:
            rep["members"] = kids
        for r in olds:  # merged NEW entries are dropped by consolidate() once verify_changes() has run
            r["status"] = "retired"
            r["retired"] = {"date": today, "by": out, "replaced_by": rid, "why": "consolidated"}
            r.pop("members", None)
        for r in rules:
            if r.get("principle") in g:
                r["principle"] = rid
        add.append(rep)
        changes.append({"op": "consolidate-merge", "rules": g, "new": [rid], "members": [], "concern": "",
                        "words": [sum(map(_size, olds)), _size(d)]})
    return [r for r in rules if r["id"] not in drop] + add, changes


# compress: a step of its own (`lmreview compress`), then vet. Only absorb and merge: making the book
# smaller is its whole job, so its effect can be judged on its own.
COMPRESS = """Below is the whole LMCache review rulebook: the entries an AI reviewer is given when it reviews a
pull request of LMCache (a KV-cache layer for LLM inference engines such as vLLM). Each entry shows its
size in words, what the human reviewers said in the comments it was learned from, the cases where it is
proven to make the reviewer raise a point it otherwise missed, and its record in reviews (citing
findings judged valid vs refuted).

Your job is to make the rulebook much SMALLER without losing anything it does: fewer entries and far
fewer words, while a reviewer given the smaller book still raises every point each entry's proven cases
and comments ask for. Every entry is loaded into every review, so overlapping entries cost on every
review and dilute the reviewer's attention.

Work in two passes. First go through EVERY entry and sort the whole book into groups of entries that are
instances of one principle or one area of project knowledge (an entry may stay alone). Then propose a
change for every group of two or more. A book grown one comment at a time has many such groups; listing
only the one or two merges you are surest of is not doing the job. Each change is checked on its own,
so a doubtful one costs nothing when it fails.

Changes:
- "absorb": one entry ("into") already makes a reviewer raise everything the others ask for, AS WRITTEN.
  It stays word for word; the others are retired. "into" must be an entry written or revised AFTER the
  others (shown as "order"): an entry older than another cannot already cover it, since that one was
  learned from a comment the reviewer missed while the older entry was in the book.
- "merge": two or more entries are instances of one principle. Write ONE entry that states that
  principle: name the common kind of situation in "when" and the common request in "expect", so that
  a reviewer recognizes each merged entry's proven cases as instances of it. Do NOT restate the merged
  entries one by one (that is packing, not merging, and saves little). The reviewer never sees
  "examples": a concrete trigger pattern a proven case needs stays in "when" as a short "e.g." clause.
  The merged entry must be at most 70% of the words of the entries it replaces together; a merge that
  is not is refused.
  Keep every condition that decides whether a merged entry fires on its proven cases: a situation it
  names that a looser word would not cover (e.g. "new types that only wrap or re-derive what the shared
  component holds", where "duplicate types" lets a reviewer decide a wrapper is not a duplicate). Drop
  wording, not conditions: a merge that drops one loses that case and is undone. Facts of a knowledge
  entry (which component holds what, where it lives) stay word for word.
  Generalizing means the entry also applies to situations none of the merged entries named: that is
  intended, as long as it is the same principle. Keep it at the lowest level that covers them all.
Do not merge entries that ask for opposite changes because they share a topic (e.g.
"shorten docstrings to the contract" and "explain tricky state changes in a docstring with a worked
example"). Do not write an entry so broad that it fits any change: a reviewer must still recognize
each proven case from the "when". Entries whose record shows refuted citations are already too wide;
do not widen them further. Groups listed under "Undone earlier" lost a proven case when they were
merged, with what the rule check said about the merged entry on that case: merge them again with a text
that fixes exactly that (it did not apply: the "when" must name that situation; it applied but found
nothing violated: the "expect" lost the condition that case needs). A repair restores the CONCRETE signal the source comment gave (e.g. "logic with a single, CUDA-only
implementation"), quoted from the original entry or the comment. Never add a clause that overrides the
reviewer's judgment ("even if it removes duplication", "even without visible callers", "flag it anyway"): if
the rule check's reason would be right on other pull requests, it is a real exception; keep it and leave
that case lost rather than bend the entry to one pull request.
List only changes; everything else stays. Every change is checked by replaying all the proven cases of
the entries it touches, and a change that loses any of them is undone; an entry whose citations later
turn out refuted in reviews gets revised or retired.

""" + GENERAL + """

For a merge, the length limit is the 70% above, not the 80 words of "Length".

Fields of a written entry (merge): "kind" (principle | knowledge), "when", "expect", "why" (one line),
"examples" (1-3 short concrete instances), "paths" (globs, [] = anywhere).

Rulebook:
@BOOK@

Answer with one JSON block only, one object per change ([] if none):
```json
[{"op": "merge|absorb", "rules": ["<id>", "<id>"], "into": "<absorb only>", "reason": "one line", "kind": "...",
  "when": "...", "expect": "...", "why": "...", "examples": ["..."], "paths": []}]
```"""

FINAL_COMPRESS = """Several independent drafts proposed which entries of the LMCache review rulebook (LMCache is a
KV-cache layer for LLM inference engines such as vLLM) to merge. An AI reviewer is given the "when" and "expect"
of EVERY entry in EVERY review; it never sees "why" (kept as a one-line record of where the entry comes
from) or "examples". For each agreed change below, write the
final entry or entries that replace the group, so that a reviewer given them still raises every proven
comment of every entry in the group.

For each change:
1. Contract first. For each proven comment of each entry in the group, write one line in "keeps" of the
   new entry that takes it over: the clause of "when" by which a reviewer recognizes that situation in a
   diff, and the ask of "expect" it must make. Use the reviewers' own words to find the condition that
   decides it (e.g. "new types that only wrap or re-derive what the shared component holds", where
   "duplicate types" lets a reviewer decide that a wrapper is not a duplicate).
   The clause is the CONCRETE pattern that case needs, quoted in double quotes word for word from the new
   text (e.g. "periodic repeat logs during a condition whose entry and exit are already logged"), not the
   principle restated ("logs that repeat existing information"): a reviewer given only the principle finds
   a reason the case is different ("this log adds the duration") and raises nothing. A quote not found
   word for word in the new entry refuses the change.
2. Then write the shortest text that satisfies every "keeps" line. State the principle the entries are
   instances of: the common kind of situation in "when", the common request in "expect", then the
   concrete patterns the proven comments need as short "e.g." clauses in "when" (the reviewer never sees
   "examples"). Do not list the entries' requests one by one. Aim at
   or under the change's budget for "when" + "expect" ("why" at most 10 words); a group whose total is not
   under 75% of the words it replaces is refused.
3. One entry is the goal. If the group's proven comments ask for different things, the group may be
   redrawn as two (each names in "from" the ids it takes over): still fewer words than the group.
   The entry must read clearly to an engineer who never saw the source PR.
4. Keep the project facts of a knowledge entry (which component holds what, where it lives) word for word.
5. Never move a deciding condition into "examples": the reviewer does not see them.

""" + GENERAL + """

Agreed changes, each with its entries, their proven comments, its budget, and the drafts' versions:
@CHANGES@

Answer with one JSON block only, one object per agreed change; every id of a group must be in the "from" of
at least one new entry:
```json
[{"change": 0, "entries": [{"from": ["<id>", "<id>"], "keeps": [{"comment": "<comment id>", "clause": "..."}],
  "kind": "...", "when": "...", "expect": "...", "why": "...", "examples": ["..."], "paths": []}]}]
```"""

SHRINK = 0.75  # a compress merge must have under this share of the words it replaces (prompt asks for 70%)


# compress, entry by entry: the words of an over-grown book sit inside its entries (RETRY additions, menus of
# remedies, exception clauses, sub-case lists), not between them. Each entry is rewritten shorter in place
# (same id, version + 1); vet replays all its proven cases and puts back the original where one is lost.
TRIM = """Below are entries of the LMCache review rulebook (LMCache is a KV-cache layer for LLM inference
engines such as vLLM). An AI reviewer is given the "when" and "expect" of EVERY entry in EVERY review; it
never sees "why" or "examples". The book has grown one missed comment at a time and is far too long, which costs on
every review and dilutes the reviewer's attention. Rewrite each entry below much SHORTER, so that a reviewer
given it still raises every one of its proven cases.

For each entry:
1. Contract first. For each proven comment listed under the entry, write one line in "keeps": the clause of
   "when" by which a reviewer recognizes that situation in a diff, and the ask of "expect" it must make. Use
   the reviewers' own words to find the condition that decides it (e.g. "new types that only wrap or
   re-derive what the shared component holds", where "duplicate types" lets a reviewer decide that a
   wrapper is not a duplicate). The clause QUOTES, in double quotes, the exact words of your new "when" or
   "expect" that carry the comment's own detail: the specific thing its reviewer pointed at (e.g. "hit
   downgraded to zero before allocation", "moving out frees nothing"), not a category that also covers it
   ("a value changing before its use"). A quote not found word for word in the new text refuses the entry.
2. Then write the shortest "when", "expect" and "why" that satisfy every "keeps" line. Each entry shows its
   budget: aim at or under it @WHY@.
3. Cut, in this order: detail in "why"; alternative remedies (keep the one the reviewers asked for);
   exception clauses no proven comment needs (keep one that answers the excuse a reviewer would otherwise
   accept, e.g. "even if it removes duplication"); lists of synonyms or near-equal cases; repeated "flag ..." sentences; instructions on
   how to review ("scan every added line", "do not wait to know the callers"), unless a "keeps" line needs
   one; sub-cases no proven comment needs.
4. Generalize where it shortens: a list of sub-cases may become the one kind of situation they share, as
   long as each proven comment is still recognizable from it. That is the point: a shorter, more general
   entry also catches the next instance nobody listed.
5. Keep the project facts of a knowledge entry (which component holds what, where it lives) word for word.
6. Never move a deciding condition into "examples": the reviewer does not see them.
7. UNCLEAR (shown under an entry): rewrite so an engineer who knows the codebase but never saw the source PR can tell what
   situation is meant and what to ask; replace the named phrase by the plain mechanism (it may cost words).
@FEEDBACK@
Entries:
@ENTRIES@

Answer with one JSON block only, one object per entry you shortened (leave out an entry that cannot get
shorter without losing a "keeps" line):
```json
[{"id": "<entry id>", "keeps": [{"comment": "<comment id>", "clause": "..."}], "when": "...", "expect": "..."}]
```"""

REPAIR_RULE = """A repair restores the CONCRETE signal the source comment gave (e.g. "logic with a single, CUDA-only
implementation"), quoted from the original entry or the comment. Never add a clause that overrides the
reviewer's judgment ("even if it removes duplication", "even without visible callers", "flag it anyway"): if
the rule check's reason would be right on other pull requests, it is a real exception; keep it and leave
that case lost rather than bend the entry to one pull request."""  # how a repair may fix what vet undid (2026-11-25: v0019c1-010)

TRIM_FEEDBACK = """
Some entries below were shortened before, and vet put the original back because a reviewer given the short
text missed a proven comment, or raised findings citing it that were judged wrong ("TOO WIDE": narrow the
"when" so those situations are left out). For each, the failed text and what the rule check said on that comment are
shown under "EARLIER TRY". Fix exactly that: if it did not apply, the "when" lost the situation; if it
applied but found nothing violated, the "expect" lost the condition that comment needs. Keep the rest short.
A repair restores the CONCRETE signal the source comment gave (e.g. "logic with a single, CUDA-only
implementation"), quoted from the original entry or the comment. Never add a clause that overrides the
reviewer's judgment ("even if it removes duplication", "even without visible callers", "flag it anyway"): if
the rule check's reason would be right on other pull requests, it is a real exception; keep it and leave
that case lost rather than bend the entry to one pull request.
"""


TRIM_BASE, TRIM_PER = 50, 10  # trim_budget: words for one proven sample, and for each further one


def trim_budget(r: dict) -> int:
    """Words for when + expect of a trimmed entry: TRIM_BASE, plus TRIM_PER for each proven sample beyond the
    first."""
    n = len({t["target"] for t in r.get("tests") or [] if t.get("result") == "corrected"})
    return TRIM_BASE + TRIM_PER * max(0, n - 1)


def trim_flags(r: dict) -> list[str]:
    """The design flags trim acts on: UNCLEAR only. OVERRIDE / PACKED text often is the signal a proven
    comment needs (v0030c1 and fx01, 2026-11-25: rewriting it lost cases); they stay in vet's report."""
    return [f for f in design_flags(r) if f.startswith("UNCLEAR")]


def _proven_of(r: dict) -> list:
    return _uniq([c for t in r.get("tests") or [] if t.get("result") == "corrected" for c in t.get("comments") or []])


def _quotes(t: str) -> list[str]:
    """Quoted spans of a contract clause: "..." or '...' (an apostrophe inside a word is not a quote)."""
    return re.findall(r'"([^"]{3,})"', t) + re.findall(r"(?<!\w)'([^']{3,}?)'(?!\w)", t)


def _contract_gap(r: dict, new: dict, keeps: list) -> list[str]:
    """Proven comments of `r` whose "keeps" line quotes nothing found word for word in the `new` text."""
    flat = lambda t: " ".join(str(t).lower().split())  # noqa: E731
    text = flat(f"{new.get('when', '')} {new.get('expect', '')}")
    quoted: dict[str, list[str]] = {}
    for k in keeps or []:
        if isinstance(k, dict):
            quoted.setdefault(str(k.get("comment")).split(":")[0], []).extend(_quotes(str(k.get("clause"))))
    return [str(c) for c in _proven_of(r)
            if not any(flat(q) in text for q in quoted.get(str(c).split(":")[0], []))]


def _trim_entry_text(r: dict, cm: dict, fb: dict | None) -> str:
    """One entry for TRIM: its text, budget, the proven comments in full and other sources briefly."""
    proven = _proven_of(r)
    body = lambda c, n: " ".join(str((cm.get(c) or cm.get(cid_of(c)) or {}).get("body", "")).split())[:n]  # noqa: E731
    who = lambda c: (cm.get(c) or cm.get(cid_of(c)) or {})  # noqa: E731
    lines = [f"### {r['id']} ({r.get('kind')}; when+expect {len((str(r.get('when')) + ' ' + str(r.get('expect'))).split())}"
             f" words, budget {trim_budget(r)})",
             f"when: {r.get('when')}", f"expect: {r.get('expect')}", f"why: {r.get('why') or ''}",
             *([f"UNCLEAR (fix this): {'; '.join(trim_flags(r))}"] if trim_flags(r) else []),
             f"examples (NOT shown to the reviewer): {'; '.join(r.get('examples') or [])}",
             "proven comments (the reviewer must still raise each):"]
    lines += [f"- [{c}] PR #{who(c).get('pr')} {who(c).get('author')}: {body(c, 1500)}" for c in proven] or ["- (none)"]
    other = [e for e in r.get("evidence") or [] if norm(e) not in {norm(c) for c in proven}][:3]
    if other:
        lines.append("other source comments (not proven):")
        lines += [f"- [{e}] PR #{who(e).get('pr')}: {body(e, 300)}" for e in other]
    if fb:
        lines.append(f"EARLIER TRY (put back by vet): when: {fb['text'].get('when')} | expect: {fb['text'].get('expect')}")
        lines += [f"  lost [{x['comment']}]: {x.get('body', '')[:200]!r}; rule check: " + (
            f"applies={x['check'].get('applies')}, violated={x['check'].get('violated')}: {x['check'].get('why')}"
            if x.get("check") else "no verdict") for x in fb.get("lost") or []]
    return "\n".join(lines)


def trim(out: str, base: str, cfg: Config | None = None, effort: str = "high", max_cost: float = 3.0,
         min_words: int = 100, batch: int = 9, only: set[str] | None = None, feedback: dict | None = None,
         workers: int = 3) -> tuple[str, int]:
    """Rewrite the long entries of rulebook `base` shorter, in place, as rulebook `out` (TRIM).

    Args:
        min_words: entries whose when + expect has more words are trimmed (unless `only` is given).
        batch: entries per call; entries are batched by kind and paths, so related ones share a call.
        only: trim exactly these ids (the repair step: those vet put back).
        feedback: id -> {"text": the failed short text, "lost": [{comment, body, check}]} for `only`.

    Returns:
        (summary, number of entries trimmed).
    """
    cfg = cfg or Config()
    _, cm = load_gold(cfg)
    rules = [json.loads(l) for l in book_path(base).open() if l.strip()]
    act = {r["id"]: r for r in rules if r.get("status", "active") == "active"}
    before = sum(map(_size, act.values()))  # the trim below updates these entries in place
    screen_cost = screen_clarity(list(act.values()), effort, cfg) if only is None else 0.0
    wc = lambda r: len((str(r.get("when")) + " " + str(r.get("expect"))).split())  # noqa: E731
    sel = [r for r in act.values() if (r["id"] in only if only is not None else
                                       wc(r) > min_words or bool(trim_flags(r)))]
    sel.sort(key=lambda r: (r.get("kind") or "", ",".join(r.get("paths") or []), r["id"]))
    batches = [sel[i:i + batch] for i in range(0, len(sel), batch)]
    fb_text = TRIM_FEEDBACK if feedback else ""
    note(f"trim {base}: {len(sel)} entries in {len(batches)} calls ({len(act)} active, {sum(map(_size, act.values()))} words)")

    def once(b: list[dict]) -> tuple[object, float]:
        ents = "\n\n".join(_trim_entry_text(r, cm, (feedback or {}).get(r["id"])) for r in b)
        why = '(write no "why": it is kept as it is)'
        return _ask(TRIM.replace("@WHY@", why).replace("@FEEDBACK@", fb_text).replace("@ENTRIES@", ents), effort, cfg)
    res, cost = capped_map(once, batches, workers, max_cost, label=lambda b: f"trim {len(b)}")
    cost += screen_cost
    today, n, changes = dt.date.today().isoformat(), 0, []
    for part in res:
        for d in part if isinstance(part, list) else []:
            r = act.get(d.get("id")) if isinstance(d, dict) else None
            if not r or not d.get("expect") or not d.get("when"):
                continue
            new = {"when": d["when"], "expect": d["expect"]}  # "why" stays as written: a record, not shown
            if _size(new) >= _size(r) and not (trim_flags(r) and not trim_flags(new)):
                changes.append({"op": "trim-refused", "rules": [r["id"]], "why": f"not shorter ({_size(new)} vs {_size(r)})"})
                continue
            if gap := _contract_gap(r, new, d.get("keeps") or []):
                changes.append({"op": "trim-refused", "rules": [r["id"]],
                                "why": f"contract quotes nothing of the new text for proven comment(s) {gap}"})
                continue
            r["history"] = list(r.get("history") or []) + [{"version": r.get("version", 1), "until": today, "by": out,
                                                             "reason": "trim", **{k: r.get(k) for k in ("when", "expect", "why")}}]
            words = [_size(r), _size(new)]
            r.update(new)
            r["version"] = r.get("version", 1) + 1
            r["revised"] = {"date": today, "by": out, "reason": "trim"}
            r["keeps"] = d.get("keeps") or []
            n += 1
            changes.append({"op": "trim", "rules": [r["id"]], "words": words,
                            "budget": trim_budget(r), "keeps": len(r["keeps"])})
    work = cfg.data / "distill" / out
    work.mkdir(parents=True, exist_ok=True)
    (work / "changes.json").write_text(json.dumps(changes, indent=1))
    book_path(out).parent.mkdir(parents=True, exist_ok=True)
    book_path(out).write_text("".join(json.dumps(r) + "\n" for r in rules))
    write_meta(out, {"base": base, "kind": "compress", "seen": []})
    a2 = [r for r in rules if r.get("status", "active") == "active"]
    msg = (f"{n} of {len(sel)} entries trimmed; {len(a2)} entries, {sum(map(_size, a2))} words "
           f"(from {before}); ${cost:.2f}")
    return msg, n


OVERRIDE = re.compile(r"\b(even if (?:it|this|that|they)|even without|regardless of whether|anyway|flag each|raise each|"
                      r"check every|always flag)\b", re.I)  # "even if release raises" (a technical condition) is not one


CLARITY = """Below are entries of a rulebook an AI reviewer of LMCache pull requests is given. Each entry says
when it applies and what the reviewer should ask for. Read each one as an engineer who knows the
codebase but has NOT seen the pull request it was learned from.

For each entry: can that engineer tell what situation in a diff it means and what to ask the author?
Name the phrase that cannot be understood without the source (e.g. "per-group passes", "the label"),
or "" when it is clear. Terse is fine; only flag what a reader cannot decode.

Output only JSON: [{"id": "...", "unclear": "..."}]

@ENTRIES@"""

_CLARITY: dict[str, list[str]] | None = None


def _clarity_path() -> pathlib.Path:
    return Config().data / "distill" / "clarity.json"


def _text_key(r: dict) -> str:
    import hashlib
    return hashlib.sha1(f"{r.get('when', '')}\n{r.get('expect', '')}".encode()).hexdigest()[:16]


def _clarity() -> dict[str, list[str]]:
    global _CLARITY
    if _CLARITY is None:
        p = _clarity_path()
        _CLARITY = json.loads(p.read_text()) if p.exists() else {}
    return _CLARITY


def screen_clarity(rules: list[dict], effort: str = "high", cfg: Config | None = None, max_cost: float = 1.0,
                   batch: int = 25) -> float:
    """Ask a model which active entries a reader without the source PR cannot follow (UNCLEAR). Rules
    are written to be read by people too: precision is left to their feedback after launch. Results are cached by text in data/distill/clarity.json,
    so each text is screened once; design_flags then reports them. Returns the cost."""
    cfg = cfg or Config()
    cache = _clarity()
    todo = [r for r in rules if r.get("status", "active") == "active" and _text_key(r) not in cache]
    if not todo:
        return 0.0
    batches = [todo[i:i + batch] for i in range(0, len(todo), batch)]

    def once(b: list[dict]) -> tuple[object, float]:
        ents = "\n\n".join(f"[{r['id']}]\nWHEN: {r.get('when', '')}\nEXPECT: {r.get('expect', '')}" for r in b)
        return _ask(CLARITY.replace("@ENTRIES@", ents), effort, cfg)
    res, cost = capped_map(once, batches, 3, max_cost, label=lambda b: f"clarity {len(b)}")
    for b, part in zip(batches, res):
        got = {d.get("id"): d for d in part if isinstance(d, dict)} if isinstance(part, list) else {}
        for r in b:
            if r["id"] not in got:
                continue  # not answered (over the cap or dropped): screened next time
            d, f = got[r["id"]], []
            if str(d.get("unclear") or "").strip():
                f.append(f"UNCLEAR: {str(d['unclear']).strip()}")
            cache[_text_key(r)] = f
    p = _clarity_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, indent=1))
    note(f"clarity screen: {len(todo)} entries, {sum(bool(cache.get(_text_key(r))) for r in todo)} flagged; ${cost:.2f}")
    return cost


def design_flags(r: dict) -> list[str]:
    """Where an entry's text goes against how entries are written (2026-11-25 read of v0029):
    OVERRIDE: a clause that overrides the reviewer's judgment ("even if ...", "flag each", "check every")
    instead of naming the concrete signal; PACKED: sub-cases listed one by one ("(a) ... (b) ...", five or
    more ";"-separated clauses) instead of one principle with short "e.g." clauses. A heuristic: the
    trim prompt may keep a flagged text when the flag is wrong (an ordered layout, a knowledge fact).
    Plus the model screen's UNCLEAR for this exact text, if it was screened."""
    out, text = [], f"{r.get('when', '')} {r.get('expect', '')}"
    if m := sorted({x.lower() for x in OVERRIDE.findall(text)}):
        out.append(f"OVERRIDE: {m}")
    for k in ("when", "expect"):
        t = str(r.get(k) or "")
        if re.search(r"\(a\).*\(b\)", t) or t.count(";") >= 4:
            out.append(f"PACKED {k}: {t.count(';') + 1} clauses")
    return out + [f for f in _clarity().get(_text_key(r), []) if f.startswith("UNCLEAR")]  # when screened


def merge_budget(rs: list[dict]) -> int:
    """Words for when + expect of an entry that takes over entries `rs`: trim_budget of their proven samples."""
    return trim_budget({"tests": [t for r in rs for t in r.get("tests") or []]})


def _merge_detail(act: dict, cm: dict) -> Callable[[list[str]], str]:
    """detail() for the final compress call: each entry of the group with its proven comments in full."""
    def detail(g: list[str]) -> str:
        rs = [act[x] for x in g if x in act]
        return (f"budget for the merged when + expect: {merge_budget(rs)} words (the group has "
                f"{sum(map(_size, rs))} words)\n" + "\n\n".join(_trim_entry_text(r, cm, None) for r in rs))
    return detail


def _regroup_refusal(g: list[str], ents: list[dict], act: dict, shrink: float) -> str:
    """Why a regroup of entries `g` into `ents` (each with "from": the ids of `g` it takes over) is refused,
    or "" if it may be applied: every entry of `g` taken over, fewer words than `shrink` of `g`'s."""
    if not ents:
        return "no entry written"
    taken = {x for e in ents for x in e.get("from") or []}
    if set(g) - taken:
        return f"not taken over by any new entry: {sorted(set(g) - taken)}"
    old, new = sum(_size(act[x]) for x in g), sum(map(_size, ents))
    if new >= old * shrink:
        return f"not short enough ({new} words vs {old}, limit {shrink:.0%})"
    gap = [c for x in g for e in ents if x in (e.get("from") or [])
           for c in _contract_gap(act[x], e, e.get("keeps") or [])]
    if gap:
        return f"contract quotes nothing of the new text for proven comment(s) {sorted(set(gap))}"
    return ""


def _apply_regroup(rules: list[dict], act: dict, g: list[str], ents: list[dict], out: str, used: set[str],
                   base_ids: set[str], cm: dict, today: str) -> list[str]:
    """Replace entries `g` by the new entries `ents` (n -> m). Each new entry takes over the evidence and
    proven cases of the entries in its "from" and links to them ("replaces"); all share "regroup" (the first
    new id), so vet keeps or undoes the group as a whole. Each old entry is retired, replaced_by the first new
    entry that took it over. Returns the new ids."""
    ids, k = [], 0
    for _ in ents:
        k += 1
        while f"{out}-{k:03d}" in used:
            k += 1
        ids.append(f"{out}-{k:03d}")
        used.add(ids[-1])
    gid = ids[0]
    for rid, e in zip(ids, ents):
        frm = [x for x in e.get("from") or [] if x in g]
        olds = [act[x] for x in frm]
        ev = _uniq([v for r in olds for v in r.get("evidence") or []])
        kids = _uniq([m for r in olds for m in r.get("members") or [] if m not in g])
        rep = _entry(e) | {"id": rid, "kind": e.get("kind") or "principle", "status": "active", "version": 1,
                           "history": [], "evidence": ev, "concern": "regrouped", "regroup": gid,
                           "keeps": [k for k in e.get("keeps") or [] if isinstance(k, dict)],
                           "replaces": [x for x in frm if x in base_ids],
                           "replaces_new": [x for x in frm if x not in base_ids],
                           "tests": [{**t, "from": r["id"]} for r in olds for t in r.get("tests") or []],
                           "n_prs": len({cm[v]["pr"] for v in ev if v in cm}),
                           "area": ",".join(sorted({cm[v].get("area") or "overall" for v in ev if v in cm}))}
        if kids:
            rep["members"] = kids
        rules.append(rep)
    for x in g:
        r = act[x]
        r["status"] = "retired"
        r["retired"] = {"date": today, "by": out, "why": "regrouped", "regroup": gid,
                        "replaced_by": next(i for i, e in zip(ids, ents) if x in (e.get("from") or []))}
        r.pop("members", None)
    for r in rules:
        if r.get("principle") in g:
            r["principle"] = next(i for i, e in zip(ids, ents) if r["principle"] in (e.get("from") or []))
    return ids


def _order(r: dict) -> int:
    """When an entry got its current text, as a version number: the candidate that wrote or last
    revised it (v0011c1-003 -> 11; revised by v0012c2 -> 12)."""
    import re
    ks = [int(m.group(1)) for x in (r["id"], (r.get("revised") or {}).get("by") or "")
          for m in [re.match(r"v(\d+)", str(x))] if m]
    return max(ks or [0])


def _book_for_compress(rules: list[dict], cm: dict, record: dict, feedback: list[dict], quotes: int = 3) -> str:
    """The active entries for COMPRESS: text, size, order, reviewers' words, proven cases, record; then
    the merges vet undid before."""
    out = []
    for r in rules:
        if r.get("status", "active") != "active":
            continue
        said = [f"    PR #{cm[e]['pr']} {cm[e]['author']}: {' '.join(cm[e]['body'].split())[:300]}"
                for e in (r.get("evidence") or [])[:quotes] if e in cm]
        more = len(r.get("evidence") or []) - len(said)
        proven = [t for t in r.get("tests") or [] if t.get("result") == "corrected"]
        rec = record.get(r["id"]) or {}
        out.append(f"- {r['id']} ({r.get('kind')}; {_size(r)} words; order {_order(r)}): When {r.get('when')}: "
                   f"{r.get('expect')}\n  examples: {'; '.join(r.get('examples') or [])} | paths {r.get('paths') or []}\n"
                   + (f"  DESIGN FLAGS: {'; '.join(design_flags(r))}\n" if design_flags(r) else "")
                   + f"  proven cases: {len(proven)} ({', '.join(sorted({t['target'] for t in proven})) or 'none'}); "
                   f"record: {len(rec.get('helpful') or [])} valid, {len(rec.get('harmful') or [])} refuted\n"
                   f"  reviewers said:\n" + "\n".join(said) + (f"\n    (+{more} more comments)" if more > 0 else ""))
    undone = [f"- {', '.join(f['group'])} ({f['op']}, {f['candidate']}): lost "
              + "; ".join(f"c{x['comment']} of {x['entry']}: {x['body']!r}"
                          + (f" (the rule check said of the merged entry: applies={x['check'].get('applies')}, "
                             f"violated={x['check'].get('violated')}: {x['check'].get('why')})" if x.get("check") else "")
                          for x in f.get("lost") or [])
              + ("".join(f"\n  The undone {f['op']} wrote {t['id']} (from {', '.join(t.get('from') or [])}): When "
                         f"{t.get('when')}: {t.get('expect')}" for t in f.get("texts") or [])
                 + "\n  A reviewer given it did not raise the lost comment (see the rule check's reason above)."
                 if f.get("texts") else "")
              + (f"\n  The undone {f['op']} read: When {f['text'].get('when')}: {f['text'].get('expect')} "
                 f"(examples: {'; '.join(f['text'].get('examples') or [])}).\n  A reviewer given it did not raise "
                 f"the lost comment. If the rule check said it did not apply, the \"when\" must name that kind of "
                 f"situation; if it applied but found nothing violated, the \"expect\" dropped the condition that "
                 f"case needs (restore it from the original entry)."
                 if f.get("text") and not f.get("texts") else "")
              for f in feedback]
    return "\n".join(out) + ("\n\nUndone earlier:\n" + "\n".join(undone) if undone else "")


def compress(out: str, base: str, cfg: Config | None = None, effort: str = "high", max_cost: float = 3.0,
             n: int = 3, record: dict | None = None, feedback: list[dict] | None = None,
             repair: bool = False) -> tuple[str, int]:
    """Make rulebook `base` smaller as rulebook `out`: `n` COMPRESS drafts, every merge they propose taken
    (overlaps resolved in _consolidate's `union`; vet is the only gate),
    absorbs only into an entry newer than the ones it absorbs, merges that generalize to at most SHRINK
    of the words they replace. No blind check: vet is the judge (a merge that loses a proven case is
    undone), and a merge too wide shows up as refuted citations that distill's signals act on. Merges
    vet undid twice (`feedback`) are not proposed again; the undone ones are shown with what they lost.

    Returns:
        (summary, number of absorbs and merges in `out`).
    """
    cfg = cfg or Config()
    _, cm = load_gold(cfg)
    base_rules = [json.loads(l) for l in book_path(base).open() if l.strip()]
    rules = json.loads(json.dumps(base_rules))
    feedback = feedback or []
    times = C.Counter(frozenset(f["group"]) for f in feedback)
    blocked = {g for g, k in times.items() if k >= 2}
    by = {r["id"]: r for r in rules}
    ok = lambda t, xs: all(_order(by[t]) >= _order(by[x]) for x in xs)  # noqa: E731
    screened = screen_clarity(rules, effort, cfg) if not repair else 0.0  # before the book: it shows the flags
    book = _book_for_compress(rules, cm, record or {}, [f for f in feedback if frozenset(f["group"]) not in blocked])
    spend = [screened]
    note(f"compress {base} ({sum(r.get('status', 'active') == 'active' for r in rules)} entries, "
         f"{sum(_size(r) for r in rules if r.get('status', 'active') == 'active')} words; {n} drafts, every merge to vet)")
    act = {r["id"]: r for r in rules if r.get("status", "active") == "active"}
    base_detail = _merge_detail(act, cm)
    forced, detail = None, base_detail
    if repair:
        last = feedback[-1]["candidate"] if feedback else None  # repair the last candidate's undone groups
        fbg = {frozenset(f["group"]): f for f in feedback
               if f.get("candidate") == last and frozenset(f["group"]) not in blocked}
        forced = [sorted(g) for g in fbg if g <= set(act)]
        detail = lambda g: (base_detail(g) + "\nEARLIER TRY (undone by vet; fix exactly what it lost). "  # noqa: E731
                            + REPAIR_RULE.replace("\n", " ") + "\n"
                            + _book_for_compress([], cm, {}, [fbg[frozenset(g)]]).split("Undone earlier:\n", 1)[-1])
        if not forced:
            return "nothing to repair", 0
    rules, changes = _consolidate(rules, {r["id"] for r in base_rules}, out, cm, effort, cfg, spend, max_cost, n,
                                  prompt=COMPRESS, book=book, absorb_ok=ok, blocked=blocked, shrink=SHRINK,
                                  final_prompt=FINAL_COMPRESS, union=True, detail=detail, forced=forced)
    note(f"      proposed: {dict(C.Counter(ch['op'] for ch in changes)) or 'nothing'}")
    rules = [r for r in rules if r["id"] in {x["id"] for x in base_rules} or r.get("status", "active") == "active"]
    if get("distill", "specificity"):  # merged texts too must describe a kind of problem (specificity.py)
        from .specificity import enforce, load_comments
        rules, more, c_sp = enforce(rules, base_rules, load_comments(cfg.data), effort)
        spend[0] += c_sp
        changes += more
        note(f"      specificity: {dict(C.Counter(ch['op'] for ch in more)) or 'all pass'} (${c_sp:.2f})")
    diff = rule_diff(base_rules, rules)
    for level, line in diff:
        note("  " + line, level)
    act = [r for r in rules if r.get("status", "active") == "active"]
    work = cfg.data / "distill" / out
    work.mkdir(parents=True, exist_ok=True)
    (work / "changes.json").write_text(json.dumps(changes, indent=1))
    book_path(out).parent.mkdir(parents=True, exist_ok=True)
    book_path(out).write_text("".join(json.dumps(r) + "\n" for r in rules))
    write_meta(out, {"base": base, "kind": "compress", "seen": []})
    retired = sum(r.get("status") == "retired" for r in rules) - sum(r.get("status") == "retired" for r in base_rules)
    msg = (f"{len(act)} entries, {sum(map(_size, act))} words (from "
           f"{sum(r.get('status', 'active') == 'active' for r in base_rules)}, "
           f"{sum(_size(r) for r in base_rules if r.get('status', 'active') == 'active')}); {retired} retired; ${spend[0]:.2f}")
    return msg, retired


# Last sub-step of consolidate: every change of an existing entry's text must be justified.
VERIFY = """Below are ORIGINAL entries of an LMCache review rulebook and a NEW text proposed to replace them.
An AI reviewer is given the entries when it reviews a pull request. Compare how a reviewer would ACT
with the NEW text versus with the ORIGINAL(s) (taken together, when there are several): on which
changes would one raise a point and the other stay silent, or ask for something different?

Report every such difference as a concrete situation: a short description of a diff, what a reviewer
given the ORIGINAL(s) does there, and what one given the NEW text does. Only behavior counts: wording,
order, emphasis or examples that would not change what the reviewer raises are not differences. A
single changed word can be a difference (e.g. "every subclass" vs "every future subclass" changes
which base-class additions get flagged); a whole rewritten sentence can be none.
@CASES@
If there are several ORIGINAL entries, also say which one (if any) a reviewer would act on exactly as
on the NEW text ("same_as").
@SUPPORT@
ORIGINAL:
@OLD@

NEW:
@NEW@

Answer with one JSON block only:
```json
{"differences": [{"situation": "...", "original": "raises ... | silent", "new": "raises ... | silent",
   "case": "<key of the case it is about, or null>", "keeps": "<true | false; only where both raise: the NEW
   text still asks for everything the ORIGINAL(s) ask for there, and only adds to it>", "supported": "<true |
   false; where the NEW text raises or asks for more than the ORIGINAL(s)>"}], "same_as": "<original id or null>"}
```"""

VERIFY_SUPPORT = """
The NEW text replaces several ORIGINAL entries at once, so it may also fire where none of them did.
For every difference where the NEW text raises a point and the ORIGINAL(s) stay silent, or asks for more
than they do, say whether the reviewers' own words below support it ("supported"): true if, from what
they said, they would ask for the same thing in that situation (the same concern and the same kind of
request, in a situation they did not happen to meet); false if it is a different concern, or a request
their words do not contain. Where both raise a point, also say whether the NEW text still asks for
everything the ORIGINAL(s) ask for there ("keeps"): false if it drops or replaces any part of their ask.

What the reviewers said, in the comments the ORIGINAL entries were learned from:
{said}
"""

VERIFY_CASES = """
The change was made because of the cases below. For each difference, give in "case" the key of the
case it is about (the situation is that case, or the case is an instance of it), or null.

Cases:
{cases}
"""


def _norm_text(r: dict) -> tuple:
    return tuple(" ".join(str(r.get(k) or "").split()).lower() for k in ("when", "expect"))


def _show_old(r: dict) -> str:
    return (f"- {r['id']}: When {r.get('when')}: {r.get('expect')}\n  examples: {'; '.join(r.get('examples') or [])}"
            f" | paths {r.get('paths') or []}")


def _verdict(kind: str, olds: list[dict], v: object) -> str | None:
    """One VERIFY answer as a verdict: accept | revert | absorb:<id> | drift (None: unusable)."""
    if not isinstance(v, dict):
        return None
    diffs = [d for d in v.get("differences") or [] if isinstance(d, dict)]
    same = v.get("same_as") if v.get("same_as") in {o["id"] for o in olds} else None
    if same:  # acts exactly like one original: that one already covered the rest; keep its text
        return "absorb:" + same
    if kind == "merge":  # may only widen, where the reviewers' words support it; a loss or a change is drift
        def raises(x: object) -> bool:
            return str(x or "").strip().lower().startswith("raise")
        def ok(d: dict) -> bool:  # wider where they stayed silent, or more on top of their whole ask
            sup = str(d.get("supported")).lower() == "true"
            if raises(d.get("new")) and not raises(d.get("original")):
                return sup
            return raises(d.get("new")) and raises(d.get("original")) and sup and str(d.get("keeps")).lower() == "true"
        return "accept" if all(ok(d) for d in diffs) else "drift"
    if not diffs:  # a rewrite that acts the same
        return "revert"
    return "accept" if any(d.get("case") not in (None, "", "null") for d in diffs) else "drift"


def verify_changes(rules: list[dict], base_rules: list[dict], out: str, effort: str, cfg: Config,
                   spend: list[float], max_cost: float, n: int = 3) -> tuple[list[dict], list[dict]]:
    """Check every change this distill made to the text of existing entries; undo the unjustified ones.

    Justified: (1) the entry acts differently on the case that motivated it (revise: a failure signal or
    a finding; generalize: the new findings); (2) a merge that acts as the entries it replaces taken
    together, or wider only where the reviewers' words they came from support it (its point is a
    smaller book; a loss or a changed request is drift). Refused: a rewrite that acts the same (rephrasing:
    the original text comes back; a replacement that acts like one of its entries is "absorb": that
    entry stays word for word and takes the others' evidence), and a difference no case asks for
    (drift). Code decides only exact equality; behavior is judged by `n` blind VERIFY calls in parallel
    (they see the texts and the cases, not the reasons), by majority; without a majority the original
    stays. A revise for a RETRY (the entry did not fire on its own source) is exempt: changing the
    wording is its point, and vet checks that the new wording fires.

    Returns:
        (the rulebook, change records "verify-*").
    """
    old = {r["id"]: r for r in base_rules}
    by = {r["id"]: r for r in rules}
    checks = []  # (kind, new entry, original entries, cases)
    for r in rules:
        if r.get("status", "active") != "active":
            continue
        if r["id"] in old and (r.get("revised") or {}).get("by") == out:
            if not r["revised"].get("retry"):
                checks.append(("revise", r, [old[r["id"]]], r["revised"].get("cases") or []))
        elif r["id"] not in old and (r.get("replaces") or r.get("replaces_new")):
            olds = [old[i] for i in r.get("replaces") or [] if i in old] + [by[i] for i in r.get("replaces_new") or [] if i in by]
            if olds:
                checks.append(("generalize" if r.get("cases") else "merge", r, olds, r.get("cases") or []))
    decided, ask = {}, []
    for c in checks:
        same = next((o for o in c[2] if _norm_text(o) == _norm_text(c[1])), None)
        if same is not None:
            decided[c[1]["id"]] = ("revert" if c[0] == "revise" else "absorb:" + same["id"], "identical text")
        else:
            ask.append(c)

    def prompt(c: tuple) -> str:
        cases = "\n".join(f"- k{i}: {x}" for i, x in enumerate(c[3]))
        said = "\n".join(f"- {o['id']}, PR #{cm[e]['pr']} {cm[e]['author']}: {' '.join(cm[e]['body'].split())[:300]}"
                         for o in c[2] for e in (o.get("evidence") or [])[:3] if e in cm)
        return (VERIFY.replace("@OLD@", "\n".join(map(_show_old, c[2]))).replace("@NEW@", _show_old(c[1]))
                .replace("@SUPPORT@", VERIFY_SUPPORT.format(said=said or "(none)") if c[0] == "merge" else "")
                .replace("@CASES@", VERIFY_CASES.format(cases=cases) if c[3] else ""))
    cm = load_gold(cfg)[1] if any(c[0] == "merge" for c in ask) else {}
    jobs = [c for c in ask for _ in range(n)]
    def call(c: tuple) -> tuple[tuple, float]:
        v, cost = _ask(prompt(c), effort, cfg)
        return (c, v), cost
    res, cost = capped_map(call, jobs, max(4, n), max(0.0, max_cost - spend[0]), label=lambda c: f"verify {c[1]['id']}")
    spend[0] += cost  # results come in completion order: each carries its check
    votes: dict[str, list[str]] = C.defaultdict(list)
    problems: dict[str, list[str]] = C.defaultdict(list)  # what a refused merge got wrong, for compress's repair
    for c, v in res:
        x = _verdict(c[0], c[2], v)
        if x:
            votes[c[1]["id"]].append(x)
        if x == "drift" and c[0] == "merge":
            for d in v.get("differences") or []:
                if isinstance(d, dict) and _verdict("merge", c[2], {"differences": [d]}) == "drift":
                    problems[c[1]["id"]].append(f"{d.get('situation')} | original: {d.get('original')} | "
                                                f"new: {d.get('new')} | supported: {d.get('supported')}")
    for c in ask:
        vs = votes.get(c[1]["id"]) or []
        top = C.Counter(vs).most_common(1)
        win = top[0][0] if top and top[0][1] > len(vs) / 2 and len(vs) * 2 > n else "unverified"
        decided[c[1]["id"]] = (win, f"votes {dict(C.Counter(vs))}")
    changes: list[dict] = []
    for kind, r, olds, _ in checks:
        if r["id"] not in decided:
            continue
        verdict, why = decided[r["id"]]
        ids = [r["id"]] + [o["id"] for o in olds if o["id"] != r["id"]]
        if verdict == "accept":
            changes.append({"op": "verify-ok", "rules": ids, "members": [], "concern": "", "why": why})
            continue
        target = verdict.split(":", 1)[1] if verdict.startswith("absorb:") else None
        changes.append({"op": "verify-" + verdict.split(":")[0], "rules": ids, "members": [], "concern": "",
                        "why": why, **({"into": target} if target else {}),
                        **({"problems": _uniq(problems[r["id"]]), "text": _entry(r)} if problems.get(r["id"]) else {})})
        rules = _undo(rules, kind, r, olds, target, old)
    for r in rules:
        (r.get("revised") or {}).pop("cases", None)
        r.pop("cases", None)
    return rules, changes


def _undo(rules: list[dict], kind: str, r: dict, olds: list[dict], target: str | None, old: dict) -> list[dict]:
    """Undo one refused change. A revise gets its original text back (keeping any new evidence). A
    replacement is removed: with `target` ("absorb") that entry stays word for word, takes the
    replacement's evidence and members, and the other originals are retired in its favor; otherwise
    every original comes back as it was."""
    by = {x["id"]: x for x in rules}
    if kind == "revise":
        x = by[r["id"]]  # the same dict as r
        orig, ev, seen = old[r["id"]], _uniq(list(x.get("evidence") or [])), x.get("signals_seen")
        x.clear()
        x.update(orig, evidence=ev)
        if seen:
            x["signals_seen"] = seen
        return rules
    ids = {o["id"] for o in olds}
    for o in olds:
        x = by.get(o["id"])
        if x is None:
            continue
        if target and x["id"] != target:
            x["status"] = "retired"
            x["retired"] = {**(x.get("retired") or {}), "replaced_by": target, "why": "absorbed"}
        else:
            x["status"] = "active"
            x.pop("retired", None)
            if o["id"] in old and old[o["id"]].get("members"):
                x["members"] = list(old[o["id"]]["members"])
    if target:
        t = by[target]
        t["evidence"] = _uniq(list(t.get("evidence") or []) + list(r.get("evidence") or []))
        t["members"] = _uniq(list(t.get("members") or []) + [m for m in r.get("members") or [] if m != target]) or None
        if t["members"] is None:
            t.pop("members")
    for x in rules:
        if x.get("principle") == r["id"]:
            home = target or next((o for o in ids if x["id"] in ((old.get(o) or {}).get("members") or [])), None)
            if home:
                x["principle"] = home
            else:
                x.pop("principle")
    return [x for x in rules if x["id"] != r["id"]]


def _size(r: dict) -> int:
    """Length of an entry in words as the reviewer sees it (when, expect): the cost side of compression. The
    "why" is kept as a record but not shown (prompt `<!-- rules: nowhy -->`), so it is not counted."""
    return sum(len(str(r.get(k) or "").split()) for k in ("when", "expect"))


def drop_unearned(rules: list[dict], base_ids: set[str]) -> tuple[list[dict], list[dict]]:
    """Drop each entry new in this distill that has no evidence comment of its own: every comment it
    cites is already cited by one of its members (a parent made by merge or induce over existing
    entries). Such an entry catches nothing its members don't, and only adds noise and vet cost.
    Its members are unlinked from it.

    Returns:
        (the rulebook, change records "drop-unearned").
    """
    by = {r["id"]: r for r in rules}
    drop = set()
    for r in rules:
        if r["id"] in base_ids or not r.get("members"):
            continue
        inherited = {e for m in r["members"] if m in by for e in by[m].get("evidence") or []}
        if not set(r.get("evidence") or []) - inherited:
            drop.add(r["id"])
    for r in rules:
        if r.get("principle") in drop:
            r.pop("principle")
    changes = [{"op": "drop-unearned", "rules": [i], "members": by[i]["members"], "concern": by[i].get("name") or "",
                "why": "no evidence comment of its own"} for i in sorted(drop)]
    return [r for r in rules if r["id"] not in drop], changes


def failure_signals(rules: list[dict], cfg: Config, per_rule: int = 3, reviewer: str | None = None,
                    prs: set[int] | None = None) -> tuple[dict, dict]:
    """Findings that cited an entry of `rules` and were judged invalid, from the judged runs of
    `reviewer` (on `prs`, if given), or from every judged run on disk.

    Returns:
        (key "s<n>" -> prompt text, key -> record {rule, reviewer, target, finding, why}).
    """
    from .reviewer import parse_reviewer
    ids = {r["id"] for r in rules if r.get("status", "active") == "active"}
    # runs from before an entry's last revision judged its old text: they are not signals any more
    since = {r["id"]: dt.datetime.fromisoformat(r["revised"]["date"]).timestamp() for r in rules if r.get("revised")}
    done = {(r["id"], *x) for r in rules for x in r.get("signals_seen") or []}  # already decided on
    from .state import outcomes
    record = outcomes()
    text, rec, n, seen = {}, {}, C.Counter(), set()
    for d in sorted((cfg.data / "runs").iterdir()):
        if reviewer and d.name != reviewer:
            continue
        try:
            if not parse_reviewer(d.name.split("#")[0])[1]:
                continue
        except ValueError:
            continue
        for f in sorted(d.glob("*.json")):
            sp = cfg.data / "scores" / d.name / f.name
            if not sp.exists():
                continue
            bad = {a["id"]: (a.get("second") or {}).get("why") or a.get("why")
                   for a in json.loads(sp.read_text()).get("ai") or [] if refuted(a)}
            run = json.loads(f.read_text())
            if prs and run["pr"] not in prs:
                continue
            for x, r in ((x, r) for x in run.get("findings") or [] for r in sorted(finding_rules(x))):
                key = (r, run["pr"], (x.get("title") or "")[:60])
                if r in ids and x["id"] in bad and n[r] < per_rule and key not in seen \
                        and f.stat().st_mtime >= since.get(r, 0) \
                        and (r, d.name, f"{run['pr']}@{run['commit'][:8]}", x["id"]) not in done:
                    n[r] += 1
                    seen.add(key)
                    k = f"s{len(rec) + 1}"
                    rec[k] = {"rule": r, "reviewer": d.name, "target": f"{run['pr']}@{run['commit'][:8]}",
                              "finding": x["id"], "why": bad[x["id"]]}
                    text[k] = (f"failure signal of {r}: a finding citing it on PR #{run['pr']} was judged invalid. "
                               f"Finding: {x.get('title')}: {' '.join((x.get('body') or '').split())[:300]} "
                               f"| judge: {bad[x['id']]}"
                               + (f" | record of {r} in learning reviews: {len(record[r]['helpful'])} citing findings "
                                  f"judged valid, {len(record[r]['harmful'])} refuted" if r in record else "")
                               + _code_at(cfg, run["commit"], x.get("locations") or []))
    return text, rec


def _code_at(cfg: Config, commit: str, locs: list[dict], ctx: int = 15) -> str:
    """The code around a finding's primary location at the reviewed commit, as a prompt block; "" when
    there is no line location or the file can't be read."""
    loc = next((l for l in locs if l.get("role", "primary") == "primary" and l.get("start")), None)
    if not loc or loc.get("side", "new") != "new":
        return ""
    try:
        src = subprocess.run(["git", "-C", str(cfg.repo), "show", f"{commit}:{loc['path']}"],
                             capture_output=True, text=True, check=True, timeout=30).stdout.splitlines()
    except (subprocess.SubprocessError, OSError):
        return ""
    lo, hi = max(1, loc["start"] - ctx), min(len(src), (loc.get("end") or loc["start"]) + ctx)
    body = "\n".join(f"{i:5d} {src[i - 1]}" for i in range(lo, hi + 1))
    return f"\n    code at {loc['path']}:{loc['start']}:\n{body}" if body else ""


def book_meta(name: str) -> dict:
    """rules/<name>.meta.json: how the book was made ({"base", "runs", "prs", "seen"}).
    A book without one (made before) counts its evidence comments as seen."""
    p = _meta_path(name)
    if p.exists():
        return json.loads(p.read_text())
    rules = [json.loads(l) for l in book_path(name).open() if l.strip()]
    return {"seen": sorted({norm(e) for r in rules for e in r.get("evidence") or []}, key=str)}


def write_meta(name: str, meta: dict) -> None:
    """Write rules/<name>.meta.json."""
    _meta_path(name).write_text(json.dumps(meta, indent=1) + "\n")


def _meta_path(name: str) -> pathlib.Path:
    """rules/<name>.meta.json, or the .meta.json next to a state book."""
    b = book_path(name)
    return b.with_name(b.stem + ".meta.json")


def rule_diff(old: list[dict], new: list[dict], width: int = 160) -> list[tuple[str, str]]:
    """What changed from rulebook `old` to `new`, as (level, line) for the log (see progress.note).

    `+` a new entry (with its text), `~` a revised entry (old and new text), `-` retired, `=` an existing
    entry that gained evidence, links (principle / members) or a contest."""
    def cut(t: str) -> str:
        t = " ".join(str(t or "").split())
        return t if len(t) <= width else t[:width - 1] + "…"

    def text(r: dict) -> str:
        return cut(f"When {r.get('when')}: {r.get('expect')}")

    O = {r["id"]: r for r in old}
    out: list[tuple[str, str]] = []
    for r in new:
        o, i = O.get(r["id"]), r["id"]
        tag = f"{i} ({r.get('kind', 'principle')}" + (f", under {r['principle']}" if r.get("principle") else "") + ")"
        if o is None:
            mem = f"; members {', '.join(r['members'])}" if r.get("members") else ""
            out += [("add", f"+ {tag}: {len(r.get('evidence') or [])} evidence comments{mem}"), ("add", f"    {text(r)}")]
            continue
        if r.get("status", "active") != o.get("status", "active") and r.get("status") == "retired":
            why = (r.get("retired") or {}).get("why")
            out.append(("drop", f"- {tag} retired" + (f": {cut(why)}" if why else "")))
            continue
        if r.get("version", 1) != o.get("version", 1):
            out += [("change", f"~ {tag} revised v{o.get('version', 1)} -> v{r.get('version', 1)}"),
                    ("dim", f"    was: {text(o)}"), ("change", f"    now: {text(r)}")]
            continue
        bits = []
        ev = set(r.get("evidence") or []) - set(o.get("evidence") or [])
        if ev:
            bits.append(f"+{len(ev)} evidence")
        if r.get("principle") != o.get("principle"):
            bits.append(f"now under {r.get('principle')}")
        mem = set(r.get("members") or []) - set(o.get("members") or [])
        if mem:
            bits.append(f"new members {', '.join(sorted(mem))}")
        if set(r.get("contested") or []) - set(o.get("contested") or []):
            bits.append("contested by a new comment")
        if bits:
            out.append(("info", f"= {tag}: {'; '.join(bits)}"))
    return out



def attribute(cs: list[dict], effort: str, cfg: Config, workers: int, max_cost: float) -> tuple[list[dict], float]:
    """Attribute comments `cs` (ATTRIBUTE): one call, then a second, independent one on every comment.

    One call alone neither learns a comment (a rule written from a comment that only confirmed the code)
    nor drops it. A comment is learned only when both calls say "learnable"; where they disagree it is
    "unclear" (no third call: state.distill_step parks it as needs_human, for a person); with no second answer (cost cap, garbled) the
    comment stays open as "unconfirmed" and a later attempt asks again.

    Args:
        cs: the comments (with their hunk, later changes and discussion; see _fmt).
        effort: the calls' effort.
        cfg: paths.
        workers: parallel calls.
        max_cost: stop starting calls once reached.

    Returns:
        (attributions: dicts with "id", "kind", "asks"/"why", "second", and "votes" when a third call
        ran, cost).
    """
    by_id = {c["id"]: c for c in cs}

    def ask(group: list[list[dict]], label: str, cap: float) -> tuple[dict, float]:
        res, cost = capped_map(lambda b: _ask(ATTRIBUTE.format(comments="\n\n".join(map(_fmt, b))), effort, cfg),
                               group, workers, cap, label=lambda b: f"{label} {len(b)}")
        got = {_resolve(a.get("id"), by_id): a for r in res if isinstance(r, list) for a in r if isinstance(a, dict)}
        return {k: v for k, v in got.items() if k in by_id}, cost

    split = lambda ids: [[by_id[i] for i in ids[n:n + BATCH]] for n in range(0, len(ids), BATCH)]  # noqa: E731
    first, spent = ask(split(list(by_id)), "attribute", max_cost)
    if not first:
        return [], spent
    note(f"      second opinion on {len(first)} comments")
    second, c2 = ask(split(list(first)), "recheck", max(0.0, max_cost - spent))
    spent += c2
    learn = lambda a: (a or {}).get("kind") == "learnable"  # noqa: E731
    # learnable needs both calls; where they disagree the comment is "unclear" (2026-11-26: a third call
    # made ~10% of comments a coin flip between learned and dropped; unclear ones are kept apart, for a person)
    split_ids = [i for i in first if i in second and learn(first[i]) != learn(second[i])]
    if split_ids:
        note(f"      {len(split_ids)} comments unclear: the two calls disagree on whether they are learnable")
    att = []
    for i, a in first.items():
        b = second.get(i)
        if b is None:
            a = {**a, "first": a.get("kind"), "second": None, "kind": "unconfirmed"}
        elif i in split_ids:
            nl = b if learn(a) else a  # the call that found no lesson says why
            a = {**a, "kind": "unclear", "votes": [a.get("kind"), b.get("kind")], "second": b.get("kind"),
                 "why": f"{nl.get('kind')}: {nl.get('why') or ''}"}
        else:
            a = {**a, "second": b.get("kind")}
        att.append({**a, "id": i})
    return att, spent

def distill(out: str, base: str, misses_of: str, comments: list[int | str], effort: str = "high", workers: int = 4,
            max_cost: float = 5.0, cfg: Config | None = None, n: int = 3, prs: list[int] | None = None,
            notes: dict[int, str] | None = None, tidy: bool = False) -> str:
    """Build the candidate book `out` from book `base`; returns a short summary. `max_cost` 0 = plan only
    (prints the estimate).

    distill does not review or judge. It learns `comments` (the ledger's to_distill points, see state.py),
    which `misses_of` (the reviewer whose judged runs filed them) missed; findings of its runs citing a base
    entry that were refuted are the entry's failure signals. Steps: (1) attribute the missed comments; (2) write: one step that
    sees the whole base book, its failure signals and the learnable findings and decides per finding
    (evidence, generalize, merge, add; revise/retire only on failure signals, an opposite finding or a
    retry); (3) update the book; (4) consolidate the whole book (parallel drafts, voted; skipped when
    write changed nothing, unless `tidy`: the base book was consolidated when it was written);
    then drop every new entry without an evidence comment of its own. Whether the
    result is kept is `lmreview vet`'s call.

    `notes`: comment id -> what earlier attempts made of it."""
    cfg = cfg or Config()
    if book_path(out).exists():
        raise FileExistsError(f"{book_path(out)} exists; pick a new name")
    _, cm0 = load_gold(cfg)
    cs = [cm0[i] for i in comments if i in cm0]
    if prs:
        cs = [c for c in cs if c["pr"] in set(prs)]
    batches = [cs[i:i + BATCH] for i in range(0, len(cs), BATCH)]
    n_cand = int(len(cs) * 0.7)  # pilot: ~75% learnable
    est = 2 * len(batches) * EST["attribute"] \
        + (n_cand // WRITE_BATCH + 1) * EST["write"] * (n + 1 if n > 1 else 1) \
        + EST["consolidate"] * (CONSOLIDATE_DRAFTS + 1)  # n drafts + merge; consolidate drafts + final
    note(f"distill {out}: {len(cs)} comments" + (f" missed by {misses_of}" if misses_of else "")
         + f", {len(batches)} attribution batches; est ${est:.1f}, cap ${max_cost:.1f}")
    if max_cost <= 0:
        return "plan only (max-cost 0); nothing written"

    work = cfg.data / "distill" / out
    work.mkdir(parents=True, exist_ok=True)
    note(f"[1/4] attribute {len(cs)} comments in {len(batches)} batches")
    att, spent = attribute(cs, effort, cfg, workers, max_cost)
    (work / "attribution.jsonl").write_text("".join(json.dumps(a) + "\n" for a in att))
    note(f"      attribution: {dict(C.Counter(a.get('kind') for a in att))}; {len(cs) - len(att)} not attributed")

    # findings: the learnable comments (an attribution from before "asks" has a candidate "rule" instead)
    base_rules = [json.loads(l) for l in book_path(base).open() if l.strip()]
    written = C.defaultdict(list)  # comment -> active entries already written from it
    for r in base_rules:
        if r.get("status", "active") == "active":
            for e in r.get("evidence") or []:
                written[norm(e)].append(r["id"])
    items, evid, retry, why = {}, {}, {}, {}
    for a in att:
        if a.get("kind") == "learnable" and (a.get("asks") or a.get("rule")):
            k = f"c{a['id']}"
            items[k], evid[k] = a.get("asks") or a["rule"], [a["id"]]
            if written.get(a["id"]):
                retry[k] = written[a["id"]]
            if (notes or {}).get(a["id"]):
                why[k] = notes[a["id"]]
    spend = [spent]
    _, cm = load_gold(cfg)
    sig_text, sig = failure_signals(base_rules, cfg, reviewer=misses_of, prs=set(prs or []) or None) \
        if base_rules else ({}, {})
    for k in sig:
        items[k], evid[k] = sig_text[k], []
    note(f"[2/4] write: {len(evid) - len(sig)} findings ({len(retry)} retries), {len(sig)} failure signals, "
         f"{sum(r.get('status', 'active') == 'active' for r in base_rules)} existing entries (${spend[0]:.2f} so far)")
    rules, changes = update_rulebook(base_rules, items, evid, out, cm, effort, cfg, spend, max_cost, workers,
                                     n=n, signals=sig, retry=retry, notes=why)
    note(f"      changes: {dict(C.Counter(ch['op'] for ch in changes))}")
    if changes or tidy:
        note(f"[3/4] consolidate the whole book ({CONSOLIDATE_DRAFTS} drafts, voted; ${spend[0]:.2f} so far)")
        rules, more = consolidate(rules, base_rules, out, cm, effort, cfg, spend, max_cost, n=CONSOLIDATE_DRAFTS)
        changes += more
        note(f"      consolidate: {dict(C.Counter(ch['op'] for ch in more)) or 'no change'}")
    else:  # the base book was consolidated when it was written; nothing changed since
        note("[3/4] consolidate: skipped, write changed nothing")
    rules, more = drop_unearned(rules, {r["id"] for r in base_rules})
    changes += more
    if get("distill", "specificity"):  # an entry must describe a kind of problem, not how to fix one PR
        from .specificity import enforce, load_comments
        rules, more, c_sp = enforce(rules, base_rules, load_comments(cfg.data), effort)
        spend[0] += c_sp
        changes += more
        note(f"      specificity: {dict(C.Counter(ch['op'] for ch in more)) or 'all pass'} (${c_sp:.2f})")
    spent = spend[0]
    diff = rule_diff(base_rules, rules)
    note(f"rule changes ({sum(l.startswith('+') for _, l in diff)} new, {sum(l.startswith('~') for _, l in diff)} revised, "
         f"{sum(l.startswith('-') for _, l in diff)} retired, {sum(l.startswith('=') for _, l in diff)} updated):"
         if diff else "rule changes: none")
    for level, line in diff:
        note("  " + line, level)
    (work / "changes.json").write_text(json.dumps(changes, indent=1))
    book_path(out).parent.mkdir(parents=True, exist_ok=True)
    book_path(out).write_text("".join(json.dumps(r) + "\n" for r in rules))
    write_meta(out, {"base": base, "runs": misses_of, "prs": sorted(prs or []) or None,
                     "seen": sorted({a["id"] for a in att}, key=str)})  # point keys mix ints and "<id>:<k>"

    kinds = C.Counter(a.get("kind") for a in att)
    md = [f"# Rulebook {out}", "",
          f"From {len(cs)} train comments" + (f" missed by {misses_of}" if misses_of else "")
          + (f", extending {base}" if base else "")
          + f"; attribution: {dict(kinds)}; cost ${spent:.2f}",
          f"{len(rules)} entries: " + ", ".join(f"{k} {v}" for k, v in C.Counter(r["kind"] for r in rules).items()), ""]
    md += ["## Changes", ""] + [f"- {ch['op']}: " + ", ".join(ch.get("rules") or ch.get("new") or [])
                                 + f" ({ch['concern']})" + (f"; lost old evidence {ch['lost']}" if ch.get("lost") else "")
                                 for ch in changes] + [""]
    for kind in ("principle", "knowledge"):
        md += [f"## {kind}", ""]
        for r in (r for r in rules if r["kind"] == kind and r.get("status", "active") == "active"):
            ev = ", ".join(f"[#{cm[e]['pr']}]({cm[e]['url']})" for e in r["evidence"][:6])
            # induced parents carry no area / n_prs: count them from the evidence
            evs = [cm[e] for e in r.get("evidence") or [] if e in cm]
            area_ = r.get("area") or ",".join(sorted({c.get("area") or "overall" for c in evs}))
            n_prs = r.get("n_prs") or len({c["pr"] for c in evs})
            md += [f"- **{r['id']}** v{r.get('version', 1)} ({area_}, {n_prs} PRs) When {r['when']}: {r['expect']}",
                   f"  - why: {r.get('why') or ''}; paths: {r.get('paths') or 'any'}",
                   f"  - e.g. {' / '.join(r.get('examples') or [])}", f"  - evidence: {ev}"]
        md.append("")
    book_path(out).with_suffix(".md").write_text("\n".join(md) + "\n")
    return (f"rules/{out}.jsonl: {len(rules)} entries ({dict(C.Counter(r['kind'] for r in rules))}) from "
            f"{len(cs)} comments ({dict(kinds)}), ${spent:.2f}")

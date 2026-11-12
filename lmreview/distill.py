"""`lmreview distill`: turn what a reviewer missed into rulebook changes; `coverage`: test whether it reuses.

distill does not review: it learns from existing review runs (`misses_of`, normally
`<prompt>+<base>@high-rc` run on train PRs with `lmreview review`).
  1. judge the runs against the human comments (cached): missed comments (change requests / nits)
     are what to learn; findings citing a base entry judged invalid are its failure signals.
     Comments whose file never changed again although the PR got later commits are dropped.
  2. attribute (batches, no tools): learnable | context | not_issue | rejected (declined in the
     thread); for learnable ones a candidate rule
  3. cluster (no tools): group candidates with the base entries by underlying concern; failure
     signals join their entry's group
  4. abstract new-only groups (n drafts merged); REVISE groups with base entries: evidence | parent
     principle | add | revise / retire (only on a failure signal or an opposite comment) | contradict
  5. update the book; a revision must still explain the entry's evidence and corrected tests
  6. induce: place standalone entries under principles (attach, or a new parent)
Output: rules/<out>.jsonl, rules/<out>.md (readable), <data>/distill/<out>/{attribution,clusters,changes}.json.
Whether the result is kept is `lmreview vet`'s call (vet.py).
Never reads test/new samples.

coverage(): for human comments of a split (default test), which entries explain them. Rules that
reuse explain held-out comments; this is checked before spending on reviewer A/B runs.
"""

from __future__ import annotations

import collections as C
import datetime as dt
import fnmatch
import json
import pathlib
import subprocess
import tempfile

from . import llm
from .budget import capped_map
from .config import RULES, Config
from .state import book_path
from .ensemble import ensemble
from .progress import note
from .score import REPORTS, _normalize, load_gold

BATCH = 30          # comments per attribution / coverage call
CLUSTER_CHUNK = 400  # candidates per clustering call
ABSTRACT_BATCH = 12  # clusters per abstraction call
EST = {"attribute": 0.17, "cluster": 0.4, "abstract": 0.15}  # $/call, from the pilot; estimates only

ATTRIBUTE = """You are distilling the review standards of the LMCache team (a KV-cache layer for LLM
inference engines such as vLLM) from past human review comments.

For each comment below (with its code hunk, what happened afterwards and the thread replies), decide:
- "learnable": it follows from a standard, a recurring concern, or knowledge of this codebase or the
  engine that a reviewer could apply to FUTURE pull requests. Write the reason as a candidate rule:
  the principle or fact behind the comment, not a restatement of this one fix. If the reviewer
  states the principle ("X does not belong in the generic layer", "use only one path"), the rule is
  at that level; the mechanism this PR used (an inline type check, an event stream) is one instance
  of it, not its condition. Keep what the
  reviewer asked the author to DO (e.g. "explain multi-step state changes in a docstring with a
  worked example of values before/after", not just "docstrings should be clear").
- "context": it needs knowledge outside the code (an offline decision, roadmap, another PR's state).
- "not_issue": a question, praise, or nothing actionable.
- "rejected": the thread shows the suggestion was declined, withdrawn or judged wrong.
Also give "paths": glob patterns of where the rule applies ([] = anywhere). Where the commented file
happens to be is not a reason: a principle that would hold in any module gets [].

Comments:
{comments}

Answer with one JSON block only:
```json
[{{"id": 123, "kind": "learnable|context|not_issue|rejected", "rule": "...", "paths": ["..."]}}]
```"""

CLUSTER = """Below are candidate review rules distilled from LMCache human review comments, one per line
with a key. Group them by UNDERLYING CONCERN: the same principle or the same piece of knowledge, asking
the author for the same kind of change, even if they come from different files, areas or wordings
(e.g. "release-path rank gating must match the acquire path" and "free buffers on every exit path
the same way they were allocated" share "acquire/release symmetry"). A shared TOPIC is not enough:
candidates that ask for different or opposite changes stay apart (e.g. "shorten docstrings to the
contract" and "explain tricky state changes in docstrings with a worked example" are two groups,
though both are about docstrings). Singletons are fine. Every key goes into exactly one group.

Candidates:
{items}

Answer with one JSON block only:
```json
[{{"concern": "short name of the shared concern", "members": ["k1", "k7"]}}]
```"""

# How general an entry must be; shared by ABSTRACT and REVISE (no braces: it goes through str.format).
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
- Level: read what the reviewer said (quoted under each candidate). When the reviewer states the
  principle behind the ask (e.g. "there are two paths for X; use only one", "this is a vendor
  specialization inside the generic layer"), write "when" and "expect" at the level of that stated
  principle, even if the candidate is narrower. The mechanism the PR happened to use (an inline type
  check, an event stream, a snapshot getter) goes to "examples", never into "when" as a condition.
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

ABSTRACT = """Each group below holds candidate review rules from LMCache human review comments that share
one concern (with the PR numbers they came from). For each group write ONE rulebook entry for the
reviewer, or skip the group if it carries no reusable principle or knowledge:
- "principle": the review principle at the level a reviewer would apply it to other changes (the
  group's candidates are instances); specific enough to check against a diff.
- "knowledge": a fact or invariant about this codebase or the engine, and what a reviewer must
  therefore check when touching that code; scope it with "paths".

""" + GENERAL + """
Fields: "group" (its number), "kind", "when" (the kind of change it applies to), "expect" (what to
check or require; checkable), "why" (one line), "examples" (1-2 short concrete instances), "paths"
(glob patterns, [] = anywhere).

Groups:
{groups}

Answer with one JSON block only:
```json
[{{"group": 0, "kind": "principle", "when": "...", "expect": "...", "why": "...", "examples": ["..."], "paths": []}}]
```"""

# Merge step of an ensemble of ABSTRACT runs: one entry per group from several drafts of it.
MERGE_ABSTRACT = """Several independent drafts were written for the rulebook entries of the groups below (each
group: candidate review rules from LMCache human review comments, with what the reviewer said). The drafts
differ by chance, mostly in how general they are. For each group write the ONE final entry:
- Its level is the one the reviewer's own words support: read the quotes. Prefer the draft whose "when"
  covers every mechanism by which a PR could break that stated principle; take the most precise
  "expect" and the best examples from any draft. Do not go above what the reviewer said.
- Skip a group only if most drafts skipped it.

""" + GENERAL + """

Groups:
{groups}

Drafts:
{drafts}

Answer with one JSON block only, in the same format as the drafts:
```json
[{{"group": 0, "kind": "principle", "when": "...", "expect": "...", "why": "...", "examples": ["..."], "paths": []}}]
```"""

REVISE = """Below are groups of an LMCache review rulebook being updated. Each group holds existing
entries (keys "b...", with id, text and examples), new candidate rules (keys "c...", from human
review comments the reviewer missed) and failure signals of existing entries (keys "s...": a finding
that cited the entry and was judged invalid), grouped as one concern. Decide how the rulebook changes. Every
key of a group appears in exactly one decision of that group:
- "keep": an existing entry stays as written (no candidate concerns it).
- "evidence": candidates are already instances of an existing entry AS WRITTEN: a reviewer applying it
  to their change would have raised their point. The entry's text stays.
- "generalize": candidates ask for the same kind of change as an existing entry, but its "when" or
  "expect" is too narrow to make a reviewer raise their point. Write the broader entry at the lowest
  level that covers the existing entry AND the candidates; it becomes a new parent principle, and the
  existing entry stays as written under it.
- "merge": two or more existing entries are one concern; write the one parent entry that covers them
  all (they stay as written under it).
- "add": candidates ask for a different change than every existing entry; write a new entry.
- "revise": the existing entry's text is WRONG as shown by the group's failure signals ("s..." keys:
  findings that cite the entry and were judged invalid) or by candidates that ask for the opposite.
  Rewrite it so it would not have produced those findings (or would agree with the reviewers), while
  still covering everything its examples asked for. List the keys that show it is wrong in "members",
  and say in "changed" (one line) which situations the new text no longer covers, or now covers, or
  what it now asks for differently, such that those findings would not arise. A rewrite that only
  rephrases (same situations, same request) is not a revise: if the signal came from the reviewer
  misapplying a correct entry, use "keep" (the signal is still recorded as considered).
- "retire": the existing entry is wrong and no rewrite fixes it, or another entry already covers it
  completely ("replaced_by": that id). Same evidence requirement as "revise".
- "contradict": candidates ask for the opposite of an existing entry, but it is unclear who is right.
  Do not rewrite it; say why.
Only "revise" and "retire" change an existing entry, and only with a failure signal or a contradicting
candidate in "members"; without one, use the other decisions.
Fields of a written entry (generalize, merge, add, revise): "kind" (principle | knowledge), "when", "expect",
"why" (one line), "examples" (short concrete instances), "paths" (globs, [] = anywhere).

""" + GENERAL + """

Groups:
@GROUPS@

Answer with one JSON block only, one object per decision:
```json
[{"group": 0, "op": "keep|evidence|generalize|merge|add|revise|retire|contradict", "rules": ["<existing id>"],
  "members": ["c123", "s1"], "kind": "...", "when": "...", "expect": "...", "why": "...", "examples": ["..."],
  "paths": [], "changed": "<revise only>", "replaced_by": "<id, retire only>"}]
```"""

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


def _ask(prompt: str, effort: str, cfg: Config) -> tuple[object, float]:
    """One tool-less LLM call in an empty directory; returns (parsed JSON, cost)."""
    cfg.sandbox.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cfg.sandbox) as d:
        r = llm.run(prompt, effort, cwd=d, tools="")
    return llm.extract_json(r["text"]), r["cost"]


def _id(x: object) -> object:
    """Comment ids come back from the model as ints or strings."""
    return int(x) if isinstance(x, str) and x.strip().isdigit() else x


def _misses(cfg: Config, reviewer: str, split: str) -> list[int]:
    """Gold comment ids of `split` that `reviewer` missed (change requests / nits, from its judge results)."""
    ss, _ = load_gold(cfg)
    ids = []
    for p in sorted((cfg.data / "scores" / reviewer).glob("*.json")):
        run = json.loads((cfg.data / "runs" / reviewer / p.name).read_text())
        if ss.get((run["pr"], run["commit"]), {}).get("split") != split:
            continue
        s = _normalize(json.loads(p.read_text()), run)
        ids += [s["gold_ids"][h["id"]] for h in s["human"]
                if h["type"] in ("change_request", "nit") and not h["matched_ai"]]
    return ids


def inputs(cfg: Config, misses_of: str | None, area: str | None, split: str = "train",
           keep_unaddressed: bool = False) -> list[dict]:
    """Human comments of `split` to distill from (or to test coverage on)."""
    ss, cm = load_gold(cfg)
    if misses_of:
        ids = _misses(cfg, misses_of, split)
    else:
        ids = [i for s in ss.values() if s["split"] == split for i in s["gold_ids"]]
    cs = [cm[i] for i in dict.fromkeys(ids)]
    if not keep_unaddressed:
        cs = [c for c in cs if c.get("addressed_reason") != "file-unchanged"]
    if not area:
        return cs
    # by PR (as `review --area` picks samples), not by the comment's own area: a team standard voiced
    # on a file of another area is still evidence (e.g. a docstring preference on an mp file)
    prs = {p["pr"]: p for p in map(json.loads, (cfg.data / "dataset" / "prs.jsonl").open())}
    return [c for c in cs if area in prs[c["pr"]]["areas"]]


OUTCOME = {"lines-changed": "the commented lines were changed afterwards",
           "file-deleted": "the file was deleted afterwards",
           "file-changed-elsewhere": "the file changed afterwards, but not at these lines",
           "no-later-commits": "no later commits in the PR"}


def _fmt(c: dict, rich: bool = True) -> str:
    """One comment for a prompt: location, hunk, body; with `rich`, outcome and thread replies."""
    if c["kind"] == "inline":
        s = (f"[{c['id']}] {c['path']}:{c['line_lo']} (PR #{c['pr']}, by {c['author']})\n"
             f"hunk:\n{(c['diff_hunk'] or '')[-600:]}\ncomment: {c['body'][:1000]}")
    else:
        s = f"[{c['id']}] overall review of PR #{c['pr']} by {c['author']}:\n{c['body'][:1500]}"
    if rich:
        if c.get("addressed_reason") in OUTCOME:
            s += f"\nafterwards: {OUTCOME[c['addressed_reason']]}"
        for r in (c.get("replies") or [])[:3]:
            s += f"\nreply by {r.get('author')}: {(r.get('body') or '')[:300]}"
    return s


def cluster(items: dict[str, str], effort: str, cfg: Config, spend: list[float], max_cost: float) -> list[dict]:
    """Group `items` (key -> text) by concern. Chunks of CLUSTER_CHUNK, then their groups are
    clustered again (recursively) by concern name so that groups from different chunks can merge.

    Returns:
        [{"concern", "members": [keys]}]; every key appears once (unplaced keys become singletons).
    """
    keys = list(items)

    def one(chunk: list[str]) -> list[dict]:
        if spend[0] >= max_cost:
            return []
        out, cost = _ask(CLUSTER.format(items="\n".join(f"{k}: {items[k]}" for k in chunk)), effort, cfg)
        spend[0] += cost
        print(f"  cluster {len(chunk)} -> {len(out)} groups ${cost:.2f} (total ${spend[0]:.2f})", flush=True)
        return [g for g in out if isinstance(g, dict) and g.get("members")]

    groups = []
    for i in range(0, len(keys), CLUSTER_CHUNK):
        groups += one(keys[i:i + CLUSTER_CHUNK])
    if len(keys) > CLUSTER_CHUNK and 1 < len(groups) < len(keys):
        # merge groups across chunks by their concern names (recursively while there are too many)
        names = {f"g{i}": g["concern"] for i, g in enumerate(groups)}
        meta = cluster(names, effort, cfg, spend, max_cost)
        groups = [{"concern": m["concern"], "members": [k for gk in m["members"] for k in groups[int(gk[1:])]["members"]]}
                  for m in meta]
    seen, out = set(), []
    for g in groups:
        mem = [k for k in g["members"] if k in items and k not in seen]
        seen.update(mem)
        if mem:
            out.append({"concern": g["concern"], "members": mem})
    out += [{"concern": items[k][:60], "members": [k]} for k in keys if k not in seen]
    return out


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


def update_rulebook(base_rules: list[dict], groups: list[dict], items: dict, evid: dict, out: str, cm: dict,
                    effort: str, cfg: Config, spend: list[float], max_cost: float,
                    workers: int = 4, n: int = 3, signals: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Apply new candidates (`items` keys "c...", grouped with the base entries "b<id>") to a rulebook.

    Groups of new candidates only become new entries (ABSTRACT, run `n` times and merged by
    MERGE_ABSTRACT: the level of abstraction varies from run to run). Groups that mix existing entries
    with candidates or failure signals, or hold several existing entries, go to REVISE: keep | evidence
    | generalize | merge | add | revise | retire | contradict. A revised entry must still explain its
    old evidence and corrected tests (else the revision is rejected).

    Existing entries change only on evidence that they are wrong: "revise" (rewrite, version + 1, the
    old text kept in "history") and "retire" are accepted only when the decision names a failure signal
    ("s..." keys; `signals` maps them to their records) or a contradicting candidate. Generalize and
    merge never rewrite: they add a parent principle with "members", and each member without one gets
    a "principle" link. `lmreview vet` then checks every kind of change on the source PRs.

    Returns:
        (the whole rulebook: base entries, changed or not, then new ones; the list of changes)
    """
    today = dt.date.today().isoformat()
    base = {f"b{r['id']}": {**r, "version": r.get("version", 1), "history": list(r.get("history") or [])}
            for r in base_rules}
    fresh = [(i, g) for i, g in enumerate(groups) if not any(k in base for k in g["members"])]
    revise = [(i, g) for i, g in enumerate(groups) if any(k in base for k in g["members"])
              and (any(k not in base for k in g["members"]) or len(g["members"]) > 1)]
    added, changes = [], []

    def show(k: str) -> str:
        if k in base:
            r = base[k]
            return (f"- {k} = existing entry {r['id']} (v{r['version']}, {r.get('kind')}): When {r.get('when')}: "
                    f"{r.get('expect')} | examples: {'; '.join(r.get('examples') or [])} | paths {r.get('paths') or []}")
        # the human comments too, with the code they were on (the same view as attribution): the
        # candidate may already be narrower than the principle the reviewer stated
        said = "\n".join("    " + _fmt(cm[e], rich=False).replace("\n", "\n    ") for e in evid.get(k, []) if e in cm)
        return f"- {k}: {items[k]}" + (f"\n  evidence:\n{said}" if said else "")

    def text(gb: list) -> str:
        return "\n\n".join(f"Group {i} ({g['concern']}):\n" + "\n".join(map(show, g["members"])) for i, g in gb)

    batches = [fresh[i:i + ABSTRACT_BATCH] for i in range(0, len(fresh), ABSTRACT_BATCH)]
    def abstract(gb: list) -> tuple[object, float]:
        # n drafts, then a merge that settles the level (abstraction varies run to run)
        def merge(ok: list) -> tuple[object, float]:
            drafts = "\n\n".join(f"Draft {i}:\n{json.dumps(d, indent=1)}" for i, (d, _) in enumerate(ok, 1))
            return _ask(MERGE_ABSTRACT.format(groups=text(gb), drafts=drafts), effort, cfg)
        e = ensemble(lambda: _ask(ABSTRACT.format(groups=text(gb)), effort, cfg), n, merge,
                     ok=lambda r: isinstance(r[0], list))
        return e.result[0], sum(c for _, c in e.runs) + (e.merge[1] if e.merge else 0.0)

    res, cost = capped_map(abstract, batches, workers,
                           max(0.0, max_cost - spend[0]), label=lambda gb: f"abstract {len(gb)} groups")
    spend[0] += cost
    for r in (x for part in res if isinstance(part, list) for x in part):
        if isinstance(r, dict) and r.get("expect") and isinstance(r.get("group"), int) and 0 <= r["group"] < len(groups):
            g = groups[r["group"]]
            ev = _uniq(e for k in g["members"] for e in evid.get(k, []))
            added.append((_entry(r), ev, g["concern"]))
            changes.append({"op": "add", "members": g["members"], "concern": g["concern"]})

    batches = [revise[i:i + ABSTRACT_BATCH] for i in range(0, len(revise), ABSTRACT_BATCH)]
    res, cost = capped_map(lambda gb: _ask(REVISE.replace("@GROUPS@", text(gb)), effort, cfg), batches, workers,
                           max(0.0, max_cost - spend[0]), label=lambda gb: f"revise {len(gb)} groups")
    spend[0] += cost
    for d in (x for part in res if isinstance(part, list) for x in part):
        if not isinstance(d, dict) or not isinstance(d.get("group"), int) or not 0 <= d["group"] < len(groups):
            continue
        g, op = groups[d["group"]], d.get("op")
        mem = [k for k in d.get("members") or [] if k in g["members"] and k not in base]
        bkeys = [f"b{x}" for x in d.get("rules") or [] if f"b{x}" in g["members"]]
        ev = _uniq(e for k in mem for e in evid.get(k, []))
        ch = {"op": op, "rules": [base[b]["id"] for b in bkeys], "members": mem, "concern": g["concern"]}
        if op == "evidence" and bkeys:
            base[bkeys[0]]["evidence"] = _uniq(list(base[bkeys[0]].get("evidence") or []) + ev)
        elif op in ("generalize", "merge") and bkeys and d.get("expect"):
            kids = [base[b]["id"] for b in bkeys]
            parent = _entry(d) | {"kind": "principle", "members": kids,
                                  "tests": [{**t, "from": base[b]["id"]} for b in bkeys for t in base[b].get("tests") or []]}
            added.append((parent, _uniq([e for b in bkeys for e in base[b].get("evidence") or []] + ev), g["concern"]))
            ch |= {"op": f"{op}-as-parent"}
        elif op in ("revise", "retire") and bkeys:
            sig = [k for k in d.get("members") or [] if k in g["members"] and k.startswith("s")
                   and (signals or {}).get(k, {}).get("rule") == base[bkeys[0]]["id"]]
            if not sig and not mem:  # no evidence that the entry is wrong: an existing entry is not touched
                ch |= {"op": f"{op}-refused", "why": "no failure signal or contradicting candidate"}
                changes.append(ch)
                continue
            r = base[bkeys[0]]
            why = {"signals": [(signals or {})[k] for k in sig], "comments": ev, "why": d.get("why")}
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
            added.append((_entry(d) | {"kind": d.get("kind") or "principle"}, ev, g["concern"]))
        elif op == "contradict" and bkeys:
            base[bkeys[0]]["contested"] = _uniq(list(base[bkeys[0]].get("contested") or []) + ev)
            ch["why"] = d.get("why")
        else:
            continue
        changes.append(ch)

    for k, x in (signals or {}).items():  # considered once: later distills do not reopen them
        b = base.get(f"b{x['rule']}")
        if b is not None and any(k in g["members"] for g in groups):
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
    for r in new:  # append-only parents: link their members, whose text stays as it was
        for m in r.get("members") or []:
            if m in by_id and not by_id[m].get("principle"):
                by_id[m]["principle"] = r["id"]
    for ch in changes:  # name new entries in the change log
        if ch["op"] in ("add",) or ch["op"].endswith("-as-parent"):
            ch["new"] = [r["id"] for r in new if set(r["evidence"]) & {e for k in ch["members"] for e in evid.get(k, [])}]
    return [finish(r) for r in base.values()] + new, changes


INDUCE = """Below is an LMCache review rulebook. Its principles each group several rules ("members") under
one operational check. The other entries stand alone. A reviewer does not carry dozens of one-off
rules; they carry a few principles and apply them with knowledge of the codebase.

Place the standalone entries:
- "attach": a standalone entry whose violation the check of an EXISTING principle would have caught
  goes under that principle. Attach only when the same question asked of the diff exposes it.
- "principles": two or more standalone entries that one NEW check would have caught together get a
  new principle. It must be applicable to any PR and must not be a platitude ("write clean code"); give
  it an operational check, a concrete question to ask of the diff whose answer exposes a violation.
  Read the reviewers' own words in the evidence, not just the rule text.
- Everything else stays standalone; do not force it. Nothing is rewritten or removed.

""" + GENERAL + """

Principles:
{principles}

Standalone entries:
{standalone}

Answer with one JSON block only:
```json
{{"attach": [{{"rule": "id", "principle": "id"}}],
 "principles": [{{"name": "short name", "when": "...", "expect": "...", "check": "the question to ask of the diff",
   "why": "one line", "members": ["ids"]}}]}}
```"""


def induce(rules: list[dict], cm: dict, effort: str, cfg: Config, spend: list[float], max_cost: float,
           out: str) -> tuple[list[dict], list[dict]]:
    """Step 6 of distill: place standalone entries under principles, append-only.

    One call over the whole book: a standalone entry may be attached to an existing principle (its
    `principle` link and the principle's `members` grow; no text changes), and standalone entries that
    one new check covers get a new parent principle (evidence and tests inherited, as in
    update_rulebook). Over the cost cap it does nothing.

    Returns:
        (the rulebook, change records).
    """
    act = [r for r in rules if r.get("status", "active") == "active"]
    ps = [r for r in act if r.get("members")]
    lone = [r for r in act if not r.get("members") and not r.get("principle")]
    if len(lone) < 2 or spend[0] >= max_cost:
        return rules, []

    def show(r: dict) -> str:
        ev = " | ".join(" ".join(cm[e]["body"].split())[:160] for e in (r.get("evidence") or [])[:2] if e in cm)
        return f"[{r['id']}] When {r.get('when')}: {r.get('expect')}" + (f"\n  comments: {ev}" if ev else "")

    try:
        res, c = _ask(INDUCE.format(principles="\n".join(map(show, ps)) or "(none)",
                                    standalone="\n".join(map(show, lone))), effort, cfg)
    except Exception as e:  # a failed induction leaves the book as it is
        print(f"induce failed: {e}")
        return rules, []
    spend[0] += c
    if not isinstance(res, dict):
        return rules, []
    by = {r["id"]: r for r in rules}
    pids, lids = {r["id"] for r in ps}, {r["id"] for r in lone}
    changes, placed = [], set()
    for a in res.get("attach") or []:
        r, p = a.get("rule"), a.get("principle")
        if r in lids and p in pids and r not in placed:
            by[r]["principle"] = p
            by[p]["members"] = [*by[p]["members"], r]
            placed.add(r)
            changes.append({"op": "induce-attach", "rules": [p], "members": [r], "concern": by[p].get("name") or p})
    used, i = set(by), 0
    for p in res.get("principles") or []:
        mem = [m for m in p.get("members") or [] if m in lids and m not in placed]
        if len(mem) < 2 or not p.get("when") or not p.get("expect"):
            continue
        i += 1
        while f"{out}-P{i}" in used:
            i += 1
        pid = f"{out}-P{i}"
        used.add(pid)
        ms = [by[m] for m in mem]
        rules.append({"id": pid, "version": 1, "status": "active", "kind": "principle", "name": p.get("name"),
                      "when": p["when"], "expect": p["expect"] + (f" Check: {p['check']}" if p.get("check") else ""),
                      "why": p.get("why"), "examples": [f"{m['id']}: {m['when'][:160]}" for m in ms][:4],
                      "paths": [], "members": mem,
                      "evidence": _uniq([e for m in ms for e in m.get("evidence") or []]),
                      "tests": [{**t, "from": m["id"]} for m in ms for t in m.get("tests") or []]})
        for m in ms:
            m["principle"] = pid
        placed |= set(mem)
        changes.append({"op": "induce-parent", "new": [pid], "members": mem, "concern": p.get("name") or ""})
    return rules, changes


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
            bad = {a["id"]: a.get("why") for a in json.loads(sp.read_text()).get("ai") or [] if a.get("valid") is False}
            run = json.loads(f.read_text())
            if prs and run["pr"] not in prs:
                continue
            for x in run.get("findings") or []:
                r = x.get("rule")
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
                               f"| judge: {bad[x['id']]}" + _code_at(cfg, run["commit"], x.get("locations") or []))
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
    """rules/<name>.meta.json: how the book was made ({"base", "runs", "prs", "samples", "seen"}).
    A book without one (made before) counts its evidence comments as seen."""
    p = _meta_path(name)
    if p.exists():
        return json.loads(p.read_text())
    rules = [json.loads(l) for l in book_path(name).open() if l.strip()]
    return {"seen": sorted({int(e) for r in rules for e in r.get("evidence") or []})}


def write_meta(name: str, meta: dict) -> None:
    """Write rules/<name>.meta.json."""
    _meta_path(name).write_text(json.dumps(meta, indent=1) + "\n")


def _meta_path(name: str) -> pathlib.Path:
    """rules/<name>.meta.json, or the .meta.json next to a state book."""
    b = book_path(name)
    return b.with_name(b.stem + ".meta.json")


def judge_runs(cfg: Config, reviewer: str, prs: set[int] | None, split: str, max_cost: float) -> tuple[list, float]:
    """Step 1 of distill: judge `reviewer`'s runs on `split` (only `prs`, if given) against the human
    comments; already judged runs are read from disk. Runs over the cost cap stay unjudged and are skipped.

    Returns:
        ([(run, normalized score)], cost).
    """
    from .progress import note
    from .score import score_one
    ss, cm = load_gold(cfg)
    out, cost = [], 0.0
    files = sorted((cfg.data / "runs" / reviewer).glob("*.json"))
    for f in files:
        run = json.loads(f.read_text())
        s = ss.get((run["pr"], run["commit"]))
        if not s or s.get("split") != split or (prs and run["pr"] not in prs) or run.get("findings") is None:
            continue
        sp = cfg.data / "scores" / reviewer / f.name
        if not sp.exists() and cost >= max_cost:
            continue
        sp.parent.mkdir(parents=True, exist_ok=True)
        was = sp.exists()
        sc = score_one(cfg, run, s, [cm[i] for i in s["gold_ids"]], sp, "high")
        cost += 0 if was else sc.get("cost", 0)
        out.append((run, _normalize(sc, run)))
        if not was:
            n = out[-1][1]
            note(f"judged #{run['pr']}@{run['commit'][:8]}: {sum(bool(h['matched_ai']) for h in n['human'])}/{len(n['human'])} "
                 f"human comments found (${sc.get('cost', 0):.2f}, total ${cost:.2f} of ${max_cost:.0f})")
    return out, cost


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


def attach_signals(groups: list[dict], items: dict, evid: dict, text: dict, rec: dict) -> None:
    """Put each failure signal into the group of the entry it is about (in place), so REVISE sees it."""
    for k, r in rec.items():
        g = next((g for g in groups if f"b{r['rule']}" in g["members"]), None)
        if g is not None:
            g["members"].append(k)
            items[k], evid[k] = text[k], []


def distill(out: str, base: str | None = None, misses_of: str | None = None, area: str | None = None,
            limit: int | None = None, effort: str = "high", workers: int = 4, max_cost: float = 5.0,
            reuse: str | None = None, keep_unaddressed: bool = False, cfg: Config | None = None,
            n: int = 3, do_induce: bool = True, prs: list[int] | None = None,
            comments: list[int] | None = None, notes: dict[int, str] | None = None) -> str:
    """Build rules/<out>.jsonl; returns a short summary. `max_cost` 0 = plan only (prints the estimate).

    distill does not review. It learns from review runs that exist: `misses_of` names the reviewer
    whose runs to use, normally `<prompt>+<base>@high-rc` run with `lmreview review` on the train PRs
    `prs`, so that the misses are the base book's own.
    Steps: (1) judge those runs against the human comments (cached); the missed comments are what to
    learn, and findings citing a base entry that were judged invalid are its failure signals;
    (2) attribute the missed comments; (3) cluster them with the base entries and their signals;
    (4) abstract each group; (5) update the book (additions; revise/retire only on a failure signal or
    an opposite comment); (6) induce principles over the standalone entries (`do_induce`). Whether the
    result is kept is `lmreview vet`'s call.

    `comments`: learn exactly these comments (the ledger's to_distill, see state.py) instead of the misses
    of `misses_of` minus the base's "seen"; `notes`: comment id -> what earlier attempts made of it."""
    cfg = cfg or Config()
    if book_path(out).exists():
        raise FileExistsError(f"{book_path(out)} exists; pick a new name")
    pre, judged = 0.0, None
    if misses_of and max_cost > 0:  # step 1: judge the runs (free when already judged)
        from .reviewer import parse_reviewer
        if base and parse_reviewer(misses_of.split("#")[0])[1] != base:
            print(f"note: {misses_of} does not use {base}: its misses are not the base book's own", flush=True)
        note(f"[1/6] judge the runs of {misses_of} (cached ones are free)")
        judged, pre = judge_runs(cfg, misses_of, set(prs or []) or None, "train", max_cost / 2)
        note(f"      {len(judged)} runs judged (${pre:.2f})")
    if comments is not None:
        _, cm0 = load_gold(cfg)
        cs, seen = [cm0[i] for i in comments if i in cm0], set()
    else:
        cs = inputs(cfg, misses_of, area, "train", keep_unaddressed)
        seen = set(book_meta(base).get("seen") or []) if base else set()  # comments an earlier distill already processed
    if prs:
        cs = [c for c in cs if c["pr"] in set(prs)]
    n_seen = sum(c["id"] in seen for c in cs)
    cs = [c for c in cs if c["id"] not in seen][:limit]
    if n_seen:
        print(f"skipping {n_seen} comments already processed into {base} or its ancestors", flush=True)
    by_id = {c["id"]: c for c in cs}
    batches = [cs[i:i + BATCH] for i in range(0, len(cs), BATCH)]
    n_cand = int(len(cs) * 0.7)  # pilot: ~75% learnable
    est = (0 if reuse else len(batches) * EST["attribute"]) + (n_cand // CLUSTER_CHUNK + 1) * EST["cluster"] \
        + (n_cand * 0.6 // ABSTRACT_BATCH + 1) * EST["abstract"] * (n + 1 if n > 1 else 1) \
        + (EST["abstract"] if do_induce else 0)  # n drafts + merge; one induce call
    note(f"distill {out}: {len(cs)} comments" + (f" missed by {misses_of}" if misses_of else "")
         + f", {len(batches)} attribution batches; est ${est:.1f}, cap ${max_cost:.1f}")
    if max_cost <= 0:
        return "plan only (max-cost 0); nothing written"

    work = cfg.data / "distill" / out
    work.mkdir(parents=True, exist_ok=True)
    if reuse:  # attribution of an earlier run (same inputs): only cluster + abstract are re-done
        res, spent = [[json.loads(l) for l in (cfg.data / "distill" / reuse / "attribution.jsonl").open()]], 0.0
    else:
        note(f"[2/6] attribute {len(cs)} comments in {len(batches)} batches")
        res, spent = capped_map(lambda b: _ask(ATTRIBUTE.format(comments="\n\n".join(map(_fmt, b))), effort, cfg),
                                batches, workers, max_cost - pre, label=lambda b: f"attribute {len(b)}")
        spent += pre
    att = [{**a, "id": _id(a.get("id"))} for r in res if isinstance(r, list) for a in r if isinstance(a, dict)]
    att = [a for a in att if a["id"] in by_id]
    (work / "attribution.jsonl").write_text("".join(json.dumps(a) + "\n" for a in att))
    note(f"      attribution: {dict(C.Counter(a.get('kind') for a in att))}; {len(cs) - len(att)} not attributed")

    # candidates: learnable comments + entries of the base rulebook (which carry their evidence)
    items, evid = {}, {}
    for a in att:
        if a.get("kind") == "learnable" and a.get("rule"):
            k = f"c{a['id']}"
            items[k] = f"{a['rule']} (PR #{by_id[a['id']]['pr']}; paths {a.get('paths') or []})" + (
                f" [earlier attempts failed, write it differently: {notes[a['id']]}]" if (notes or {}).get(a["id"]) else "")
            evid[k] = [a["id"]]
    if base:
        for r in map(json.loads, filter(str.strip, book_path(base).open())):
            if r.get("status", "active") != "active":  # retired entries are carried over untouched
                continue
            k = f"b{r['id']}"
            items[k] = f"When {r.get('when')}: {r.get('expect')} (existing rule; paths {r.get('paths') or []})"
            evid[k] = r.get("evidence") or []
    spend = [spent]
    note(f"[3/6] cluster {sum(k.startswith('c') for k in items)} candidates with {sum(k.startswith('b') for k in items)} "
         f"existing entries (${spend[0]:.2f} so far)")
    groups = cluster(items, effort, cfg, spend, max_cost)
    _, cm = load_gold(cfg)
    base_rules = [json.loads(l) for l in book_path(base).open() if l.strip()] if base else []
    sig_text, sig = failure_signals(base_rules, cfg, reviewer=misses_of, prs=set(prs or []) or None) \
        if base_rules and misses_of else ({}, {})
    attach_signals(groups, items, evid, sig_text, sig)
    note(f"      {len(groups)} groups, {sum(any(m.startswith('c') for m in g['members']) for g in groups)} with new "
         f"candidates; {len(sig)} failure signals attached")
    note(f"[4-5/6] abstract new groups and update the book (${spend[0]:.2f} so far)")
    (work / "clusters.json").write_text(json.dumps(groups, indent=1))
    rules, changes = update_rulebook(base_rules, groups, items, evid, out, cm, effort, cfg, spend, max_cost, workers,
                                     n=n, signals=sig)
    note(f"      changes: {dict(C.Counter(ch['op'] for ch in changes))}")
    if do_induce:
        note(f"[6/6] induce principles over standalone entries (${spend[0]:.2f} so far)")
        rules, more = induce(rules, cm, effort, cfg, spend, max_cost, out)
        changes += more
        note(f"      induce: {dict(C.Counter(ch['op'] for ch in more)) or 'no change'}")
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
                     "samples": sorted({f"{r['pr']}@{r['commit'][:8]}" for r, _ in judged or []}),
                     "seen": sorted(seen | {a["id"] for a in att})})  # vet reads this; the next distill skips "seen"

    kinds = C.Counter(a.get("kind") for a in att)
    md = [f"# Rulebook {out}", "",
          f"From {len(cs)} train comments" + (f" missed by {misses_of}" if misses_of else "")
          + (f", area {area}" if area else "") + (f", extending {base}" if base else "")
          + f"; attribution: {dict(kinds)}; {len(groups)} concern groups; cost ${spent:.2f}",
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
            f"{len(cs)} comments ({dict(kinds)}), {len(groups)} groups, ${spent:.2f}")


def coverage(rules_name: str, split: str = "test", area: str | None = None, misses_of: str | None = None,
             effort: str = "high", workers: int = 4, max_cost: float = 2.0, cfg: Config | None = None) -> str:
    """Which rulebook entries explain the human comments of `split` (only those `misses_of` missed, if
    given). Writes reports/coverage_<rules>_<split>.md (and .json: the explained comments); returns its headline. `max_cost` 0 = plan only."""
    cfg = cfg or Config()
    rules = [r for r in map(json.loads, filter(str.strip, book_path(rules_name).open()))
             if r.get("status", "active") == "active"]
    cs = inputs(cfg, misses_of, area, split, keep_unaddressed=True)
    batches = [cs[i:i + BATCH] for i in range(0, len(cs), BATCH)]
    print(f"coverage {rules_name} on {split}" + (f" ({area})" if area else "") + f": {len(cs)} comments, "
          f"{len(batches)} calls; est ${len(batches) * EST['attribute']:.1f}, cap ${max_cost:.1f}", flush=True)
    if max_cost <= 0:
        return "plan only (max-cost 0)"
    rtext = "\n".join(f"{r['id']}: when {r.get('when')} -> {r.get('expect')}" for r in rules)
    res, spent = capped_map(lambda b: _ask(COVERAGE.format(rules=rtext, comments="\n\n".join(_fmt(c, False) for c in b)),
                                           effort, cfg), batches, workers, max_cost, label=lambda b: f"coverage {len(b)}")
    hits = {}
    for part in res:
        for x in part if isinstance(part, list) else []:
            if isinstance(x, dict) and _id(x.get("id")) in {c["id"] for c in cs}:
                hits[_id(x["id"])] = [r for r in x.get("rules") or [] if any(r == y["id"] for y in rules)]
    covered = [i for i, rs in hits.items() if rs]
    use = C.Counter(r for rs in hits.values() for r in rs)
    byid = {r["id"]: r for r in rules}
    L = [f"# Coverage of {rules_name} on {split}" + (f" ({area})" if area else "")
         + (f", comments missed by {misses_of}" if misses_of else ""), "",
         f"- comments checked: {len(hits)} of {len(cs)}; explained by some entry: {len(covered)} "
         f"({len(covered) / max(len(hits), 1):.0%})",
         f"- entries used at least once: {len(use)} of {len(rules)}; cost ${spent:.2f}", "",
         "| entry | kind | train PRs | held-out comments explained | rule |", "| --- | --- | --- | --- | --- |"]
    for rid, n in use.most_common():
        r = byid[rid]
        L.append(f"| {rid} | {r.get('kind')} | {r.get('n_prs')} | {n} | When {r.get('when')}: {(r.get('expect') or '')[:100]} |")
    (REPORTS / f"coverage_{rules_name}_{split}.md").write_text("\n".join(L) + "\n")
    (REPORTS / f"coverage_{rules_name}_{split}.json").write_text(json.dumps(
        [{"comment": i, "pr": next(c["pr"] for c in cs if c["id"] == i), "rules": rs} for i, rs in hits.items() if rs], indent=1))
    return "\n".join(L[:5])


TEST_RESULTS = ("corrected", "both-hit", "both-miss", "uncited-gain", "regressed")


def record_test(name: str, rule: str, target: str, control: str, treated: str, result: str, note: str = "",
                comments: list[int] | None = None) -> None:
    """Append one A/B record to entry `rule` of rules/<name>.jsonl (entry field "tests").

    A fair target is a PR the rule was not distilled from whose diff ADDS code meeting the rule's
    condition (moved code does not count), reviewed by `control` (same prompt, without the rule) and
    `treated` (with it). result: corrected = control missed, treated hit citing the rule; both-hit /
    both-miss = no signal; uncited-gain = treated hit without citing it; regressed = treated lost a hit.
    `comments`: the human comment ids the rule is tested on (what `lmreview regress` replays and checks).
    """
    if result not in TEST_RESULTS:
        raise ValueError(f"result must be one of {TEST_RESULTS}")
    path = book_path(name)
    rules = [json.loads(l) for l in path.open() if l.strip()]
    hit = [r for r in rules if r["id"] == rule]
    if not hit:
        raise KeyError(f"{rule} not in {name}")
    hit[0].setdefault("tests", []).append({"target": target, "control": control, "with": treated,
                                           "result": result, "note": note, "comments": comments or [],
                                           "date": dt.date.today().isoformat()})
    path.write_text("".join(json.dumps(r) + "\n" for r in rules))


def audit(name: str, cfg: Config | None = None) -> str:
    """Free checks that suggest retiring entries of rules/<name> (it never changes the rulebook).

    - paths gone: the entry's path globs match no file on dev any more
    - judged invalid: findings that cite the entry (runs of reviewers using this rulebook) and how
      the judge rated them
    - contested: later human comments asked for the opposite (set by distill's revise step)
    - tests: the entry's A/B records (see record_test); "corrected" = the control missed, the rule
      reviewer hit with a finding citing the entry. An active entry with no corrected test is a candidate.
    Writes reports/audit_<name>.md; returns it.
    """
    from .reviewer import parse_reviewer
    cfg = cfg or Config()
    rules = [json.loads(l) for l in book_path(name).open() if l.strip()]
    files = subprocess.run(["git", "-C", str(cfg.repo), "ls-tree", "-r", "--name-only", "origin/dev"],
                           capture_output=True, text=True, check=True).stdout.split()
    cited, valid = C.Counter(), C.Counter()
    for d in (cfg.data / "runs").iterdir():
        try:
            uses = d.is_dir() and not d.name.startswith("_") and parse_reviewer(d.name.split("#")[0])[1] == name
        except ValueError:
            uses = False
        if not uses:
            continue
        for p in d.glob("*.json"):
            run = json.loads(p.read_text())
            sp = cfg.data / "scores" / d.name / p.name
            judged = {a["id"]: a.get("valid") for a in json.loads(sp.read_text()).get("ai", [])} if sp.exists() else {}
            for f in run.get("findings") or []:
                if f.get("rule"):
                    cited[f["rule"]] += 1
                    valid[f["rule"]] += judged.get(f["id"]) is True
    L = [f"# Audit of rulebook {name}", "", "Suggestions only; retiring an entry is a decision.", "",
         "| entry | status | v | evidence PRs | paths on dev | findings citing it | judged valid | tests (corrected/run) "
         "| suggestion |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rules:
        gone = bool(r.get("paths")) and not any(fnmatch.fnmatch(f, g) for g in r["paths"] for f in files)
        n, ok = cited[r["id"]], valid[r["id"]]
        why = (["retire? paths gone"] if gone else []) + (["review: mostly judged invalid"] if n >= 3 and ok / n < 0.5 else []) \
            + ([f"contested by {len(r['contested'])} comments"] if r.get("contested") else [])
        tests = r.get("tests") or []
        fixed = sum(t["result"] == "corrected" for t in tests)
        if r.get("status", "active") == "active" and not fixed:
            why.append("candidate: no corrected test" + ("" if tests else " (no target yet)"))
        L.append(f"| {r['id']} | {r.get('status', 'active')} | {r.get('version', 1)} | {r.get('n_prs')} | "
                 f"{'gone' if gone else 'ok'} | {n} | {ok} | {fixed}/{len(tests)} | {'; '.join(why)} |")
    (REPORTS / f"audit_{name}.md").write_text("\n".join(L) + "\n")
    return "\n".join(L)


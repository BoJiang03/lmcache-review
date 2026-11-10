"""`lmreview distill`: turn human review comments into a rulebook; `coverage`: test whether it reuses.

Input: human review comments on train samples. With `misses_of`, only the ones that reviewer
missed (human-only, from its judge results); that is the intended input: learn what the AI lacks.
Comments whose file never changed again although the PR got later commits are dropped (likely not
taken); the rest go in with their outcome and thread replies.
  1. attribute (batches, no tools): learnable | context | not_issue | rejected (declined in the
     thread); for learnable ones a candidate rule
  2. cluster (no tools, all areas together): group candidates by underlying concern
  3. abstract (batches of clusters, no tools): one entry per cluster, or none
       principle  a review principle the reviewer applied (one instance is enough)
       knowledge  a fact / invariant about this codebase or the engine a reviewer must know there
     evidence = the cluster's comments (computed here, not by the model); n_prs is informational
Output: rules/<out>.jsonl, rules/<out>.md (readable), <data>/distill/<out>/{attribution,clusters}.json*.
Never reads test/new samples.

coverage(): for human comments of a split (default test), which entries explain them. Rules that
reuse explain held-out comments; this is checked before spending on reviewer A/B runs.
"""

from __future__ import annotations

import collections as C
import datetime as dt
import fnmatch
import json
import subprocess
import tempfile

from . import llm
from .budget import capped_map
from .config import RULES, Config
from .ensemble import ensemble
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
entries (keys "b...", with id, text and examples) and/or new candidate rules (keys "c...", from human
review comments the reviewer missed), grouped as one concern. Decide how the rulebook changes. Every
key of a group appears in exactly one decision of that group:
- "keep": an existing entry stays as written (no candidate concerns it).
- "evidence": candidates are already instances of an existing entry AS WRITTEN: a reviewer applying it
  to their change would have raised their point. The entry's text stays.
- "generalize": candidates ask for the same kind of change as an existing entry, but its "when" or
  "expect" is too narrow to make a reviewer raise their point. Rewrite the entry at the lowest level
  that covers its old examples AND the candidates; never drop what it asked for before; keep its old
  examples and add one for the candidates.
- "merge": two or more existing entries are one concern; write the one entry that covers them all.
- "add": candidates ask for a different change than every existing entry; write a new entry.
- "contradict": candidates ask for the OPPOSITE of an existing entry. Do not rewrite it; say why.
Fields of a written entry (generalize, merge, add): "kind" (principle | knowledge), "when", "expect",
"why" (one line), "examples" (short concrete instances), "paths" (globs, [] = anywhere).

""" + GENERAL + """

Groups:
@GROUPS@

Answer with one JSON block only, one object per decision:
```json
[{"group": 0, "op": "keep|evidence|generalize|merge|add|contradict", "rules": ["<existing id>"],
  "members": ["c123"], "kind": "...", "when": "...", "expect": "...", "why": "...", "examples": ["..."],
  "paths": []}]
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
                    workers: int = 4, n: int = 3) -> tuple[list[dict], list[dict]]:
    """Apply new candidates (`items` keys "c...", grouped with the base entries "b<id>") to a rulebook.

    Groups of new candidates only become new entries (ABSTRACT, run `n` times and merged by
    MERGE_ABSTRACT: the level of abstraction varies from run to run). Groups that mix existing entries
    with candidates, or hold several existing entries, go to REVISE: keep | evidence | generalize |
    merge | add | contradict. A generalized or merged entry keeps its id, gets version + 1 and
    a history line, and must still explain all its old evidence (else the rewrite is rejected and
    becomes a new entry). Merged-away entries are retired, never deleted.

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
        # the human words too: the candidate may already be narrower than the principle the reviewer stated
        said = " | ".join(" ".join((cm[e].get("body") or "").split())[:400] for e in evid.get(k, []) if e in cm)
        return f"- {k}: {items[k]}" + (f"\n    reviewer said: \"{said}\"" if said else "")

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
            r = base[bkeys[0]]
            old_ev = _uniq(e for b in bkeys for e in base[b].get("evidence") or [])
            if spend[0] >= max_cost:  # no budget left to verify the rewrite: keep the entries as they are
                ch |= {"op": f"{op}-skipped", "why": "cost cap reached before the regression check"}
                changes.append(ch)
                continue
            lost = _regress({"id": r["id"], **_entry(d)}, old_ev, cm, effort, cfg, spend)
            if lost:  # the rewrite would stop explaining what the entry stood for: keep it, add the rewrite
                ch |= {"op": f"{op}-rejected", "lost": lost}
                if ev:  # a rewrite with no new evidence would only duplicate the entries kept
                    added.append((_entry(d) | {"kind": d.get("kind") or r.get("kind")}, ev, g["concern"]))
            else:
                r["history"].append({"version": r["version"], "until": today, "by": out, "reason": op,
                                     **{k: r.get(k) for k in ("when", "expect", "examples", "paths")}})
                r.update({k: v for k, v in _entry(d).items() if v is not None})
                r["version"] += 1
                r["evidence"] = _uniq(old_ev + ev)
                for b in bkeys[1:]:
                    base[b]["status"] = "retired"
                    base[b]["retired"] = {"date": today, "by": out, "reason": f"merged into {r['id']}"}
                ch |= {"version": r["version"], "when": r["when"], "expect": r["expect"]}
        elif op == "add" and d.get("expect") and mem:
            added.append((_entry(d) | {"kind": d.get("kind") or "principle"}, ev, g["concern"]))
        elif op == "contradict" and bkeys:
            base[bkeys[0]]["contested"] = _uniq(list(base[bkeys[0]].get("contested") or []) + ev)
            ch["why"] = d.get("why")
        else:
            continue
        changes.append(ch)

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
    for ch in changes:  # name new entries in the change log
        if ch["op"] in ("add",) or ch["op"].endswith("-rejected"):
            ch["new"] = [r["id"] for r in new if set(r["evidence"]) & {e for k in ch["members"] for e in evid.get(k, [])}]
    return [finish(r) for r in base.values()] + new, changes


def distill(out: str, base: str | None = None, misses_of: str | None = None, area: str | None = None,
            limit: int | None = None, effort: str = "high", workers: int = 4, max_cost: float = 5.0,
            reuse: str | None = None, keep_unaddressed: bool = False, cfg: Config | None = None,
            n: int = 3) -> str:
    """Build rules/<out>.jsonl; returns a short summary. `max_cost` 0 = plan only (prints the estimate)."""
    cfg = cfg or Config()
    if (RULES / f"{out}.jsonl").exists():
        raise FileExistsError(f"rules/{out}.jsonl exists; pick a new name")
    cs = inputs(cfg, misses_of, area, "train", keep_unaddressed)[:limit]
    by_id = {c["id"]: c for c in cs}
    batches = [cs[i:i + BATCH] for i in range(0, len(cs), BATCH)]
    n_cand = int(len(cs) * 0.7)  # pilot: ~75% learnable
    est = (0 if reuse else len(batches) * EST["attribute"]) + (n_cand // CLUSTER_CHUNK + 1) * EST["cluster"] \
        + (n_cand * 0.6 // ABSTRACT_BATCH + 1) * EST["abstract"] * (n + 1 if n > 1 else 1)  # n drafts + merge
    print(f"distill {out}: {len(cs)} comments" + (f" missed by {misses_of}" if misses_of else "")
          + f", {len(batches)} attribution batches; est ${est:.1f}, cap ${max_cost:.1f}", flush=True)
    if max_cost <= 0:
        return "plan only (max-cost 0); nothing written"

    work = cfg.data / "distill" / out
    work.mkdir(parents=True, exist_ok=True)
    if reuse:  # attribution of an earlier run (same inputs): only cluster + abstract are re-done
        res, spent = [[json.loads(l) for l in (cfg.data / "distill" / reuse / "attribution.jsonl").open()]], 0.0
    else:
        res, spent = capped_map(lambda b: _ask(ATTRIBUTE.format(comments="\n\n".join(map(_fmt, b))), effort, cfg),
                                batches, workers, max_cost, label=lambda b: f"attribute {len(b)}")
    att = [{**a, "id": _id(a.get("id"))} for r in res if isinstance(r, list) for a in r if isinstance(a, dict)]
    att = [a for a in att if a["id"] in by_id]
    (work / "attribution.jsonl").write_text("".join(json.dumps(a) + "\n" for a in att))

    # candidates: learnable comments + entries of the base rulebook (which carry their evidence)
    items, evid = {}, {}
    for a in att:
        if a.get("kind") == "learnable" and a.get("rule"):
            k = f"c{a['id']}"
            items[k] = f"{a['rule']} (PR #{by_id[a['id']]['pr']}; paths {a.get('paths') or []})"
            evid[k] = [a["id"]]
    if base:
        for r in map(json.loads, (RULES / f"{base}.jsonl").open()):
            if r.get("status", "active") != "active":  # retired entries are carried over untouched
                continue
            k = f"b{r['id']}"
            items[k] = f"When {r.get('when')}: {r.get('expect')} (existing rule; paths {r.get('paths') or []})"
            evid[k] = r.get("evidence") or []
    spend = [spent]
    groups = cluster(items, effort, cfg, spend, max_cost)
    (work / "clusters.json").write_text(json.dumps(groups, indent=1))

    _, cm = load_gold(cfg)
    base_rules = [json.loads(l) for l in (RULES / f"{base}.jsonl").open() if l.strip()] if base else []
    rules, changes = update_rulebook(base_rules, groups, items, evid, out, cm, effort, cfg, spend, max_cost, workers,
                                     n=n)
    spent = spend[0]
    (work / "changes.json").write_text(json.dumps(changes, indent=1))
    RULES.mkdir(exist_ok=True)
    (RULES / f"{out}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rules))

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
            md += [f"- **{r['id']}** v{r.get('version', 1)} ({r['area']}, {r['n_prs']} PRs) When {r['when']}: {r['expect']}",
                   f"  - why: {r.get('why') or ''}; paths: {r.get('paths') or 'any'}",
                   f"  - e.g. {' / '.join(r.get('examples') or [])}", f"  - evidence: {ev}"]
        md.append("")
    (RULES / f"{out}.md").write_text("\n".join(md) + "\n")
    return (f"rules/{out}.jsonl: {len(rules)} entries ({dict(C.Counter(r['kind'] for r in rules))}) from "
            f"{len(cs)} comments ({dict(kinds)}), {len(groups)} groups, ${spent:.2f}")


def coverage(rules_name: str, split: str = "test", area: str | None = None, misses_of: str | None = None,
             effort: str = "high", workers: int = 4, max_cost: float = 2.0, cfg: Config | None = None) -> str:
    """Which rulebook entries explain the human comments of `split` (only those `misses_of` missed, if
    given). Writes reports/coverage_<rules>_<split>.md (and .json: the explained comments); returns its headline. `max_cost` 0 = plan only."""
    cfg = cfg or Config()
    rules = [r for r in map(json.loads, filter(str.strip, (RULES / f"{rules_name}.jsonl").open()))
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


def audit(name: str, cfg: Config | None = None) -> str:
    """Free checks that suggest retiring entries of rules/<name> (it never changes the rulebook).

    - paths gone: the entry's path globs match no file on dev any more
    - judged invalid: findings that cite the entry (runs of reviewers using this rulebook) and how
      the judge rated them
    - contested: later human comments asked for the opposite (set by distill's revise step)
    Writes reports/audit_<name>.md; returns it.
    """
    from .reviewer import parse_reviewer
    cfg = cfg or Config()
    rules = [json.loads(l) for l in (RULES / f"{name}.jsonl").open() if l.strip()]
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
         "| entry | status | v | evidence PRs | paths on dev | findings citing it | judged valid | suggestion |",
         "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rules:
        gone = bool(r.get("paths")) and not any(fnmatch.fnmatch(f, g) for g in r["paths"] for f in files)
        n, ok = cited[r["id"]], valid[r["id"]]
        why = (["retire? paths gone"] if gone else []) + (["review: mostly judged invalid"] if n >= 3 and ok / n < 0.5 else []) \
            + ([f"contested by {len(r['contested'])} comments"] if r.get("contested") else [])
        L.append(f"| {r['id']} | {r.get('status', 'active')} | {r.get('version', 1)} | {r.get('n_prs')} | "
                 f"{'gone' if gone else 'ok'} | {n} | {ok} | {'; '.join(why)} |")
    (REPORTS / f"audit_{name}.md").write_text("\n".join(L) + "\n")
    return "\n".join(L)


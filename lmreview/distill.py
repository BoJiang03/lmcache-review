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
import json
import tempfile

from . import llm
from .budget import capped_map
from .config import RULES, Config
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
  the principle or fact behind the comment, not a restatement of this one fix. Keep what the
  reviewer asked the author to DO (e.g. "explain multi-step state changes in a docstring with a
  worked example of values before/after", not just "docstrings should be clear").
- "context": it needs knowledge outside the code (an offline decision, roadmap, another PR's state).
- "not_issue": a question, praise, or nothing actionable.
- "rejected": the thread shows the suggestion was declined, withdrawn or judged wrong.
Also give "paths": glob patterns of where the rule applies ([] = anywhere).

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

ABSTRACT = """Each group below holds candidate review rules from LMCache human review comments that share
one concern (with the PR numbers they came from). For each group write ONE rulebook entry for the
reviewer, or skip the group if it carries no reusable principle or knowledge:
- "principle": the review principle at the level a reviewer would apply it to other changes (the
  group's candidates are instances); specific enough to check against a diff. "expect" states the
  change a reviewer should ask for, as the candidates did; do not generalize it into a vaguer goal.
  But neither "when" nor "expect" may carry the instances' particulars: "when" names a KIND of
  situation a reviewer can recognize in any diff (e.g. "a docstring explains in prose a process the
  reader has to simulate in their head"), not the mechanisms, identifiers or parameters of the PRs it
  came from (e.g. not "appending/relocating block ids, nulling slots"); those go in "examples" only.
- "knowledge": a fact or invariant about this codebase or the engine, and what a reviewer must
  therefore check when touching that code; scope it with "paths".
Fields: "group" (its number), "kind", "when" (the kind of change it applies to), "expect" (what to
check or require; checkable), "why" (one line), "examples" (1-2 short concrete instances), "paths"
(glob patterns, [] = anywhere).

Groups:
{groups}

Answer with one JSON block only:
```json
[{{"group": 0, "kind": "principle", "when": "...", "expect": "...", "why": "...", "examples": ["..."], "paths": []}}]
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


def distill(out: str, base: str | None = None, misses_of: str | None = None, area: str | None = None,
            limit: int | None = None, effort: str = "high", workers: int = 4, max_cost: float = 5.0,
            reuse: str | None = None, keep_unaddressed: bool = False, cfg: Config | None = None) -> str:
    """Build rules/<out>.jsonl; returns a short summary. `max_cost` 0 = plan only (prints the estimate)."""
    cfg = cfg or Config()
    if (RULES / f"{out}.jsonl").exists():
        raise FileExistsError(f"rules/{out}.jsonl exists; pick a new name")
    cs = inputs(cfg, misses_of, area, "train", keep_unaddressed)[:limit]
    by_id = {c["id"]: c for c in cs}
    batches = [cs[i:i + BATCH] for i in range(0, len(cs), BATCH)]
    n_cand = int(len(cs) * 0.7)  # pilot: ~75% learnable
    est = (0 if reuse else len(batches) * EST["attribute"]) + (n_cand // CLUSTER_CHUNK + 1) * EST["cluster"] \
        + (n_cand * 0.6 // ABSTRACT_BATCH + 1) * EST["abstract"]
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
            k = f"b{r['id']}"
            items[k] = f"When {r.get('when')}: {r.get('expect')} (existing rule; paths {r.get('paths') or []})"
            evid[k] = r.get("evidence") or []
    spend = [spent]
    groups = cluster(items, effort, cfg, spend, max_cost)
    (work / "clusters.json").write_text(json.dumps(groups, indent=1))

    _, cm = load_gold(cfg)
    gbatches = [list(enumerate(groups))[i:i + ABSTRACT_BATCH] for i in range(0, len(groups), ABSTRACT_BATCH)]

    def abstract(gb):
        text = "\n\n".join(f"Group {i} ({g['concern']}):\n" + "\n".join(f"- {items[k]}" for k in g["members"])
                           for i, g in gb)
        return _ask(ABSTRACT.format(groups=text), effort, cfg)

    res, cost = capped_map(abstract, gbatches, workers, max(0.0, max_cost - spend[0]),
                           label=lambda gb: f"abstract {len(gb)} groups")
    spent = spend[0] + cost
    rules = []
    for r in (x for part in res if isinstance(part, list) for x in part):
        if not isinstance(r, dict) or not r.get("expect") or not isinstance(r.get("group"), int) \
                or not 0 <= r["group"] < len(groups):
            continue
        g = groups[r["group"]]
        ev = list(dict.fromkeys(e for k in g["members"] for e in evid.get(k, []) if e in cm))
        rules.append({k: r.get(k) for k in ("kind", "when", "expect", "why", "examples", "paths")}
                     | {"concern": g["concern"], "evidence": ev, "n_prs": len({cm[e]["pr"] for e in ev}),
                        "area": ",".join(sorted({cm[e].get("area") or "overall" for e in ev})), "status": "active"})
    rules.sort(key=lambda r: -r["n_prs"])
    for i, r in enumerate(rules, 1):
        r["id"] = f"{out}-{i:03d}"
    RULES.mkdir(exist_ok=True)
    (RULES / f"{out}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rules))

    kinds = C.Counter(a.get("kind") for a in att)
    md = [f"# Rulebook {out}", "",
          f"From {len(cs)} train comments" + (f" missed by {misses_of}" if misses_of else "")
          + (f", area {area}" if area else "") + (f", extending {base}" if base else "")
          + f"; attribution: {dict(kinds)}; {len(groups)} concern groups; cost ${spent:.2f}",
          f"{len(rules)} entries: " + ", ".join(f"{k} {v}" for k, v in C.Counter(r["kind"] for r in rules).items()), ""]
    for kind in ("principle", "knowledge"):
        md += [f"## {kind}", ""]
        for r in (r for r in rules if r["kind"] == kind):
            ev = ", ".join(f"[#{cm[e]['pr']}]({cm[e]['url']})" for e in r["evidence"][:6])
            md += [f"- **{r['id']}** ({r['area']}, {r['n_prs']} PRs) When {r['when']}: {r['expect']}",
                   f"  - why: {r.get('why') or ''}; paths: {r.get('paths') or 'any'}",
                   f"  - e.g. {' / '.join(r.get('examples') or [])}", f"  - evidence: {ev}"]
        md.append("")
    (RULES / f"{out}.md").write_text("\n".join(md) + "\n")
    return (f"rules/{out}.jsonl: {len(rules)} entries ({dict(C.Counter(r['kind'] for r in rules))}) from "
            f"{len(cs)} comments ({dict(kinds)}), {len(groups)} groups, ${spent:.2f}")


def coverage(rules_name: str, split: str = "test", area: str | None = None, misses_of: str | None = None,
             effort: str = "high", workers: int = 4, max_cost: float = 2.0, cfg: Config | None = None) -> str:
    """Which rulebook entries explain the human comments of `split` (only those `misses_of` missed, if
    given). Writes reports/coverage_<rules>_<split>.md; returns its headline. `max_cost` 0 = plan only."""
    cfg = cfg or Config()
    rules = [json.loads(l) for l in (RULES / f"{rules_name}.jsonl").open()]
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
    return "\n".join(L[:5])

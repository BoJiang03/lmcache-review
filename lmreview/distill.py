"""`lmreview distill`: turn human review comments into a rulebook.

Input: human change requests / nits on train samples. All of them by default; with `misses_of`,
only the ones that reviewer missed (human-only, from its judge results).
  1. attribute (batches of comments, no tools): learnable rule | missing context | not an issue;
     for learnable ones, a general rule that would also apply to future PRs
  2. merge (per area, no tools): turn candidates (and the base rulebook) into two kinds of entries:
       principle  a review principle the reviewer applied; abstracted from its instances (one is enough)
       knowledge  a fact / invariant about this codebase or the engine a reviewer must know there
     each = kind / when / expect / why / examples / paths / evidence
  3. global merge (no tools, only if several areas): merge duplicates across areas
How many PRs back an entry (n_prs) is recorded but does not gate it: a comment seen once still came
from a principle or from knowledge. Whether entries help is decided by eval flips on test.
Output: rules/<out>.jsonl, rules/<out>.md (readable), <data>/distill/<out>/attribution.jsonl.
Never reads test/new samples.
"""

from __future__ import annotations

import collections as C
import json
import tempfile

from . import llm
from .budget import capped_map
from .config import RULES, Config
from .score import _normalize, load_gold

BATCH = 30

ATTRIBUTE = """You are distilling the review standards of the LMCache team (a KV-cache layer for LLM
inference engines such as vLLM) from past human review comments.

For each comment below, decide why the reviewer raised it:
- "learnable": it follows from a standard, convention or recurring concern of this team that a
  reviewer could apply to FUTURE pull requests (e.g. "new config options must be documented in
  docs/...", "do not catch broad exceptions in the storage path"). Write that standard as a short,
  general, checkable rule; not a restatement of this one fix.
- "context": it needs knowledge outside the code (an offline decision, a roadmap, runtime behavior
  seen in production, another repo).
- "not_issue": a question, praise, or something with no actionable point.
Also give "paths": glob patterns of where the rule applies (e.g. ["lmcache/v1/storage_backend/**"]),
or [] if it applies anywhere.

Comments:
{comments}

Answer with one JSON block only:
```json
[{{"id": 123, "kind": "learnable|context|not_issue", "rule": "...", "paths": ["..."]}}]
```"""

MERGE = """Below are candidate review rules for the LMCache team ({scope}), each from one human review
comment (comment id and PR number given){base_note}.
A reviewer raised each comment for a reason: either a review PRINCIPLE they apply (the comment is
one instance of it), or KNOWLEDGE of how this codebase or the inference engine works (a fact or
invariant). Recover those reasons as rulebook entries:
- "principle": state the principle at the level a reviewer would apply it to other changes
  (e.g. "conditions for acquiring and releasing a resource must match on every path"), with the
  candidates as examples. One instance is enough. Candidates that are instances of the same
  principle become one entry; union their evidence. Not so vague it cannot be checked.
- "knowledge": a fact or invariant about this code or the engine (e.g. "only the lead TP rank
  acquires daemon read locks", "vLLM already validates X at engine init"), and what a reviewer
  must therefore check when touching that code. Scope it with "paths".
- Drop candidates that carry no reusable principle or knowledge (pure one-off fixes, typos).
Each entry: "kind" (principle|knowledge), "when" (the kind of change it applies to), "expect" (what
to check or require; checkable), "why" (one line), "examples" (1-2 short concrete instances),
"paths" (glob patterns, [] = anywhere), "evidence" (all comment ids it covers).

Candidates:
{cands}

Answer with one JSON block only:
```json
[{{"kind": "principle", "when": "...", "expect": "...", "why": "...", "examples": ["..."], "paths": ["..."], "evidence": [123, 456]}}]
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


def inputs(cfg: Config, misses_of: str | None, area: str | None) -> list[dict]:
    """Train-split human comments to distill from."""
    ss, cm = load_gold(cfg)
    train = {k: s for k, s in ss.items() if s["split"] == "train"}
    if misses_of:
        ids = []
        for p in sorted((cfg.data / "scores" / misses_of).glob("*.json")):
            run = json.loads((cfg.data / "runs" / misses_of / p.name).read_text())
            if (run["pr"], run["commit"]) not in train:
                continue
            s = _normalize(json.loads(p.read_text()), run)
            ids += [s["gold_ids"][h["id"]] for h in s["human"]
                    if h["type"] in ("change_request", "nit") and not h["matched_ai"]]
    else:
        ids = [i for s in train.values() for i in s["gold_ids"]]
    cs = [cm[i] for i in dict.fromkeys(ids)]
    return [c for c in cs if not area or (c.get("area") or "overall") == area]


def _fmt(c: dict) -> str:
    if c["kind"] == "inline":
        return (f"[{c['id']}] {c['path']}:{c['line_lo']} (PR #{c['pr']})\nhunk:\n{(c['diff_hunk'] or '')[-600:]}\n"
                f"comment: {c['body'][:1000]}")
    return f"[{c['id']}] overall review of PR #{c['pr']}:\n{c['body'][:1500]}"


def distill(out: str, base: str | None = None, misses_of: str | None = None, area: str | None = None,
            limit: int | None = None, effort: str = "high", workers: int = 4, max_cost: float = 5.0,
            reuse: str | None = None, cfg: Config | None = None) -> str:
    """Build rules/<out>.jsonl; returns a short summary."""
    cfg = cfg or Config()
    if (RULES / f"{out}.jsonl").exists():
        raise FileExistsError(f"rules/{out}.jsonl exists; pick a new name")
    cs = inputs(cfg, misses_of, area)[:limit]
    by_id = {c["id"]: c for c in cs}
    batches = [cs[i:i + BATCH] for i in range(0, len(cs), BATCH)]
    print(f"distill {out}: {len(cs)} comments in {len(batches)} batches (cap ${max_cost:.0f})", flush=True)
    if reuse:  # attribution of an earlier run (same inputs): only the merge is re-done
        res = [[json.loads(l) for l in (cfg.data / "distill" / reuse / "attribution.jsonl").open()]]
        spent = 0.0
    else:
        res, spent = capped_map(lambda b: _ask(ATTRIBUTE.format(comments="\n\n".join(map(_fmt, b))), effort, cfg),
                                batches, workers, max_cost, label=lambda b: f"batch of {len(b)}")
    att = [{**a, "id": _id(a.get("id"))} for r in res if isinstance(r, list) for a in r if isinstance(a, dict)]
    att = [a for a in att if a["id"] in by_id]
    work = cfg.data / "distill" / out
    work.mkdir(parents=True, exist_ok=True)
    (work / "attribution.jsonl").write_text("".join(json.dumps(a) + "\n" for a in att))

    groups: dict[str, list] = C.defaultdict(list)
    for a in att:
        if a.get("kind") == "learnable" and a.get("rule"):
            groups[by_id[a["id"]].get("area") or "overall"].append(a)
    base_rules = [json.loads(l) for l in (RULES / f"{base}.jsonl").open()] if base else []
    _, cm = load_gold(cfg)
    pr_of = lambda e: cm[e]["pr"] if e in cm else None  # noqa: E731

    def merge(scope: str, cands: list[str], has_base: bool) -> list[dict]:
        nonlocal spent
        if spent >= max_cost:
            print(f"  cost cap reached; {scope} not merged", flush=True)
            return []
        try:
            merged, cost = _ask(MERGE.format(scope=scope, cands="\n".join(cands),
                                             base_note=" (some come from the current rulebook)" if has_base else ""),
                                effort, cfg)
        except Exception as e:  # keep the other areas
            print(f"  merge {scope}: FAIL {e}", flush=True)
            return []
        spent += cost
        out = [r for r in merged if isinstance(r, dict) and r.get("expect")]
        print(f"  merge {scope}: {len(cands)} candidates -> {len(out)} rules ${cost:.2f} (total ${spent:.2f})", flush=True)
        return out

    fmt = lambda r: (f"- [{r.get('kind', 'principle')}] when: {r.get('when')} | expect: {r.get('expect')} | paths={r.get('paths') or []} "  # noqa: E731
                     f"| evidence={r.get('evidence')} (PRs {sorted({pr_of(e) for e in r.get('evidence') or []} - {None})})")
    rules = []
    for g, items in sorted(groups.items()):
        cands = [f"- {a['rule']} | paths={a.get('paths') or []} | evidence=[{a['id']}] (PR #{by_id[a['id']]['pr']})"
                 for a in items]
        old = [r for r in base_rules if r.get("area") == g]
        rules += [{**r, "area": g} for r in merge(f"area: {g}", cands + [fmt(r) for r in old], bool(old))]
    if len(groups) > 1 and rules:
        glob = merge("all areas; merge only rules that are duplicates across areas", [fmt(r) for r in rules], False)
        if glob:
            area_of = {e: r["area"] for r in rules for e in r.get("evidence") or []}
            rules = [{**r, "area": ",".join(sorted({area_of.get(e, "?") for e in r.get("evidence") or []}))}
                     for r in glob]
    for i, r in enumerate(rules, 1):
        r["id"] = f"{out}-{i:03d}"
        r["evidence"] = list(dict.fromkeys(e for e in map(_id, r.get("evidence") or []) if e in cm))
        r["n_prs"] = len({pr_of(e) for e in r["evidence"]})
        r["status"] = "active"
    RULES.mkdir(exist_ok=True)
    (RULES / f"{out}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rules))
    kinds = C.Counter(a.get("kind") for a in att)
    md = [f"# Rulebook {out}", "", f"From {len(cs)} train comments" + (f" missed by {misses_of}" if misses_of else "")
          + (f", area {area}" if area else "") + f"; attribution: {dict(kinds)}; cost ${spent:.2f}",
          f"{len(rules)} entries: " + ", ".join(f"{k} {v}" for k, v in C.Counter(r.get("kind") for r in rules).items()),
          ""]
    for st in ("principle", "knowledge"):
        md += [f"## {st}", ""]
        for r in sorted((r for r in rules if r.get("kind", "principle") == st), key=lambda r: -r["n_prs"]):
            ev = ", ".join(f"[#{cm[e]['pr']}]({cm[e]['url']})" for e in r["evidence"][:6])
            md += [f"- **{r['id']}** ({r['area']}, {r['n_prs']} PRs) When {r.get('when')}: {r.get('expect')}",
                   f"  - why: {r.get('why', '')}; paths: {r.get('paths') or 'any'}",
                   f"  - e.g. {' / '.join(r.get('examples') or [])}", f"  - evidence: {ev}"]
        md.append("")
    (RULES / f"{out}.md").write_text("\n".join(md) + "\n")
    return (f"rules/{out}.jsonl: {len(rules)} entries ({dict(C.Counter(r.get('kind') for r in rules))}) from "
            f"{len(cs)} comments ({dict(kinds)}), ${spent:.2f}")

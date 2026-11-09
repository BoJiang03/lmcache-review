"""`lmreview distill`: turn human review comments into a rulebook.

Input: human change requests / nits on train samples. All of them by default; with `misses_of`,
only the ones that reviewer missed (human-only, from its judge results).
  1. attribute (batches of comments, no tools): learnable rule | missing context | not an issue;
     for learnable ones, a general rule that would also apply to future PRs
  2. merge (per area, no tools): dedupe candidates (and the base rulebook) into rules with evidence
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

MERGE = """Below are candidate review rules for the LMCache team (area: {area}), each with the ids of
the human review comments it came from{base_note}.
Merge them into a clean rulebook:
- merge rules that say the same thing (union their evidence);
- drop rules that are one-off fixes rather than standards a reviewer would apply to future PRs;
- keep each rule short, specific and checkable; add a one-line "why";
- keep "paths" as glob patterns ([] = anywhere).

Candidates:
{cands}

Answer with one JSON block only:
```json
[{{"rule": "...", "why": "...", "paths": ["..."], "evidence": [123, 456]}}]
```"""


def _ask(prompt: str, effort: str, cfg: Config) -> tuple[object, float]:
    """One tool-less LLM call in an empty directory; returns (parsed JSON, cost)."""
    cfg.sandbox.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cfg.sandbox) as d:
        r = llm.run(prompt, effort, cwd=d, tools="")
    return llm.extract_json(r["text"]), r["cost"]


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
            cfg: Config | None = None) -> str:
    """Build rules/<out>.jsonl; returns a short summary."""
    cfg = cfg or Config()
    if (RULES / f"{out}.jsonl").exists():
        raise FileExistsError(f"rules/{out}.jsonl exists; pick a new name")
    cs = inputs(cfg, misses_of, area)[:limit]
    by_id = {c["id"]: c for c in cs}
    batches = [cs[i:i + BATCH] for i in range(0, len(cs), BATCH)]
    print(f"distill {out}: {len(cs)} comments in {len(batches)} batches (cap ${max_cost:.0f})", flush=True)
    res, spent = capped_map(lambda b: _ask(ATTRIBUTE.format(comments="\n\n".join(map(_fmt, b))), effort, cfg),
                            batches, workers, max_cost, label=lambda b: f"batch of {len(b)}")
    att = [a for r in res if isinstance(r, list) for a in r if isinstance(a, dict) and a.get("id") in by_id]
    work = cfg.data / "distill" / out
    work.mkdir(parents=True, exist_ok=True)
    (work / "attribution.jsonl").write_text("".join(json.dumps(a) + "\n" for a in att))

    groups: dict[str, list] = C.defaultdict(list)
    for a in att:
        if a.get("kind") == "learnable" and a.get("rule"):
            groups[by_id[a["id"]].get("area") or "overall"].append(a)
    base_rules = [json.loads(l) for l in (RULES / f"{base}.jsonl").open()] if base else []
    rules = []
    for g, items in sorted(groups.items()):
        if spent >= max_cost:
            print(f"  cost cap reached; area {g} not merged", flush=True)
            continue
        cands = "\n".join(f"- {a['rule']} paths={a.get('paths') or []} evidence=[{a['id']}]" for a in items)
        old = [r for r in base_rules if r.get("area") == g]
        cands += "".join(f"\n- {r['rule']} paths={r.get('paths') or []} evidence={r.get('evidence')}" for r in old)
        try:
            merged, cost = _ask(MERGE.format(area=g, cands=cands,
                                             base_note=" (some are rules from the current rulebook)" if old else ""),
                                effort, cfg)
        except Exception as e:  # keep the other areas
            print(f"  merge {g}: FAIL {e}", flush=True)
            continue
        spent += cost
        print(f"  merge {g}: {len(items)} candidates -> {len(merged)} rules ${cost:.2f} (total ${spent:.2f})", flush=True)
        rules += [{**r, "area": g} for r in merged if isinstance(r, dict) and r.get("rule")]
    for i, r in enumerate(rules, 1):
        r["id"] = f"{out}-{i:03d}"
        r["evidence"] = [e for e in r.get("evidence") or [] if e in by_id or base]
    RULES.mkdir(exist_ok=True)
    (RULES / f"{out}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rules))
    kinds = C.Counter(a.get("kind") for a in att)
    _, cm = load_gold(cfg)
    md = [f"# Rulebook {out}", "", f"From {len(cs)} train comments" + (f" missed by {misses_of}" if misses_of else "")
          + (f", area {area}" if area else "") + f"; attribution: {dict(kinds)}; cost ${spent:.2f}", ""]
    for r in rules:
        ev = ", ".join(f"[{e}]({cm[e]['url']})" for e in r["evidence"][:5] if e in cm)
        md += [f"- **{r['id']}** ({r['area']}) {r['rule']}", f"  - why: {r.get('why', '')}; paths: {r.get('paths') or 'any'}; "
               f"evidence ({len(r['evidence'])}): {ev}"]
    (RULES / f"{out}.md").write_text("\n".join(md) + "\n")
    return f"rules/{out}.jsonl: {len(rules)} rules from {len(cs)} comments ({dict(kinds)}), ${spent:.2f}"

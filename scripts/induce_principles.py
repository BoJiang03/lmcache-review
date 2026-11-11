"""Induce the few higher-level principles that a rulebook's specific rules are specializations of.

Experiment: reviewers likely do not hold one-off rules like "keep the transfer driver thin"; they hold
a few principles (e.g. "the next change of this kind should touch one place") and apply them with
knowledge of where LMCache's boundaries and resources are. This rewrites a rulebook into that shape:
a few principles, plus knowledge entries (project facts) linked to them, plus whatever fits no principle.

    python scripts/induce_principles.py miss1-r9 pk1 [--extra data/distill/miss1/m4639.v3.jsonl] [--n 3] [--run]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lmreview.config import RULES, Config  # noqa: E402
from lmreview.distill import _ask, _fmt  # noqa: E402
from lmreview.ensemble import ensemble  # noqa: E402
from lmreview.score import load_gold  # noqa: E402

INDUCE = """Below are review rules distilled one by one from LMCache maintainers' review comments, each with
the human comments it came from. Many look like one-off rules, but a reviewer does not carry dozens of
one-off rules in their head. They carry a few principles and apply them using knowledge of where this
codebase's boundaries, owners and shared resources are.

Recover that structure.

1. Principles: find the FEW (3 to 6) principles that the rules are specializations of. Read the
   reviewers' own words in the comments, not just the rule text. A principle must be something a
   reviewer can apply to any PR. It must not be a platitude ("write clean code") the model already
   follows: give it an operational check, a concrete question to ask of the diff whose answer
   exposes a violation (e.g. "if a second X is added next month, which existing files must change?").
   Group rules under one principle only if the same check would have caught them.
2. Knowledge: for each rule under a principle, keep what is specific to LMCache as a knowledge
   entry: the fact the reviewer relied on (where a boundary, owner, shared resource, lane, variant or
   fallback is), stated so the reviewer can apply its principle to future changes there. Do not
   restate the principle in it.
3. Standalone: list rules that fit no principle (a genuinely separate concern). Do not force them.

Rules:
{rules}

Finish with one JSON block:
```json
{{"principles": [{{"id": "P1", "name": "short name", "value": "what the reviewers care about, one sentence",
   "check": "the operational question(s) to ask of every diff", "when": "the situations where it applies",
   "expect": "what to ask of the author", "members": ["rule ids"]}}],
 "knowledge": [{{"from": "rule id", "principle": "P1", "when": "the LMCache situation (code area, operation)",
   "fact": "the project fact the reviewer relied on, and what it implies for the check"}}],
 "standalone": ["rule ids"]}}
```"""

MERGE = """Several drafts below each restructure the same rulebook into a few principles plus project
knowledge. Merge them into one.

- Take the principle set that the most drafts agree on. Prefer principles that the reviewers' own words
  support. Prefer an operational check over a vague one.
- Every rule id must end up in exactly one place: under a principle (with a knowledge entry) or in
  standalone.
- Keep the same JSON shape.

Rules (for reference):
{rules}

Drafts:
{drafts}

Finish with one JSON block in the same shape as the drafts."""


def rule_text(rules: list[dict], cm: dict) -> str:
    """Each rule with its evidence comments, for the prompts."""
    out = []
    for r in rules:
        ev = "\n".join("  " + _fmt(cm[e], False).replace("\n", "\n  ")[:900] for e in (r.get("evidence") or [])[:3] if e in cm)
        out.append(f"[{r['id']}] ({r.get('kind')}) When {r.get('when')}: {r.get('expect')}\n  comments:\n{ev}")
    return "\n\n".join(out)


def ok(res: tuple[object, float]) -> bool:
    """A parsed draft with principles."""
    return isinstance(res[0], dict) and bool(res[0].get("principles"))


def build(src: list[dict], ind: dict) -> list[dict]:
    """The new rulebook: principles first (evidence and corrected tests of their members carried
    over, so the leak guard and `lmreview regress` still see them), then knowledge, then standalone."""
    by = {r["id"]: r for r in src}
    out = []
    for p in ind["principles"]:
        mem = [by[m] for m in p.get("members") or [] if m in by]
        out.append({"id": p["id"], "kind": "principle", "status": "active", "version": 1, "name": p.get("name"),
                    "when": p["when"], "expect": f"{p['expect']} Check: {p['check']}",
                    "why": p.get("value"), "examples": [f"{m['id']}: {m['when'][:160]}" for m in mem][:4],
                    "paths": [], "members": [m["id"] for m in mem],
                    "evidence": list(dict.fromkeys(e for m in mem for e in m.get("evidence") or [])),
                    # replayed by `lmreview regress`; a finding citing the principle or a member passes
                    "tests": [{**t, "from": m["id"]} for m in mem for t in m.get("tests") or []]})
    # Members stay as they were (text, scope, examples, tests): a model rewrite into "facts" lost
    # content (pk1: m4042-001 kept only one of its three PRs and #4805 regressed). Only the link is added.
    for p in ind["principles"]:
        for m in p.get("members") or []:
            if m in by:
                out.append({**by[m], "principle": p["id"]})
    placed = {x["id"] for x in out}
    out += [{**by[i], "status": "active"} for i in ind.get("standalone") or [] if i in by and i not in placed]
    lost = [r["id"] for r in src if r["id"] not in {x["id"] for x in out}]
    if lost:
        print(f"WARNING: not placed anywhere, kept as they were: {lost}")
        out += [by[i] for i in lost]
    return out


def main() -> None:
    """Induce, merge, write rules/<out>.jsonl and print the structure."""
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("out")
    ap.add_argument("--extra", action="append", default=[], help="jsonl with candidate entries to include")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--effort", default="high")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--principles-from", help="rulebook whose principles to reuse instead of inducing")
    a = ap.parse_args()
    cfg = Config()
    _, cm = load_gold(cfg)
    src = [r for r in map(json.loads, filter(str.strip, (RULES / f"{a.book}.jsonl").open()))
           if r.get("status", "active") == "active"]
    for f in a.extra:
        src += [r for r in map(json.loads, filter(str.strip, open(f))) if r.get("evidence")]
    text = rule_text(src, cm)
    print(f"{len(src)} rules, prompt {len(text)} chars, n={a.n}")
    if a.principles_from:  # reuse the principles of an earlier induction (free)
        prev = [r for r in map(json.loads, filter(str.strip, (RULES / f"{a.principles_from}.jsonl").open()))]
        ps = [{"id": r["id"], "name": r.get("name"), "when": r["when"], "expect": r["expect"].split(" Check: ")[0],
               "check": r["expect"].split(" Check: ", 1)[1], "value": r.get("why"), "members": r["members"]}
              for r in prev if r.get("members") is not None]
        placed = {m for p in ps for m in p["members"]}
        ind = {"principles": ps, "standalone": [r["id"] for r in src if r["id"] not in placed]}
        rules = build(src, ind)
        (RULES / f"{a.out}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rules))
        print(f"wrote {len(rules)} entries to rules/{a.out}.jsonl (principles from {a.principles_from})")
        return
    if not a.run:
        return

    def merge(good: list[tuple[object, float]]) -> tuple[object, float]:
        drafts = "\n\n".join(f"Draft {i}:\n{json.dumps(d, indent=1)}" for i, (d, _) in enumerate(good, 1))
        return _ask(MERGE.format(rules=text, drafts=drafts), a.effort, cfg)

    e = ensemble(lambda: _ask(INDUCE.format(rules=text), a.effort, cfg), a.n, merge, ok=ok)
    cost = sum(c for _, c in e.runs) + (e.merge[1] if e.merge else 0.0)
    ind = e.result[0]
    for i, (d, _) in enumerate(e.runs, 1):
        if isinstance(d, dict):
            print(f"draft {i}: " + " | ".join(f"{p['id']} {p.get('name')} {p.get('members')}" for p in d.get("principles", [])))
    print(f"\nmerged={e.merged} cost ${cost:.2f}\n")
    for p in ind["principles"]:
        print(f"== {p['id']} {p['name']}: {p['value']}\n   check: {p['check']}\n   members: {p['members']}")
    for k in ind.get("knowledge") or []:
        print(f"-- [{k['from']} -> {k.get('principle')}] {k['fact'][:220]}")
    print("standalone:", ind.get("standalone"))
    rules = build(src, ind)
    (RULES / f"{a.out}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rules))
    print(f"wrote {len(rules)} entries to rules/{a.out}.jsonl")


if __name__ == "__main__":
    main()

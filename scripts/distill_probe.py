"""Probe distill on a handful of hand-picked comments: attribute -> cluster -> abstract, printed.

Checks one question cheaply: can distill turn a given human comment into the rule we expect, and does
clustering keep apart asks that share a topic but go in different directions? Writes nothing.
Unlike `lmreview distill`, it may read any split: the comments are named explicitly.

usage: python3 scripts/distill_probe.py [--run] [--effort high] [--max-cost 1]
       (without --run: print the inputs and the estimate only; nothing is spent)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from lmreview.config import Config  # noqa: E402
from lmreview.config import RULES  # noqa: E402
from lmreview.distill import ATTRIBUTE, EST, _ask, _fmt, _id, cluster, update_rulebook  # noqa: E402
from lmreview.score import load_gold  # noqa: E402

# probe sets: id -> role in the probe
PROBES = {}
PROBES["docex"] = {
    4066665554: "target    #5004 (test) ApostaC: replace prose docstring with a worked example",
    3448895452: "sibling   #3776 (train) ApostaC: hard to understand, use an illustrative example",
    3456756099: "sibling   #3776 (train) ApostaC: maybe have an example here",
    4076791494: "contrast  #5004 (test) ApostaC: good description but too long",
    3314905220: "contrast  #3248 (train) ApostaC: docstring describes public behavior, not internals",
    3672537889: "contrast  #4062 (train): docstring part not needed, too much implementation detail",
    3900966932: "contrast  #4834 (train): docstring has unnecessary detail, simplify",
    3299865533: "unrelated #3248 (train) ApostaC: only TP? what about PP?",
    3299887479: "unrelated #3248 (train) ApostaC: duplicated code, make a helper",
}
PROBES["recovery"] = {
    4238283183: "target    #5222 (test) zhengfeihe: renegotiate chunk size on recovery after LMCache restart",
    4996346428: "sibling   #4662 (train) andyluo7: fast server restart loses registration; PING is not registration",
    3833555656: "sibling   #4687 (train) rob-9: lazy heartbeat takes new server's token as baseline; recovery never runs",
    3223576654: "contrast  #3231 (train) ApostaC: duplicate registration is a noop (restart semantics, knowledge)",
    3314905220: "unrelated #3248 (train) ApostaC: docstring describes public behavior, not internals",
    3448895452: "unrelated #3776 (train) ApostaC: hard to understand, use an illustrative example",
    3299887479: "unrelated #3248 (train) ApostaC: duplicated code, make a helper",
}

# one missed comment per PR, no siblings: can distill generalize from a single example?
PROBES["oneshot"] = {
    4033893835: "single    #5150 (test) chunxiaozheng: define proto fields in order",
    4147509834: "single    #5405 (test) Zefan-Cai: temporary sized by the moves; bound it with chunks",
    4147509854: "single    #5405 (test) Zefan-Cai: destination block may be shared via prefix caching",
    5671926237: "single    #5938 (test) ApostaC: why reported at all; why an LMCache-side fix, not vLLM",
    4066665554: "single    #5004 (test) ApostaC: replace prose docstring with a worked example",
    4238283183: "single    #5222 (test) zhengfeihe: renegotiate chunk size on recovery after restart",
}

# a new comment against an existing rulebook (use with --base probe-recovery): evidence or generalize?
PROBES["recovery-new"] = {
    4238283183: "new       #5222 (test) zhengfeihe: renegotiate chunk size on recovery after restart",
}

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="docex", choices=sorted(PROBES))
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--max-cost", type=float, default=1.0)
    ap.add_argument("--train-only", action="store_true", help="drop the test comments (fair rule for testing on them)")
    ap.add_argument("--json", help="write the resulting rulebook here")
    ap.add_argument("--base", help="existing rulebook (rules/<name>.jsonl) to update instead of starting empty")
    a = ap.parse_args()
    cfg = Config()
    _, cm = load_gold(cfg)
    PROBE = PROBES[a.set]
    cs = [cm[i] for i in PROBE if not (a.train_only and "(test)" in PROBE[i])]
    for c in cs:
        print(f"[{c['id']}] {PROBE[c['id']]}")
    est = EST["attribute"] + EST["cluster"] + EST["abstract"]
    print(f"\n3 calls (attribute, cluster, abstract) at effort {a.effort}; est ${est:.2f}, cap ${a.max_cost:.2f}")
    if not a.run:
        print("plan only; pass --run to spend")
        return

    att, cost = _ask(ATTRIBUTE.format(comments="\n\n".join(map(_fmt, cs))), a.effort, cfg)
    spend = [cost]
    att = [{**x, "id": _id(x.get("id"))} for x in att if isinstance(x, dict)]
    print(f"\n== attribute (${cost:.2f})")
    for x in att:
        print(f"[{x['id']}] {x.get('kind')}: {x.get('rule') or ''}  paths={x.get('paths')}")

    items = {f"c{x['id']}": x["rule"] for x in att if x.get("kind") == "learnable" and x.get("rule")}
    evid = {k: [int(k[1:])] for k in items}
    base = [json.loads(l) for l in (RULES / f"{a.base}.jsonl").open() if l.strip()] if a.base else []
    for r in base:
        if r.get("status", "active") == "active":
            items[f"b{r['id']}"] = f"When {r.get('when')}: {r.get('expect')} (existing rule; paths {r.get('paths') or []})"
            evid[f"b{r['id']}"] = r.get("evidence") or []
    groups = cluster(items, a.effort, cfg, spend, a.max_cost)
    print("\n== cluster")
    for i, g in enumerate(groups):
        print(f"group {i} ({g['concern']}): " + ", ".join(g["members"]))
    rules, changes = update_rulebook(base, groups, items, evid, "probe", cm, a.effort, cfg, spend, a.max_cost)
    print("\n== changes")
    for ch in changes:
        print(json.dumps(ch, ensure_ascii=False))
    print("\n== entries added or changed")
    touched = {x for ch in changes for x in (ch.get("rules") or []) + (ch.get("new") or [])}
    for r in rules:
        if r["id"] in touched:
            print(json.dumps({k: r.get(k) for k in ("id", "version", "status", "kind", "when", "expect", "examples",
                                                    "paths", "evidence")}, ensure_ascii=False, indent=1))
    if a.json:
        pathlib.Path(a.json).write_text("".join(json.dumps(r) + "\n" for r in rules))
        print(f"wrote {len(rules)} entries to {a.json}")
    print(f"\ntotal ${spend[0]:.2f}")


if __name__ == "__main__":
    main()

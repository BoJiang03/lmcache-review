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

# miss1 #1: the three major misses of #4639 (train), against team-v1
PROBES["m4639"] = {
    3826508379: "single    #4639 (train) ruizhang0101: use event driven instead of taking a snapshot",
    4988786836: "single    #4639 (train) ruizhang0101: capacity has two paths (event, snapshot); use only one",
    3826909561: "single    #4639 (train) ruizhang0101: make capacity a 'config' cache event; registry consumes it",
}

# miss1 #2: the three major misses of #3877 (train), against team-v1
PROBES["m3877"] = {
    3543858387: "single    #3877 (train) maobaolong: avoid device type checks in the generic LMCache layer",
    3543864444: "single    #3877 (train) maobaolong: ditto, a MUSA specialization inside general layer code",
    3543873753: "single    #3877 (train) maobaolong: ditto",
}

# miss1 #3: the three major misses of #4042 (train); use with --base t1m3877b (maintain: generalize or add?)
PROBES["m4042"] = {
    3633033001: "single    #4042 (train) KuntaiDu: init a dispatcher in the connector",
    3633043948: "single    #4042 (train) KuntaiDu: dispatcher.dispatch('register_kv_caches', ...)",
    3633046216: "single    #4042 (train) KuntaiDu: dispatcher.dispatch('save_kv_layer', ...)",
}

# miss1 #4: the two major misses of #3631 (train), against miss1-r4
PROBES["m3631"] = {
    3405496325: "single    #3631 (train) ApostaC: PING on SYNC dispatch shares the thread with slow REGISTER_KV_CACHE",
    3405567725: "single    #3631 (train) ApostaC: management module can't see transfer modules; route via MPEngineContext",
}

# miss1 #5: the misses of #4723 (train), against miss1-r5
PROBES["m4723"] = {
    3858664052: "single    #4723 (train) ApostaC: quota_api names concrete controllers; OOT controllers break; packages register own APIs",
    5025696552: "single    #4723 (train) ApostaC: follow-ups: controller interface, controllers don't see each other, APIs in package",
    3858548304: "single    #4723 (train) ApostaC: OOT coordinators may need extra config (extra_config field)",
    3858673315: "single    #4723 (train) ApostaC: why is get_durable_components a method of View",
}

# miss1 #6: the two major misses of #4736 (train), against miss1-r6
PROBES["m4736"] = {
    3862855463: "single    #4736 (train) superleo: pick IPC vs local event by transfer mode; engine-driven keeps a local event",
    3862888755: "single    #4736 (train) superleo: connector falls back to vLLM's vendored adapter, which lacks the new method",
}

# miss1 #7: the misses of #3485 (train), against miss1-r7
PROBES["m3485"] = {
    3424943905: "single    #3485 (train) ApostaC: spec holds a raw ref to kv_caches; GPU KV refs must go on engine disconnect",
    3424917792: "single    #3485 (train) ApostaC: non-MP-only helper should carry an lmcache_deprecate warning",
    3424928429: "single    #3485 (train) ApostaC: base class: say which functions are MP and which non-MP only",
    3397484415: "single    #3485 (train) maobaolong: one spec per file, discovered dynamically, not a manual registry",
    3397500084: "single    #3485 (train) maobaolong: strategy pattern (format detectors) instead of if/elif",
}

# miss1 #8: the misses of #4079 (train), against miss1-r8
PROBES["m4079"] = {
    3745856118: "single    #4079 (train) hlin99: transfer module thin; descriptor/plan expose build+consume, internals hidden",
    3745857294: "single    #4079 (train) hlin99: change signature and move this helper out of the file",
    3745868321: "single    #4079 (train) hlin99: move out so contract changes leave lmcache_driven_transfer untouched",
    3745869082: "single    #4079 (train) hlin99: ditto, move out of the file",
}

# miss1 #9: the misses of #3231 (train), against pk3 (principles + knowledge)
PROBES["m3231"] = {
    3223576654: "single    #3231 (train) ApostaC: duplicate registration of an existing instance must stay a noop (#3208)",
    3223589685: "single    #3231 (train) ApostaC: design doc keeps AI planning details; keep only the final design",
    3223595657: "single    #3231 (train) ApostaC: why introduce this? could be over design",
    3223608962: "single    #3231 (train) ApostaC: unnecessarily complicated; think about the clear logic",
}

# m3231-001 read too narrowly (only corner-case latches): add train siblings of the same ask
PROBES["m3231b"] = {
    3313900972: "sibling   #3217 (train) YaoJiayi: we only need this line right?",
    3277103036: "sibling   #3336 (train) ApostaC: no need for this fallback; c_ops is always compiled for MP",
    3326817114: "sibling   #3359 (train) ApostaC: no backward compat needed; LMCache controls client and server",
    3351063372: "sibling   #3492 (train) ApostaC: why introduce covered_keys?",
    3406260333: "sibling   #3584 (train) ApostaC: no need for new l1_use_shm; raise when both set",
    3611472206: "sibling   #4077 (train) ApostaC: remove this flag and NativePlanType",
}

def main() -> None:
    """Run attribute, cluster and rulebook update on one probe set and print the changes."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="docex", choices=sorted(PROBES))
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--max-cost", type=float, default=1.0)
    ap.add_argument("--train-only", action="store_true", help="drop the test comments (fair rule for testing on them)")
    ap.add_argument("--json", help="write the resulting rulebook here")
    ap.add_argument("--n", type=int, default=3, help="abstraction drafts to merge (1 = no ensemble)")
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
    rules, changes = update_rulebook(base, groups, items, evid, "probe", cm, a.effort, cfg, spend, a.max_cost, n=a.n)
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

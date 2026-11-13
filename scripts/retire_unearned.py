"""One-off (2026-11-13): retire the principles of the book in use that have no evidence of their own.

Older principle induction (scripts/induce_principles.py, distill step 6) put parents over existing
entries whose evidence is all inherited from their members (v0001: P1-P7). distill no longer makes
such entries (distill.drop_unearned), so this cleans up the ones already in the book, once.

What retiring can lose is only what those parents caught: human comments matched by a finding that
cites one of them. So the check reviews only those samples with the pruned book (the old book's runs
are cached) and judges them; nothing else changes for the reviewer except the parents' absence.

    python3 scripts/retire_unearned.py                  # plan only (free)
    python3 scripts/retire_unearned.py --max-cost 15    # review + judge the samples
    python3 scripts/retire_unearned.py --max-cost 15 --promote   # and promote when nothing is lost

Promoting needs no candidate waiting (vet it or discard it first). A parent whose catch is lost is
kept, and the comment it caught becomes its own evidence.
"""

import argparse
import copy
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from lmreview import state  # noqa: E402
from lmreview.config import Config  # noqa: E402
from lmreview.distill import judge_runs  # noqa: E402
from lmreview.progress import note, step  # noqa: E402
from lmreview.replay import replay  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--max-cost", type=float, default=0.0, help="0 = print the plan only")
ap.add_argument("--promote", action="store_true", help="promote the pruned book when no catch is lost")
a = ap.parse_args()
cfg = Config()

head = state.head()
book = state.load_book(state.vname(head))
by = {r["id"]: r for r in book}
unearned = [r["id"] for r in book if r.get("status", "active") == "active" and r.get("members")
            and not set(r.get("evidence") or [])
            - {e for m in r["members"] if m in by for e in by[m].get("evidence") or []}]
note(f"{state.vname(head)}: {len(unearned)} principles without evidence of their own: {', '.join(unearned) or 'none'}")
if not unearned:
    sys.exit(0)

# what they caught: human comments matched by a finding that cites one of them (judged runs on disk)
old_rv = state.reviewer()
judged, _ = judge_runs(cfg, old_rv, None, "train", 0.0)
caught = {}  # (pr, commit8) -> {comment id: rule}
for run, sc in judged:
    cites = {x["id"]: x.get("rule") for x in run.get("findings") or []}
    for h in sc["human"]:
        for f in h.get("matched_ai") or []:
            if cites.get(f) in unearned:
                caught.setdefault((run["pr"], run["commit"][:8]), {})[int(sc["gold_ids"][h["id"]])] = cites[f]
for (pr, c), cs in sorted(caught.items()):
    note(f"  #{pr}@{c}: " + ", ".join(f"comment {k} via {v}" for k, v in cs.items()))
note(f"{len(caught)} samples to check; {len(judged)} judged runs of {old_rv} looked at")

pruned = copy.deepcopy(book)
pb = {r["id"]: r for r in pruned}
today = dt.date.today().isoformat()
for i in unearned:
    pb[i]["status"] = "retired"
    pb[i]["retired"] = {"date": today, "by": "retire_unearned", "why": "no evidence of its own"}
for r in pruned:
    if r.get("principle") in unearned:
        r.pop("principle")
name = f"{state.vname(head)}-unearned"
(state.RULES / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in pruned))
new_rv = state.reviewer(name)
note(f"pruned book: rules/{name}.jsonl; reviewer {new_rv}")
if a.max_cost <= 0:
    note(f"plan only: about {len(caught)} reviews (~$3 each) + judging; rerun with --max-cost")
    sys.exit(0)

specs = [f"{pr}:{c}" for pr, c in sorted(caught)]
with step("review", f"{len(specs)} samples with {name}") as s:
    s.cost = replay(new_rv, "train", None, 4, a.max_cost, specs, cfg=cfg)
with step("judge", new_rv) as s:
    now, s.cost = judge_runs(cfg, new_rv, {pr for pr, _ in caught}, "train", max(0.0, a.max_cost))
found = {}
for run, sc in now:
    key = (run["pr"], run["commit"][:8])
    if key in caught:
        found[key] = {int(sc["gold_ids"][h["id"]]) for h in sc["human"] if h.get("matched_ai")}
lost = {k: [c for c in cs if c not in found.get(k, set())] for k, cs in caught.items()}
missing = [k for k in caught if k not in found]
for k, cs in sorted(caught.items()):
    note(f"  #{k[0]}@{k[1]}: " + ("not reviewed (cost cap)" if k in missing else
         ", ".join(f"comment {c} {'kept' if c not in lost[k] else 'LOST'}" for c in cs)))
if missing:
    note("INCOMPLETE: rerun with a higher --max-cost (finished runs are cached)")
    sys.exit(1)

keep = sorted({caught[k][c] for k in lost for c in lost[k]})
for i in keep:  # a parent that caught something on its own: keep it, with that comment as its evidence
    pb[i].pop("retired")
    pb[i]["status"] = "active"
    pb[i]["evidence"] = list(dict.fromkeys(pb[i]["evidence"]
                                           + [c for k in lost for c in lost[k] if caught[k][c] == i]))
    for m in pb[i]["members"]:
        if m in pb:
            pb[m]["principle"] = i
gone = [i for i in unearned if i not in keep]
note(f"retire {', '.join(gone) or 'none'}" + (f"; keep {', '.join(keep)} (caught a comment on its own)" if keep else ""))
if a.promote and gone:
    with state.lock():
        if state.candidate():
            sys.exit(f"candidate {state.candidate()['name']} is waiting: vet or discard it first")
        if state.head() != head:
            sys.exit("the book in use changed meanwhile: rerun")
        n = state.new_version(pruned, head, by="retire_unearned", retired=gone, kept=keep,
                              note="principles without evidence of their own; checked on the samples they caught")
        note(f"promoted {state.vname(n)}")

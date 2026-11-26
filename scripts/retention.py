#!/usr/bin/env python3
"""Retention of learned points: does the production reviewer still catch what the ledger calls learned?

A point is learned when the ledger files it as covered (a reviewer caught it once) or resolved (a rule
fixed it). Re-review its PR:commit with the production reviewer `reps` times and count, per point, how
many runs caught it: 2/2 is retained; retention = retained points / points.

A run that misses a point is classified:
  a  covered, no rule was ever learned for it: the main review did not think of it this time;
  b  resolved, its rule (the active book entry whose tests corrected the comment, or what it was
     merged into) is in the book, and no rule-check finding cites it in this run;
  c  resolved, a finding on the commented file cites the rule, but the judge matched it to no point
     ("c-elsewhere": the rule is cited only on other files);
  x  resolved, but no active entry carries it any more (lost in maintenance).

Runs, judging and caching are scripts/skill_compare.py's (lmreview arm, blinded judge); this script only
picks the samples and reads the results. Nothing here writes lmreview/state/.

Usage (env as in skill_compare: SC_REVIEWER, SC_REP, SC_MAIN_FROM, SC_RC_FROM):
    scripts/retention.py select                      # fix the pilot and holdout sets (once)
    SC_REP=2 scripts/retention.py run --set pilot --cap 25
    scripts/retention.py report --set pilot --reviewer p990f2d2e+v0032@medium-rc --reps 1 2
"""

from __future__ import annotations

import argparse
import collections as C
import json
import os
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "retention"
SC = ROOT / "data" / "skill_compare"
STATE = ROOT / "lmreview" / "state"
PILOT_FIXED = ("3869-39e1696b",)  # the 42-file PR where rules exist but did not fire


def ledger() -> list[dict]:
    return [json.loads(x) for x in (STATE / "ledger.jsonl").open() if x.strip()]


def book() -> list[dict]:
    return [json.loads(x) for x in (STATE / "book.jsonl").open() if x.strip()]


def learned_samples() -> dict[str, list[dict]]:
    """{"<pr>-<commit8>": ledger rows with status covered or resolved}."""
    out: dict[str, list[dict]] = C.defaultdict(list)
    for r in ledger():
        if r["status"] in ("covered", "resolved"):
            out[f"{r['pr']}-{r['commit'][:8]}"].append(r)
    return dict(out)


def select(seed: int = 0) -> dict:
    """Pilot (15) and holdout (15) sets from the learned samples, one sample per PR, fixed at t0.

    Pilot: PILOT_FIXED, then the 10 learned samples of the four-way compare (their production-config run
    is cached as repeat 1), then by kind (doc, inprocess, bugfix, other) and size until 15; holdout: 15
    others, shuffled with `seed`, spread over kinds."""
    ls = learned_samples()
    scope = json.loads((ROOT / "data" / "sets" / "deploy_scope.json").read_text())["by_pr"]
    kind = {json.loads(x)["pr"]: json.loads(x)["kind"] for x in (ROOT / "data" / "sets" / "pr_kind.jsonl").open()}
    prs = {json.loads(x)["pr"]: json.loads(x) for x in (ROOT / "data" / "dataset" / "prs.jsonl").open()}

    def tag(k: str) -> str:
        pr = int(k.split("-")[0])
        t = scope.get(str(pr)) or []
        return "inprocess" if "inprocess" in t else "doc" if "doc" in t else "bugfix" if "bugfix" in t or kind.get(pr) == "bugfix" else "other"

    def size(k: str) -> int:
        m = prs.get(int(k.split("-")[0])) or {}
        return (m.get("additions") or 0) + (m.get("deletions") or 0)
    compared = sorted(p.stem for p in (SC / "lmreview" / "p990f2d2e_v0032_medium-rc" / "scores").glob("*.json")
                      if p.stem in ls)
    pilot: list[str] = []

    def add(k: str, into: list[str]) -> None:
        if k not in pilot + into and all(x.split("-")[0] != k.split("-")[0] for x in pilot + into):
            into.append(k)
    for k in PILOT_FIXED + tuple(compared):
        add(k, pilot)
    rest = sorted(ls)
    random.Random(seed).shuffle(rest)
    for want in ("inprocess", "doc", "inprocess", "small", "doc", "bugfix"):
        if len(pilot) >= 15:
            break
        for k in rest:
            if (tag(k) == want or (want == "small" and size(k) < 150)) and k not in pilot:
                before = len(pilot)
                add(k, pilot)
                if len(pilot) > before:
                    break
    holdout: list[str] = []
    by_tag = C.defaultdict(list)
    for k in rest:
        by_tag[tag(k)].append(k)
    while len(holdout) < 15 and any(by_tag.values()):
        for t in ("bugfix", "inprocess", "other", "doc"):
            while by_tag[t]:
                k = by_tag[t].pop(0)
                before = len(holdout)
                add(k, holdout)
                if len(holdout) > before:
                    break
            if len(holdout) >= 15:
                break
    sets = {"pilot": pilot[:15], "holdout": holdout[:15],
            "tags": {k: tag(k) for k in pilot + holdout}, "sizes": {k: size(k) for k in pilot + holdout},
            "points": {k: len(ls[k]) for k in pilot + holdout}}
    return sets


def sample_of(key: str) -> dict:
    pr, c = key.split("-")
    for x in (ROOT / "data" / "dataset" / "samples.jsonl").open():
        s = json.loads(x)
        if s["pr"] == int(pr) and s["commit"].startswith(c):
            return s
    raise KeyError(key)


def run(set_name: str, cap: float, workers: int) -> None:
    """The lmreview arm of skill_compare on the set's samples (cached runs are reused), judged."""
    sys.path.insert(0, str(ROOT / "scripts"))
    os.environ.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    import skill_compare as sc
    from concurrent.futures import ThreadPoolExecutor

    from lmreview.config import Config
    sets = json.loads((OUT / "sets.json").read_text())
    cfg, budget = Config(), sc.Budget(cap)

    def one(key: str) -> str:
        s = sample_of(key)
        try:
            r = sc.run_lmreview(cfg, s, budget)
            if r.get("findings") is None:
                return f"{key}: no findings ({r.get('error')})"
            sc.judge(cfg, s, "lmreview", r, budget)
        except sc.BudgetStop as e:
            return f"{key}: {e}"
        except Exception as e:  # noqa: BLE001  one sample failing must not stop the others
            return f"{key}: error {e!r}"
        return f"{key}: ok (spent ${budget.spent:.2f})"
    with ThreadPoolExecutor(workers) as ex:
        for msg in ex.map(one, sets[set_name]):
            print(msg, flush=True)
    print(f"spent this process: ${budget.spent:.2f}")


def rules_of(row: dict, entries: list[dict]) -> set[str]:
    """Active book entries that carry a resolved ledger row: an entry whose tests corrected the comment,
    or the end of the replaced_by chain of the entry that resolved it."""
    cid = str(row["comment"]).split(":")[0]
    active = {e["id"]: e for e in entries if e.get("status") != "retired"}
    byid = {e["id"]: e for e in entries}
    out = {e["id"] for e in active.values()
           if any(cid in map(str, t.get("comments") or []) for t in e.get("tests") or [])}
    cur = (row.get("resolved_by") or {}).get("entry")
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        if cur in active:
            out.add(cur)
            break
        cur = ((byid.get(cur) or {}).get("retired") or {}).get("replaced_by")
    return out


PATHS = {str(c["id"]): c.get("path") for c in map(json.loads, (ROOT / "data" / "dataset" / "comments.jsonl").open())}


def tag_dir(reviewer: str, rep: int) -> str:
    return reviewer.replace("+", "_").replace("@", "_") + (f"#r{rep}" if rep > 1 else "")


def report(set_name: str, reviewer: str, reps: list[int], book_entries: list[dict] | None = None) -> dict:
    """Per point: hits over the repeats; misses classified a/b/c/x; cost per run. Free."""
    sets = json.loads((OUT / "sets.json").read_text())
    ls, entries = learned_samples(), book_entries or book()
    pts, miss_cls, cost, n_runs = [], C.Counter(), [], 0
    for key in sets[set_name]:
        rows = ls[key]
        per_rep = []
        for k in reps:
            d = tag_dir(reviewer, k)
            rp, sp = SC / "lmreview" / "runs" / d / f"{key}.json", SC / "lmreview" / d / "scores" / f"{key}.json"
            bp = SC / "lmreview" / d / "blind" / f"{key}.json"
            if not (rp.exists() and sp.exists() and bp.exists()):
                per_rep.append(None)
                continue
            run_, sc_, mp = json.loads(rp.read_text()), json.loads(sp.read_text()), json.loads(bp.read_text())["map"]
            cost.append(run_.get("cost") or 0)
            n_runs += 1
            per_rep.append((run_, sc_, mp))
        for row in rows:
            cid, _, point = str(row["comment"]).partition(":")
            hits, classes = 0, []
            for got in per_rep:
                if got is None:
                    continue
                run_, sc_, mp = got
                hs = [h for h in sc_["human"]  # a key is "<comment id>" or "<comment id>:<point>"
                      if str(h.get("key")) == str(row["comment"]) or (not point and str(h.get("key")).split(":")[0] == cid)]
                hit = any(h.get("matched_ai") for h in hs)
                hits += hit
                if hit:
                    continue
                if row["status"] == "covered":
                    classes.append("a")
                    continue
                rs = rules_of(row, entries)
                if not rs:
                    classes.append("x")
                    continue
                fired = [f for f in run_.get("findings") or [] if (f.get("rule") in rs or set(f.get("rules") or []) & rs)]
                here = [f for f in fired if any(loc.get("path") == PATHS.get(cid) for loc in f.get("locations") or [])]
                classes.append("c" if here else "c-elsewhere" if fired else "b")
            n = sum(g is not None for g in per_rep)
            pts.append({"sample": key, "comment": row["comment"], "status": row["status"], "hits": hits, "n": n,
                        "classes": classes, "rules": sorted(rules_of(row, entries)) if row["status"] == "resolved" else []})
            miss_cls.update(classes)
    full = [p for p in pts if p["n"] == len(reps)]
    dist = C.Counter(f"{p['hits']}/{p['n']}" for p in full)
    return {"set": set_name, "reviewer": reviewer, "reps": reps, "points": len(pts), "complete": len(full),
            "retained": dist.get(f"{len(reps)}/{len(reps)}", 0),
            "retention": round(dist.get(f"{len(reps)}/{len(reps)}", 0) / len(full), 3) if full else None,
            "dist": dict(sorted(dist.items())), "miss_classes": dict(miss_cls),
            "by_status": {s: dict(C.Counter(f"{p['hits']}/{p['n']}" for p in full if p["status"] == s)) for s in ("covered", "resolved")},
            "runs": n_runs, "cost_per_run": round(sum(cost) / len(cost), 3) if cost else None, "detail": pts}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["select", "run", "report"])
    ap.add_argument("--set", default="pilot")
    ap.add_argument("--cap", type=float, default=25.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--reviewer", default=os.environ.get("SC_REVIEWER", "p990f2d2e+v0032@medium-rc"))
    ap.add_argument("--reps", type=int, nargs="+", default=[1, 2])
    ap.add_argument("--detail", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.cmd == "select":
        p = OUT / "sets.json"
        if p.exists():
            print(f"{p} exists: the sets are fixed at t0 (delete it by hand to reselect)")
            print(p.read_text())
            return
        sets = select()
        p.write_text(json.dumps(sets, indent=1))
        print(json.dumps(sets, indent=1))
    elif a.cmd == "run":
        run(a.set, a.cap, a.workers)
    else:
        r = report(a.set, a.reviewer, a.reps)
        if not a.detail:
            r.pop("detail")
        print(json.dumps(r, indent=1))


if __name__ == "__main__":
    main()

"""Compress experiments on a copy: compress a frozen book, vet the candidate, repeat with the undone merges as
feedback; never touches lmreview/state/.

    python3 scripts/compress_exp.py NAME [--base v0027] [--tries 2] [--compress-cost 3] [--vet-cost 8] [--note "..."]

Writes rules/<NAME>k<k>.jsonl (candidates) and rules/<NAME>k<k>v.jsonl (what vet kept), the result to
data/compress_exp/<NAME>.json, and one line to data/compress_exp/results.md. Fails if state/ changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from lmreview import llm  # noqa: E402
from lmreview.config import Config, get  # noqa: E402
from lmreview.distill import COMPRESS, FINAL_COMPRESS, _size, compress  # noqa: E402
from lmreview.reviewer import load_rules  # noqa: E402
from lmreview.state import STATE, compress_undone, outcomes, prompt_id  # noqa: E402
from lmreview.vet import vet  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[1] / "data" / "compress_exp"


def state_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(STATE.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(STATE)).encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


COST = {"draft": 0.0, "final": 0.0, "vet": 0.0, "other": 0.0}
DRAFTS: list[str] = []  # raw draft outputs of the current compress
_run = llm.run
_draft_head, _final_head = COMPRESS[:60], FINAL_COMPRESS[:60]
_phase = ["other"]


def run(prompt: str, *a, **k) -> dict:
    """llm.run, with its cost booked to the compress draft / final / vet phase."""
    r = _run(prompt, *a, **k)
    kind = "draft" if prompt.startswith(_draft_head) else "final" if prompt.startswith(_final_head) else _phase[0]
    COST[kind] = COST.get(kind, 0.0) + float(r.get("cost") or 0)
    if kind == "draft":
        DRAFTS.append(r.get("text") or "")
    return r


llm.run = run


def size(name: str) -> tuple[int, int]:
    act = [r for r in load_rules(name) if r.get("status", "active") == "active"]
    return len(act), sum(map(_size, act))


def draft_groups(text: str) -> list[list[str]]:
    try:
        arr = llm.extract_json(text)
    except Exception:
        return []
    return [sorted(d.get("rules") or []) for d in arr or [] if isinstance(d, dict) and d.get("op") in ("merge", "absorb")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--base", default="v0027")
    ap.add_argument("--tries", type=int, default=2)
    ap.add_argument("--compress-cost", type=float, default=3.0)
    ap.add_argument("--vet-cost", type=float, default=8.0)
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cfg, h0, t0 = Config(), state_hash(), time.time()
    effort = str(get("distill", "effort"))
    e0, w0 = size(a.base)
    cur, fb, tries = a.base, [], []
    for k in range(1, a.tries + 1):
        out = f"{a.name}k{k}"
        DRAFTS.clear()
        _phase[0] = "other"
        c0 = dict(COST)
        msg, retired = compress(out, cur, cfg, effort=effort, max_cost=a.compress_cost, record=outcomes(), feedback=fb)
        ch = json.loads((cfg.data / "distill" / out / "changes.json").read_text())
        tr = {"try": k, "base": cur, "candidate": out, "compress": msg,
              "draft_groups": [draft_groups(t) for t in DRAFTS],
              "taken": [{"op": c["op"], "rules": c["rules"]} for c in ch if c["op"].startswith("consolidate-")],
              "cost_draft": round(COST["draft"] - c0["draft"], 2), "cost_final": round(COST["final"] - c0["final"], 2)}
        tries.append(tr)
        if not retired:
            tr["stop"] = "nothing proposed"
            break
        _phase[0] = "vet"
        v0, res = COST["vet"], {}
        vet(out, base=cur, prompt=prompt_id(), effort="high", suffix="-ro", max_cost=a.vet_cost, write=out + "v",
            cfg=cfg, out=res)
        _phase[0] = "other"
        tr["cost_vet"] = round(COST["vet"] - v0, 2)
        if not res:
            tr["stop"] = "vet returned nothing"
            break
        tr["verdict"] = res["verdict"]
        J = res["J"]
        tr["lost"] = [[i, str(e)] for i, e in J["lost"]]
        tr["no_effect"] = J["no_effect"]
        if res["verdict"] == "INCOMPLETE":
            tr["stop"] = "vet INCOMPLETE"
            break
        groups, rows = compress_undone(out, {r["id"] for r in load_rules(cur)}, load_rules(out), J, cfg)
        tr["groups"] = {t: g for t, g in groups.items()}
        tr["undone"] = [{"group": r["group"], "into": r["into"],
                         "lost": [{"entry": x["entry"], "comment": str(x["comment"]), "check": x.get("check")}
                                  for x in r["lost"]]} for r in rows]
        tr["kept_groups"] = len(groups) - len(rows)
        tr["after"] = size(out + "v")
        fb += rows
        cur = out + "v"
        if not rows:
            break
    e1, w1 = size(cur)
    h1 = state_hash()
    result = {"name": a.name, "note": a.note, "base": a.base, "final": cur, "before": [e0, w0], "after": [e1, w1],
              "words_cut": round(1 - w1 / w0, 3), "tries": tries, "cost": {k: round(v, 2) for k, v in COST.items()},
              "minutes": round((time.time() - t0) / 60, 1), "state_unchanged": h0 == h1}
    (OUT / f"{a.name}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    proposed = sum(len(t["taken"]) for t in tries)
    kept = sum(t.get("kept_groups", 0) for t in tries)
    lost = sum(len(t.get("lost") or []) for t in tries)
    line = (f"| {a.name} | {a.note} | {proposed} / {kept} | {e0}→{e1} entries, {w0}→{w1} words "
            f"(-{result['words_cut']:.0%}) | {lost} lost (undone) | draft ${result['cost']['draft']:.2f}, "
            f"final ${result['cost']['final']:.2f}, vet ${result['cost']['vet']:.2f} |")
    with (OUT / "results.md").open("a") as f:
        f.write(line + "\n")
    print(line)
    print(json.dumps({k: result[k] for k in ("before", "after", "words_cut", "cost", "minutes", "state_unchanged")}))
    if h0 != h1:
        raise SystemExit("state/ CHANGED during the experiment")


if __name__ == "__main__":
    main()

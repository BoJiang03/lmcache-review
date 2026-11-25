"""How often an UNCHANGED entry misses one of its own proven cases in a vet-style replay (rule check alone,
only that entry shown), i.e. the noise floor for "lost" in a compress vet. Never touches lmreview/state/.

    python3 scripts/compress_noise.py [--book v0027] [--n 10] [--reps 2] [--max-cost 6] [--seed 1]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from lmreview.config import RULES, Config  # noqa: E402
from lmreview.regress import replay  # noqa: E402
from lmreview.reviewer import load_rules  # noqa: E402
from lmreview.state import book_path, prompt_id  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from compress_exp import OUT, state_hash  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="v0027")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--max-cost", type=float, default=6.0)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    h0 = state_hash()
    copy = f"noise{a.book[1:]}"
    shutil.copy(book_path(a.book), RULES / f"{copy}.jsonl")  # same text, a name of its own: no cached runs
    act = [r for r in load_rules(copy) if r.get("status", "active") == "active"]
    cases = [(r["id"], {"target": t["target"], "with": f"{prompt_id()}@high", "comments": t["comments"][:1]})
             for r in act for t in r.get("tests") or [] if t.get("result") == "corrected" and t.get("comments")]
    seen, pick = set(), []
    random.Random(a.seed).shuffle(cases)
    for c in cases:  # one case per target: targets are what cost
        if c[1]["target"] not in seen:
            seen.add(c[1]["target"])
            pick.append(c)
        if len(pick) == a.n:
            break
    rows, cost = [], 0.0
    for i, t in pick:
        r, c = replay(copy, [(i, t)], a.reps, a.max_cost - cost, Config(), suffix="-ro", only={i})
        rows += r
        cost += c
    out = [{"entry": r["entry"], "target": r["target"], "runs": r.get("runs") or r.get("passes"), "passed": r.get("passed")}
           for r in rows]
    res = {"book": a.book, "cases": out, "cost": round(cost, 2), "state_unchanged": state_hash() == h0}
    (OUT / f"noise_{a.book}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

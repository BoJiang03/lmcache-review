"""retain by severity tier ([tiers] retain_need / retain_requeues) on a temp state and data dir. No LLM calls.

Run: python3 tests/test_retain_tiers.py (or pytest)."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

TMP = tempfile.gettempdir()
os.environ["LMREVIEW_STATE"] = tempfile.mkdtemp(prefix="lmr-state-", dir=TMP)  # before importing state
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lmreview import replay as replay_mod, runs, score, state  # noqa: E402
from lmreview.config import Config  # noqa: E402

S = {"pr": 7, "commit": "c" * 40}
# comment: (severity, hits of 2, retain requeues so far) -> expected outcome
CASES = {31: ("major", 1, 0, "requeued"), 32: ("major", 1, 2, "needs_human"), 33: ("blocker", 2, 0, "retained"),
         41: ("minor", 1, 0, "requeued"), 42: ("minor", 1, 1, "unretained"),
         51: ("nit", 1, 0, "retained"), 52: ("nit", 0, 0, "unretained")}


def test_retain_tiers() -> None:
    cfg = Config(data=pathlib.Path(tempfile.mkdtemp(prefix="lmr-data-", dir=TMP)))
    ann = cfg.data / "annotations" / "a2"
    ann.mkdir(parents=True)
    ann.joinpath(f"7-{'c' * 8}.json").write_text(json.dumps({"comments": {
        str(c): [{"text": "t", "type": "change_request", "severity": v[0]}] for c, v in CASES.items()}}))
    state.save_ledger({c: {"comment": c, "pr": 7, "commit": S["commit"], "status": "resolved", "reviewer": "x",
                           "tries": [], **({"retain_requeues": v[2]} if v[2] else {})} for c, v in CASES.items()})
    old = replay_mod.replay, score.judge_runs, runs.hits, state._retain_why, state.load_book
    replay_mod.replay = lambda *a, **k: 0.0
    score.judge_runs = lambda *a, **k: ([], 0.0)
    runs.hits = lambda rv, smp, c, cfg: (CASES[c][1], 2)
    state._retain_why = lambda *a: "why"
    state.load_book = lambda name: []
    try:
        line = state.retain_step({7}, 1.0, 2, cfg=cfg, reviewer="p1+v0001@medium-rc")
    finally:
        replay_mod.replay, score.judge_runs, runs.hits, state._retain_why, state.load_book = old
    rows = state.ledger()
    got = {c: ("retained" if r.get("retained") else "unretained" if r.get("unretained") else r["status"].replace("to_distill", "requeued"))
           for c, r in rows.items()}
    assert got == {c: v[3] for c, v in CASES.items()}, (got, line)
    assert "major+ 1/3" in line and "nit 1/2" in line, line


if __name__ == "__main__":
    test_retain_tiers()
    print("ok")

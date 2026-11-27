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
    """Each tier is retained, requeued, marked unretained or parked as [tiers] says."""
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


def test_vet_tolerates_nit_losses() -> None:
    """vet moves lost nit points (per point of a multi-point comment) to tolerated, the rest stay lost."""
    from lmreview import vet
    cfg = Config(data=pathlib.Path(tempfile.mkdtemp(prefix="lmr-data-", dir=TMP)))
    ann = cfg.data / "annotations" / "a2"
    ann.mkdir(parents=True)
    ann.joinpath("8-dddddddd.json").write_text(json.dumps({"comments": {
        "61": [{"text": "t", "type": "nit", "severity": "nit"}],
        "62": [{"text": "t", "type": "change_request", "severity": "major"}],
        "63": [{"text": "a", "type": "change_request", "severity": "nit"},
               {"text": "b", "type": "change_request", "severity": "minor"}]}}))
    J = {"lost": [("e1", 61), ("e2", 62), ("e3", "63:0"), ("e3", "63:1")]}
    vet._tolerate(J, cfg)
    assert J["tolerated"] == [("e1", 61), ("e3", "63:0")], J
    assert J["lost"] == [("e2", 62), ("e3", "63:1")], J


def test_compress_hit() -> None:
    """Retained resolved rows behind entries a compress merged, retired or rewrote; not those behind kept text."""
    old = {"a": {"id": "a", "when": "w", "expect": "e", "evidence": [1]},
           "b": {"id": "b", "when": "w", "expect": "e", "evidence": [2]},
           "c": {"id": "c", "when": "w", "expect": "e", "evidence": [3]},
           "d": {"id": "d", "when": "w", "expect": "e", "evidence": [4]}}
    new = [{"id": "a", "when": "w", "expect": "e"},                   # kept as is
           {"id": "b", "when": "w2", "expect": "e"},                  # rewritten
           {"id": "c", "status": "retired", "when": "w", "expect": "e"},  # merged away
           {"id": "m", "when": "w", "expect": "e"}]                   # the merge; d dropped
    row = lambda c, **k: {"comment": c, "pr": 1, "commit": "x" * 40, "status": "resolved", "tries": [], **k}  # noqa: E731
    rows = {1: row(1, retained={"hits": "2/2"}), 2: row(2, retained={"hits": "2/2"}), 3: row(3, retained={"hits": "2/2"}), 4: row(4),
            5: row(5, retained={"hits": "2/2"}, status="covered")}
    assert state.compress_hit(old, new, rows) == {2, 3}, state.compress_hit(old, new, rows)


if __name__ == "__main__":
    test_compress_hit()
    test_retain_tiers()
    test_vet_tolerates_nit_losses()
    print("ok")

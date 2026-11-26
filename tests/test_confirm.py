"""round's miss confirmation (C, state.confirm_misses) on a temp state and data dir. No LLM calls.

Run: python3 tests/test_confirm.py (or pytest)."""

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

RV = "p1234abcd+v0001@high-ms"
A, B = {"pr": 1, "commit": "a" * 40}, {"pr": 2, "commit": "b" * 40}


def put(cfg: Config, s: dict, k: int, matched: dict) -> None:
    """Run k of RV on sample s, judged: `matched` {comment: matched?}."""
    f = runs.run_dir(cfg, RV, k) / runs.sample_file(s)
    fs = [{"id": "f1", "severity": "minor", "scope": "pr", "title": "t"}]
    runs.save_run(cfg, f, {**s, "findings": fs, "error": None, "model": ""})
    sp = cfg.data / "scores" / f.parent.name / f.name
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({"judge": score.JUDGE, "gold_ids": list(matched), "ai": [], "human": [
        {"id": i, "key": c, "type": "change_request", "matched_ai": ["f1"] if m else []}
        for i, (c, m) in enumerate(matched.items())]}))


def test_confirm_misses() -> None:
    cfg = Config(data=pathlib.Path(tempfile.mkdtemp(prefix="lmr-data-", dir=TMP)))
    ds = cfg.data / "dataset"
    ds.mkdir(parents=True)
    (ds / "samples.jsonl").write_text("".join(json.dumps({**s, "split": "train", "gold_ids": g, "time": "t"}) + "\n"
                                              for s, g in ((A, [11, 12]), (B, [21]))))
    (ds / "comments.jsonl").write_text("".join(json.dumps({"id": i, "author": "a", "body": "b"}) + "\n" for i in (11, 12, 21)))
    put(cfg, A, 1, {11: False, 12: False})
    put(cfg, B, 1, {21: False})
    rows = {k: {"comment": k, "pr": s["pr"], "commit": s["commit"], "status": "to_distill", "reviewer": RV, "tries": []}
            for k, s in ((11, A), (12, A), (21, B))}
    rows[99] = {"comment": 99, "pr": 2, "commit": B["commit"], "status": "covered", "reviewer": RV, "tries": []}
    state.save_ledger(rows)
    calls = []

    def fake_replay(reviewer, split, limit, workers, max_cost, prs, cfg=None, rep=1):
        calls.append((reviewer, sorted(prs), rep, max_cost))
        put(cfg, A, rep, {11: True, 12: False})  # B's second run does not happen (say, the cost cap)
        return 0.7

    def fake_judge(cfg_, reviewer, prs, split, max_cost, rep=1):
        calls.append(("judge", reviewer, sorted(prs), rep))
        return [], 0.3

    old = replay_mod.replay, score.judge_runs
    replay_mod.replay, score.judge_runs = fake_replay, fake_judge
    try:
        line, cost = state.confirm_misses(RV, [11, 12, 21, 99], 10.0, cfg)
    finally:
        replay_mod.replay, score.judge_runs = old
    assert line == "confirm: 3 misses, 1 flaky, $1.00, 1 unconfirmed", line
    assert abs(cost - 1.0) < 1e-9
    assert calls[0][:3] == (RV, ["1:aaaaaaaa", "2:bbbbbbbb"], 2) and calls[1] == ("judge", RV, [1, 2], 2), calls
    led = state.ledger()
    assert led[11]["status"] == "to_distill" and led[11]["flaky"] is True and led[11]["hits"] == "1/2"
    assert led[12]["status"] == "to_distill" and "flaky" not in led[12] and led[12]["hits"] == "0/2"
    assert led[21]["unconfirmed"] is True and "hits" not in led[21]
    assert "flaky" not in led[99]
    order = [r["comment"] for r in sorted(state.to_distill(led), key=state.distill_order)]
    assert order == [12, 21, 11], order  # the flaky miss goes last
    log = [json.loads(x) for x in (state.STATE / "log.jsonl").read_text().splitlines()]
    assert log[-1]["step"] == "confirm" and log[-1]["flaky"] == 1, log[-1]


def test_confirm_nothing() -> None:
    assert state.confirm_misses(RV, [], 10.0, Config(data=pathlib.Path(TMP)))[0] == "confirm: 0 misses, 0 flaky, $0.00"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

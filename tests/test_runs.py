"""Run records (runs.py): repeats, models, hits. Synthetic data in a temp dir; no LLM calls.

Run: python3 tests/test_runs.py (or pytest)."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lmreview import llm, runs  # noqa: E402
from lmreview.config import Config  # noqa: E402
from lmreview.score import JUDGE  # noqa: E402

R = "p1234abcd+v0001@high-rc"
SAMPLE = {"pr": 7, "commit": "abcdef0123456789"}


def tmp_cfg() -> Config:
    """A Config whose data dir is a fresh temp dir."""
    return Config(data=pathlib.Path(tempfile.mkdtemp(prefix="lmr-test-", dir="/home/bo/.claude/jobs/63e1ad63/tmp")))


def put(cfg: Config, k: int, findings: list | None, human: list | None, model: str | None = "claude-opus-5-5",
        reviewer: str = R) -> None:
    """Write run k of `reviewer` on SAMPLE and (if `human`) its score."""
    run = {"pr": 7, "commit": SAMPLE["commit"], "findings": findings, "error": None if findings is not None else "bad"}
    if model is not None:
        run["model"] = model
    runs.save_run(cfg, runs.run_dir(cfg, reviewer, k) / runs.sample_file(SAMPLE), run)
    if human is not None:
        sp = cfg.data / "scores" / runs.run_dir(cfg, reviewer, k).name / runs.sample_file(SAMPLE)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({"judge": JUDGE, "gold_ids": [11, 12], "ai": [],
                                  "human": [{"id": i, "key": key, "type": "change_request", "matched_ai": m}
                                            for i, (key, m) in enumerate(human)]}))


def test_run_dir_and_reps() -> None:
    cfg = tmp_cfg()
    assert runs.run_dir(cfg, R, 1).name == R and runs.run_dir(cfg, R, 3).name == R + "#r3"
    assert runs.sample_file("#7@abcdef01") == runs.sample_file(SAMPLE) == "7-abcdef01.json"
    put(cfg, 1, [], None)
    put(cfg, 2, [], None)
    put(cfg, 1, [], None, reviewer=R + "#oabc")  # another cache tag: not a repeat of R
    assert [k for k, _ in runs.rep_dirs(cfg, R)] == [1, 2]


def test_hits() -> None:
    cfg = tmp_cfg()
    f = {"id": "f1", "severity": "minor", "scope": "pr", "title": "t", "rule": "e1", "rules": ["e1"]}
    g = {"id": "f2", "severity": "minor", "scope": "pr", "title": "t", "rule": None, "rules": []}
    put(cfg, 1, [g], [(11, []), ("12:0", [])])          # missed both
    put(cfg, 2, [f, g], [(11, ["f1"]), ("12:0", ["f2"])])  # 11 by a citing finding, 12:0 by another
    put(cfg, 3, [], None)                               # no findings: every comment missed, no score
    put(cfg, 4, None, None)                             # failed run: not counted
    put(cfg, 5, [g], [(11, ["f2"])])                    # judged for comment 11 only
    assert runs.hits(R, SAMPLE, 11, cfg) == (2, 4)
    assert runs.hits(R, SAMPLE, 11, cfg, cites={"e1"}) == (1, 4)
    assert runs.hits(R, SAMPLE, "12:0", cfg) == (1, 3)
    assert runs.hits(R, SAMPLE, 12, cfg) == (1, 3)      # a comment id is matched by any of its points
    assert runs.hits(R, "#7@abcdef01", "12:0", cfg, cites={"e1"}) == (0, 3)
    assert runs.hits(R + "#r9", SAMPLE, 11, cfg) == (0, 0)


def test_models() -> None:
    cfg = tmp_cfg()
    assert llm.primary_model({"modelUsage": {"a": {"costUSD": 0.1}, "b": {"costUSD": 2.0}}}) == "b"
    assert llm.primary_model({}) is None
    path = runs.models_path(cfg)
    llm.observe("default", "claude-opus-5-5", path)
    llm.observe("claude-sonnet-5-5", "claude-sonnet-5-5", path)
    put(cfg, 1, [], None, model="claude-opus-5-5")
    f = runs.run_dir(cfg, R, 1) / runs.sample_file(SAMPLE)
    assert runs.cached(cfg, R, f)
    put(cfg, 2, [], None, model=None)                    # older run: unknown model, still reused
    f2 = runs.run_dir(cfg, R, 2) / runs.sample_file(SAMPLE)
    assert runs.cached(cfg, R, f2)
    llm.observe("default", "claude-opus-5-6", path)      # Claude Code moved its default model
    assert json.loads(path.read_text())["default"] == "claude-opus-5-6"
    assert not runs.cached(cfg, R, f)
    assert runs.cached(cfg, R, f2)
    put(cfg, 3, None, None, model="")                    # failed: reused unless rerun_failed
    f3 = runs.run_dir(cfg, R, 3) / runs.sample_file(SAMPLE)
    assert runs.cached(cfg, R, f3) and not runs.cached(cfg, R, f3, rerun_failed=True)
    assert runs.run_models({"model": "b", "runs": [{"model": "a"}, {"model": None}, {}]}) == "a,b"
    assert runs.run_models({}) == ""
    assert runs.unknown_model(cfg, R, [SAMPLE]) == 1


def test_save_run_moves_score() -> None:
    cfg = tmp_cfg()
    put(cfg, 1, [{"id": "f1", "severity": "minor", "scope": "pr", "title": "t"}], [(11, ["f1"])])
    assert runs.hits(R, SAMPLE, 11, cfg) == (1, 1)
    put(cfg, 1, [{"id": "f1", "severity": "minor", "scope": "pr", "title": "t"}], None)      # run again: the old score must not be read for it
    assert runs.hits(R, SAMPLE, 11, cfg) == (0, 0)
    assert (cfg.data / "scores" / "_replaced" / R / runs.sample_file(SAMPLE)).exists()


def dataset(cfg: Config) -> None:
    """A one-sample gold set (train) with comments 11 and 12."""
    ds = cfg.data / "dataset"
    ds.mkdir(parents=True, exist_ok=True)
    (ds / "samples.jsonl").write_text(json.dumps({**SAMPLE, "split": "train", "gold_ids": [11, 12], "time": "t"}) + "\n")
    (ds / "comments.jsonl").write_text("".join(json.dumps({"id": i, "author": "a", "body": "b", "kind": "review"}) + "\n"
                                               for i in (11, 12)))


def test_judge_runs_rep() -> None:
    from lmreview.score import judge_runs
    from lmreview.settings import get
    cfg = tmp_cfg()
    dataset(cfg)
    f = {"id": "f1", "severity": "minor", "scope": "pr", "title": "t"}
    put(cfg, 1, [f], [(11, []), (12, [])])
    put(cfg, 2, [f], [(11, ["f1"]), (12, [])])
    for k in (1, 2):  # judged already: read from disk, no call
        sp = cfg.data / "scores" / runs.run_dir(cfg, R, k).name / runs.sample_file(SAMPLE)
        sp.write_text(json.dumps({**json.loads(sp.read_text()), "effort": get("judge", "effort"), "cost": 0}))
    out, cost = judge_runs(cfg, R, {7}, "train", 0.0, rep=2)
    assert cost == 0 and len(out) == 1 and out[0][1]["human"][0]["matched_ai"] == ["f1"]
    assert runs.hits(R, SAMPLE, 11, cfg) == (1, 2)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

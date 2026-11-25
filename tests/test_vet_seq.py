"""vet's sequential check (B): verdict rules, and a whole vet over a fake replay. No LLM calls.

Run: python3 tests/test_vet_seq.py (or pytest)."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lmreview import runs, vet  # noqa: E402
from lmreview.config import Config  # noqa: E402
from lmreview.regress import run_tag  # noqa: E402
from lmreview.score import JUDGE  # noqa: E402

TMP = "/home/bo/.claude/jobs/63e1ad63/tmp"


def test_effect_verdict() -> None:
    v = vet.effect_verdict
    assert v(0, 0) == ("more", 1) and v(1, 1) == ("more", 2) and v(0, 1) == ("more", 2)
    assert v(2, 2)[0] == "works" and v(0, 2)[0] == "no" and v(1, 2) == ("more", 4)
    assert v(3, 4)[0] == "works" and v(2, 4)[0] == "no" and v(1, 3)[0] == "no" and v(2, 3) == ("more", 4)
    assert v(3, 3)[0] == "works" and v(4, 5)[0] == "works" and v(3, 5)[0] == "no"


def test_side_verdict() -> None:
    v, b = vet.side_verdict, vet.base_verdict
    assert v(1, 1)[0] == "kept" and v(0, 1) == ("more", 2) and v(0, 2)[0] == "miss"
    assert v(1, 2) == ("more", 3) and v(2, 3)[0] == "kept" and v(1, 3)[0] == "miss" and v(2, 2)[0] == "kept"
    assert b(1, 1)[0] == "hit" and b(0, 1) == ("more", 2) and b(0, 2)[0] == "miss" and b(1, 2)[0] == "hit"


# ---- a whole vet: NEW adds e2 (evidence 201, effect) and rewrites e1 (evidence 101, side effect) --------

S1, S2 = (1, "a" * 40), (2, "b" * 40)
OLD = [{"id": "e1", "when": "x happens", "expect": "say y", "evidence": [101]}]
NEW = [{"id": "e1", "when": "x happens at all", "expect": "say y", "evidence": [101]},
       {"id": "e2", "when": "z happens", "expect": "say w", "evidence": [201]}]
# (book, sample pr, run k) -> whether the run matches the sample's comment with a finding citing the entry
OUT = {("n1", 2, 1): True, ("n1", 2, 2): False, ("n1", 2, 3): True, ("n1", 2, 4): True,
       ("n1", 1, 1): False, ("n1", 1, 2): True, ("n1", 1, 3): False,
       ("b0", 1, 1): True}


def setup(monkey: dict, cfg: Config) -> dict:
    """Patch vet's inputs and its replay with synthetic ones; returns the log of runs made."""
    ss = {S1: {"pr": 1, "commit": S1[1], "gold_ids": [101], "split": "train"},
          S2: {"pr": 2, "commit": S2[1], "gold_ids": [201], "split": "train"}}
    cm = {101: {"id": 101, "author": "h", "body": "b1"}, 201: {"id": 201, "author": "h", "body": "b2"}}
    made: dict = {"runs": []}

    def fake_replay(book, cases, reps, max_cost, cfg_, workers=4, suffix="", only=None):
        spent, rows = 0.0, []
        for i, t in cases:
            pr = int(t["target"].split("@")[0])
            rv = f"p1+{book}@high{suffix}" + run_tag(only)
            flags = []
            for k in range(1, reps + 1):
                f = runs.run_dir(cfg, rv, k) / f"{pr}-{t['target'].split('@')[1]}.json"
                if not f.exists():
                    if spent >= max_cost:
                        flags.append(None)
                        continue
                    hit = OUT.get((book, pr, k), False)
                    fs = [{"id": "f1", "severity": "minor", "scope": "pr", "title": "t", "rule": i, "rules": [i]}]
                    runs.save_run(cfg, f, {"pr": pr, "commit": t["target"].split("@")[1], "findings": fs, "error": None})
                    sp = cfg.data / "scores" / f.parent.name / f.name
                    sp.parent.mkdir(parents=True, exist_ok=True)
                    c = t["comments"][0]
                    sp.write_text(json.dumps({"judge": JUDGE, "gold_ids": [c], "ai": [], "human": [
                        {"id": 0, "key": c, "type": "change_request", "matched_ai": ["f1"] if hit else []}]}))
                    spent += 1.0
                    made["runs"].append((book, pr, k))
                sc = json.loads((cfg.data / "scores" / f.parent.name / f.name).read_text())
                flags.append(bool(sc["human"][0]["matched_ai"]))
            ran = [x for x in flags if x is not None]
            rows.append({"entry": i, "target": t["target"], "comments": t["comments"], "reviewer": book, "runs": flags,
                         "passed": any(ran) if ran else None, "any": any(ran) if ran else None, "invalid": 0,
                         "verdicts": []})
        return rows, spent

    monkey.update({"replay": vet.replay, "load_gold": vet.load_gold, "load_rules": vet.load_rules,
                   "book_meta": vet.book_meta, "REPORTS": vet.REPORTS})
    vet.replay = fake_replay
    vet.load_gold = lambda cfg_: (ss, cm)
    vet.load_rules = lambda name: {"n1": NEW, "b0": OLD}[name]
    vet.book_meta = lambda name: {"base": "b0", "runs": "p1+b0@high-ms"}
    vet.REPORTS = pathlib.Path(tempfile.mkdtemp(dir=TMP))
    return made


def restore(monkey: dict) -> None:
    for k, v in monkey.items():
        setattr(vet, k, v)


def test_vet_sequential() -> None:
    cfg = Config(data=pathlib.Path(tempfile.mkdtemp(prefix="lmr-vet-", dir=TMP)))
    monkey: dict = {}
    made = setup(monkey, cfg)
    try:
        plan = vet.vet("n1", cfg=cfg, max_cost=0)
        assert "plus 1 second runs of effect samples" in plan and "est $2" in plan, plan
        out: dict = {}
        rep = vet.vet("n1", cfg=cfg, max_cost=20, out=out)
    finally:
        restore(monkey)
    J = out["J"]
    assert J["works"] == {"e2"} and J["lost"] == [("e1", 101)] and not J["unknown"] and not J["s_unknown"], J
    assert out["verdict"] == "PARTLY KEPT", out["verdict"]
    assert "(NEW 3/4)" in rep and "NEW 1/3, BASE 1/1" in rep, rep
    assert sorted(made["runs"]) == sorted(OUT), made["runs"]  # every planned run, none twice


def test_vet_sequential_capped() -> None:
    cfg = Config(data=pathlib.Path(tempfile.mkdtemp(prefix="lmr-vet-", dir=TMP)))
    monkey: dict = {}
    setup(monkey, cfg)
    try:
        out: dict = {}
        rep = vet.vet("n1", cfg=cfg, max_cost=4, out=out)  # first pass, base, one retry, one more: then the cap
    finally:
        restore(monkey)
    assert out["verdict"] == "INCOMPLETE", rep
    assert "undecided" in rep or "NOT RUN" in rep, rep


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

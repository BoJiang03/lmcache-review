"""`lmreview watch` (watch.py): what gets reviewed, what gets learned, how steps are invoked.
Synthetic homes in a temp dir; `gh` and the lmreview subprocesses are stubbed: no LLM, no GitHub.

Run: python3 tests/test_watch.py (or pytest)."""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lmreview import watch  # noqa: E402

TMP = pathlib.Path(os.environ.get("CLAUDE_JOB_DIR", tempfile.gettempdir())) / "tmp"
NOW = dt.datetime(2026, 11, 27, 12, tzinfo=dt.timezone.utc)


def new_home(**settings: object) -> tuple[pathlib.Path, dict]:
    TMP.mkdir(parents=True, exist_ok=True)
    home = pathlib.Path(tempfile.mkdtemp(prefix="lmr-watch-", dir=TMP))
    w = {"repo": "o/r", "branch": "main", "since": "2026-11-20", "learn_from": "2026-11-20T00:00:00Z",
         "added": "2026-11-20T00:00:00Z", "settings": {**watch.DEFAULTS, **settings}, "reviewed": {},
         "learned": {}, "spent": {"review": 0.0, "learn": 0.0}, "cycles": 0, "last_cycle": None}
    watch.save(home, w)
    return home, watch.load(home)


def pr(n: int, head: str, draft: bool = False, bot: bool = False, updated: str = "2026-11-26T00:00:00Z") -> dict:
    return {"number": n, "title": f"pr {n}", "isDraft": draft, "headRefOid": head, "updatedAt": updated,
            "baseRefName": "main", "author": {"login": "x[bot]" if bot else "alice", "__typename": "User"}}


def test_to_review() -> None:
    _, w = new_home()
    w["reviewed"] = {"1": {"commit": "a" * 40, "ok": True},                 # same head, done
                     "2": {"commit": "b" * 40, "ok": True},                 # pushed since
                     "3": {"commit": "c" * 40, "ok": False, "fails": 3},    # gave up on this head
                     "4": {"commit": "d" * 40, "ok": False, "fails": 1}}    # retry
    prs = [pr(1, "a" * 40), pr(2, "B" * 40, updated="2026-11-25T00:00:00Z"), pr(3, "c" * 40), pr(4, "d" * 40),
           pr(5, "e" * 40, draft=True), pr(6, "f" * 40, bot=True), pr(7, "g" * 40, updated="2026-11-24T00:00:00Z")]
    assert [p["number"] for p in watch.to_review(w, prs)] == [7, 2, 4]  # oldest update first
    w["settings"]["drafts"] = True
    assert 5 in [p["number"] for p in watch.to_review(w, prs)]


def put_dataset(home: pathlib.Path, prs: list[dict], comments: list[dict], samples: list[dict]) -> None:
    ds = home / "data" / "dataset"
    ds.mkdir(parents=True)
    for name, rows in (("prs", prs), ("comments", comments), ("samples", samples)):
        (ds / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def sample(n: int, commit: str, t: str, gold: list[int], split: str = "train", approval: bool = False) -> dict:
    return {"pr": n, "commit": commit, "split": split, "time": t, "gold_ids": gold, "approval_only": approval}


def test_to_learn() -> None:
    home, w = new_home(settle_hours=24)
    put_dataset(home,
                prs=[{"pr": 1, "state": "MERGED", "head": "h1"}, {"pr": 2, "state": "OPEN", "head": "c2new"},
                     {"pr": 3, "state": "OPEN", "head": "c3"}, {"pr": 4, "state": "OPEN", "head": "c4"}],
                comments=[{"id": 10, "created": "2026-11-21T00:00:00Z"}, {"id": 20, "created": "2026-11-27T11:00:00Z"},
                          {"id": 30, "created": "2026-11-27T11:00:00Z"}, {"id": 31, "created": "2026-11-21T00:00:00Z"},
                          {"id": 40, "created": "2026-11-25T00:00:00Z"}],
                samples=[sample(1, "c1aaaaaaaa", "2026-11-21T00:00:00Z", [10]),       # merged: settled
                         sample(2, "c2oldaaaaa", "2026-11-27T11:00:00Z", [20]),       # head moved on: settled
                         sample(3, "c3", "2026-11-21T00:00:00Z", [31, 30]),           # open head, comment 1h ago
                         sample(4, "c4", "2026-11-25T00:00:00Z", [40]),               # open head, quiet for 2 days
                         sample(5, "c5", "2026-11-10T00:00:00Z", [40]),               # before learn_from
                         sample(6, "c6", "2026-11-22T00:00:00Z", [40], approval=True),
                         sample(7, "c7", "2026-11-22T00:00:00Z", [40], split="test")])
    w["learned"]["1:c1aaaaaa"] = {"at": "x"}
    got, skipped = watch.to_learn(home, w, NOW)
    assert [s["pr"] for s in got] == [4, 2], got
    assert skipped == {"not settled": 1, "before learn_from": 2, "approval only": 1}, skipped


def fake_lmreview(calls: list, code: int = 0, out: str = "", write: dict | None = None):
    def run(home, repo, args, log):
        calls.append(args)
        if write and "--out" in args:
            p = pathlib.Path(args[args.index("--out") + 1])
            p.with_suffix(".json").write_text(json.dumps(write))
            p.with_suffix(".md").write_text("# review\n")
        return code, out
    return run


def test_review_one_and_learn() -> None:
    home, w = new_home(round_cost=5.0)
    calls: list = []
    watch.lmreview = fake_lmreview(calls, write={"cost": 3.5, "findings": [{}, {}]})
    line = watch.review_one(home, w, pr(9, "9" * 40), post=False)
    assert calls[-1][:4] == ["review", "9", "--commit", "9" * 40], calls
    assert w["reviewed"]["9"]["ok"] and w["reviewed"]["9"]["findings"] == 2 and w["spent"]["review"] == 3.5, line

    watch.lmreview = fake_lmreview(calls, code=1, out="boom\n")
    for k in range(1, 4):
        watch.review_one(home, w, pr(8, "8" * 40), post=False)
        assert w["reviewed"]["8"]["fails"] == k
    assert watch.to_review(w, [pr(8, "8" * 40)]) == []  # given up on this head
    assert watch.to_review(w, [pr(8, "7" * 40)]) != []  # a new push is tried again

    watch.lmreview = fake_lmreview(calls, out="...\nround total: $12.50\n\nbook in use: v0003\n")
    line = watch.learn(home, w, [sample(4, "c4cccccccc", "t", [1])])
    assert calls[-1][:2] == ["round", "4:c4cccccc"] and calls[-1].count("5.0") == len(watch.ROUND_COST), calls[-1]
    assert "4:c4cccccc" in w["learned"] and w["spent"]["learn"] == 12.5 and "v0003" in line, line

    watch.lmreview = fake_lmreview(calls, code=2, out="round total: $1.00\n")
    watch.learn(home, w, [sample(5, "c5cccccccc", "t", [1])])
    assert "5:c5cccccc" not in w["learned"]  # a failed round is tried again next cycle


def test_split_overlay() -> None:
    """A home's overlay makes PRs from `since` on train, and derive.split_of follows the settings."""
    TMP.mkdir(parents=True, exist_ok=True)
    cfg = pathlib.Path(tempfile.mkdtemp(prefix="lmr-cfg-", dir=TMP)) / "config.toml"
    cfg.write_text(watch.overlay("main", "2026-11-20"))
    code = ("import sys; sys.path.insert(0, 'src'); import derive; "
            "print(derive.split_of('2026-11-19T00:00:00Z'), derive.split_of('2026-11-21T00:00:00Z'))")
    env = {**os.environ, "LMREVIEW_CONFIG": str(cfg), "LMREVIEW_DATA": str(cfg.parent), "LMREVIEW_REPO": str(cfg.parent)}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert out.stdout.split()[1] == "train", out.stdout + out.stderr  # (earlier PRs are not collected: start)
    env.pop("LMREVIEW_CONFIG")  # the defaults keep the LMCache splits
    out = subprocess.run([sys.executable, "-c", code.replace("2026-11-19", "2026-08-01")], cwd=ROOT, env=env,
                         capture_output=True, text=True)
    assert out.stdout.split() == ["train", "new"], out.stdout + out.stderr


def test_generic_project() -> None:
    """Another project: its prompts render, its overlay parses, and every prompt names it, not LMCache."""
    home, _ = new_home()
    watch.render_prompts(watch.GENERIC, home / "prompts", "Foo", 'a "web" framework')
    (home / "config.toml").write_text(watch.overlay("main", "2026-11-20", ("Foo", 'a "web" framework'), home / "prompts"))
    for f, keys in (("reviewer.md", ("number", "title", "body")), ("rulecheck.md", ("number", "title", "shared", "body", "rules")),
                    ("rulepick.md", ("number", "title", "shared", "rules"))):
        text = (home / "prompts" / f).read_text().format(**{k: "X" for k in keys})
        assert "@" not in text.replace("@{", "") and "LMCache" not in text and "lmcache" not in text, f
    assert 'of Foo (a "web" framework).' in (home / "prompts" / "reviewer.md").read_text()
    code = ("import sys; sys.path.insert(0, '.'); from lmreview import config, state, distill, reviewer, settings; "
            "print(config.PROMPTS, state.prompt_id(), settings.get('project', 'name'), "
            "any('LMCache' in v for m in (distill, reviewer) for k, v in vars(m).items() if k.isupper() and isinstance(v, str)))")
    env = {**os.environ, **watch.env_for(home, "o/r")}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    path, pid, name, left = out.stdout.split()
    env.pop("LMREVIEW_CONFIG")
    base = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True).stdout.split()
    assert (path, name, left) == (str(home / "prompts"), "Foo", "False") and pid != base[1], (out.stdout, out.stderr, base)


def test_env_and_repo_name() -> None:
    home, _ = new_home()
    env = watch.env_for(home, "o/r")
    assert env["LMREVIEW_STATE"] == str(home / "state") and env["LMREVIEW_GH_REPO"] == "o/r"
    for bad in ("o", "o/r/x", "o/r;rm", ""):
        try:
            watch.check_repo(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_history_skips_posted_reviews() -> None:
    from lmreview.history import AI_MARK, format_history
    raw = {"reviewThreads": {"nodes": []}, "reviews": {"nodes": []},
           "comments": {"nodes": [{"author": {"login": "bo"}, "createdAt": "2026-11-21T00:00:00Z", "body": AI_MARK + "\nAI"},
                                  {"author": {"login": "al"}, "createdAt": "2026-11-22T00:00:00Z", "body": "human"}]}}
    h = format_history(raw)
    assert "human" in h and "AI" not in h, h


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f()
            print("ok", name)

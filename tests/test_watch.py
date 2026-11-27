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
    w["settings"]["review_since"] = "2026-11-25T12:00:00Z"  # a backlog left alone
    assert [p["number"] for p in watch.to_review(w, prs)] == [4, 5]


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


def test_book_label() -> None:
    """A seeded book is v0001 of its own repository, and its label says where it came from."""
    home, _ = new_home()
    seed = home / "seed.jsonl"
    seed.write_text('{"id": "a", "when": "w", "expect": "e"}\n')
    (home / "config.toml").write_text(watch.overlay("main", "2026-11-20"))
    code = ("import sys; sys.path.insert(0, '.'); from lmreview import state; "
            "n = state.init(sys.argv[1], 'x', 'LMCache/LMCache v0036'); print(state.vname(n)); print(state.book_label('v0001')); "
            "print(state.book_seed())")
    env = {**os.environ, **watch.env_for(home, "LMCache/LMCache_inprocess")}
    out = subprocess.run([sys.executable, "-c", code, str(seed)], cwd=ROOT, env=env, capture_output=True, text=True)
    assert out.stdout.splitlines() == ["v0001", "LMCache/LMCache_inprocess v0001", "LMCache/LMCache v0036"], \
        out.stdout + out.stderr


DIFF = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -10,4 +10,5 @@ def f():
 ctx10
-old11
+new11
+new12
 ctx13
 ctx14
@@ -40,2 +41,3 @@ def g():
 ctx41
+new42
 ctx43
diff --git a/old.py b/new.py
similarity index 90%
rename from old.py
rename to new.py
--- a/old.py
+++ b/new.py
@@ -1,1 +1,1 @@
-x
+y
"""


def test_ghreview() -> None:
    from lmreview import ghreview
    from lmreview.history import AI_MARK
    from lmreview.schema import parse_findings
    lines = ghreview.commentable(DIFF)
    assert sorted(lines[("a.py", "RIGHT")]) == [10, 11, 12, 13, 14, 41, 42, 43]
    assert sorted(lines[("a.py", "LEFT")]) == [10, 11, 12, 13, 40, 41]
    assert lines[("new.py", "RIGHT")] == {1: 3} and lines[("old.py", "LEFT")] == {1: 3}
    L = lambda **k: ghreview.Location(**{"path": "a.py", **k})  # noqa: E731
    assert ghreview.anchor(L(start=11, end=13), lines) == {"path": "a.py", "line": 13, "side": "RIGHT",
                                                           "start_line": 11, "start_side": "RIGHT"}
    assert ghreview.anchor(L(start=12, end=42), lines)["start_line"] == 41  # one hunk: the last one hit
    assert ghreview.anchor(L(start=20, end=30), lines) is None              # outside the diff
    assert ghreview.anchor(L(start=11, side="old"), lines) == {"path": "a.py", "line": 11, "side": "LEFT"}
    fs = parse_findings([
        {"id": "1.f1", "severity": "minor", "scope": "line", "title": "in diff", "body": "b",
         "locations": [{"path": "a.py", "start": 12, "end": 12}, {"path": "b.py", "start": 3, "role": "related"}]},
        {"id": "2.r1", "severity": "major", "scope": "line", "title": "outside", "body": "b", "rule": "x1",
         "locations": [{"path": "a.py", "start": 90}]},
        {"id": "1.f2", "severity": "nit", "scope": "pr", "title": "whole pr", "body": "b", "locations": []}])
    r = {"commit": "c" * 40, "reviewer": "p+v0001@medium-rc", "cost": 1.0, "parallel": 2, "rules_label": "o/r v0001"}
    out = ghreview.build(r, fs, DIFF, {"x1": {"when": "W"}}, "o/r")
    assert [c["line"] for c in out["comments"]] == [12] and out["event"] == "COMMENT" and out["commit_id"] == "c" * 40
    assert all(x.startswith(AI_MARK) for x in [out["body"]] + [c["body"] for c in out["comments"]])
    assert "outside" in out["body"] and "whole pr" in out["body"] and "in diff" not in out["body"]
    assert "<sub>team rule `x1`</sub>" in out["body"] and "`x1` applies when: W" in out["body"] and "o/r v0001" in out["body"]
    assert "<sub>general review</sub>" in out["comments"][0]["body"] and "found by" not in out["body"]
    assert "blob/" + "c" * 40 + "/b.py#L3" in out["comments"][0]["body"]
    c0 = out["comments"][0]["body"]
    assert c0.index("<details><summary>Other places</summary>") < c0.index("b.py#L3") and c0.rstrip().endswith("</details>")
    assert "**Where:**" in out["body"] and "<summary>Team rule</summary>" in out["body"]
    assert ghreview.build(r, fs, DIFF, {}, "o/r", inline=False)["comments"] == []
    old = ghreview.build(r | {"rules_label": "o/r v0001 (seeded from a/b v0036)"}, fs, DIFF, {}, "o/r")
    assert "**o/r v0001**" in old["body"] and "seeded" not in old["body"]


def test_post_review_falls_back() -> None:
    home, _ = new_home()
    out = home / "reviews" / "1-abc"
    out.parent.mkdir()
    for name, tag in ((".ghreview.json", "inline"), (".ghreview-flat.json", "flat")):
        pathlib.Path(str(out) + name).write_text(json.dumps({"body": tag, "comments": [], "refs": {}}))
    sent = []

    def fake_run(cmd, **kw):
        tag = json.loads(kw["input"])["body"]
        sent.append(tag)
        ok = tag == "flat"
        return subprocess.CompletedProcess(cmd, 0 if ok else 1, '{"id": 5, "html_url": "U"}' if ok else "", "" if ok else "422 line")
    real, watch.subprocess.run = watch.subprocess.run, fake_run
    try:
        assert watch.post_review("o/r", 1, out) == ("U", "")
    finally:
        watch.subprocess.run = real
    assert sent == ["inline", "flat"]


def test_refs_link_to_comments() -> None:
    """'root cause of f1' in a finding becomes the title of finding f1 of the same run, linked to its comment."""
    from lmreview import ghreview
    from lmreview.schema import parse_findings
    fs = parse_findings([
        {"id": "1.f1", "severity": "major", "scope": "line", "title": "First [one]", "body": "b",
         "locations": [{"path": "a.py", "start": 11}]},
        {"id": "1.f2", "severity": "minor", "scope": "line", "title": "Second", "suggestion": "see f1",
         "body": "the root cause of f1; not `f1` in code, nor r1 or f9", "locations": [{"path": "a.py", "start": 12}]},
        {"id": "2.r1", "severity": "nit", "scope": "pr", "title": "Third", "body": "like f1", "locations": []}])
    p = ghreview.build({"commit": "c" * 40, "reviewer": "x", "cost": 0}, fs, DIFF, {}, "o/r")
    second = p["comments"][1]["body"]
    assert "the root cause of [[ref:1.f1]]; not `f1` in code, nor r1 or f9" in second and "see [[ref:1.f1]]" in second
    assert "like f1" in p["body"]  # the rule check's own run has no f1
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "POST" in cmd:
            assert "[[ref:" not in kw["input"] and "*First (one)*" in kw["input"] and '"refs"' not in kw["input"]
            return subprocess.CompletedProcess(cmd, 0, '{"id": 9, "html_url": "R"}', "")
        if "GET" in cmd or "--paginate" in cmd:
            cs = [{"id": 100 + i, "html_url": f"C{i}", "body": c["body"]} for i, c in enumerate(p["comments"])]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(cs), "")
        return subprocess.CompletedProcess(cmd, 0, "{}", "")
    real, watch.subprocess.run = watch.subprocess.run, fake_run
    try:
        review, why = watch.post_payload("o/r", 1, p)
    finally:
        watch.subprocess.run = real
    patches = [c for c in calls if "PATCH" in c]
    assert review["id"] == 9 and why == "" and len(patches) == 1 and patches[0][4].endswith("/comments/101")
    assert "the root cause of [First (one)](C0)" in patches[0][-1] and "see [First (one)](C0)" in patches[0][-1]
    assert not [c for c in calls if "PUT" in c]  # the summary mentions no other finding


def test_rule_sources() -> None:
    """A rule lists the comments it was learned from, from the dataset or the state's sources.json, mentions quieted."""
    home, _ = new_home()
    (home / "config.toml").write_text(watch.overlay("main", "2026-11-20"))
    ds = home / "data" / "dataset"
    ds.mkdir(parents=True)
    (ds / "comments.jsonl").write_text(json.dumps({"id": 1, "pr": 5, "author": "al", "body": "hi @bob, avoid this",
                                                   "url": "https://github.com/o/r/pull/5#discussion_r1"}) + "\n")
    (home / "state").mkdir()
    (home / "state" / "sources.json").write_text(json.dumps({"2": {"repo": "x/y", "pr": 9, "author": "cy", "url": "U", "quote": "q"}}))
    code = ("import sys, json; sys.path.insert(0, '.'); from lmreview.provenance import sources; "
            "print(json.dumps(sources({'evidence': [1, '2:0', 3, 1]})))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env={**os.environ, **watch.env_for(home, "o/r")},
                         capture_output=True, text=True)
    got = json.loads(out.stdout or "null") if out.returncode == 0 else out.stderr
    assert [(s["repo"], s["pr"], s["author"]) for s in got] == [("o/r", 5, "al"), ("x/y", 9, "cy")], got
    assert got[0]["quote"] == "hi `@bob`, avoid this", got
    from lmreview.provenance import quiet
    assert quiet("see #12 and @al, not `@x #3` or a&#39;b; `cut") == "see `#12` and `@al`, not `@x #3` or a&#39;b; `cut`"


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
    ai = {"author": {"login": "bo"}, "createdAt": "2026-11-21T00:00:00Z", "body": AI_MARK + "\nAI", "path": "a.py"}
    raw = {"reviewThreads": {"nodes": [{"comments": {"nodes": [ai, {**ai, "body": "reply"}]}}]},
           "reviews": {"nodes": [{**ai, "submittedAt": ai["createdAt"], "state": "COMMENTED"}]},
           "comments": {"nodes": [{"author": {"login": "bo"}, "createdAt": "2026-11-21T00:00:00Z", "body": AI_MARK + "\nAI"},
                                  {"author": {"login": "al"}, "createdAt": "2026-11-22T00:00:00Z", "body": "human"}]}}
    h = format_history(raw)
    assert "human" in h and "AI" not in h and "reply" not in h, h


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f()
            print("ok", name)

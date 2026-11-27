"""`lmreview watch`: follow a GitHub repository with the logged-in `gh` and `claude` CLIs.

Each cycle, per repository:

  review  every open PR whose head changed since its last review is reviewed once (`lmreview review`);
          the review is kept in <home>/reviews/, and posted as a PR comment only with `post` on
  learn   `lmreview sync` collects the human reviews; every sample (PR, commit a human reviewed) that
          has settled is learned from with `lmreview round PR:commit`. A sample settles when the PR is
          closed, the commit is no longer its head, or no human commented on it for `settle_hours`.

Each repository has its own home, <[paths] watch>/<owner>__<name>/, so repositories never share a
clone, a dataset, a cache or a book:

  watch.json    settings and progress (reviewed heads, learned samples, spend)
  config.toml   settings overlay ($LMREVIEW_CONFIG): the main branch, [dataset] dates that make every
                PR created since `since` a train sample, and for a project other than LMCache its
                [project] (name, GitHub description) and [paths] prompts
  prompts/      reviewer.md / rulecheck.md / rulepick.md of a project other than LMCache: rendered from
                lmreview/prompts/generic/ (or a dir given to `add`), and the user's to edit
  state/        the book ($LMREVIEW_STATE, lmreview/state/ layout); `add` starts it at v0001
  data/         dataset, runs, scores, logs ($LMREVIEW_DATA)
  repo/         the clone ($LMREVIEW_REPO)
  reviews/      <pr>-<commit8>.json / .md
  logs/         one log per review / sync / round

Steps run as `python -m lmreview ...` with those variables set (the modules read them at import).
Only samples from `learn_from` on (the time the repository was added, unless --backfill) are learned:
the dataset keeps older PRs as context, but learning from all of them at once would be one large paid
batch nobody asked for.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterator

from .config import _CACHE
from .github import gh_graphql
from .history import AI_MARK
from .settings import get

PKG_ROOT = pathlib.Path(__file__).resolve().parent.parent  # what `python -m lmreview` needs on PYTHONPATH
GENERIC = pathlib.Path(__file__).resolve().parent / "prompts" / "generic"
PROMPT_FILES = ("reviewer.md", "rulecheck.md", "rulepick.md")
# the files a project other than LMCache greps for SYMBOLS ([project] source_globs)
SOURCE_GLOBS = ["*.py", "*.pyi", "*.c", "*.cc", "*.cpp", "*.cu", "*.cuh", "*.h", "*.hpp", "*.rs", "*.go", "*.java",
                "*.kt", "*.scala", "*.js", "*.jsx", "*.ts", "*.tsx", "*.mjs", "*.rb", "*.php", "*.cs", "*.swift",
                "*.m", "*.sh", "*.sql", "*.proto", "*.md", "*.rst", "*.toml", "*.yaml", "*.yml", "*.json"]
DEFAULTS = {"review": True, "learn": True, "post": False, "drafts": False, "settle_hours": 24.0,
            "max_reviews": 5, "max_learn": 3, "round_cost": None,
            "review_since": None}  # ISO time: open PRs last updated before it are not reviewed (a backlog)
MAX_FAILS = 3  # review attempts on one head before it is skipped until the PR is pushed again

OPEN_Q = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 100, after: $after, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number title isDraft headRefOid updatedAt baseRefName author { login __typename } }
    }
  }
}"""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _iso(t: dt.datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _parse(t: str) -> dt.datetime:
    return dt.datetime.fromisoformat(t.replace("Z", "+00:00"))


def root() -> pathlib.Path:
    """Where the homes are: $LMREVIEW_WATCH, else [paths] watch, else ~/.cache/lmreview/watch."""
    return pathlib.Path(os.environ.get("LMREVIEW_WATCH") or get("paths", "watch") or _CACHE / "watch")


def check_repo(repo: str) -> str:
    """`repo` as owner/name; raises ValueError on anything else."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        raise ValueError(f"expected OWNER/NAME, got {repo!r}")
    return repo


def home_of(repo: str) -> pathlib.Path:
    """The home of `repo` (owner/name)."""
    return root() / check_repo(repo).replace("/", "__")


def homes() -> list[pathlib.Path]:
    """Every home that has a watch.json."""
    r = root()
    return sorted(p.parent for p in r.glob("*/watch.json")) if r.exists() else []


def load(home: pathlib.Path) -> dict:
    """watch.json of `home`, with any settings it lacks at their defaults."""
    w = json.loads((home / "watch.json").read_text())
    w["settings"] = {**DEFAULTS, **w.get("settings", {})}
    return w


def save(home: pathlib.Path, w: dict) -> None:
    """Write watch.json atomically."""
    tmp = home / "watch.json.tmp"
    tmp.write_text(json.dumps(w, indent=1, sort_keys=True) + "\n")
    tmp.replace(home / "watch.json")


@contextlib.contextmanager
def lock(home: pathlib.Path) -> Iterator[None]:
    """One watcher per home at a time."""
    with open(home / "watch.lock", "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f"another `lmreview watch` holds {home / 'watch.lock'}") from None
        yield


def env_for(home: pathlib.Path, repo: str) -> dict[str, str]:
    """The environment that points lmreview at this home."""
    env = dict(os.environ)
    env.update(LMREVIEW_GH_REPO=repo, LMREVIEW_REPO=str(home / "repo"), LMREVIEW_DATA=str(home / "data"),
               LMREVIEW_STATE=str(home / "state"), LMREVIEW_CONFIG=str(home / "config.toml"),
               PYTHONPATH=str(PKG_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""))
    return env


def lmreview(home: pathlib.Path, repo: str, args: list[str], log: str) -> tuple[int, str]:
    """Run `python -m lmreview <args>` for this home; its output goes to <home>/logs/<time>-<log>.log.

    Returns:
        (exit code, the output).
    """
    (home / "logs").mkdir(exist_ok=True)
    path = home / "logs" / f"{_now():%Y%m%d-%H%M%S}-{log}.log"
    with open(path, "w") as f:
        p = subprocess.run([sys.executable, "-m", "lmreview", *args], env=env_for(home, repo),
                           stdout=f, stderr=subprocess.STDOUT, text=True)
    return p.returncode, path.read_text()


def _toml(s: str) -> str:
    """`s` as a TOML basic string (JSON's escapes are TOML's)."""
    return json.dumps(s, ensure_ascii=False)


def overlay(branch: str, since: str, project: tuple[str, str] | None = None, prompts: pathlib.Path | None = None) -> str:
    """config.toml of a home: PRs created from `since` on are collected and are all train samples;
    `project` (name, one-line description) and `prompts` for a project other than LMCache."""
    out = (f"# lmreview watch: settings of this repository on top of lmreview/config.toml\n"
           f"[dataset]\nstart = {_toml(since)}\nbranch = {_toml(branch)}\n"
           f"train_before = {_toml(since)}\ntest_before = {_toml(since)}\nafter = \"train\"\n")
    if project:
        out += (f"\n[project]\nname = {_toml(project[0])}\nabout = {_toml(project[1])}\n"
                f"source_globs = {json.dumps(SOURCE_GLOBS)}\n")
    if prompts:
        out += f"\n[paths]\nprompts = {_toml(str(prompts))}\n"
    return out


def render_prompts(src: pathlib.Path, dst: pathlib.Path, name: str, about: str) -> None:
    """Copy the three prompts from `src` to `dst`, with @PROJECT@ / @ABOUT@ filled in."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in PROMPT_FILES:
        text = (src / f).read_text()
        (dst / f).write_text(text.replace("@PROJECT@", name).replace("@ABOUT@", f" ({about})" if about else ""))


def preflight() -> list[str]:
    """What is missing to run the steps: the CLIs on PATH and a `gh` login."""
    bad = [f"{t} not on PATH" for t in ("claude", "gh", "git") if not shutil.which(t)]
    if shutil.which("gh") and subprocess.run(["gh", "auth", "status"], capture_output=True).returncode != 0:
        bad.append("gh is not logged in (`gh auth login`)")
    return bad


def add(repo: str, since: str | None = None, book: str | None = None, backfill: bool = False,
        prompts: str = "auto", **settings: object) -> str:
    """Start watching `repo`: create its home, its settings overlay and its book (v0001).

    Args:
        repo: owner/name, readable by the `gh` login.
        since: date (YYYY-MM-DD) from which PRs are collected; default today. Their samples are learned
            only with `backfill` (default: only samples reviewed from now on).
        book: rulebook .jsonl to start from. Default: with the LMCache prompts, the book in use of this
            lmreview's own state (the LMCache team's rules); with any other prompts, no entries.
        prompts: "lmcache" (lmreview/prompts/, written for LMCache), "generic" (lmreview/prompts/generic/,
            for any project), or a directory with the three prompt files; "auto": lmcache for a repository
            of the LMCache organization, else generic. Other than lmcache, they are rendered into
            <home>/prompts/ and [project] names the repository in every prompt.
        **settings: any of DEFAULTS.
    """
    home = home_of(repo)
    if (home / "watch.json").exists():
        raise RuntimeError(f"{repo} is already watched ({home}); change settings with `lmreview watch set`")
    unknown = set(settings) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown watch settings: {sorted(unknown)}")
    owner, name = repo.split("/")
    if prompts == "auto":
        prompts = "lmcache" if owner.lower() == "lmcache" else "generic"
    src = None if prompts == "lmcache" else GENERIC if prompts == "generic" else pathlib.Path(prompts).resolve()
    if src and not all((src / f).exists() for f in PROMPT_FILES):
        raise FileNotFoundError(f"{src} must hold {', '.join(PROMPT_FILES)}")
    info = gh_graphql("query($o: String!, $n: String!) { repository(owner: $o, name: $n) "
                      "{ nameWithOwner description defaultBranchRef { name } viewerPermission } }",
                      o=owner, n=name)["repository"]
    branch = info["defaultBranchRef"]["name"]
    about = " ".join((info.get("description") or "").split()).rstrip(".")
    now = _now()
    since = since or now.date().isoformat()
    dt.date.fromisoformat(since)  # a bad date fails here, before anything is written
    home.mkdir(parents=True, exist_ok=True)
    if src:
        render_prompts(src, home / "prompts", name, about)
    (home / "config.toml").write_text(overlay(branch, since, (name, about) if src else None,
                                              home / "prompts" if src else None))
    note = f"lmreview watch add {repo}"
    if book is None and src is None:  # the LMCache prompts: start from the LMCache team's book in use
        from . import state
        n = state.head()
        if n:
            book = str(home / f"seed-{state.vname(n)}.jsonl")
            shutil.copy(state.book_path(state.vname(n)), book)
            note += f"; seeded from {state.STATE} {state.vname(n)}"
    if book is None:
        book = str(home / "empty-book.jsonl")
        pathlib.Path(book).write_text("")
    code, out = lmreview(home, repo, ["init", str(pathlib.Path(book).resolve()), "--note", note], "init")
    if code:
        raise RuntimeError(f"init failed:\n{out}")
    w = {"repo": info["nameWithOwner"], "branch": branch, "since": since, "prompts": prompts,
         "learn_from": since + "T00:00:00Z" if backfill else _iso(now), "added": _iso(now),
         "settings": {**DEFAULTS, **settings}, "reviewed": {}, "learned": {}, "spent": {"review": 0.0, "learn": 0.0},
         "cycles": 0, "last_cycle": None, "permission": info["viewerPermission"]}
    save(home, w)
    return (f"watching {w['repo']} (branch {branch}, prompts {prompts}) in {home}\n"
            + (f"prompts: {home / 'prompts'} (edit them for this project's conventions)\n" if src else "") + out.strip())


def set_(repo: str, **settings: object) -> str:
    """Change settings of a watched repository."""
    home = home_of(repo)
    w = load(home)
    unknown = set(settings) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown watch settings: {sorted(unknown)}")
    w["settings"].update(settings)
    save(home, w)
    return json.dumps(w["settings"], indent=1, sort_keys=True)


def open_prs(repo: str) -> list[dict]:
    """The open PRs of `repo`, most recently updated first."""
    owner, name = repo.split("/")
    out, after = [], None
    while True:
        d = gh_graphql(OPEN_Q, owner=owner, name=name, after=after)["repository"]["pullRequests"]
        out += [n for n in d["nodes"] if n]
        if not d["pageInfo"]["hasNextPage"]:
            return out
        after = d["pageInfo"]["endCursor"]


def is_bot(pr: dict) -> bool:
    a = pr.get("author") or {}
    return a.get("__typename") == "Bot" or (a.get("login") or "").endswith("[bot]")


def to_review(w: dict, prs: list[dict]) -> list[dict]:
    """The open PRs whose head has not been reviewed yet (oldest update first: a PR waits its turn)."""
    s, out = w["settings"], []
    for pr in prs:
        if (pr["isDraft"] and not s["drafts"]) or is_bot(pr):
            continue
        if s.get("review_since") and pr["updatedAt"] < s["review_since"]:
            continue
        r = w["reviewed"].get(str(pr["number"])) or {}
        if r.get("commit") == pr["headRefOid"] and (r.get("ok") or r.get("fails", 0) >= MAX_FAILS):
            continue
        out.append(pr)
    return sorted(out, key=lambda p: p["updatedAt"])


def review_one(home: pathlib.Path, w: dict, pr: dict, post: bool) -> str:
    """Review the head of `pr`, keep it in reviews/, post it if `post`; records the result in `w`."""
    n, c = pr["number"], pr["headRefOid"]
    out = home / "reviews" / f"{n}-{c[:8]}"
    out.parent.mkdir(exist_ok=True)
    code, log = lmreview(home, w["repo"], ["review", str(n), "--commit", c, "--out", str(out)], f"review-{n}")
    prev = w["reviewed"].get(str(n)) or {}
    fails = prev.get("fails", 0) if prev.get("commit") == c else 0
    rec = {"commit": c, "at": _iso(_now()), "ok": code == 0 and out.with_suffix(".json").exists()}
    if not rec["ok"]:
        w["reviewed"][str(n)] = {**rec, "fails": fails + 1, "error": log.strip().splitlines()[-1:] or [""]}
        return f"#{n} {c[:8]}: review FAILED ({fails + 1}/{MAX_FAILS}), see {home / 'logs'}"
    r = json.loads(out.with_suffix(".json").read_text())
    rec["cost"] = float(r.get("cost") or 0)
    rec["findings"] = len(r.get("findings") or [])
    w["spent"]["review"] += rec["cost"]
    line = f"#{n} {c[:8]}: {rec['findings']} findings, ${rec['cost']:.2f} -> {out}.md"
    if post:
        body = f"{AI_MARK}\n" + out.with_suffix(".md").read_text()
        p = subprocess.run(["gh", "pr", "comment", str(n), "--repo", w["repo"], "--body-file", "-"],
                           input=body, capture_output=True, text=True)
        rec["posted"] = p.stdout.strip() if p.returncode == 0 else None
        line += f"; posted {rec['posted']}" if rec["posted"] else f"; post FAILED: {p.stderr.strip()[:200]}"
    w["reviewed"][str(n)] = rec
    return line


def _jsonl(p: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in p.open() if l.strip()] if p.exists() else []


def to_learn(home: pathlib.Path, w: dict, now: dt.datetime | None = None) -> tuple[list[dict], dict[str, int]]:
    """Settled train samples from `learn_from` on that are not learned yet, oldest first.

    Returns:
        (samples, counts of the samples left out by reason).
    """
    now = now or _now()
    ds = home / "data" / "dataset"
    prs = {p["pr"]: p for p in _jsonl(ds / "prs.jsonl")}
    last = {}  # comment id -> time, to find a sample's latest human comment
    for c in _jsonl(ds / "comments.jsonl"):
        last[c["id"]] = c.get("created") or ""
    settle = dt.timedelta(hours=float(w["settings"]["settle_hours"]))
    out, skipped = [], {}

    def skip(why: str) -> None:
        skipped[why] = skipped.get(why, 0) + 1

    for s in _jsonl(ds / "samples.jsonl"):
        key = f"{s['pr']}:{s['commit'][:8]}"
        if key in w["learned"]:
            continue
        if s["split"] != "train" or s["time"] < w["learn_from"]:
            skip("before learn_from")
            continue
        if s.get("approval_only"):
            skip("approval only")
            continue
        pr = prs.get(s["pr"]) or {}
        latest = max((last.get(i) or s["time"] for i in s["gold_ids"]), default=s["time"])
        if pr.get("state") == "OPEN" and pr.get("head") == s["commit"] and now - _parse(latest) < settle:
            skip("not settled")
            continue
        out.append(s)
    return sorted(out, key=lambda s: s["time"]), skipped


ROUND_COST = ("--review-cost", "--judge-cost", "--confirm-cost", "--distill-cost", "--vet-cost")


def learn(home: pathlib.Path, w: dict, samples: list[dict]) -> str:
    """One `lmreview round` on `samples`; marks them learned when it finishes."""
    keys = [f"{s['pr']}:{s['commit'][:8]}" for s in samples]
    cost = w["settings"]["round_cost"]
    args = ["round", *keys] + ([x for k in ROUND_COST for x in (k, str(cost))] if cost is not None else [])
    code, out = lmreview(home, w["repo"], args, "round")
    m = re.findall(r"round total: \$([0-9.]+)", out)
    spent = float(m[-1]) if m else 0.0
    w["spent"]["learn"] += spent
    if code:
        return f"round on {' '.join(keys)} FAILED (exit {code}; ${spent:.2f}), see {home / 'logs'}"
    for k in keys:
        w["learned"][k] = {"at": _iso(_now()), "round_cost": spent}
    book = re.findall(r"book in use: (v\d{4})", out) or re.findall(r"book (v\d{4})", out)
    return f"learned {len(keys)} sample(s): {' '.join(keys)}; ${spent:.2f}" + (f"; book {book[-1]}" if book else "")


def cycle(home: pathlib.Path, dry_run: bool = False, now: dt.datetime | None = None) -> str:
    """One review + learn pass over the repository of `home`. `dry_run`: only list what would be done
    (sync still runs: it is free and changes only the local dataset)."""
    w = load(home)
    s, repo, lines = w["settings"], w["repo"], []
    with lock(home):
        if s["review"]:
            prs = open_prs(repo)
            todo = to_review(w, prs)
            drafts = sum(p["isDraft"] for p in prs) if not s["drafts"] else 0
            lines.append(f"review: {len(prs)} open PRs ({drafts} drafts, {sum(map(is_bot, prs))} by bots: skipped), "
                         f"{len(todo)} with an unreviewed head"
                         + (f", reviewing {min(len(todo), s['max_reviews'])} now" if todo else ""))
            for pr in todo[:s["max_reviews"]]:
                if dry_run:
                    lines.append(f"  would review #{pr['number']} {pr['headRefOid'][:8]} {pr['title'][:70]}"
                                 + (" and post it" if s["post"] else ""))
                else:
                    lines.append("  " + review_one(home, w, pr, s["post"]))
                    save(home, w)
        if s["learn"]:
            code, out = lmreview(home, repo, ["sync"], "sync")
            if code:
                lines.append(f"learn: sync FAILED (exit {code}), see {home / 'logs'}")
            else:
                lines.append(f"learn: {out.strip().splitlines()[-1] if out.strip() else 'synced'}")
                todo, skipped = to_learn(home, w, now)
                lines.append(f"  {len(todo)} settled sample(s) to learn"
                             + (f"; left out: {', '.join(f'{k} {v}' for k, v in sorted(skipped.items()))}" if skipped else ""))
                batch = todo[:s["max_learn"]]
                if batch and dry_run:
                    specs = " ".join(f"{x['pr']}:{x['commit'][:8]}" for x in batch)
                    lines.append(f"  would run: lmreview round {specs}")
                elif batch:
                    lines.append("  " + learn(home, w, batch))
        if not dry_run:
            w["cycles"] += 1
            w["last_cycle"] = _iso(_now())
            save(home, w)
    return f"[{_iso(_now())}] {repo}" + (" (dry run)" if dry_run else "") + "\n" + "\n".join(lines)


def run(repos: list[str] | None = None, once: bool = False, interval: int = 600, dry_run: bool = False) -> None:
    """Cycle over `repos` (default: every watched one) every `interval` seconds; `once`: one cycle."""
    bad = preflight()
    if bad:
        raise RuntimeError("cannot watch: " + "; ".join(bad))
    while True:
        hs = [home_of(r) for r in repos] if repos else homes()
        if not hs:
            raise RuntimeError(f"nothing watched under {root()}: `lmreview watch add OWNER/NAME` first")
        for h in hs:
            try:
                print(cycle(h, dry_run), flush=True)
            except Exception as e:  # one repository failing does not stop the others
                print(f"[{_iso(_now())}] {h.name}: cycle FAILED: {e}", flush=True)
        if once or dry_run:
            return
        time.sleep(interval)


def _pidfile() -> pathlib.Path:
    return root() / "watch.pid"


def running() -> int | None:
    """The pid of the background watcher started by `start`, if it is still alive."""
    try:
        pid = int(_pidfile().read_text().split()[0])
        os.kill(pid, 0)
        return pid
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return None


def start(repos: list[str] | None = None, interval: int = 600) -> str:
    """Run `watch run` in the background, detached from the terminal (its own session: closing the
    terminal or the SSH connection does not stop it). Output goes to <root>/watch.log."""
    if pid := running():
        raise RuntimeError(f"a watcher is already running (pid {pid}); `lmreview watch stop` first")
    bad = preflight()
    if bad:
        raise RuntimeError("cannot watch: " + "; ".join(bad))
    root().mkdir(parents=True, exist_ok=True)
    log = root() / "watch.log"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PKG_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    with open(log, "a") as f:
        p = subprocess.Popen([sys.executable, "-u", "-m", "lmreview", "watch", "run", *(repos or []),
                              "--interval", str(interval)], stdout=f, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    _pidfile().write_text(f"{p.pid} {_iso(_now())} {' '.join(repos or ['(all)'])}\n")
    time.sleep(2)
    if p.poll() is not None:
        raise RuntimeError(f"the watcher exited at once (code {p.returncode}); see {log}")
    return f"watcher started (pid {p.pid}, every {interval}s); log: {log}; stop: lmreview watch stop"


def stop() -> str:
    """Stop the background watcher and what it is running (a review or round in progress is lost)."""
    pid = running()
    if pid is None:
        _pidfile().unlink(missing_ok=True)
        return "no watcher running"
    os.killpg(pid, signal.SIGTERM)  # its session: the watcher and the lmreview / claude processes under it
    for _ in range(20):
        if running() is None:
            break
        time.sleep(0.5)
    else:
        os.killpg(pid, signal.SIGKILL)
    _pidfile().unlink(missing_ok=True)
    return f"watcher {pid} stopped"


def status() -> str:
    """The background watcher, then one block per watched repository."""
    pid = running()
    out = [f"watcher: running (pid {pid}; {_pidfile().read_text().strip()}); log {root() / 'watch.log'}" if pid
           else "watcher: not running (`lmreview watch start`)"]
    for h in homes():
        w = load(h)
        head = h / "state" / "HEAD.json"
        v = f"v{json.loads(head.read_text())['version']:04d}" if head.exists() else "none"
        s = w["settings"]
        out.append(f"{w['repo']} ({h})\n  book {v}; {len(w['reviewed'])} PRs reviewed, {len(w['learned'])} samples "
                   f"learned; spent review ${w['spent']['review']:.2f}, learn ${w['spent']['learn']:.2f}; "
                   f"{w['cycles']} cycles, last {w['last_cycle'] or 'never'}\n  review {s['review']} (post {s['post']}, "
                   f"drafts {s['drafts']}, at most {s['max_reviews']}/cycle"
                   + (f", PRs updated since {s['review_since']}" if s.get("review_since") else "") + "); learn {s['learn']} (from {w['learn_from']}, "
                   f"settle {s['settle_hours']}h, at most {s['max_learn']} samples/cycle, round cap "
                   f"{'default' if s['round_cost'] is None else '$' + str(s['round_cost'])})")
    return "\n".join(out + ([] if len(out) > 1 else [f"nothing watched under {root()}"]))

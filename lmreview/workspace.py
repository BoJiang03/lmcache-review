"""The workspace an agent sees. Reviewer and judge get the SAME workspace; see docs/agent_context.md.

  <repo files at C>   full snapshot via `git archive` (incl. the repo's own CLAUDE.md/AGENTS.md),
                      no .git, so other commits cannot leak
  PR.diff             git diff <base>..C
  PR_HISTORY.md       review discussion (replay: strictly before t0; live review: everything so far)
  _context/vllm/      only if the prompt declares `context: vllm`: the `vllm/` package of vLLM main
                      as of t0 (LMCache CI runs vLLM nightly), described in _context/README.md
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import shutil
import uuid
import subprocess
from collections.abc import Iterator

from .config import Config
from .history import format_history

TOOLS = "Read,Grep,Glob"


def git(repo: pathlib.Path, *a: str) -> str:
    """Run git in `repo`, return stdout, raise on failure."""
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout


def pr_meta(raw: dict) -> dict:
    """Prompt fields shared by every agent: PR number, title, description."""
    return {"number": raw["number"], "title": raw["title"], "body": (raw.get("body") or "")[:4000]}


@contextlib.contextmanager
def build(cfg: Config, name: str, commit: str, base: str, history: str, context: tuple[str, ...] = (),
          at: str | None = None) -> Iterator[pathlib.Path]:
    """Materialize a workspace under cfg.sandbox/<name>; removed on exit.

    `context`: extra sources ("vllm"), taken as of time `at` (ISO; None = now).
    """
    wt = cfg.sandbox / name
    shutil.rmtree(wt, ignore_errors=True)
    wt.mkdir(parents=True)
    try:
        arch = subprocess.run(["git", "-C", str(cfg.repo), "archive", commit], check=True, capture_output=True)
        subprocess.run(["tar", "-x", "-C", str(wt)], input=arch.stdout, check=True)
        (wt / "PR.diff").write_text(git(cfg.repo, "diff", "-M", base, commit))
        (wt / "PR_HISTORY.md").write_text(history or "(no discussion yet)\n")
        if "vllm" in context:
            add_vllm(cfg, wt, at)
        yield wt
    finally:
        shutil.rmtree(wt, ignore_errors=True)


def add_vllm(cfg: Config, wt: pathlib.Path, at: str | None) -> None:
    """Put vLLM main's `vllm/` package as of `at` into wt/_context/vllm/."""
    ref = git(cfg.vllm, "rev-list", "-1", *([f"--before={at}"] if at else []), "origin/main").strip()
    ctx = wt / "_context"
    ctx.mkdir()
    arch = subprocess.run(["git", "-C", str(cfg.vllm), "archive", ref, "vllm/"], check=True, capture_output=True)
    subprocess.run(["tar", "-x", "-C", str(ctx)], input=arch.stdout, check=True)
    date = git(cfg.vllm, "log", "-1", "--format=%cI", ref).strip()
    (ctx / "README.md").write_text(
        f"_context/vllm/ is the `vllm` Python package of vLLM main at {ref[:12]} ({date}), the latest\n"
        "commit before this review. LMCache CI installs vLLM nightly, so this is the vLLM the PR runs\n"
        "against. It is reference only; it is not part of the PR.\n")


@contextlib.contextmanager
def sample_workspace(cfg: Config, s: dict, tag: str, context: tuple[str, ...] = ()) -> Iterator[tuple[pathlib.Path, str]]:
    """Replay workspace for eval sample `s` (a samples.jsonl row): commit C, history before t0.

    Yields (path, base). `tag` separates concurrent users of one sample ("review", "judge").
    """
    dev_then = git(cfg.repo, "rev-list", "-1", f"--before={s['time']}", "origin/dev").strip()
    base = git(cfg.repo, "merge-base", dev_then, s["commit"]).strip()
    name = f"{s['pr']}-{s['commit'][:8]}-{tag}-{uuid.uuid4().hex[:6]}"  # unique: parallel runs may share a sample
    with build(cfg, name, s["commit"], base, s["history"], context, s["time"]) as wt:
        yield wt, base


def cached_pr(cfg: Config, pr: int) -> dict:
    """The raw PR stored in the dataset (eval only)."""
    return json.loads((cfg.data / "raw" / "pr" / f"{pr}.json").read_text())


@contextlib.contextmanager
def live_workspace(cfg: Config, raw: dict, commit: str | None = None,
                   context: tuple[str, ...] = ()) -> Iterator[tuple[pathlib.Path, str, str]]:
    """Workspace for reviewing a PR now: its head (or `commit`) vs its base branch, full history.

    Fetches the PR head and base branch into cfg.repo first. Yields (path, commit, base).
    """
    n, base_ref = raw["number"], raw["baseRefName"]
    git(cfg.repo, "fetch", "-q", "origin", f"+refs/pull/{n}/head:refs/remotes/pr/{n}",
        f"+refs/heads/{base_ref}:refs/remotes/origin/{base_ref}")
    commit = commit or raw["headRefOid"]
    base = git(cfg.repo, "merge-base", f"origin/{base_ref}", commit).strip()
    if "vllm" in context:
        git(cfg.vllm, "fetch", "-q", "origin", "main")
    with build(cfg, f"live-{n}-{commit[:8]}-{uuid.uuid4().hex[:6]}", commit, base, format_history(raw), context) as wt:
        yield wt, commit, base

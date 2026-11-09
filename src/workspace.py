"""The workspace an agent sees for one eval sample. Reviewer and judge get the SAME workspace.

See docs/agent_context.md. For sample (PR, commit C, first human review time t0):
  <repo files at C>   full snapshot via `git archive` (incl. the repo's own CLAUDE.md/AGENTS.md),
                      no .git, so later commits cannot leak
  PR.diff             git diff merge-base(dev@t0, C)..C
  PR_HISTORY.md       review discussion strictly before t0
Nothing after t0 is in the workspace.
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import shutil
import subprocess
from collections.abc import Iterator

ROOT = pathlib.Path(__file__).resolve().parent.parent
GIT = ROOT / "data" / "LMCache"
RAW = ROOT / "data" / "raw" / "pr"
SANDBOX = pathlib.Path("/raid/bo/review-sandbox")  # outside this repo; llm.run confines tools to cwd
TOOLS = "Read,Grep,Glob"


def git(*a: str) -> str:
    """Run git in the clone, return stdout, raise on failure."""
    return subprocess.run(["git", "-C", str(GIT), *a], check=True, capture_output=True, text=True).stdout


def pr_meta(pr: int) -> dict:
    """Title and description of a PR (shown to both agents in the prompt)."""
    raw = json.loads((RAW / f"{pr}.json").read_text())
    return {"number": pr, "title": raw["title"], "body": (raw.get("body") or "")[:4000]}


@contextlib.contextmanager
def workspace(s: dict, tag: str) -> Iterator[tuple[pathlib.Path, str]]:
    """Materialize the workspace for sample `s`; yields (path, base commit); removed on exit.

    Args:
        s: a row of samples.jsonl.
        tag: distinguishes concurrent users of the same sample (e.g. "review", "judge").
    """
    commit = s["commit"]
    dev_then = git("rev-list", "-1", f"--before={s['time']}", "origin/dev").strip()
    base = git("merge-base", dev_then, commit).strip()
    wt = SANDBOX / f"{s['pr']}-{commit[:8]}-{tag}"
    shutil.rmtree(wt, ignore_errors=True)
    wt.mkdir(parents=True)
    try:
        arch = subprocess.run(["git", "-C", str(GIT), "archive", commit], check=True, capture_output=True)
        subprocess.run(["tar", "-x", "-C", str(wt)], input=arch.stdout, check=True)
        (wt / "PR.diff").write_text(git("diff", "-M", base, commit))
        (wt / "PR_HISTORY.md").write_text(s["history"] or "(no discussion yet)\n")
        yield wt, base
    finally:
        shutil.rmtree(wt, ignore_errors=True)

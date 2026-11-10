"""A PR as it was at a given time, so a replay shows what the human reviewer saw then.

GitHub keeps every edit of a PR's description, its reviews and its comments (`userContentEdits`)
and every title change (`RenamedTitleEvent`); github.fetch_edits stores them in the raw PR as
`_edits`. Code, vLLM and dev context are already taken as of the review time elsewhere.
"""

from __future__ import annotations

import copy
import datetime as dt
import subprocess

UNAVAILABLE = "(this text was edited later; the version at review time is no longer on GitHub)"


def text_at(versions: list[dict] | None, current: str, t: str) -> str:
    """The text as of time `t`, from its versions (oldest first); `current` if never edited."""
    if not versions:
        return current
    seen = [v for v in versions if v["at"] <= t]
    if not seen:  # created at/after t: callers only show texts created before t
        return versions[0]["text"] or UNAVAILABLE
    return seen[-1]["text"] if seen[-1]["text"] is not None else UNAVAILABLE


def title_at(renames: list[dict], current: str, t: str) -> str:
    """Title as of time `t`: the old title of the first rename after `t`, else the current one."""
    later = sorted((r for r in renames if r["at"] > t), key=lambda r: r["at"])
    return later[0]["from"] if later else current


def as_of(raw: dict, t: str) -> dict:
    """A copy of raw PR `raw` with title, description, reviews and comments as they read at `t`.

    Raises:
        KeyError: if `raw` has no `_edits` (run scripts/backfill_edits.py or `lmreview sync`).
    """
    e = raw["_edits"]
    out = copy.deepcopy(raw)
    out["title"] = title_at(e["renames"], raw["title"], t)
    out["body"] = text_at(e["body"], raw.get("body") or "", t)
    for r in out["reviews"]["nodes"]:
        r["body"] = text_at(e["nodes"].get(f"review:{r['databaseId']}"), r.get("body") or "", t)
    for th in out["reviewThreads"]["nodes"]:
        for c in th["comments"]["nodes"]:
            c["body"] = text_at(e["nodes"].get(f"thread:{c['databaseId']}"), c.get("body") or "", t)
    for c in out["comments"]["nodes"]:
        c["body"] = text_at(e["nodes"].get(f"comment:{c['databaseId']}"), c.get("body") or "", t)
    return out


def commit_at(raw: dict, t: str, hint: str, repo: str) -> str | None:
    """The PR head a reviewer saw at time `t`.

    GitHub's commit for a review (`review.commit`) can name a commit pushed after the review. `hint`
    is kept when it was committed by `t`. Otherwise the head at `t` is found from the force pushes:
    the head just before the first force push after `t` (or the current head) is walked back along
    first parents to the newest commit made by `t` that is not on dev. A commit made before `t`
    but pushed after it would be picked wrongly; GitHub keeps no push times for ordinary pushes.

    Returns:
        The commit, or None if it cannot be found locally or remotely.
    """
    def git(*a: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)

    def utc(iso: str) -> str:
        return dt.datetime.fromisoformat(iso).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    d = git("log", "-1", "--format=%cI", hint).stdout.strip()
    if d and utc(d) <= t:
        return hint
    later = sorted((p for p in raw["_edits"]["force_pushes"] if p["at"] > t and p["before"]), key=lambda p: p["at"])
    end = later[0]["before"] if later else raw["headRefOid"]
    if git("cat-file", "-e", f"{end}^{{commit}}").returncode and git("fetch", "-q", "origin", end).returncode:
        return None
    dev = git("rev-list", "-1", f"--before={t}", "origin/dev").stdout.strip()
    for line in git("log", "--first-parent", "--format=%H %cI", "-n", "500", end).stdout.splitlines():
        h, when = line.split()
        if utc(when) <= t:
            return h if git("merge-base", "--is-ancestor", h, dev).returncode else None
    return None

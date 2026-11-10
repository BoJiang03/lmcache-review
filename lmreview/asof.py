"""A PR's texts as they read at a given time, so a replay shows what the human reviewer saw then.

GitHub keeps every edit of a PR's description, its reviews and its comments (`userContentEdits`)
and every title change (`RenamedTitleEvent`); github.fetch_edits stores them in the raw PR as
`_edits`. Code, vLLM and dev context are already taken as of the review time elsewhere.
"""

from __future__ import annotations

import copy

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

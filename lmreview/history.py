"""Render a PR's review discussion as markdown for the agents (PR_HISTORY.md)."""

from __future__ import annotations

from .asof import as_of


def _who(node: dict) -> str:
    return (node.get("author") or {}).get("login") or "(deleted)"


def format_history(raw: dict, before: str | None = None) -> str:
    """Discussion of a PR (raw GraphQL dict from github.PR_Q), oldest first.

    Args:
        raw: the PR as returned by github.fetch_pr.
        before: ISO time; only events strictly before it are included (replay uses the first
            human review time t0 so nothing from the future leaks). None = everything. Texts are
            shown as they read at `before` (needs raw["_edits"]), not as later edited.
    """
    if before is not None:
        raw = as_of(raw, before)
    ok = (lambda t: True) if before is None else (lambda t: t < before)
    ev = []
    for t in raw["reviewThreads"]["nodes"]:
        cs = [c for c in t["comments"]["nodes"] if ok(c["createdAt"])]
        if cs:
            root = cs[0]
            lines = [f"- `{root['path']}` line {root.get('originalLine')} — thread:"]
            lines += [f"  - {_who(c)}: {c['body'][:1200]}" for c in cs]
            ev.append((root["createdAt"], "\n".join(lines)))
    for r in raw["reviews"]["nodes"]:
        if r.get("submittedAt") and ok(r["submittedAt"]) and (r.get("body") or "").strip():
            ev.append((r["submittedAt"], f"- review by {_who(r)} ({r['state']}): {r['body'][:1500]}"))
    for c in raw["comments"]["nodes"]:
        if ok(c["createdAt"]):
            ev.append((c["createdAt"], f"- PR comment by {_who(c)}: {c['body'][:1500]}"))
    return "\n".join(x for _, x in sorted(ev))

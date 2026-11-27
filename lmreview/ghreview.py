"""A review as GitHub shows one: a summary plus one inline comment per finding, posted in one call
(POST /repos/{owner}/{repo}/pulls/{n}/reviews, event COMMENT: it neither approves nor blocks).

GitHub accepts an inline comment only on a line of the PR's diff (a changed line or one of the three
context lines around it), and a multi-line comment only within one hunk. A finding whose primary place is
not in the diff (scope pr / file, or code outside the diff) goes into the summary instead.

Every body carries history.AI_MARK, so `lmreview sync` never takes these comments for a human's.
"""

from __future__ import annotations

import re

from .history import AI_MARK
from .schema import SEVERITIES, Finding, Location

HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def commentable(diff: str) -> dict[tuple[str, str], dict[int, int]]:
    """The lines of a unified diff (`git diff -U3 base commit`) GitHub can comment on.

    Returns:
        {(path, "RIGHT" | "LEFT"): {line: hunk number}}: RIGHT lines are numbered in the new file
        (added and context lines), LEFT lines in the old one (deleted and context lines).
    """
    out: dict[tuple[str, str], dict[int, int]] = {}
    new = old = None
    path = old_path = ""
    hunk = 0
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            new = old = None
        elif line.startswith("--- "):
            old_path = line[6:] if line.startswith("--- a/") else ""
        elif line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else old_path  # a deleted file: its old path
        elif m := HUNK.match(line):
            old, new, hunk = int(m[1]), int(m[2]), hunk + 1
        elif new is None or line.startswith("\\"):
            continue
        elif line.startswith("+"):
            out.setdefault((path, "RIGHT"), {})[new] = hunk
            new += 1
        elif line.startswith("-"):
            out.setdefault((old_path or path, "LEFT"), {})[old] = hunk
            old += 1
        else:  # context
            out.setdefault((path, "RIGHT"), {})[new] = hunk
            out.setdefault((old_path or path, "LEFT"), {})[old] = hunk
            new += 1
            old += 1
    return out


def anchor(loc: Location, lines: dict[tuple[str, str], dict[int, int]]) -> dict | None:
    """Where on the diff an inline comment about `loc` goes: the commentable lines of its range (within
    one hunk, ending at its last commentable line), or None when none of it is in the diff."""
    if not loc.start:
        return None
    side = "LEFT" if loc.side == "old" else "RIGHT"
    m = lines.get((loc.path, side)) or {}
    hit = [n for n in range(loc.start, (loc.end or loc.start) + 1) if n in m]
    if not hit:
        return None
    end = hit[-1]
    start = min(n for n in hit if m[n] == m[end])
    a = {"path": loc.path, "line": end, "side": side}
    if start < end:
        a |= {"start_line": start, "start_side": side}
    return a


def basis(f: Finding) -> str:
    """What a finding rests on, for the author: the team rules it follows, or the reviewer's own judgement.
    (Which agent raised it is not said: the main review is given the rules too, so it can raise a rule's
    finding, and the rule check only raises them.)"""
    rs = f.rules or ([f.rule] if f.rule else [])
    return ("team rule " + ", ".join(f"`{r}`" for r in rs)) if rs else "general review"


def _link(repo: str, commit: str, loc: Location) -> str:
    where = loc.path + (f":{loc.start}" + (f"-{loc.end}" if loc.end and loc.end != loc.start else "") if loc.start else "")
    frag = f"#L{loc.start}" + (f"-L{loc.end}" if loc.end and loc.end != loc.start else "") if loc.start else ""
    return f"[`{where}`](https://github.com/{repo}/blob/{commit}/{loc.path}{frag})"


def finding_text(f: Finding, rules: dict[str, dict], repo: str, commit: str, heading: str,
                 at: Location | None = None) -> str:
    """The markdown of one finding (an inline comment, or a section of the summary); `at`: the location the
    inline comment is on (every other location is linked)."""
    out = [f"{heading}**[{f.severity}] {f.title}** · <sub>{basis(f)}</sub>", "", f.body]
    if f.suggestion:
        out += ["", f"**Suggestion:** {f.suggestion}"]
    for rid in f.rules or ([f.rule] if f.rule else []):
        x = rules.get(rid)
        out += ["", f"**Team rule** `{rid}`" + (f" applies when: {x.get('when') or x.get('rule', '')}" if x else "")]
    where = [l for l in f.locations if l.role != "related" and l is not at]
    rel = [l for l in f.locations if l.role == "related"]
    if where:
        out += ["", ("**Also at:** " if at else "**Where:** ") + ", ".join(_link(repo, commit, l) for l in where)]
    if rel:
        out += ["", "**Related:** " + ", ".join(_link(repo, commit, l) for l in rel)]
    return "\n".join(out)


def build(r: dict, fs: list[Finding], diff: str, rules: dict[str, dict], repo: str, inline: bool = True) -> dict:
    """The review payload for a run `r` of review_pr with findings `fs`.

    Args:
        diff: `git diff -U3 <base> <commit>`, to tell which findings can be inline.
        rules: the rulebook's entries by id, to show the rules findings cite.
        inline: False puts every finding in the summary (when GitHub refuses the inline comments).

    Returns:
        {"commit_id", "event": "COMMENT", "body", "comments": [{path, line, side, [start_line, start_side], body}]}
    """
    commit = r["commit"]
    lines = commentable(diff) if inline else {}
    fs = sorted(fs, key=lambda f: SEVERITIES.index(f.severity))
    comments, rest = [], []
    for f in fs:
        p = f.primary()
        a = anchor(p, lines) if p and f.scope == "line" else None
        if a:
            comments.append(a | {"body": AI_MARK + "\n" + finding_text(f, rules, repo, commit, "", p)})
        else:
            rest.append(f)
    counts = ", ".join(f"{k} {s}" for s in SEVERITIES if (k := sum(f.severity == s for f in fs)))
    body = [AI_MARK, "## AI review (first round)", "",
            f"Commit `{commit[:10]}`, checked against the team rules of **{r.get('rules_label') or 'no rulebook'}**.", ""]
    if not fs:
        body.append("No findings.")
    else:
        body.append(f"**{len(fs)} findings**: {counts}." + (f" {len(comments)} are inline comments on the diff." if comments else ""))
        if rest:
            body += ["", "### Not tied to a line of the diff" if comments else "### Findings"]
            body += ["\n" + finding_text(f, rules, repo, commit, "") for f in rest]
    body += ["", "<sub>An AI first-round review: it can be wrong, so reply on a comment that is, or resolve it. "
             + "Each finding says what it rests on: a team rule (learned from this team's past reviews) or "
               "general review (the reviewer's own judgement). "
             + f"Reviewer {r.get('reviewer', '')} · ${float(r.get('cost') or 0):.2f}</sub>"]
    return {"commit_id": commit, "event": "COMMENT", "body": "\n".join(body), "comments": comments}

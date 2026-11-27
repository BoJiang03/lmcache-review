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
from .provenance import QUOTE
from .schema import SEVERITIES, Finding, Location

SHOW_SOURCES = 3  # source comments listed per rule
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# A finding's text names other findings by their id in its run ("root cause of f1", "see r2"); outside code
# spans these become REF markers, and render_refs turns them into the other finding's title, linked to its
# comment once the review is posted (watch.post_review).
_ID_IN_TEXT = re.compile(r"(?<![\w.`-])([fr]\d+)(?![\w-])")
REF = re.compile(r"\[\[ref:([\w.]+)\]\]")
FINDING_MARK = "<!-- lmreview: finding {} -->"  # in each inline comment, to find its URL after posting


def mark_refs(text: str, f: Finding, ids: set[str]) -> str:
    """`text` of finding `f` with its mentions of other findings (ids of the same run, outside `code`) as REF
    markers. Merged runs prefix ids with the run ("1.f2"): a mention means the finding of its own run."""
    run = f.id.rsplit(".", 1)[0] + "." if "." in f.id else ""
    parts = text.split("`")
    for i in range(0, len(parts), 2):  # even parts are outside code spans
        parts[i] = _ID_IN_TEXT.sub(lambda m: f"[[ref:{run + m[1]}]]" if run + m[1] in ids and run + m[1] != f.id
                                   else m[0], parts[i])
    return "`".join(parts)


def render_refs(text: str, titles: dict[str, str], urls: dict[str, str] | None = None) -> str:
    """REF markers as the findings' titles, linked to their comments when `urls` has them."""
    def one(m: re.Match) -> str:
        t = titles.get(m[1], m[1]).replace("[", "(").replace("]", ")")
        u = (urls or {}).get(m[1])
        return f"[{t}]({u})" if u else f"*{t}*"
    return REF.sub(one, text)


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
                 at: Location | None = None, ids: set[str] = frozenset()) -> str:
    """The markdown of one finding (an inline comment, or a section of the summary); `at`: the location the
    inline comment is on (every other location is linked); `ids`: the review's finding ids (see mark_refs)."""
    out = [f"{heading}**[{f.severity}] {f.title}** · <sub>{basis(f)}</sub>", "", mark_refs(f.body, f, ids)]
    where = [l for l in f.locations if l.role != "related" and l is not at]
    if where and not at:  # a finding in the summary: where it is stays in view
        out += ["", "**Where:** " + ", ".join(_link(repo, commit, l) for l in where)]
    # the rest supports the finding: folded, so a long review stays short (the raw markdown, which an agent
    # reads, has all of it)
    more, parts = [], []
    if f.suggestion:
        more += ["", f"**Suggestion:** {mark_refs(f.suggestion, f, ids)}"]
        parts.append("suggestion")
    rids = f.rules or ([f.rule] if f.rule else [])
    for rid in rids:
        x = rules.get(rid)
        more += ["", f"**Team rule** `{rid}`" + (f" applies when: {x.get('when') or x.get('rule', '')}" if x else "")]
        src = (x or {}).get("_sources") or []
        if src:
            more += ["", "Learned from these team review comments:"]
            more += [f"- [{s['repo'] + '#' if s.get('repo') else '#'}{s['pr']}]({s['url']}) · {s['author']}: "
                     f"\"{s['quote']}{'…' if len(s['quote']) >= QUOTE else ''}\"" for s in src[:SHOW_SOURCES]]
            if len(src) > SHOW_SOURCES:
                more.append(f"- and {len(src) - SHOW_SOURCES} more")
    if rids:
        parts.append("team rule")
    rel = [l for l in f.locations if l.role == "related"] + (where if at else [])
    if rel:
        more += ["", "**Other places:** " + ", ".join(_link(repo, commit, l) for l in rel)]
        parts.append("other places")
    if more:
        label = ", ".join(parts)
        out += ["", f"<details><summary>{label[0].upper() + label[1:]}</summary>", *more, "", "</details>"]
    return "\n".join(out)


def build(r: dict, fs: list[Finding], diff: str, rules: dict[str, dict], repo: str, inline: bool = True) -> dict:
    """The review payload for a run `r` of review_pr with findings `fs`.

    Args:
        diff: `git diff -U3 <base> <commit>`, to tell which findings can be inline.
        rules: the rulebook's entries by id, to show the rules findings cite.
        inline: False puts every finding in the summary (when GitHub refuses the inline comments).

    Returns:
        {"commit_id", "event": "COMMENT", "body", "comments": [{path, line, side, [start_line, start_side], body}],
         "refs": {finding id: title}}. Bodies hold REF markers: post_payload renders them, and "refs" is
        not sent to GitHub.
    """
    commit = r["commit"]
    lines = commentable(diff) if inline else {}
    fs = sorted(fs, key=lambda f: SEVERITIES.index(f.severity))
    ids = {f.id for f in fs}
    comments, rest = [], []
    for f in fs:
        p = f.primary()
        a = anchor(p, lines) if p and f.scope == "line" else None
        if a:
            comments.append(a | {"body": AI_MARK + "\n" + FINDING_MARK.format(f.id) + "\n"
                                 + finding_text(f, rules, repo, commit, "", p, ids)})
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
            body += ["\n" + finding_text(f, rules, repo, commit, "", None, ids) for f in rest]
    body += ["", "<sub>An AI first-round review: it can be wrong, so reply on a comment that is, or resolve it. "
             + "Each finding says what it rests on: a team rule (learned from this team's past reviews) or "
               "general review (the reviewer's own judgement). "
             + f"Reviewer {r.get('reviewer', '')} · ${float(r.get('cost') or 0):.2f}</sub>"]
    return {"commit_id": commit, "event": "COMMENT", "body": "\n".join(body), "comments": comments,
            "refs": {f.id: f.title for f in fs}}

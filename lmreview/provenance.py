"""Where a rule comes from: the human review comments it was learned from (an entry's "evidence"), so a
PR author who is shown a rule can read what the team actually said.

A comment is looked up in this state's dataset (<data>/dataset/comments.jsonl), then in the state's
sources.json: the comments behind a book copied from another repository (`lmreview watch add` writes it
when it seeds a book; `write_sources` makes one), whose dataset is elsewhere.
"""

from __future__ import annotations

import functools
import json
import pathlib
import re

from .config import Config

QUOTE = 160  # characters of a comment shown with its link


def _cid(x: object) -> int | None:
    """A comment id from an evidence item: an id, or "<id>:<point>" for one point of a comment."""
    s = str(x).split(":")[0]
    return int(s) if s.isdigit() else None


def source_of(c: dict) -> dict:
    """The fields shown for comment `c` of a dataset."""
    url = c.get("url") or ""
    repo = url.split("github.com/")[1].split("/pull/")[0] if "github.com/" in url and "/pull/" in url else ""
    return {"repo": repo, "pr": c.get("pr"), "author": c.get("author"), "url": url,
            "quote": quiet(" ".join((c.get("body") or "").split())[:QUOTE])}


def quiet(text: str) -> str:
    """`text` safe to repost in another repository: @mentions and #numbers in code spans (they must not notify
    the people a quote names, nor link to that number in the other repository), code spans closed."""
    if text.count("`") % 2:  # cut inside a code span
        text += "`"
    parts = text.split("`")
    for i in range(0, len(parts), 2):  # outside code spans
        parts[i] = re.sub(r"(?<![\w&])([@#])([A-Za-z0-9][\w-]*)", r"`\1\2`", parts[i])
    return "`".join(parts)


@functools.lru_cache(maxsize=4)
def _dataset(path: str) -> dict[int, dict]:
    p = pathlib.Path(path)
    return {c["id"]: c for c in map(json.loads, p.open())} if p.exists() else {}


def _state_sources() -> dict[str, dict]:
    from .state import STATE
    p = STATE / "sources.json"
    return json.loads(p.read_text()) if p.exists() else {}


def sources(entry: dict, cfg: Config | None = None) -> list[dict]:
    """The comments rule `entry` was learned from, as source_of dicts, in evidence order (unknown ids are left out)."""
    cfg = cfg or Config()
    ds, saved, out, seen = _dataset(str(cfg.data / "dataset" / "comments.jsonl")), _state_sources(), [], set()
    for x in entry.get("evidence") or []:
        cid = _cid(x)
        if cid is None or cid in seen:
            continue
        seen.add(cid)
        if cid in ds:
            out.append(source_of(ds[cid]))
        elif str(cid) in saved:
            out.append(saved[str(cid)])
    return out


def write_sources(book: list[dict], comments: pathlib.Path, dest: pathlib.Path) -> int:
    """Write dest (a state's sources.json) with the comments behind `book`'s entries, from the dataset
    `comments` of the repository the book was learned on. Returns how many were found."""
    ds = _dataset(str(comments))
    old = json.loads(dest.read_text()) if dest.exists() else {}
    for e in book:
        for x in e.get("evidence") or []:
            cid = _cid(x)
            if cid is not None and cid in ds:
                old[str(cid)] = source_of(ds[cid])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(old, indent=1, sort_keys=True) + "\n")
    return len(old)


def public_book(name: str, label: str) -> str:
    """Rulebook version `name` as a page anyone can read: each active entry under its id (the anchor a review
    links to) with when / expect / why and every comment it was learned from. Nothing internal (tests,
    history, examples)."""
    from .state import load_book
    act = [e for e in load_book(name) if e.get("status", "active") == "active"]
    out = [f"# Team review rules: {label}", "",
           f"{len(act)} rules an AI reviewer checks pull requests against. Each was learned from this team's own "
           "review comments, listed under it. A review that cites a rule links here.", ""]
    for e in sorted(act, key=lambda e: e["id"]):
        out += [f"## {e['id']}", "", f"**When** {e.get('when') or e.get('rule', '')}", ""]
        if e.get("expect"):
            out += [f"**Expect** {e['expect']}", ""]
        if e.get("why"):
            out += [f"**Why** {e['why']}", ""]
        src = sources(e)
        if src:
            out += ["Learned from:", ""]
            out += [f"- [{s['repo'] + '#' if s.get('repo') else '#'}{s['pr']}]({s['url']}) · {s['author']}: \"{s['quote']}"
                    f"{'…' if len(s['quote']) >= QUOTE else ''}\"" for s in src]
            out.append("")
    return "\n".join(out)

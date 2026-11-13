"""Annotate the human comments of a sample once: split each into points, and give each point a type and
severity. Every judge of every run on the sample uses the same annotation, so whether a comment counts
(and as what) no longer changes from one judge call to the next.

A point's key is the comment id (an int) when the comment makes one point, else "<comment id>:<k>". Rule
evidence and ledger rows use these keys; load_gold (score.py) adds each point of a multi-point comment as
a comment of its own under its key, so code that looks comments up by id works for points too.
"""

from __future__ import annotations

import json
import pathlib

from . import llm
from .config import Config
from .workspace import TOOLS, cached_pr, pr_meta, sample_workspace

ANNOTATOR = "a1"  # annotation prompt version; another version is never mixed in
TYPES = ("change_request", "question", "nit", "praise")
SEVERITIES = ("blocker", "major", "minor", "nit")

PROMPT = """Below are the human review comments made on one commit of LMCache PR #{number}. Your working
directory is the repository as of that commit, with `PR.diff` (the PR's changes) and `PR_HISTORY.md`
(the discussion before these comments). Read code wherever a judgment depends on it. Do not modify files.

PR title: {title}

Comments (inline ones show their code location and hunk; overall reviews may hold several points):
{comments}

For each comment, list its points: each distinct thing the reviewer asks for, questions or says. An
inline comment is usually one point. An overall review may hold several; list each separately, and
leave out pure framing ("a few comments below", "thanks"). A comment that is only approval or thanks is
one praise point.

For each point:
- "text": the point on its own, keeping the reviewer's specifics (names, values), at most 30 words.
- "type": change_request (asks for, or clearly implies, a code/test/doc change), question (asks for
  an explanation; no change implied), nit (tiny style/naming/typo suggestion), praise.
- "severity", for change_request and nit only, as you would rate a review finding: blocker (must not
  merge: breaks correctness, data, compatibility), major (real bug, design or maintainability problem
  worth blocking on), minor (worth fixing, limited impact), nit (cosmetic or preference).

Answer with one JSON block only, one entry per comment, in order:
```json
{{"comments": [{{"id": 0, "points": [{{"text": "...", "type": "change_request", "severity": "minor"}}]}}]}}
```"""


def path(cfg: Config, sample: dict) -> pathlib.Path:
    return cfg.data / "annotations" / ANNOTATOR / f"{sample['pr']}-{sample['commit'][:8]}.json"


def key(cid: int, k: int, n: int) -> int | str:
    """The key of point k of n of comment cid."""
    return cid if n == 1 else f"{cid}:{k}"


def cid_of(key: int | str) -> int:
    """The comment a point key belongs to."""
    return int(str(key).split(":")[0])


def _fmt(i: int, c: dict) -> str:
    if c["kind"] == "inline":
        return (f"[{i}] {c['path']}:{c['line_lo']}-{c['line_hi']} by {c['author']}\n"
                f"hunk:\n{(c['diff_hunk'] or '')[-1200:]}\ncomment: {c['body'][:1500]}")
    return f"[{i}] overall review by {c['author']} ({c['review_state']}):\n{c['body'][:2500]}"


def _clean(raw: object, gold: list[dict]) -> dict[str, list[dict]]:
    """The model's answer as {comment id: [point]}; a comment it skipped or garbled gets one point
    with no type (it then counts as nothing, and the next annotator version can fix it)."""
    by = {}
    for e in (raw or {}).get("comments") or [] if isinstance(raw, dict) else []:
        if isinstance(e, dict) and isinstance(e.get("id"), int) and 0 <= e["id"] < len(gold):
            by[e["id"]] = [p for p in e.get("points") or [] if isinstance(p, dict)]
    out = {}
    for i, c in enumerate(gold):
        ps = []
        for p in by.get(i) or [{"text": "", "type": None}]:
            t = p.get("type") if p.get("type") in TYPES else None
            sev = p.get("severity") if t in ("change_request", "nit") and p.get("severity") in SEVERITIES else None
            ps.append({"text": str(p.get("text") or "")[:400], "type": t, "severity": sev})
        out[str(c["id"])] = ps
    return out


def annotate(cfg: Config, sample: dict, gold: list[dict], effort: str) -> dict:
    """The sample's annotation ({"comments": {comment id: [point]}, "cost", ...}); cached on disk.
    The workspace is the one the reviewer saw (context directives do not matter: no reviewer prompt)."""
    p = path(cfg, sample)
    if p.exists():
        a = json.loads(p.read_text())
        if set(a["comments"]) >= {str(c["id"]) for c in gold}:
            return a | {"cost": 0.0, "cached": True}
    raw_pr = cached_pr(cfg, sample["pr"], sample["time"])
    with sample_workspace(cfg, sample, "annotate") as (wt, _):
        r = llm.run(PROMPT.format(comments="\n\n".join(_fmt(i, c) for i, c in enumerate(gold)),
                                  **pr_meta(raw_pr)), effort, cwd=str(wt), tools=TOOLS)
    try:
        raw = llm.extract_json(r["text"])
    except ValueError:
        raw = None
    a = {"annotator": ANNOTATOR, "effort": effort, "pr": sample["pr"], "commit": sample["commit"],
         "comments": _clean(raw, gold), "cost": r["cost"]}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(a, indent=1))
    return a


def points(a: dict, gold: list[dict]) -> list[dict]:
    """The annotated points of `gold`, in order: {"id": comment index, "point", "key", "text", "type",
    "severity"}."""
    out = []
    for i, c in enumerate(gold):
        ps = a["comments"][str(c["id"])]
        out += [{"id": i, "point": k, "key": key(c["id"], k, len(ps)), **p} for k, p in enumerate(ps)]
    return out


def point_comments(cfg: Config, cm: dict) -> dict[str, dict]:
    """Every annotated point of a multi-point comment as a comment of its own, by its key: the comment
    with the point's text first, so distill and reports see which point is meant."""
    out = {}
    for f in (cfg.data / "annotations" / ANNOTATOR).glob("*.json") if (cfg.data / "annotations").exists() else []:
        for cid, ps in json.loads(f.read_text())["comments"].items():
            c = cm.get(int(cid))
            if c is None or len(ps) < 2:
                continue
            for k, p in enumerate(ps):
                out[key(int(cid), k, len(ps))] = c | {
                    "id": key(int(cid), k, len(ps)), "point": k, "comment": c["id"],
                    "body": f"(point {k + 1} of {len(ps)} in this review) {p['text']}\n\nthe whole review:\n{c['body']}"}
    return out

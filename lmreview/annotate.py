"""Annotate the human comments of a sample once (two independent annotations, a third vote where they
differ): split each into points, and give each point a type and
severity. Every judge of every run on the sample uses the same annotation, so whether a comment counts
(and as what) no longer changes from one judge call to the next.

A point's key is the comment id (an int) when the comment makes one point, else "<comment id>:<k>". Rule
evidence and ledger rows use these keys; load_gold (score.py) adds each point of a multi-point comment as
a comment of its own under its key, so code that looks comments up by id works for points too.
"""

from __future__ import annotations

import json
import pathlib
from concurrent.futures import ThreadPoolExecutor

from . import llm
from .config import Config
from .workspace import TOOLS, cached_pr, pr_meta, sample_workspace

ANNOTATOR = "a2"  # annotation prompt version; another version is never mixed in
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
    """Where the annotation of `sample` is cached."""
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


def _once(cfg: Config, sample: dict, gold: list[dict], effort: str) -> tuple[dict[str, list[dict]], float]:
    """One independent annotation of `gold`: ({comment id: [point]}, cost)."""
    raw_pr = cached_pr(cfg, sample["pr"], sample["time"])
    with sample_workspace(cfg, sample, "annotate") as (wt, _):
        r = llm.run(PROMPT.format(comments="\n\n".join(_fmt(i, c) for i, c in enumerate(gold)),
                                  **pr_meta(raw_pr)), effort, cwd=str(wt), tools=TOOLS)
    try:
        raw = llm.extract_json(r["text"])
    except ValueError:
        raw = None
    return _clean(raw, gold), r["cost"]


def _shape(ps: list[dict]) -> tuple:
    """What two annotations of a comment must agree on: its points' types, in order (the count with it)."""
    return tuple(p["type"] for p in ps)


def annotate(cfg: Config, sample: dict, gold: list[dict], effort: str) -> dict:
    """The sample's annotation ({"comments": {comment id: [point]}, "cost", ...}); cached on disk.

    Two independent annotations; a comment they split or type differently gets a third, and the shape
    two of the three share wins (no majority: the one with the most change_request / nit points, so a
    point the team asked for is not lost). The workspace is the one the reviewer saw."""
    p = path(cfg, sample)
    if p.exists():
        a = json.loads(p.read_text())
        if set(a["comments"]) >= {str(c["id"]) for c in gold}:
            return a | {"cost": 0.0, "cached": True}
    with ThreadPoolExecutor(2) as ex:
        runs = list(ex.map(lambda _: _once(cfg, sample, gold, effort), range(2)))
    cost = sum(c for _, c in runs)
    split = [cid for cid in runs[0][0] if _shape(runs[0][0][cid]) != _shape(runs[1][0][cid])]
    if split:
        third, c3 = _once(cfg, sample, [c for c in gold if str(c["id"]) in split], effort)
        runs.append(({**runs[0][0], **third}, c3))
        cost += c3
    out, votes = {}, {}
    for cid in runs[0][0]:
        cands = [r[cid] for r, _ in runs]
        shapes = [_shape(x) for x in cands]
        best = next((x for x, s in zip(cands, shapes) if shapes.count(s) >= 2), None)
        out[cid] = best or max(cands, key=lambda x: sum(q["type"] in ("change_request", "nit") for q in x))
        votes[cid] = "agreed" if cid not in split else "majority" if best else "no majority"
    a = {"annotator": ANNOTATOR, "effort": effort, "pr": sample["pr"], "commit": sample["commit"],
         "comments": out, "votes": votes, "cost": cost}
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

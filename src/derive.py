"""Turn raw PR JSON into the P0 dataset.

Outputs (data/dataset/):
  prs.jsonl       one row per PR: first human review commit/time, outcome, areas, split
  comments.jsonl  one row per review comment (inline thread roots, review bodies, PR comments),
                  human and bot, with the `addressed` label computed from git

`addressed` (inline, RIGHT side only): the commented lines (+/- MARGIN) were changed between
the commit the comment was made on and the PR's final head.
"""

from __future__ import annotations

import collections
import datetime as dt
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "pr"
GIT = ROOT / "data" / "LMCache"
OUT = ROOT / "data" / "dataset"
MARGIN = 3

AI_BOTS = {"gemini-code-assist", "copilot-pull-request-reviewer", "Copilot", "cursor",
           "chatgpt-codex-connector", "claude", "coderabbitai", "github-advanced-security"}

# Ordered: first matching prefix wins.
AREAS = [
    ("lmcache/integration/", "vllm-integration"),
    ("lmcache/v1/multiprocess/", "mp"),
    ("lmcache/v1/mp_coordinator/", "mp"),
    ("lmcache/v1/mp_observability/", "observability"),
    ("lmcache/v1/distributed/", "distributed"),
    ("lmcache/v1/gpu_connector/", "gpu-connector"),
    ("csrc/", "kernels"),
    ("rust/", "kernels"),
    ("lmcache/v1/storage_backend/", "storage"),
    ("lmcache/storage_backend/", "storage"),
    ("lmcache/inprocess/", "inprocess"),
    ("lmcache/v1/cache_engine.py", "inprocess"),
    ("lmcache/v1/platform/", "platform"),
    ("lmcache/v1/memory", "memory"),
    ("lmcache/cli/", "cli"),
    ("lmcache/", "core-other"),
    ("tests/", "tests"),
    ("docs/", "docs"),
    (".github/", "ci-build"),
    (".buildkite/", "ci-build"),
    ("docker/", "ci-build"),
    ("operator/", "operator"),
    ("setup", "ci-build"),
    ("pyproject", "ci-build"),
    ("requirements/", "ci-build"),
    ("examples/", "examples"),
    ("benchmarks/", "examples"),
]


def area_of(path: str) -> str:
    """Map a repo path to a coarse review area."""
    if path.endswith((".md", ".rst")):
        return "docs"
    for prefix, area in AREAS:
        if path.startswith(prefix):
            return area
    return "other"


def login(node: dict | None) -> str:
    """Return the author's login, or '' for deleted users."""
    return ((node or {}).get("author") or {}).get("login") or ""


def is_bot(node: dict) -> bool:
    """True if the author is a bot account."""
    a = node.get("author") or {}
    lg = a.get("login") or ""
    return a.get("__typename") == "Bot" or lg.endswith("[bot]") or lg in AI_BOTS


def bot_name(lg: str) -> str:
    """Normalize bot logins (strip the [bot] suffix)."""
    return lg.removesuffix("[bot]")


def split_of(created: str) -> str:
    """Time-based split by PR creation date (UTC)."""
    d = created[:10]
    if d < "2026-09-01":
        return "train"
    if d < "2026-11-01":
        return "test"
    return "holdout"


def git(*args: str) -> subprocess.CompletedProcess:
    """Run git in the LMCache clone."""
    return subprocess.run(["git", "-C", str(GIT), *args], capture_output=True, text=True)


_have: dict[str, bool] = {}


def have_commit(oid: str) -> bool:
    """True if the commit exists locally."""
    if oid not in _have:
        _have[oid] = git("cat-file", "-e", f"{oid}^{{commit}}").returncode == 0
    return _have[oid]


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", re.M)


def lines_changed(c0: str, head: str, path: str, lo: int, hi: int) -> tuple[bool | None, str]:
    """Whether lines [lo, hi] of `path` at c0 were changed by head.

    Returns:
        (changed, reason). changed is None when it cannot be determined.
    """
    if c0 == head:
        return False, "no-later-commits"
    if not (have_commit(c0) and have_commit(head)):
        return None, "commit-missing"
    p = git("diff", "-U0", "-M", c0, head, "--", path)
    if p.returncode != 0:
        return None, "diff-failed"
    if not p.stdout.strip():
        return False, "file-unchanged"
    if "\ndeleted file mode" in p.stdout or p.stdout.startswith("deleted file mode"):
        return True, "file-deleted"
    for m in HUNK.finditer(p.stdout):
        a = int(m.group(1))
        b = 1 if m.group(2) is None else int(m.group(2))
        old_lo, old_hi = (a, a + 1) if b == 0 else (a, a + b - 1)
        if old_lo <= hi + MARGIN and old_hi >= lo - MARGIN:
            return True, "lines-changed"
    return False, "file-changed-elsewhere"


def first_human_review(pr: dict, author: str) -> dict | None:
    """Earliest review activity by a human other than the PR author."""
    events = []
    for r in pr["reviews"]["nodes"]:
        if login(r) and login(r) != author and not is_bot(r) and r.get("submittedAt"):
            events.append((r["submittedAt"], (r.get("commit") or {}).get("oid"), login(r), r["state"]))
    for t in pr["reviewThreads"]["nodes"]:
        for c in t["comments"]["nodes"]:
            if login(c) and login(c) != author and not is_bot(c):
                events.append((c["createdAt"], (c.get("originalCommit") or {}).get("oid"), login(c), "INLINE"))
    if not events:
        return None
    t, oid, who, state = min(events)
    return {"time": t, "commit": oid, "reviewer": who, "state": state}


def main() -> None:
    """Build prs.jsonl and comments.jsonl from data/raw/pr/*.json."""
    OUT.mkdir(parents=True, exist_ok=True)
    prs_out, cm_out = [], []
    for f in sorted(RAW.glob("*.json"), key=lambda p: int(p.stem)):
        pr = json.loads(f.read_text())
        n, author = pr["number"], login(pr)
        head = pr["headRefOid"]
        files = [x["path"] for x in pr["files"]["nodes"]]
        commits = [c["commit"] for c in pr["commits"]["nodes"]]
        fhr = first_human_review(pr, author)
        human_states = [r["state"] for r in pr["reviews"]["nodes"]
                        if login(r) != author and not is_bot(r)]
        truncated = [k for k in ("files", "commits", "reviews", "reviewThreads", "comments")
                     if pr[k].get("pageInfo", {}).get("hasNextPage")]
        prs_out.append({
            "pr": n, "title": pr["title"], "author": author, "state": pr["state"],
            "created": pr["createdAt"], "merged": pr["mergedAt"], "closed": pr["closedAt"],
            "split": split_of(pr["createdAt"]), "head": head, "base": pr["baseRefName"],
            "files": files, "areas": sorted({area_of(p) for p in files}),
            "additions": pr["additions"], "deletions": pr["deletions"],
            "n_commits": pr["commits"]["totalCount"],
            "has_merge_commits": any(c["parents"]["totalCount"] > 1 for c in commits),
            "first_human_review": fhr,
            "human_review_states": human_states,
            "human_changes_requested": "CHANGES_REQUESTED" in human_states,
            "truncated": truncated,
            "cross_refs": [x["source"] for x in pr["timelineItems"]["nodes"] if x.get("source")],
        })

        # Inline threads: one row per thread root, replies summarized.
        for t in pr["reviewThreads"]["nodes"]:
            cs = t["comments"]["nodes"]
            if not cs:
                continue
            root, replies = cs[0], cs[1:]
            lo = root.get("originalStartLine") or root.get("originalLine")
            hi = root.get("originalLine") or lo
            c0 = (root.get("originalCommit") or {}).get("oid")
            side = t.get("diffSide")
            if side == "RIGHT" and lo and c0:
                addressed, why = lines_changed(c0, head, root["path"], lo, hi)
            else:
                addressed, why = None, f"side={side}" if side != "RIGHT" else "no-line"
            lg = login(root)
            cm_out.append({
                "pr": n, "id": root["databaseId"], "kind": "inline", "author": lg,
                "is_bot": is_bot(root), "bot": bot_name(lg) if is_bot(root) else None,
                "is_pr_author": lg == author, "created": root["createdAt"],
                "path": root["path"], "area": area_of(root["path"]), "side": side,
                "line_lo": lo, "line_hi": hi, "commit": c0,
                "is_first_review_commit": bool(fhr and c0 == fhr["commit"]),
                "body": root["body"], "diff_hunk": root["diffHunk"],
                "review_state": (root.get("pullRequestReview") or {}).get("state"),
                "thread_resolved": t["isResolved"], "thread_outdated": t["isOutdated"],
                "n_replies": len(replies),
                "pr_author_replied": any(login(r) == author for r in replies),
                "replies": [{"author": login(r), "body": r["body"][:500]} for r in replies[:5]],
                "addressed": addressed, "addressed_reason": why,
                "url": f"https://github.com/LMCache/LMCache/pull/{n}#discussion_r{root['databaseId']}",
            })
        # Review summary bodies and PR conversation comments (no line anchor).
        for r in pr["reviews"]["nodes"]:
            if (r.get("body") or "").strip():
                lg = login(r)
                cm_out.append({
                    "pr": n, "id": r["databaseId"], "kind": "review_body", "author": lg,
                    "is_bot": is_bot(r), "bot": bot_name(lg) if is_bot(r) else None,
                    "is_pr_author": lg == author, "created": r.get("submittedAt"),
                    "review_state": r["state"], "commit": (r.get("commit") or {}).get("oid"),
                    "body": r["body"],
                    "url": f"https://github.com/LMCache/LMCache/pull/{n}#pullrequestreview-{r['databaseId']}",
                })
        for c in pr["comments"]["nodes"]:
            lg = login(c)
            cm_out.append({
                "pr": n, "id": c["databaseId"], "kind": "pr_comment", "author": lg,
                "is_bot": is_bot(c), "bot": bot_name(lg) if is_bot(c) else None,
                "is_pr_author": lg == author, "created": c["createdAt"], "body": c["body"],
                "url": f"https://github.com/LMCache/LMCache/pull/{n}#issuecomment-{c['databaseId']}",
            })

    (OUT / "prs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in prs_out))
    (OUT / "comments.jsonl").write_text("".join(json.dumps(r) + "\n" for r in cm_out))
    missing = sorted({c["commit"] for c in cm_out
                      if c.get("addressed_reason") == "commit-missing" and c.get("commit")})
    (OUT / "missing_commits.txt").write_text("\n".join(missing))
    print(f"prs={len(prs_out)} comments={len(cm_out)} missing_commits={len(missing)}")
    print("addressed reasons:", collections.Counter(
        c["addressed_reason"] for c in cm_out if c["kind"] == "inline").most_common())


if __name__ == "__main__":
    main()

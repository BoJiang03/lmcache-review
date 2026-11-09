"""P0 dataset report + a spot-check sample for the `addressed` label.

Writes reports/p0_stats.md and reports/p0_spotcheck.md.
"""

from __future__ import annotations

import collections as C
import json
import pathlib
import random
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
DS = ROOT / "data" / "dataset"
GIT = ROOT / "data" / "LMCache"
REP = ROOT / "reports"


def load(name: str) -> list[dict]:
    """Read a jsonl file from the dataset dir."""
    return [json.loads(l) for l in (DS / name).read_text().splitlines() if l.strip()]


def pct(a: int, b: int) -> str:
    """Format a/b as a percentage."""
    return f"{a / b:.0%}" if b else "-"


def diff_snippet(c: dict, head: str) -> str:
    """The part of git diff (comment commit -> PR head) for the commented file, trimmed."""
    if not c.get("commit"):
        return "(no commit)"
    p = subprocess.run(["git", "-C", str(GIT), "diff", "-U2", "-M", c["commit"], head, "--", c["path"]],
                       capture_output=True, text=True)
    out = p.stdout.strip() or "(no change to this file)"
    return out[:1500] + ("\n…" if len(out) > 1500 else "")


def main() -> None:
    """Compute stats and write the spot-check sample."""
    REP.mkdir(exist_ok=True)
    prs = {p["pr"]: p for p in load("prs.jsonl")}
    cs = load("comments.jsonl")
    human = [c for c in cs if not c["is_bot"] and not c["is_pr_author"] and c["author"]]
    inl = [c for c in human if c["kind"] == "inline"]
    bots = [c for c in cs if c["is_bot"]]

    L = ["# P0 dataset stats", ""]
    L += ["## PRs", "", "| split | PRs | merged | with human review | human changes requested |",
          "| --- | --- | --- | --- | --- |"]
    for s in ("train", "test", "holdout"):
        ps = [p for p in prs.values() if p["split"] == s]
        L.append(f"| {s} | {len(ps)} | {sum(bool(p['merged']) for p in ps)} | "
                 f"{sum(bool(p['first_human_review']) for p in ps)} | "
                 f"{sum(p['human_changes_requested'] for p in ps)} |")
    L += ["", f"PRs with merge commits (addressed label less reliable): "
          f"{sum(p['has_merge_commits'] for p in prs.values())}",
          f"PRs with truncated connections: {sum(bool(p['truncated']) for p in prs.values())}", ""]

    L += ["## Human review comments (not by PR author)", "",
          "| kind | train | test | holdout |", "| --- | --- | --- | --- |"]
    for k in ("inline", "review_body", "pr_comment"):
        row = [sum(1 for c in human if c["kind"] == k and prs[c["pr"]]["split"] == s)
               for s in ("train", "test", "holdout")]
        L.append(f"| {k} | " + " | ".join(map(str, row)) + " |")
    L += ["", "Top inline reviewers: " + ", ".join(
        f"{a} {n}" for a, n in C.Counter(c["author"] for c in inl).most_common(10)), ""]

    L += ["## `addressed` label (human inline roots)", "",
          "| addressed | count | share | thread outdated | thread resolved |",
          "| --- | --- | --- | --- | --- |"]
    for v in (True, False, None):
        g = [c for c in inl if c["addressed"] is v]
        L.append(f"| {v} | {len(g)} | {pct(len(g), len(inl))} | "
                 f"{pct(sum(c['thread_outdated'] for c in g), len(g))} | "
                 f"{pct(sum(c['thread_resolved'] for c in g), len(g))} |")
    L += ["", "Reasons: " + ", ".join(f"{r} {n}" for r, n in
                                       C.Counter(c["addressed_reason"] for c in inl).most_common()), ""]
    known = [c for c in inl if c["addressed"] is not None]
    agree = sum(c["addressed"] == c["thread_outdated"] for c in known)
    L += [f"Agreement of `addressed` with GitHub `isOutdated`: {agree}/{len(known)} ({pct(agree, len(known))})", ""]

    L += ["## By area (human inline roots)", "", "| area | comments | addressed |", "| --- | --- | --- |"]
    for a, n in C.Counter(c["area"] for c in inl).most_common():
        g = [c for c in inl if c["area"] == a]
        L.append(f"| {a} | {n} | {pct(sum(c['addressed'] is True for c in g), n)} |")

    L += ["", "## Bot review comments (baseline material for P1)", "",
          "| bot | comments | on PRs that also have human review |", "| --- | --- | --- |"]
    for b, n in C.Counter(c["bot"] for c in bots).most_common(8):
        on = sum(1 for c in bots if c["bot"] == b and prs[c["pr"]]["first_human_review"])
        L.append(f"| {b} | {n} | {on} |")
    (REP / "p0_stats.md").write_text("\n".join(L) + "\n")

    # Spot check: 30 human inline roots with a known label, stratified True/False.
    rnd = random.Random(0)
    t = [c for c in inl if c["addressed"] is True]
    f = [c for c in inl if c["addressed"] is False]
    sample = rnd.sample(t, min(20, len(t))) + rnd.sample(f, min(10, len(f)))
    S = ["# P0 spot check: `addressed` label", "",
         "For each: does the later diff actually respond to the comment?", ""]
    for i, c in enumerate(sample, 1):
        p = prs[c["pr"]]
        S += [f"## {i}. PR #{c['pr']} — label addressed={c['addressed']} ({c['addressed_reason']})",
              f"{c['url']}  ", f"`{c['path']}` lines {c['line_lo']}–{c['line_hi']} · reviewer {c['author']} "
              f"· outdated={c['thread_outdated']} resolved={c['thread_resolved']}", "",
              "Comment:", "", "> " + c["body"].replace("\n", "\n> ")[:800], "",
              "Later diff of this file (comment commit → PR head):", "", "```diff",
              diff_snippet(c, p["head"]), "```", ""]
    (REP / "p0_spotcheck.md").write_text("\n".join(S) + "\n")
    print((REP / "p0_stats.md").read_text())


if __name__ == "__main__":
    main()

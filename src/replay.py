"""Replay a reviewer on PRs at their first-human-review commit.

For each PR: export a plain snapshot (no git history) of the commit the first human
reviewer saw, write the PR diff against dev as of that time to PR.diff, run the reviewer with read-only tools, save its findings to
data/runs/<version>/<pr>.json.

Usage: python3 -I src/replay.py --version v0 --split test --limit 10
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import pathlib
import subprocess
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import llm  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
GIT = ROOT / "data" / "LMCache"
DS = ROOT / "data" / "dataset"
PROMPTS = ROOT / "prompts"
# No git in the snapshot: the reviewer must not see later commits (answer leakage).
TOOLS = "Read,Grep,Glob"


def git(*a: str, cwd: pathlib.Path = GIT) -> str:
    """Run git, return stdout, raise on failure."""
    return subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout


def eval_prs(split: str) -> list[dict]:
    """PRs in `split` whose first human review left inline comments (the gold set)."""
    prs = {json.loads(l)["pr"]: json.loads(l) for l in (DS / "prs.jsonl").open()}
    gold = {json.loads(l)["pr"] for l in (DS / "comments.jsonl").open()
            if (c := json.loads(l))["kind"] == "inline" and c["is_first_review_commit"]
            and not c["is_bot"] and not c["is_pr_author"] and c["author"]}
    return sorted((p for n, p in prs.items() if n in gold and p["split"] == split),
                  key=lambda p: p["pr"])


def review_one(pr: dict, version: str) -> str:
    """Run the reviewer on one PR; returns a status string."""
    out = ROOT / "data" / "runs" / version / f"{pr['pr']}.json"
    if out.exists():
        return "cached"
    fr = pr["first_human_review"]
    commit, t = fr["commit"], fr["time"]
    dev_then = git("rev-list", "-1", f"--before={t}", "origin/dev").strip()
    base = git("merge-base", dev_then, commit).strip()
    wt = ROOT / "data" / "wt" / str(pr["pr"])
    shutil.rmtree(wt, ignore_errors=True)
    wt.mkdir(parents=True)
    arch = subprocess.run(["git", "-C", str(GIT), "archive", commit], check=True, capture_output=True)
    subprocess.run(["tar", "-x", "-C", str(wt)], input=arch.stdout, check=True)
    (wt / "PR.diff").write_text(git("diff", "-M", base, commit))
    try:
        prompt = (PROMPTS / f"reviewer_{version}.md").read_text().format(
            number=pr["pr"], title=pr["title"], base=base, head=commit,
            body=(json.loads((ROOT / "data" / "raw" / "pr" / f"{pr['pr']}.json").read_text())
                  .get("body") or "")[:4000])
        r = llm.run(prompt, cwd=str(wt), tools=TOOLS)
        try:
            findings = llm.extract_json(r["text"])
        except ValueError:
            findings = None
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"pr": pr["pr"], "commit": commit, "base": base,
                                   "findings": findings, "raw": r["text"], "cost": r["cost"],
                                   "turns": r["turns"]}, indent=1))
        return f"{len(findings) if findings is not None else 'PARSE-FAIL'} findings ${r['cost']:.2f}"
    finally:
        shutil.rmtree(wt, ignore_errors=True)


def main() -> None:
    """Replay the reviewer over the first `--limit` eval PRs of a split."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v0")
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    prs = eval_prs(a.split)
    print(f"{len(prs)} eval PRs in {a.split}; running {min(a.limit, len(prs))}", flush=True)
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(review_one, p, a.version): p["pr"] for p in prs[:a.limit]}
        for f in cf.as_completed(futs):
            try:
                print(f"  #{futs[f]}: {f.result()}", flush=True)
            except Exception as e:  # keep going
                print(f"  #{futs[f]}: FAIL {e}", flush=True)


if __name__ == "__main__":
    main()

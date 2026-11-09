"""Replay a reviewer on eval samples: one per (PR, commit a human reviewed).

For each sample: export a full snapshot of the repo at the reviewed commit (all files, but no git
history, so later commits cannot leak), write the PR diff against dev as of that time to PR.diff
and the discussion so far to PR_HISTORY.md, run the reviewer with read-only tools, save its
findings to data/runs/<version>/<pr>-<commit8>.json.

Usage: python3 -I src/replay.py --version v0 --split test --limit 10
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import pathlib
import random
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import llm  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
GIT = ROOT / "data" / "LMCache"
DS = ROOT / "data" / "dataset"
PROMPTS = ROOT / "prompts"
TOOLS = "Read,Grep,Glob"
SANDBOX = pathlib.Path("/raid/bo/review-sandbox")  # outside this repo; llm.run confines tools to cwd


def git(*a: str) -> str:
    """Run git in the clone, return stdout, raise on failure."""
    return subprocess.run(["git", "-C", str(GIT), *a], check=True, capture_output=True, text=True).stdout


def run_path(version: str, s: dict) -> pathlib.Path:
    """Where the run for sample `s` is stored."""
    return ROOT / "data" / "runs" / version / f"{s['pr']}-{s['commit'][:8]}.json"


def review_one(s: dict, prs: dict, version: str, effort: str) -> str:
    """Run the reviewer on one sample; returns a status string."""
    out = run_path(version, s)
    if out.exists():
        return "cached"
    pr, commit = prs[s["pr"]], s["commit"]
    dev_then = git("rev-list", "-1", f"--before={s['time']}", "origin/dev").strip()
    base = git("merge-base", dev_then, commit).strip()
    wt = SANDBOX / f"{s['pr']}-{commit[:8]}"
    shutil.rmtree(wt, ignore_errors=True)
    wt.mkdir(parents=True)
    try:
        arch = subprocess.run(["git", "-C", str(GIT), "archive", commit], check=True, capture_output=True)
        subprocess.run(["tar", "-x", "-C", str(wt)], input=arch.stdout, check=True)
        (wt / "PR.diff").write_text(git("diff", "-M", base, commit))
        (wt / "PR_HISTORY.md").write_text(s["history"] or "(no discussion yet)\n")
        body = json.loads((ROOT / "data" / "raw" / "pr" / f"{s['pr']}.json").read_text()).get("body") or ""
        prompt = (PROMPTS / f"reviewer_{version}.md").read_text().format(
            number=s["pr"], title=pr["title"], body=body[:4000])
        r = llm.run(prompt, effort, cwd=str(wt), tools=TOOLS)
        try:
            findings = llm.extract_json(r["text"])
        except ValueError:
            findings = None
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"pr": s["pr"], "commit": commit, "base": base,
                                   "findings": findings, "raw": r["text"], "cost": r["cost"],
                                   "turns": r["turns"], "denials": r["denials"],
                                   "effort": effort}, indent=1))
        return (f"{len(findings) if findings is not None else 'PARSE-FAIL'} findings ${r['cost']:.2f}"
                + (f" DENIED {len(r['denials'])}" if r["denials"] else ""))
    finally:
        shutil.rmtree(wt, ignore_errors=True)


def main() -> None:
    """Replay the reviewer over `--limit` samples of a split (random but fixed order)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v0")
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--effort", default="high")
    a = ap.parse_args()
    prs = {json.loads(l)["pr"]: json.loads(l) for l in (DS / "prs.jsonl").open()}
    ss = [json.loads(l) for l in (DS / "samples.jsonl").open()]
    ss = [s for s in ss if s["split"] == a.split]
    random.Random(0).shuffle(ss)
    ss = ss[:a.limit]
    print(f"running {len(ss)} samples of {a.split}", flush=True)
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(review_one, s, prs, a.version, a.effort): f"{s['pr']}-{s['commit'][:8]}" for s in ss}
        for f in cf.as_completed(futs):
            try:
                print(f"  #{futs[f]}: {f.result()}", flush=True)
            except Exception as e:  # keep going
                print(f"  #{futs[f]}: FAIL {e}", flush=True)


if __name__ == "__main__":
    main()

"""Replay a reviewer on eval samples: one per (PR, commit a human reviewed).

The reviewer works in the sample's workspace (see workspace.py / docs/agent_context.md) and its
findings are saved to data/runs/<version>/<pr>-<commit8>.json.

Usage: python3 -I src/replay.py --version v0 --split test --limit 10 --effort high
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import llm  # noqa: E402
from workspace import TOOLS, pr_meta, workspace  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DS = ROOT / "data" / "dataset"
PROMPTS = ROOT / "prompts"


def run_path(version: str, s: dict) -> pathlib.Path:
    """Where the run for sample `s` is stored."""
    return ROOT / "data" / "runs" / version / f"{s['pr']}-{s['commit'][:8]}.json"


def review_one(s: dict, version: str, effort: str) -> str:
    """Run the reviewer on one sample; returns a status string."""
    out = run_path(version, s)
    if out.exists():
        return "cached"
    with workspace(s, "review") as (wt, base):
        prompt = (PROMPTS / f"reviewer_{version}.md").read_text().format(**pr_meta(s["pr"]))
        r = llm.run(prompt, effort, cwd=str(wt), tools=TOOLS)
    try:
        findings = llm.extract_json(r["text"])
    except ValueError:
        findings = None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"pr": s["pr"], "commit": s["commit"], "base": base,
                               "findings": findings, "raw": r["text"], "cost": r["cost"],
                               "turns": r["turns"], "denials": r["denials"], "effort": effort},
                              indent=1))
    return (f"{len(findings) if findings is not None else 'PARSE-FAIL'} findings ${r['cost']:.2f}"
            + (f" DENIED {len(r['denials'])}" if r["denials"] else ""))


def main() -> None:
    """Replay the reviewer over `--limit` samples of a split (random but fixed order)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v0")
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--effort", default="high")
    a = ap.parse_args()
    ss = [json.loads(l) for l in (DS / "samples.jsonl").open()]
    ss = [s for s in ss if s["split"] == a.split]
    random.Random(0).shuffle(ss)
    ss = ss[:a.limit]
    print(f"running {len(ss)} samples of {a.split}", flush=True)
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(review_one, s, a.version, a.effort): f"{s['pr']}-{s['commit'][:8]}" for s in ss}
        for f in cf.as_completed(futs):
            try:
                print(f"  #{futs[f]}: {f.result()}", flush=True)
            except Exception as e:  # keep going
                print(f"  #{futs[f]}: FAIL {e}", flush=True)


if __name__ == "__main__":
    main()

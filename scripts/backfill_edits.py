"""Add `_edits` (edit history of title, description, reviews, comments) to raw PRs that lack it.

Read-only on GitHub; no LLM. Leaves every other field of the raw PR untouched, so the dataset
(samples, gold) does not change; only what replays show as "text at review time" does.

usage: python3 scripts/backfill_edits.py [--all] [--workers 4]
       (default: only PRs in data/dataset/prs.jsonl)
"""

from __future__ import annotations

import argparse
import concurrent.futures as F
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from lmreview.config import Config  # noqa: E402
from lmreview.github import fetch_edits  # noqa: E402


def one(path: pathlib.Path) -> str:
    raw = json.loads(path.read_text())
    if "_edits" in raw:
        return "had"
    raw["_edits"] = fetch_edits(raw["number"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw))
    tmp.rename(path)
    return "added"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="every raw PR, not just the dataset's")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    cfg = Config()
    rawdir = cfg.data / "raw" / "pr"
    if a.all:
        paths = sorted(rawdir.glob("*.json"))
    else:
        paths = [rawdir / f"{json.loads(l)['pr']}.json" for l in (cfg.data / "dataset" / "prs.jsonl").open()]
    done = {"had": 0, "added": 0, "failed": 0}
    with F.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(one, p): p for p in paths}
        for i, f in enumerate(F.as_completed(futs), 1):
            try:
                done[f.result()] += 1
            except Exception as e:  # keep going; rerun picks up the rest
                done["failed"] += 1
                print(f"  FAIL {futs[f].name}: {e}", flush=True)
            if i % 100 == 0:
                print(f"  {i}/{len(paths)} {done}", flush=True)
    print(done)


if __name__ == "__main__":
    main()

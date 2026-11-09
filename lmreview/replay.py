"""Eval: replay a reviewer on historical samples, one per (PR, commit a human reviewed).

Each run is saved to <data>/runs/<version>/<pr>-<commit8>.json (cached: existing runs are reused).
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import pathlib
import random

from .config import Config
from .reviewer import run_reviewer
from .workspace import cached_pr, sample_workspace


def load_samples(cfg: Config, split: str, limit: int, prs: list[int] | None = None) -> list[dict]:
    """`limit` samples of `split` in a fixed random order (same subset every time), optionally
    restricted to PR numbers `prs`."""
    ss = [json.loads(l) for l in (cfg.data / "dataset" / "samples.jsonl").open()]
    ss = [s for s in ss if s["split"] == split]
    random.Random(0).shuffle(ss)
    ss = ss[:limit]
    return [s for s in ss if s["pr"] in prs] if prs else ss


def run_path(cfg: Config, version: str, s: dict) -> pathlib.Path:
    """Where the run for sample `s` is stored."""
    return cfg.data / "runs" / version / f"{s['pr']}-{s['commit'][:8]}.json"


def replay_one(cfg: Config, s: dict, version: str, effort: str) -> str:
    """Run the reviewer on one sample; returns a status string."""
    out = run_path(cfg, version, s)
    if out.exists():
        return "cached"
    with sample_workspace(cfg, s, "review") as (wt, base):
        r = run_reviewer(wt, cached_pr(cfg, s["pr"]), version, effort)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"pr": s["pr"], "commit": s["commit"], "base": base, **r}, indent=1))
    n = len(r["findings"]) if r["findings"] is not None else f"INVALID ({r['error']})"
    return f"{n} findings ${r['cost']:.2f}" + (f" DENIED {len(r['denials'])}" if r["denials"] else "")


def replay(version: str = "v0", split: str = "test", limit: int = 10, workers: int = 4,
           effort: str = "high", prs: list[int] | None = None, cfg: Config | None = None) -> None:
    """Replay the reviewer over `limit` samples of `split`, printing progress."""
    cfg = cfg or Config()
    ss = load_samples(cfg, split, limit, prs)
    print(f"running {len(ss)} samples of {split}", flush=True)
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(replay_one, cfg, s, version, effort): f"{s['pr']}-{s['commit'][:8]}" for s in ss}
        for f in cf.as_completed(futs):
            try:
                print(f"  #{futs[f]}: {f.result()}", flush=True)
            except Exception as e:  # keep going
                print(f"  #{futs[f]}: FAIL {e}", flush=True)

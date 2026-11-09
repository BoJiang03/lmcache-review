"""Run a reviewer over samples, one per (PR, commit a human reviewed): historical splits and new PRs.

Splits (by PR creation date): train (distill only from here), test (compare versions), new (PRs
since 2026-11-01, filled by `sync`; the launch gate looks here; never distilled from).
Each run is saved to <data>/runs/<reviewer>/<pr>-<commit8>.json and reused if present.
"""

from __future__ import annotations

import json
import pathlib
import random

from .budget import capped_map
from .config import Config
from .reviewer import DEFAULT_REVIEWER, load_rules, parse_reviewer, run_reviewer
from .workspace import cached_pr, sample_workspace

EST_COST = 1.3  # $/sample for a high-effort review, from earlier runs; used only for the estimate


def load_samples(cfg: Config, split: str, limit: int | None, prs: list[int] | None = None) -> list[dict]:
    """Samples of `split` in a fixed random order (same subset every time), optionally only PRs `prs`."""
    ss = [json.loads(l) for l in (cfg.data / "dataset" / "samples.jsonl").open()]
    ss = [s for s in ss if s["split"] == split and (not prs or s["pr"] in prs)]
    random.Random(0).shuffle(ss)
    return ss[:limit] if limit else ss


def run_path(cfg: Config, reviewer: str, s: dict) -> pathlib.Path:
    """Where the run for sample `s` is stored."""
    return cfg.data / "runs" / reviewer / f"{s['pr']}-{s['commit'][:8]}.json"


def replay_one(cfg: Config, s: dict, reviewer: str) -> tuple[str, float]:
    """Run the reviewer on one sample; returns (status, cost)."""
    out = run_path(cfg, reviewer, s)
    with sample_workspace(cfg, s, "review") as (wt, base):
        r = run_reviewer(wt, cached_pr(cfg, s["pr"]), reviewer)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"pr": s["pr"], "commit": s["commit"], "base": base, **r}, indent=1))
    n = len(r["findings"]) if r["findings"] is not None else f"INVALID ({r['error']})"
    return f"{n} findings" + (f" DENIED {len(r['denials'])}" if r["denials"] else ""), r["cost"]


def replay(reviewer: str = DEFAULT_REVIEWER, split: str = "test", limit: int | None = 10, workers: int = 4,
           max_cost: float = 15.0, prs: list[int] | None = None, cfg: Config | None = None) -> float:
    """Run `reviewer` over samples of `split` not run yet, stopping at `max_cost`. Returns $ spent."""
    cfg = cfg or Config()
    rules = parse_reviewer(reviewer)[1]
    if rules:
        load_rules(rules)  # fail now, not once per sample
    ss = load_samples(cfg, split, limit, prs)
    todo = [s for s in ss if not run_path(cfg, reviewer, s).exists()]
    print(f"{reviewer} on {split}: {len(ss)} samples, {len(ss) - len(todo)} cached, {len(todo)} to run "
          f"(est ${len(todo) * EST_COST:.0f}, cap ${max_cost:.0f})", flush=True)
    _, spent = capped_map(lambda s: replay_one(cfg, s, reviewer), todo, workers, max_cost,
                          label=lambda s: f"#{s['pr']}-{s['commit'][:8]}")
    return spent

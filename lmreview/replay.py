"""Run a reviewer over samples, one per (PR, commit a human reviewed): historical splits and new PRs.

Splits (by PR creation date): train (distill only from here), test (compare versions), new (PRs
since 2026-11-01, filled by `sync`; the launch gate looks here; never distilled from).
Each run is saved to <data>/runs/<reviewer>/<pr>-<commit8>.json and reused if present.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

from .budget import capped_map
from .progress import note
from .config import Config
from .reviewer import DEFAULT_REVIEWER, load_rules, rulecheck_of, parse_reviewer, reviewer_context, rule_evidence, run_reviewer
from .workspace import cached_pr, sample_workspace

EST_COST = 1.2  # $/sample for a high-effort review, from earlier runs; used only for the estimate
EST_RC = 3.3    # with the rule check and vLLM context (v0c+pk8/pk9@high-rc: $3.0-3.5)


def _picked(s: dict, prs: list) -> bool:
    """`prs` entries: a PR number (all its samples) or "PR:commit-prefix" (one sample)."""
    for p in prs:
        n, _, c = str(p).partition(":")
        if s["pr"] == int(n) and s["commit"].startswith(c):
            return True
    return False


def load_samples(cfg: Config, split: str, limit: int | None, prs: list | None = None,
                 area: str | None = None) -> list[dict]:
    """Samples of `split` in a fixed random order (a hash of PR and commit, so adding or removing
    samples does not reorder the others), optionally only `prs`
    (PR numbers or "PR:commit") or PRs whose files touch `area`. Samples whose gold is only
    approvals are skipped unless named in `prs`."""
    ss = [json.loads(l) for l in (cfg.data / "dataset" / "samples.jsonl").open()]
    ss = [s for s in ss if s["split"] == split and (_picked(s, prs) if prs else not s.get("approval_only"))]
    if area:
        meta = {p["pr"]: p for p in map(json.loads, (cfg.data / "dataset" / "prs.jsonl").open())}
        ss = [s for s in ss if area in meta[s["pr"]]["areas"]]
    ss.sort(key=lambda s: hashlib.sha256(f"{s['pr']}-{s['commit']}".encode()).hexdigest())
    return ss[:limit] if limit else ss


def run_path(cfg: Config, reviewer: str, s: dict) -> pathlib.Path:
    """Where the run for sample `s` is stored."""
    return cfg.data / "runs" / reviewer / f"{s['pr']}-{s['commit'][:8]}.json"


def replay_one(cfg: Config, s: dict, reviewer: str) -> tuple[str, float]:
    """Run the reviewer on one sample; returns (status, cost)."""
    out = run_path(cfg, reviewer, s)
    with sample_workspace(cfg, s, "review", reviewer_context(reviewer)) as (wt, base):
        r = run_reviewer(wt, cached_pr(cfg, s["pr"], s["time"]), reviewer)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"pr": s["pr"], "commit": s["commit"], "base": base, **r}, indent=1))
    n = len(r["findings"]) if r["findings"] is not None else f"INVALID ({r['error']})"
    return f"{n} findings" + (f" DENIED {len(r['denials'])}" if r["denials"] else ""), r["cost"]


def replay(reviewer: str = DEFAULT_REVIEWER, split: str = "test", limit: int | None = 10, workers: int = 4,
           max_cost: float = 15.0, prs: list | None = None, area: str | None = None,
           cfg: Config | None = None) -> float:
    """Run `reviewer` over samples of `split` not run yet, stopping at `max_cost`. Returns $ spent."""
    cfg = cfg or Config()
    rules = parse_reviewer(reviewer)[1]
    if rules:
        load_rules(rules)  # fail now, not once per sample
    ss = load_samples(cfg, split, limit, prs, area)
    ev = rule_evidence(reviewer)
    leak = [s for s in ss if ev & set(s["gold_ids"])]
    if leak:  # its rulebook was distilled from these samples' own human comments
        note(f"skipping {len(leak)} samples whose comments the rulebook came from: "
              + ", ".join(f"#{s['pr']}-{s['commit'][:8]}" for s in leak))
        ss = [s for s in ss if s not in leak]
    todo = [s for s in ss if not run_path(cfg, reviewer, s).exists()]
    note(f"{reviewer} on {split}" + (f" ({area})" if area else "") + f": {len(ss)} samples, {len(ss) - len(todo)} cached, {len(todo)} to run "
          f"(est ${len(todo) * (EST_RC if rulecheck_of(reviewer) else EST_COST):.0f}, cap ${max_cost:.0f})")
    _, spent = capped_map(lambda s: replay_one(cfg, s, reviewer), todo, workers, max_cost,
                          label=lambda s: f"#{s['pr']}-{s['commit'][:8]}")
    return spent

"""`round`'s first step: which new training samples are worth reviewing.

Learning pays for a full review of every sample it reads. Most of what a review is for in a round is
the human points the reviewer misses, and how likely a point is to be missed shows before any review:
its type and severity (on 252 samples: nits 88% missed, minor change requests 56%, major 26%,
blockers 0%). So each new sample gets the sum, over its change-request and nit points, of the miss
rate of the point's kind, and only the top `keep` share of the new samples is reviewed. On the same 252
samples the top half held about 88% of the misses (counting points alone: 85%; a perfect ranking: 94%).

Points come from annotate (cached; judge would annotate the same samples anyway). Miss rates come from
the reviewer's own judged training runs where a kind has at least `min_points` points, else from the
defaults in config.toml. Samples the reviewer has already run on are not ranked: they pass through.

Only `round` uses this: a live review, vet's replays and eval pick their samples otherwise.
"""

from __future__ import annotations

import collections as C
import datetime as dt
import json
import math

from .annotate import annotate, points
from .budget import capped_map
from .config import Config
from .progress import note
from .settings import get

WANT = ("change_request", "nit")  # the point types a round learns from (score.WANT)


def kind(p: dict) -> str:
    """A point's kind for the miss rate: "<type>/<severity>"."""
    return f"{p.get('type')}/{p.get('severity')}"


def miss_rates(cfg: Config, reviewer: str) -> dict[str, float]:
    """Share of points of each kind that `reviewer` missed in its judged training runs; a kind with fewer
    than `min_points` judged points keeps its default from config.toml ([select.weights])."""
    rates = dict(get("select", "weights"))
    seen: dict[str, list[int]] = C.defaultdict(lambda: [0, 0])  # kind -> [missed, all]
    d = cfg.data / "scores" / reviewer
    for f in d.glob("*.json") if d.exists() else []:
        for h in json.loads(f.read_text()).get("human") or []:
            if h.get("type") in WANT:
                seen[kind(h)][0] += not h.get("matched_ai")
                seen[kind(h)][1] += 1
    n_min = int(get("select", "min_points"))
    rates |= {k: m / n for k, (m, n) in seen.items() if n >= n_min}
    return rates


def select(specs: list[str], reviewer: str, max_cost: float, cfg: Config) -> tuple[list[str], float]:
    """Keep the samples of `specs` ("PR:commit8") worth reviewing with `reviewer`; see the module docstring.

    Returns:
        (the kept specs in the given order: every sample already run, plus the top share of the new
         ones; a new sample that could not be annotated within `max_cost` is left out), cost.
    """
    from .replay import run_path
    from .reviewer import rule_evidence
    from .score import load_gold
    ss, cm = load_gold(cfg)

    def sample(spec: str) -> dict:
        pr, c = spec.split(":")
        return next(s for (p, cc), s in ss.items() if p == int(pr) and cc.startswith(c))

    ev = rule_evidence(reviewer)  # replay skips samples whose comments the book came from: never select them
    leak = [x for x in specs if ev & set(sample(x)["gold_ids"])]
    specs = [x for x in specs if x not in leak]
    if leak:
        note(f"select: {len(leak)} sample(s) skipped, the book was distilled from their comments", "dim")
    new = [x for x in specs if not run_path(cfg, reviewer, sample(x)).exists()]
    if not new:
        note("select: no new samples (all already reviewed)", "dim")
        return specs, 0.0

    def ann(spec: str) -> tuple[tuple[str, list[dict]], float]:
        s = sample(spec)
        gold = [cm[i] for i in s["gold_ids"]]
        a = annotate(cfg, s, gold, str(get("annotate", "effort")))
        return (spec, points(a, gold)), a["cost"]
    res, cost = capped_map(ann, new, 4, max_cost, label=lambda x: f"annotate #{x}", est=0.15)
    pts = dict(res)
    rates = miss_rates(cfg, reviewer)
    score = {x: sum(rates.get(kind(p), 0.5) for p in ps if p.get("type") in WANT) for x, ps in pts.items()}
    n_keep = math.ceil(len(new) * float(get("select", "keep")))
    ranked = sorted((x for x in score if score[x] > 0), key=lambda x: -score[x])
    keep = set(ranked[:n_keep])
    note(f"select: {len(keep)} of {len(new)} new samples (top {get('select', 'keep')}; "
         f"{sum(v == 0 for v in score.values())} with nothing to learn, {len(new) - len(pts)} not annotated "
         f"within the cap); annotate ${cost:.2f}")
    for x in sorted(score, key=lambda x: -score[x]):
        note(f"    {'keep' if x in keep else 'skip'} #{x}  score {score[x]:.2f}  "
             f"({len([p for p in pts[x] if p.get('type') in WANT])} points)", "dim")
    log = cfg.data / "select" / "log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as f:
        f.write(json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                            "reviewer": reviewer, "rates": rates, "keep": float(get("select", "keep")),
                            "scores": score, "kept": sorted(keep), "cost": cost}) + "\n")
    return [x for x in specs if x not in new or x in keep], cost

"""`lmreview eval`: one report for a reviewer.

  1. judge runs not judged yet (paid, capped) and score them        -> reports/score_<r>.md
  2. human-only rate on change requests, per split and area         (the pre-launch target)
  3. passive signals from git history (free)                        -> reports/signals_<r>.md
  4. with `vs`: per-comment flips against another reviewer (free)   -> reports/compare_<vs>_vs_<r>.md
Summary -> reports/eval_<r>.md
"""

from __future__ import annotations

import collections as C

from .compare import compare
from .config import Config
from .score import REPORTS, load_gold, score
from .signals import signals


def human_only_table(runs: list[dict], res: list[dict], cfg: Config) -> list[str]:
    """Rows: split / area -> human change requests, how many the AI missed (human-only), rate."""
    ss, cm = load_gold(cfg)
    tot, miss = C.Counter(), C.Counter()
    for r, s in zip(runs, res):
        split = ss[(r["pr"], r["commit"])]["split"]
        for h in s["human"]:
            if h["type"] != "change_request":
                continue
            c = cm[s["gold_ids"][h["id"]]]
            area = c.get("area") or "(overall review)"
            for k in ((split, "all"), (split, area)):
                tot[k] += 1
                miss[k] += not h["matched_ai"]
    rows = ["| split | area | human change requests | human-only (AI missed) | rate |", "| --- | --- | --- | --- | --- |"]
    for k in sorted(tot, key=lambda k: (k[0], k[1] != "all", -tot[k])):
        rows.append(f"| {k[0]} | {k[1]} | {tot[k]} | {miss[k]} | {miss[k] / tot[k]:.0%} |")
    return rows


def evaluate(reviewer: str, vs: str | None = None, workers: int = 4, judge_effort: str = "high",
             max_cost: float = 10.0, cfg: Config | None = None) -> str:
    """Write reports/eval_<reviewer>.md and return it."""
    cfg = cfg or Config()
    from .score import judge  # judged results are cached, so score() below re-reads them for free
    runs, res = judge(reviewer, workers, judge_effort, max_cost, cfg)
    L = [f"# Eval: {reviewer}", "", "## Score (vs human reviews on the same commit)", "",
         *score(reviewer, workers, judge_effort, 0.0, cfg).splitlines()[2:], "",
         "## Human-only on change requests (pre-launch target: lower is better)", "",
         *human_only_table(runs, res, cfg), "",
         "## Passive signals", "", *signals(reviewer, cfg).splitlines()[2:]]
    if vs:
        L += ["", f"## Flips vs {vs}", "", *compare(vs, reviewer, cfg).splitlines()[2:]]
    L += ["", f"Details: score_{reviewer}.md, signals_{reviewer}.md" + (f", compare_{vs}_vs_{reviewer}.md" if vs else "")]
    text = "\n".join(L) + "\n"
    (REPORTS / f"eval_{reviewer}.md").write_text(text)
    return text

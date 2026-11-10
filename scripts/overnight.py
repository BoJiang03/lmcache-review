"""Run a reviewer over train in small batches, within the Claude subscription's 5-hour limit.

Before each batch it reads the account's usage (the same endpoint Claude Code uses). If the next batch
would push the 5-hour window past --stop-at percent, it sleeps until the window resets, then goes on.
It stops for good when the weekly usage reaches --weekly-cap, or when every sample is done. Each batch is
judged (j2) right after it runs, so the misses are ready to analyse.

Usage: nohup python3 scripts/overnight.py --reviewer v0b+team-v1@high > data/overnight/run.log 2>&1 &
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lmreview.config import Config  # noqa: E402
from lmreview.replay import load_samples, replay, run_path  # noqa: E402
from lmreview.score import judge  # noqa: E402

PT = dt.timezone(dt.timedelta(hours=-8))


def now() -> str:
    """Current Pacific time, for log lines."""
    return dt.datetime.now(PT).strftime("%m-%d %H:%M PT")


def usage() -> dict | None:
    """{"five": percent, "five_reset": datetime, "week": percent} for this account, or None on failure."""
    try:
        tok = json.load(open(os.path.expanduser("~/.claude/.credentials.json")))["claudeAiOauth"]["accessToken"]
        req = urllib.request.Request("https://api.anthropic.com/api/oauth/usage", headers={
            "Authorization": f"Bearer {tok}", "anthropic-beta": "oauth-2025-04-20", "User-Agent": "claude-cli"})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        return {"five": float(d["five_hour"]["utilization"]),
                "five_reset": dt.datetime.fromisoformat(d["five_hour"]["resets_at"]) if d["five_hour"].get("resets_at")
                else dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5),  # no use yet in this window
                "week": float(d["seven_day"]["utilization"])}
    except Exception as e:  # expired token, network: the caller retries
        print(f"[{now()}] usage check failed: {e}", flush=True)
        return None


def refresh_login() -> None:
    """One tiny claude call; it refreshes the OAuth token in ~/.claude/.credentials.json."""
    env = {k: v for k, v in os.environ.items() if not (k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_PID"))}
    subprocess.run(["claude", "-p", "Say OK.", "--tools", "", "--effort", "low"], env=env,
                   capture_output=True, timeout=300)


def main() -> None:
    """Run batches until train is done or the weekly cap is reached; sleep through 5-hour limits."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--split", default="train")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--stop-at", type=float, default=95.0, help="5-hour usage percent not to cross")
    ap.add_argument("--weekly-cap", type=float, default=50.0, help="stop for good at this weekly percent")
    ap.add_argument("--max-cost", type=float, default=12.0, help="USD cap per batch (review + judge)")
    a = ap.parse_args()
    cfg = Config()
    total = len(load_samples(cfg, a.split, None))
    deltas, fails = [7.0], 0  # 5-hour percent used by recent batches; the next batch is assumed as costly as the worst
    while True:
        step = max(deltas)
        u = usage()
        if u is None:
            fails += 1
            if fails % 3 == 0:
                refresh_login()
            time.sleep(600)
            continue
        fails = 0
        done = sum(run_path(cfg, a.reviewer, s).exists() for s in load_samples(cfg, a.split, None))
        print(f"[{now()}] 5h {u['five']:.0f}%  week {u['week']:.0f}%  done {done}/{total}  "
              f"(~{step:.1f}% per batch)", flush=True)
        if done >= total:
            print(f"[{now()}] all {total} samples done", flush=True)
            return
        if u["week"] >= a.weekly_cap:
            print(f"[{now()}] weekly usage {u['week']:.0f}% >= cap {a.weekly_cap:.0f}%: stopping", flush=True)
            return
        if u["five"] + step > a.stop_at:
            wake = u["five_reset"] + dt.timedelta(minutes=3)
            secs = max(60.0, (wake - dt.datetime.now(dt.timezone.utc)).total_seconds())
            print(f"[{now()}] next batch would cross {a.stop_at:.0f}%: sleeping until "
                  f"{wake.astimezone(PT).strftime('%m-%d %H:%M PT')}", flush=True)
            time.sleep(secs)
            continue
        before = u["five"]
        spent = replay(a.reviewer, a.split, done + a.batch, workers=a.batch, max_cost=a.max_cost)
        judge(a.reviewer, workers=a.batch, max_cost=a.max_cost)
        after = usage()
        if after and after["five"] >= before:  # same window: measure what one batch costs
            deltas = (deltas + [after["five"] - before])[-5:]
        print(f"[{now()}] batch done: review ${spent:.2f}; 5h {before:.0f}% -> "
              f"{after['five'] if after else '?'}%", flush=True)


if __name__ == "__main__":
    main()

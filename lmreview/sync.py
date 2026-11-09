"""`lmreview sync`: bring the dataset up to date with GitHub. Read-only on GitHub; no LLM.

  1. list PRs updated since the last sync (created on/after the dataset start) and re-fetch them
  2. git fetch dev and every commit the reviews refer to
  3. rebuild prs.jsonl / comments.jsonl / samples.jsonl (PRs created since 2026-11-01 are split "new")
"""

from __future__ import annotations

import collections as C
import datetime as dt
import json
import pathlib
import subprocess
import sys

from .config import Config
from .github import PR_Q, REPO_NAME, REPO_OWNER, gh_graphql

ROOT = pathlib.Path(__file__).resolve().parent.parent
START = "2026-05-01"  # dataset start (PR creation date)
SEARCH_Q = """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest { number } }
  }
}"""


def updated_prs(since: str) -> list[int]:
    """PRs created on/after START and updated on/after `since` (ISO date or time)."""
    q = f"repo:{REPO_OWNER}/{REPO_NAME} is:pr created:>={START} updated:>={since}"
    nums, after = set(), None
    while True:
        d = gh_graphql(SEARCH_Q, q=q, after=after)["search"]
        nums.update(n["number"] for n in d["nodes"] if n)
        if not d["pageInfo"]["hasNextPage"]:
            return sorted(nums)
        after = d["pageInfo"]["endCursor"]


def fetch(cfg: Config, n: int) -> None:
    """(Re-)fetch PR `n` into <data>/raw/pr/<n>.json."""
    pr = gh_graphql(PR_Q, owner=REPO_OWNER, name=REPO_NAME, n=n)["repository"]["pullRequest"]
    pr["_fetched_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    path = cfg.data / "raw" / "pr" / f"{n}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(pr))
    tmp.rename(path)


def sync(since: str | None = None, cfg: Config | None = None) -> str:
    """Run the three steps; returns a one-paragraph summary."""
    cfg = cfg or Config()
    state = cfg.data / "raw" / "sync_state.json"
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if since is None:
        if state.exists():
            since = json.loads(state.read_text())["last"]
        else:  # first sync: from the oldest fetch time in the raw data
            since = min(json.loads(p.read_text())["_fetched_at"] for p in (cfg.data / "raw" / "pr").glob("*.json"))
        since = since[:19].rstrip("Z")
    nums = updated_prs(since)
    print(f"{len(nums)} PRs updated since {since}", flush=True)
    for i, n in enumerate(nums, 1):
        try:
            fetch(cfg, n)
        except Exception as e:  # keep going
            print(f"  FAIL #{n}: {e}", flush=True)
        if i % 50 == 0:
            print(f"  {i}/{len(nums)}", flush=True)
    subprocess.run(["git", "-C", str(cfg.repo), "fetch", "-q", "origin", "dev"], check=True)
    for script in ("fetch_commits.py", "derive.py", "samples.py"):
        subprocess.run([sys.executable, str(ROOT / "src" / script)], check=True, stdout=subprocess.DEVNULL)
    state.write_text(json.dumps({"last": now}))
    ss = [json.loads(l) for l in (cfg.data / "dataset" / "samples.jsonl").open()]
    return f"synced {len(nums)} PRs; samples by split: {dict(C.Counter(s['split'] for s in ss))}"

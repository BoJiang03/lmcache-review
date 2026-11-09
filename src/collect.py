"""Collect raw PR review data for LMCache/LMCache via the GitHub GraphQL API.

Step 1 (list):  every PR created in [--since, --until], via search sliced by month.
Step 2 (fetch): one GraphQL query per PR -> data/raw/pr/<N>.json (resumable).

Uses the `gh` CLI for auth. Read-only.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lmreview.github import PR_Q, REPO_NAME, REPO_OWNER, gh_graphql  # noqa: E402
RAW = ROOT / "data" / "raw"

SEARCH_Q = """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 100, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest { number createdAt } }
  }
}"""

def month_slices(since: dt.date, until: dt.date) -> list[tuple[str, str]]:
    """Split [since, until] into calendar-month ranges for the 1000-result search cap."""
    out, cur = [], since
    while cur <= until:
        nxt = (cur.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        end = min(nxt - dt.timedelta(days=1), until)
        out.append((cur.isoformat(), end.isoformat()))
        cur = nxt
    return out


def list_prs(since: dt.date, until: dt.date) -> list[int]:
    """Return numbers of all PRs created within [since, until]."""
    nums: set[int] = set()
    for a, b in month_slices(since, until):
        q = f"repo:{REPO_OWNER}/{REPO_NAME} is:pr created:{a}..{b}"
        after = None
        while True:
            d = gh_graphql(SEARCH_Q, q=q, after=after)["search"]
            nums.update(n["number"] for n in d["nodes"] if n)
            if not d["pageInfo"]["hasNextPage"]:
                break
            after = d["pageInfo"]["endCursor"]
        print(f"  {a}..{b}: total so far {len(nums)} (search count {d['issueCount']})", flush=True)
    return sorted(nums)


def fetch_pr(n: int) -> str:
    """Fetch one PR into data/raw/pr/<n>.json unless already present."""
    path = RAW / "pr" / f"{n}.json"
    if path.exists():
        return "cached"
    pr = gh_graphql(PR_Q, owner=REPO_OWNER, name=REPO_NAME, n=n)["repository"]["pullRequest"]
    pr["_fetched_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(pr))
    tmp.rename(path)
    return "fetched"


def main() -> None:
    """Entry point: list PRs, then fetch each one with a small thread pool."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-05-01")
    ap.add_argument("--until", default="2026-11-06")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    (RAW / "pr").mkdir(parents=True, exist_ok=True)

    lst = RAW / "pr_list.json"
    if lst.exists():
        nums = json.loads(lst.read_text())
    else:
        nums = list_prs(dt.date.fromisoformat(args.since), dt.date.fromisoformat(args.until))
        lst.write_text(json.dumps(nums))
    print(f"{len(nums)} PRs in window", flush=True)

    done = fails = 0
    with cf.ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(fetch_pr, n): n for n in nums}
        for f in cf.as_completed(futs):
            try:
                f.result()
            except Exception as e:  # keep going; failures are listed at the end
                fails += 1
                print(f"  FAIL #{futs[f]}: {e}", file=sys.stderr, flush=True)
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(nums)} done, {fails} failed", flush=True)
    print(f"finished: {done} PRs, {fails} failed", flush=True)


if __name__ == "__main__":
    main()

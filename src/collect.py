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
import subprocess
import sys
import time

REPO_OWNER, REPO_NAME = "LMCache", "LMCache"
ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

SEARCH_Q = """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 100, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest { number createdAt } }
  }
}"""

AUTHOR = "author { login __typename }"

PR_Q = f"""
query($owner: String!, $name: String!, $n: Int!) {{
  repository(owner: $owner, name: $name) {{
    pullRequest(number: $n) {{
      number title body state isDraft createdAt closedAt mergedAt
      {AUTHOR} authorAssociation
      baseRefName baseRefOid headRefOid
      mergedBy {{ login }}
      additions deletions changedFiles
      labels(first: 30) {{ nodes {{ name }} }}
      files(first: 100) {{ pageInfo {{ hasNextPage }} nodes {{ path additions deletions changeType }} }}
      commits(first: 100) {{ totalCount pageInfo {{ hasNextPage }}
        nodes {{ commit {{ oid committedDate authoredDate messageHeadline
                          parents(first: 3) {{ totalCount }} }} }} }}
      reviews(first: 100) {{ totalCount pageInfo {{ hasNextPage }}
        nodes {{ databaseId {AUTHOR} state body submittedAt commit {{ oid }} }} }}
      reviewThreads(first: 100) {{ totalCount pageInfo {{ hasNextPage }}
        nodes {{ isResolved isOutdated path diffSide line originalLine startLine originalStartLine
                 resolvedBy {{ login }}
                 comments(first: 50) {{ totalCount
                   nodes {{ databaseId {AUTHOR} body createdAt path diffHunk
                            line originalLine startLine originalStartLine outdated
                            commit {{ oid }} originalCommit {{ oid }}
                            replyTo {{ databaseId }}
                            pullRequestReview {{ databaseId state }} }} }} }} }}
      comments(first: 100) {{ totalCount pageInfo {{ hasNextPage }}
        nodes {{ databaseId {AUTHOR} body createdAt }} }}
      timelineItems(first: 50, itemTypes: [CROSS_REFERENCED_EVENT]) {{
        nodes {{ ... on CrossReferencedEvent {{ createdAt
          source {{ ... on PullRequest {{ number title createdAt mergedAt }}
                    ... on Issue {{ number title createdAt }} }} }} }} }}
    }}
  }}
}}"""


def gh_graphql(query: str, **variables: object) -> dict:
    """Run one GraphQL query through `gh api graphql`, retrying transient failures.

    Args:
        query: GraphQL document.
        **variables: GraphQL variables; ints are passed with -F, strings with -f.

    Returns:
        The decoded `data` object.

    Raises:
        RuntimeError: if the query still fails after retries.
    """
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        if v is None:
            continue
        cmd += (["-F", f"{k}={v}"] if isinstance(v, int) else ["-f", f"{k}={v}"])
    last = ""
    for attempt in range(6):
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode == 0:
            out = json.loads(p.stdout)
            if "errors" not in out:
                return out["data"]
            last = json.dumps(out["errors"])[:500]
        else:
            last = (p.stderr or p.stdout)[:500]
        if "could not resolve" in last.lower() or "NOT_FOUND" in last:
            break
        if "rate limit" in last.lower():
            time.sleep(60)
        else:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"graphql failed: {last}")


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

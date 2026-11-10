"""GitHub access through the `gh` CLI (read-only)."""

from __future__ import annotations

import json
import subprocess
import time

REPO_OWNER, REPO_NAME = "LMCache", "LMCache"

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


def fetch_pr(n: int) -> dict:
    """Fetch one PR with everything the reviewer and the dataset need."""
    return gh_graphql(PR_Q, owner=REPO_OWNER, name=REPO_NAME, n=n)["repository"]["pullRequest"]


# Edit history, so a replay can show text as it was at review time (see lmreview/asof.py).
# Pass 1 finds which texts were ever edited; pass 2 pulls the versions of just those.
EDITED_Q = """
query($owner: String!, $name: String!, $n: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $n) {
      lastEditedAt
      userContentEdits(first: 100) { totalCount nodes { editedAt deletedAt diff } }
      timelineItems(first: 50, itemTypes: [RENAMED_TITLE_EVENT]) {
        nodes { ... on RenamedTitleEvent { createdAt previousTitle currentTitle } } }
      reviews(first: 100) { nodes { id databaseId lastEditedAt } }
      reviewThreads(first: 100) { nodes { comments(first: 50) { nodes { id databaseId lastEditedAt } } } }
      comments(first: 100) { nodes { id databaseId lastEditedAt } }
    }
  }
}"""

VERSIONS_Q = """
query {
  nodes(ids: %s) {
    id
    ... on Comment { userContentEdits(first: 100) { totalCount nodes { editedAt deletedAt diff } } }
  }
}"""


def _versions(conn: dict) -> list[dict]:
    """[{at, text}] oldest first; text None where GitHub no longer has it. Raises if truncated."""
    if conn["totalCount"] > len(conn["nodes"]):
        raise RuntimeError(f"edit history truncated ({conn['totalCount']} edits)")
    return [{"at": e["editedAt"], "text": None if e["deletedAt"] else e["diff"]} for e in reversed(conn["nodes"])]


def fetch_edits(n: int) -> dict:
    """Edit history of PR `n`'s title, description, reviews and comments.

    Returns:
        {"body": [{at, text}], "renames": [{at, from, to}],
         "nodes": {"review:<databaseId>" | "thread:<databaseId>" | "comment:<databaseId>": [{at, text}]}}
        Versions are oldest first; the first is the original text. Unedited texts are absent.
    """
    pr = gh_graphql(EDITED_Q, owner=REPO_OWNER, name=REPO_NAME, n=n)["repository"]["pullRequest"]
    keyed = [(f"review:{r['databaseId']}", r) for r in pr["reviews"]["nodes"]]
    keyed += [(f"thread:{c['databaseId']}", c) for t in pr["reviewThreads"]["nodes"] for c in t["comments"]["nodes"]]
    keyed += [(f"comment:{c['databaseId']}", c) for c in pr["comments"]["nodes"]]
    edited = {x["id"]: k for k, x in keyed if x["lastEditedAt"]}
    nodes, ids = {}, list(edited)
    for i in range(0, len(ids), 50):
        for x in gh_graphql(VERSIONS_Q % json.dumps(ids[i:i + 50]))["nodes"]:
            nodes[edited[x["id"]]] = _versions(x["userContentEdits"])
    renames = [{"at": e["createdAt"], "from": e["previousTitle"], "to": e["currentTitle"]}
               for e in pr["timelineItems"]["nodes"] if e]
    return {"body": _versions(pr["userContentEdits"]), "renames": renames, "nodes": nodes}


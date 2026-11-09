"""Fetch every commit the dataset refers to (often force-pushed away) into the local clone.

GitHub serves unadvertised commits by SHA, so `git fetch origin <sha>` recovers commits
that review comments were made on even after the PR branch was force-pushed.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "pr"
GIT = ROOT / "data" / "LMCache"
BATCH = 40


def have(oid: str) -> bool:
    """True if the commit exists in the local clone."""
    return subprocess.run(["git", "-C", str(GIT), "cat-file", "-e", f"{oid}^{{commit}}"],
                          capture_output=True).returncode == 0


def wanted() -> set[str]:
    """All commit oids referenced by raw PRs: heads, review commits, comment commits."""
    oids: set[str] = set()
    for f in RAW.glob("*.json"):
        pr = json.loads(f.read_text())
        oids.add(pr["headRefOid"])
        for r in pr["reviews"]["nodes"]:
            if r.get("commit"):
                oids.add(r["commit"]["oid"])
        for t in pr["reviewThreads"]["nodes"]:
            for c in t["comments"]["nodes"]:
                for k in ("commit", "originalCommit"):
                    if c.get(k):
                        oids.add(c[k]["oid"])
    return oids


def main() -> None:
    """Fetch missing commits in batches; report what could not be recovered."""
    missing = sorted(o for o in wanted() if not have(o))
    print(f"missing before: {len(missing)}", flush=True)
    for i in range(0, len(missing), BATCH):
        chunk = missing[i:i + BATCH]
        p = subprocess.run(["git", "-C", str(GIT), "fetch", "-q", "origin", *chunk],
                           capture_output=True, text=True)
        if p.returncode != 0:  # one bad sha fails the batch; retry one by one
            for o in chunk:
                subprocess.run(["git", "-C", str(GIT), "fetch", "-q", "origin", o],
                               capture_output=True)
        print(f"  {min(i + BATCH, len(missing))}/{len(missing)}", flush=True)
    still = [o for o in missing if not have(o)]
    (ROOT / "data" / "unrecoverable_commits.txt").write_text("\n".join(still))
    print(f"unrecoverable: {len(still)}")


if __name__ == "__main__":
    main()

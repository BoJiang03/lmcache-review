"""One-off (2026-11-12): start lmreview/state from rulebook pk9 and seed the ledger from its history.

- v0001 = rules/pk9.jsonl (its side-effect vet was never run; noted in v0001.meta.json).
- Comments that are evidence of a pk9 entry: resolved (legacy: written before vet recorded per-comment results).
- Comments distill processed into pk9 or its ancestors (pk9.meta.json "seen") without an entry: not_rulable (legacy).
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from lmreview import state  # noqa: E402
from lmreview.config import Config  # noqa: E402
from lmreview.distill import book_meta  # noqa: E402
from lmreview.score import load_gold  # noqa: E402

state.init("pk9", note="pk9 (pk8 + train misses 23-27); effect vetted on its sources, side effects never vetted")
ss, cm = load_gold(Config())
where = {}
for (pr, commit), s in ss.items():
    for c in s["gold_ids"]:
        where.setdefault(int(c), (pr, commit))
rules = state.load_book("v0001")
ev = {int(e): r["id"] for r in rules for e in r.get("evidence") or []}
rows = {}
for c, rid in ev.items():
    if c in where:
        rows[c] = {"comment": c, "pr": where[c][0], "commit": where[c][1], "status": "resolved", "reviewer": None,
                   "tries": [], "resolved_by": {"book": "v0001", "entry": rid, "legacy": True}}
for c in map(int, book_meta("pk9")["seen"]):
    if c in where and c not in rows:
        rows[c] = {"comment": c, "pr": where[c][0], "commit": where[c][1], "status": "not_rulable", "reviewer": None,
                   "tries": [], "note": "legacy: processed by distill before the ledger; no entry kept"}
state.save_ledger(rows)
state.log("migrate", source="pk9", resolved=sum(r["status"] == "resolved" for r in rows.values()),
          not_rulable=sum(r["status"] == "not_rulable" for r in rows.values()))
print(state.status())

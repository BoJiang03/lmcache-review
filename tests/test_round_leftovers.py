"""round distills the comments still to_distill from earlier rounds, on any PR. No LLM calls.

Run: python3 tests/test_round_leftovers.py (or pytest)."""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile

TMP = tempfile.gettempdir()
os.environ["LMREVIEW_STATE"] = tempfile.mkdtemp(prefix="lmr-state-", dir=TMP)  # before importing state
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lmreview import replay as replay_mod, state  # noqa: E402
from lmreview.config import Config  # noqa: E402


def test_round_takes_leftovers() -> None:
    """A round on PR 1 also distills the to_distill row left on PR 9; a resolved row on PR 8 is not pulled in."""
    cfg = Config(data=pathlib.Path(tempfile.mkdtemp(prefix="lmr-data-", dir=TMP)))
    state.save_ledger({
        91: {"comment": 91, "pr": 9, "commit": "9" * 40, "status": "to_distill", "tries": []},
        81: {"comment": 81, "pr": 8, "commit": "8" * 40, "status": "resolved", "tries": []}})
    seen = []
    patched = {"judge": lambda *a, **k: "judged", "confirm_misses": lambda *a, **k: ("confirmed", 0.0),
               "requeue_parked": lambda **k: set(), "pick_samples": lambda prs, cfg=None: prs, "compress_if_big": lambda *a, **k: [],
               "distill_step": lambda prs, **k: seen.append(set(prs)) or "distilled", "status": lambda: ""}
    old = {k: getattr(state, k) for k in patched} | {"replay": replay_mod.replay}
    for k, v in patched.items():
        setattr(state, k, v)
    replay_mod.replay = lambda *a, **k: 0.0
    try:
        state.round_(["1:" + "a" * 8], 0, 0, 0, 0, confirm_cost=0, cfg=cfg)
    finally:
        replay_mod.replay = old.pop("replay")
        for k, v in old.items():
            setattr(state, k, v)
    assert seen == [{1, 9}], seen


if __name__ == "__main__":
    test_round_takes_leftovers()
    print("ok")

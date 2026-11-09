"""Where things live. Defaults match this checkout; override with env vars or a Config()."""

from __future__ import annotations

import dataclasses
import os
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent


@dataclasses.dataclass(frozen=True)
class Config:
    """Paths used by the library.

    Attributes:
        repo: a full LMCache clone with an `origin` remote (snapshots and diffs come from here).
        sandbox: scratch dir for agent workspaces; must not contain anything the agent shouldn't see.
        data: dataset / runs / scores dir (eval only).
    """

    repo: pathlib.Path = pathlib.Path(os.environ.get("LMREVIEW_REPO", _ROOT / "data" / "LMCache"))
    sandbox: pathlib.Path = pathlib.Path(os.environ.get("LMREVIEW_SANDBOX", "/raid/bo/review-sandbox"))
    data: pathlib.Path = pathlib.Path(os.environ.get("LMREVIEW_DATA", _ROOT / "data"))


PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"
RULES = _ROOT / "rules"  # distilled rulebooks: rules/<name>.jsonl (versioned in git)

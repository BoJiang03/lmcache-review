"""Where things live. Override with env vars or a Config().

Defaults: a checkout of this repo uses its data/ dir (eval data, clones); an installed copy uses
~/.cache/lmreview/ and clones LMCache (and vLLM, if a prompt needs it) there on first use.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CACHE = pathlib.Path(os.environ.get("XDG_CACHE_HOME", pathlib.Path.home() / ".cache")) / "lmreview"


def _default(env: str, local: pathlib.Path, cached: pathlib.Path) -> pathlib.Path:
    """$env if set, else `local` if it exists (this checkout), else `cached`."""
    if os.environ.get(env):
        return pathlib.Path(os.environ[env])
    return local if local.exists() else cached


@dataclasses.dataclass(frozen=True)
class Config:
    """Paths used by the library.

    Attributes:
        repo: a full LMCache clone with an `origin` remote (snapshots and diffs come from here);
            cloned on first use if missing.
        sandbox: scratch dir for agent workspaces; must not contain anything the agent shouldn't see.
        data: dataset / runs / scores dir (eval only).
        vllm: a vLLM clone with an `origin` remote (for prompts that declare `context: vllm`);
            cloned on first use if missing.
    """

    repo: pathlib.Path = _default("LMREVIEW_REPO", _ROOT / "data" / "LMCache", _CACHE / "LMCache")
    sandbox: pathlib.Path = pathlib.Path(os.environ.get("LMREVIEW_SANDBOX", _CACHE / "sandbox"))
    data: pathlib.Path = _default("LMREVIEW_DATA", _ROOT / "data", _CACHE / "data")
    vllm: pathlib.Path = _default("LMREVIEW_VLLM", _ROOT / "data" / "vllm", _CACHE / "vllm")


PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"
RULES = pathlib.Path(__file__).resolve().parent / "rules"  # distilled rulebooks, versioned in git
REPO_URLS = {"repo": "https://github.com/LMCache/LMCache.git", "vllm": "https://github.com/vllm-project/vllm.git"}

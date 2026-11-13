"""Where things live: env vars, then [paths] in config.toml (see settings.py), then the defaults below.

Defaults: a checkout of this repo uses its data/ dir (eval data, clones); an installed copy uses
~/.cache/lmreview/ and clones LMCache (and vLLM, if a prompt needs it) there on first use.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib

from .settings import get

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CACHE = pathlib.Path(os.environ.get("XDG_CACHE_HOME", pathlib.Path.home() / ".cache")) / "lmreview"


def _setting(env: str, key: str) -> str:
    """$env if set, else [paths] `key` of the settings ("" = not set), with {uid} filled in."""
    return (os.environ.get(env) or str(get("paths", key))).replace("{uid}", str(os.getuid()))


def _default(env: str, key: str, local: pathlib.Path, cached: pathlib.Path) -> pathlib.Path:
    """$env or the setting if set, else `local` if it exists (this checkout), else `cached`."""
    if v := _setting(env, key):
        return pathlib.Path(v)
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

    repo: pathlib.Path = _default("LMREVIEW_REPO", "repo", _ROOT / "data" / "LMCache", _CACHE / "LMCache")
    # outside $HOME and /tmp: an agent with a shell is denied reading those (see llm.sandbox_settings)
    sandbox: pathlib.Path = pathlib.Path(_setting("LMREVIEW_SANDBOX", "sandbox") or f"/var/tmp/lmreview-{os.getuid()}/sandbox")
    data: pathlib.Path = _default("LMREVIEW_DATA", "data", _ROOT / "data", _CACHE / "data")
    vllm: pathlib.Path = _default("LMREVIEW_VLLM", "vllm", _ROOT / "data" / "vllm", _CACHE / "vllm")


PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"
RULES = pathlib.Path(__file__).resolve().parent / "rules"  # distilled rulebooks, versioned in git
REPO_URLS = {"repo": "https://github.com/LMCache/LMCache.git", "vllm": "https://github.com/vllm-project/vllm.git"}

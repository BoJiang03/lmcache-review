"""lmreview's settings: lmreview/config.toml, then the keys set in the file $LMREVIEW_CONFIG."""

from __future__ import annotations

import copy
import functools
import os
import pathlib

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # Python 3.10: the vendored copy of the same parser
    from ._vendor import tomli as tomllib

DEFAULTS = pathlib.Path(__file__).resolve().parent / "config.toml"


def _merge(base: dict, over: dict, where: str = "") -> dict:
    """`over` on top of `base`; a key `base` does not have is an error."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k not in base:
            raise KeyError(f"unknown setting {where}{k} in {os.environ.get('LMREVIEW_CONFIG')}")
        out[k] = _merge(base[k], v, f"{where}{k}.") if isinstance(base[k], dict) else v
    return out


@functools.lru_cache(maxsize=None)
def _load(user: str | None) -> dict:
    s = tomllib.loads(DEFAULTS.read_text())
    return _merge(s, tomllib.loads(pathlib.Path(user).read_text())) if user else s


def settings() -> dict:
    """All settings as nested dicts (see config.toml). Do not modify the result."""
    return _load(os.environ.get("LMREVIEW_CONFIG") or None)


def get(section: str, key: str) -> object:
    """One setting, e.g. get("review", "effort")."""
    return settings()[section][key]

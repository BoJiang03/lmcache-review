"""The project under review: [project] in config.toml. The built-in prompts were written for LMCache;
`localize` rewrites their mentions of it for another project, and leaves them byte for byte as they are
for LMCache (so prompt ids, and every cached run and score, stay valid)."""

from __future__ import annotations

import re

from .settings import get

LMCACHE, LMCACHE_ABOUT = "LMCache", "a KV-cache layer for LLM inference engines such as vLLM"
NAME, ABOUT = str(get("project", "name")), str(get("project", "about"))


def _phrase(s: str) -> str:
    """A regex for `s` that allows any whitespace (a line break) between its words."""
    return r"\s+".join(map(re.escape, s.split()))


def localize(text: str, name: str | None = None, about: str | None = None) -> str:
    """`text` with LMCache's name and description replaced by the project's."""
    name, about = name or NAME, ABOUT if about is None else about
    if (name, about) == (LMCACHE, LMCACHE_ABOUT):
        return text
    text = re.sub(_phrase(f"LMCache ({LMCACHE_ABOUT})"), f"{name} ({about})" if about else name, text)
    text = re.sub(r"\s*" + _phrase(f"(LMCache is {LMCACHE_ABOUT})"), f" ({name} is {about})" if about else "", text)
    text = re.sub(r"\s*" + _phrase(f"({LMCACHE_ABOUT})"), f" ({about})" if about else "", text)  # "the LMCache team (a ...)"
    text = text.replace('"lmcache/..."', '"src/..."')
    return re.sub(r"\bLMCache\b", name, text)


def localize_module(ns: dict) -> None:
    """Localize every module-level prompt (an upper-case str constant) of a module, in place."""
    if (NAME, ABOUT) == (LMCACHE, LMCACHE_ABOUT):
        return
    for k, v in list(ns.items()):
        if k.isupper() and isinstance(v, str) and "LMCache" in v:
            ns[k] = localize(v)

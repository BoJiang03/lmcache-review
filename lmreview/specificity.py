"""Specificity checks for rulebook entries: an entry must describe a kind of problem, not how to fix one PR.

Two checks, cheapest first (docs/plan-retention.md):

1. lint (free): a principle's "when" and "expect" must not name what its evidence PRs name: an identifier
   quoted or written in code style in an evidence comment (function, class, variable, config key), a
   file path or file name an evidence comment is on, or a PR number. "examples" and "why" may: that is
   where the specific case belongs.
2. judge (one small call, see `judge`): shown only the entry text, a model says whether it describes a
   class of problems or the fix for one place in the code.
"""

from __future__ import annotations

import json
import pathlib
import re

CODE = re.compile(r"`([^`\n]{3,80})`")
IDENT = re.compile(r"\b(?:[A-Za-z_][A-Za-z0-9]*_[A-Za-z0-9_]+|[a-z]+[A-Z][A-Za-z0-9]+|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+){1,})\b")
PRNUM = re.compile(r"(?:#|\bPR\s*)\d{3,5}\b")
# words in code style that are vocabulary, not one PR's names
GENERIC = {"self", "None", "True", "False", "dict", "list", "tuple", "str", "int", "float", "bool", "Any", "object",
           "assert", "import", "return", "async", "await", "lambda", "print", "logger", "logging", "typing",
           "Optional", "Union", "TODO", "kwargs", "args", "init", "__init__", "pytest", "torch", "numpy", "vLLM",
           "vllm", "LMCache", "lmcache", "README", "TypeError", "ValueError", "RuntimeError", "KeyError",
           "NotImplementedError", "Exception", "dataclass", "property", "staticmethod", "classmethod"}


def names_in(text: str) -> set[str]:
    """Identifiers a comment names: code spans (and identifier-like words inside them), plus snake_case,
    camelCase and CamelCase words outside them."""
    out: set[str] = set()
    for span in CODE.findall(text or ""):
        span = span.strip()
        if re.fullmatch(r"[\w.:/]+(?:\(\))?", span):
            out.add(span.removesuffix("()"))
        out.update(IDENT.findall(span))
    out.update(IDENT.findall(CODE.sub(" ", text or "")))
    return {x for x in out if len(x) >= 4 and x not in GENERIC and x.strip("_") not in GENERIC
            and not re.fullmatch(r"[a-z]+", x)}  # a plain lowercase word in code style is vocabulary


def evidence_names(entry: dict, comments: dict[str, dict]) -> dict[str, str]:
    """{name: where it came from} for every name and path the entry's evidence comments carry."""
    out: dict[str, str] = {}
    for cid in entry.get("evidence") or []:
        c = comments.get(str(cid).split(":")[0])
        if not c:
            continue
        for n in names_in(c.get("body") or ""):
            out.setdefault(n, f"comment {cid}")
        p = c.get("path")
        if p:
            out.setdefault(p, f"path of comment {cid}")
            stem = pathlib.PurePosixPath(p).name
            out.setdefault(stem, f"file of comment {cid}")
            if stem.endswith(".py") and len(stem) > 7:
                out.setdefault(stem[:-3], f"module of comment {cid}")
    return out


def lint(entry: dict, comments: dict[str, dict]) -> list[str]:
    """Why the entry's "when" / "expect" are too specific (empty: passes). A "knowledge" entry exists to
    carry project facts (an API to use, where something lives), so it may name the project's code; only
    PR numbers are checked there, and the model check judges the rest."""
    text = " ".join(str(entry.get(k) or "") for k in ("when", "expect"))
    bad = [f"PR number {m}" for m in PRNUM.findall(text)]
    if entry.get("kind") == "knowledge":
        return bad
    for name, src in sorted(evidence_names(entry, comments).items()):
        if re.search(r"(?<![\w./])" + re.escape(name) + r"(?![\w/])", text):
            bad.append(f"names {name!r} ({src})")
    return bad


def load_comments(data: pathlib.Path) -> dict[str, dict]:
    return {str(c["id"]): c for c in map(json.loads, (data / "dataset" / "comments.jsonl").open())}


JUDGE_PROMPT = """Below is one entry of a code review rulebook. A good entry describes a kind of problem that can
come up in many changes, so a reviewer can recognize it in code they have never seen. A bad entry is
really the fix for one place in one change: it names that change's own functions, variables, files or
values, or tells the author exactly what edit to make there.

{kind_note}Judge only the text below (when the entry applies, and what the reviewer should ask for). Answer with one
JSON object only: {{"verdict": "class" | "specific", "why": "<one short sentence>"}}

when: {when}
expect: {expect}"""


def judge(entry: dict, effort: str = "low") -> dict:
    """One small model call: {"verdict": "class" | "specific", "why", "cost"} ("error" when unparsable)."""
    from . import llm
    from .settings import get
    note = ("This entry is project knowledge: it may name the project's own APIs, modules and conventions, "
            "as long as the fact holds across changes, not only for the one change it came from.\n\n"
            if entry.get("kind") == "knowledge" else "")
    r = llm.run(JUDGE_PROMPT.format(when=entry.get("when", ""), expect=entry.get("expect", ""), kind_note=note), effort,
                model=get("review", "dedupe_model"))
    j = llm.extract_json(r.get("text")) or {}
    v = j.get("verdict") if j.get("verdict") in ("class", "specific") else "error"
    return {"verdict": v, "why": j.get("why", ""), "cost": r.get("cost") or 0}


def check(entry: dict, comments: dict[str, dict], use_model: bool = True) -> dict:
    """Both checks on one entry: {"ok", "lint": [...], "judge": {...} | None, "cost"}. The model is asked
    only when the lint passes."""
    bad = lint(entry, comments)
    j = judge(entry) if use_model and not bad else None
    return {"ok": not bad and (j is None or j["verdict"] != "specific"), "lint": bad, "judge": j,
            "cost": (j or {}).get("cost", 0)}

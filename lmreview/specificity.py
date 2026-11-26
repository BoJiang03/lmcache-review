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


REWRITE_PROMPT = """This entry of a code review rulebook is too specific: {why}

A good entry describes a kind of problem that can come up in many changes, so a reviewer recognizes it in
code it has never seen. Rewrite only "when" (the situation the entry applies to) and "expect" (what the
reviewer should ask for) so that they:
- describe the kind of situation and the kind of fix, in the project's general vocabulary;
- do not name the change's own functions, classes, variables, config keys, files or PR numbers{names};
- do not spell out the exact edit for one place.
Keep the meaning: on the change this entry came from, a reviewer given the new text must still raise the
same problem. The specific case stays in "examples", which you do not change.

kind: {kind}
when: {when}
expect: {expect}
examples: {examples}

Answer with one JSON object only: {{"when": "...", "expect": "..."}}"""


def rewrite(entry: dict, why: str, bad_names: list[str], effort: str = "high") -> tuple[dict | None, float]:
    """One call: the entry with "when" / "expect" rewritten to describe the class (None if unparsable)."""
    from . import llm
    names = f" (here: {', '.join(bad_names[:12])})" if bad_names else ""
    r = llm.run(REWRITE_PROMPT.format(why=why, names=names, kind=entry.get("kind", ""), when=entry.get("when", ""),
                                      expect=entry.get("expect", ""), examples=json.dumps(entry.get("examples") or [])),
                effort)
    j = llm.extract_json(r.get("text")) or {}
    if not (isinstance(j.get("when"), str) and isinstance(j.get("expect"), str) and j["when"].strip() and j["expect"].strip()):
        return None, r.get("cost") or 0
    return {**entry, "when": j["when"].strip(), "expect": j["expect"].strip()}, r.get("cost") or 0


def enforce(rules: list[dict], base_rules: list[dict], comments: dict[str, dict], effort: str = "high",
            use_model: bool = True) -> tuple[list[dict], list[dict], float]:
    """Hold every entry this distill or compress wrote (new, or "when" / "expect" changed from the base) to
    both checks. A failing entry gets one rewrite and is checked again; if it still fails, a new entry is
    dropped (and the entries it replaced come back) and a revised one goes back to its base text.

    Returns:
        (the rulebook, change records "specific-rewrite" / "specific-drop" / "specific-revert", cost).
    """
    base = {r["id"]: r for r in base_rules}
    changes, cost, out, dropped = [], 0.0, [], set()
    for r in rules:
        b = base.get(r["id"])
        if r.get("status", "active") != "active" or (b and (b.get("when"), b.get("expect")) == (r.get("when"), r.get("expect"))):
            out.append(r)
            continue
        c = check(r, comments, use_model)
        cost += c["cost"]
        if c["ok"]:
            out.append(r)
            continue
        why = "; ".join(c["lint"]) or (c["judge"] or {}).get("why") or "it describes one fix"
        bad = [x.split("'")[1] for x in c["lint"] if x.startswith("names '")]
        new, k = rewrite(r, why, bad, effort)
        cost += k
        c2 = check(new, comments, use_model) if new else {"ok": False, "lint": [], "judge": None, "cost": 0}
        cost += c2["cost"]
        if c2["ok"]:
            out.append(new)
            changes.append({"op": "specific-rewrite", "rules": [r["id"]], "concern": r.get("name") or "", "why": why,
                            "before": {"when": r.get("when"), "expect": r.get("expect")}})
            continue
        why2 = "; ".join(c2["lint"]) or (c2["judge"] or {}).get("why") or "rewrite unparsable"
        if b:
            out.append(b)
            changes.append({"op": "specific-revert", "rules": [r["id"]], "concern": r.get("name") or "",
                            "why": f"{why}; after one rewrite: {why2}"})
        else:
            dropped.add(r["id"])
            changes.append({"op": "specific-drop", "rules": [r["id"]], "concern": r.get("name") or "",
                            "why": f"{why}; after one rewrite: {why2}", "text": {"when": r.get("when"), "expect": r.get("expect")}})
    if dropped:  # what a dropped entry replaced comes back; links to it go
        fixed = []
        for r in out:
            if (r.get("retired") or {}).get("replaced_by") in dropped and r["id"] in base:
                r = base[r["id"]]
            if r.get("principle") in dropped:
                r = {k: v for k, v in r.items() if k != "principle"}
            if r.get("members"):
                r = {**r, "members": [m for m in r["members"] if m not in dropped]}
            fixed.append(r)
        out = fixed
    return out, changes, cost

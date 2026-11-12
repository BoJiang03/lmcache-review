"""`lmreview vet`: check a distill result (rulebook NEW built from BASE) before it becomes the next book.

distill only writes rules; vet decides whether they are kept. Three checks, then a verdict:

1. generality (free, no model): flags in the new or changed entries' text that tie a principle to the
   PR it came from: identifiers or numbers in "when"/"expect", "paths" naming single files.
2. effect: for every comment that NEW adds as evidence (the misses it was distilled from), the
   comment's sample is re-reviewed with BASE and with NEW. The entry works if NEW matches the comment
   with a finding citing it (or a linked principle/member). These runs leak (the entry was written
   from that comment): they show that the reviewer applies the rule, not that it generalizes. An
   existing entry that gained evidence is the exception: BASE already had it, so a BASE hit there is
   a fair hit (the rule generalized to a PR it was not written from).
3. side effects: the entries of BASE whose rendering or neighbours changed (a new parent principle,
   a changed text, a new link; `--all`: every entry) are replayed on their own source comments. A
   comment matched with a citation under BASE but not under NEW is a regression.

2 and 3 share the runs: one review per (sample, book). Runs are cached under data/runs/<reviewer>/,
so an earlier A/B with the same reviewer names costs nothing here.

Verdict: PASS if every entry with new evidence works on at least one of its comments and nothing
regressed; generality flags are listed for the reader and do not fail the book.
"""

from __future__ import annotations

import re

from .config import Config
from .regress import EST_RUN, FIELDS, replay
from .reviewer import load_rules
from .score import REPORTS, load_gold

LINKS = ("principle", "members")


def _related_ids(rules: list[dict]) -> dict[str, set[str]]:
    """Entry id -> ids linked to it by principle/members in either direction (itself included)."""
    m: dict[str, set[str]] = {r["id"]: {r["id"]} for r in rules}
    for r in rules:
        for x in ([r["principle"]] if r.get("principle") else []) + list(r.get("members") or []):
            m.setdefault(r["id"], {r["id"]}).add(x)
            m.setdefault(x, {x}).add(r["id"])
    return m


def lint(r: dict) -> list[str]:
    """Generality flags for one entry (knowledge entries may name code; only their paths are checked)."""
    out = []
    files = [p for p in r.get("paths") or [] if "*" not in p]
    if files:
        out.append(f"paths name single files: {files}")
    if r.get("kind") == "knowledge":
        return out
    text = f"{r.get('when', '')} {r.get('expect', '')}"
    ids = sorted(set(re.findall(r"`[^`]+`|\b[a-z]+_[a-z0-9_]+\b|\b\w+\(\)", text)))
    if ids:
        out.append(f"identifiers in when/expect: {ids[:5]}")
    nums = sorted(set(re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?:[KMG]B?|%)?(?![\w.])", text)))
    if nums:
        out.append(f"numbers in when/expect: {nums[:5]}")
    return out


def vet(book: str, base: str, prompt: str = "v0c", effort: str = "high", suffix: str = "-rc", reps: int = 1,
        max_cost: float = 30.0, everything: bool = False, every_sample: bool = False,
        cfg: Config | None = None) -> str:
    """Vet rulebook `book` against `base`; see the module docstring.

    Args:
        book: the new rulebook (a distill result).
        base: the rulebook it was built from.
        prompt, effort, suffix: the reviewer is `<prompt>+<book>@<effort><suffix>`, and the same with base.
        reps: runs per sample and book; a comment counts as matched if any run matches it.
        max_cost: cap for all runs together; 0 prints the plan only.
        everything: replay every active entry of base on its sources, not only the affected ones.
        every_sample: test new comments in every sample of a PR, not only the one holding most of them.
        cfg: configuration.

    Returns:
        The report, also written to reports/vet_<book>.md.
    """
    cfg = cfg or Config()
    act = lambda rs: {r["id"]: r for r in rs if r.get("status", "active") == "active"}  # noqa: E731
    new_rules = load_rules(book)
    N, O = act(new_rules), act(load_rules(base))
    ss, cm = load_gold(cfg)
    where = {int(c): k for k, s in ss.items() for c in s["gold_ids"]}
    tgt = lambda c: f"{where[c][0]}@{where[c][1][:8]}"  # noqa: E731

    # what changed: new entries, changed text/scope, changed links
    touched = {i for i, r in N.items() if i not in O or any(r.get(k) != O[i].get(k) for k in FIELDS + LINKS)}
    rel = _related_ids(new_rules)
    old_ev = {i: {int(e) for e in r.get("evidence") or []} for i, r in O.items()}
    in_base = set().union(*old_ev.values()) if old_ev else set()
    effect = [(i, int(e)) for i, r in N.items() for e in r.get("evidence") or []
              if int(e) not in in_base and int(e) in where]  # comments new to the book (a parent's
    # inherited evidence is not new: its members' source comments are replayed as side effects)
    if not every_sample:  # one sample per PR: the one holding most of the new comments
        n_in: dict = {}
        for _, e in effect:
            n_in[where[e]] = n_in.get(where[e], 0) + 1
        best = {k[0]: max((x for x in n_in if x[0] == k[0]), key=n_in.get) for k in n_in}
        effect = [(i, e) for i, e in effect if where[e] == best[where[e][0]]]
    eff_set = set(effect)
    affected = [i for i in O if i in N and (everything or rel.get(i, {i}) & touched)]
    side = [(i, e) for i in affected for e in sorted(old_ev[i]) if e in where and (i, e) not in eff_set]
    case = lambda i, e: (i, {"target": tgt(e), "with": f"{prompt}@{effort}", "comments": [e]})  # noqa: E731
    cases = [case(i, e) for i, e in effect + side]
    samples = {t["target"] for _, t in cases}
    todo = [(b, t, k) for b in (base, book) for t in samples for k in range(1, reps + 1)
             if not (cfg.data / "runs" / (f"{prompt}+{b}@{effort}{suffix}" + ("" if k == 1 else f"#r{k}"))
                     / f"{t.split('@')[0]}-{t.split('@')[1]}.json").exists()
             and not any((cfg.data / "runs" / (f"{prompt}+{b}@{effort}{suffix}" + ("" if k == 1 else f"#r{k}"))).glob(
                 f"{t.split('@')[0]}-{t.split('@')[1]}*.json"))]
    est = len(todo) * EST_RUN * (2 if suffix else 1)
    flags = {i: f for i in sorted(touched) if (f := lint(N[i]))}

    L = [f"# Vet of {book} (from {base})", "",
         f"- reviewer: {prompt}+<book>@{effort}{suffix}, {reps} run(s) per sample and book",
         f"- changed entries: {len(touched)}; evidence comments added: {len(effect)}; "
         f"base entries replayed for side effects: {len(affected)} ({len(side)} comments"
         f"{', all entries' if everything else ''})",
         f"- {len(samples)} samples x 2 books, {len(todo)} runs not cached yet, est ${est:.0f}, cap ${max_cost:.0f}", "",
         "## 1. Generality flags", ""]
    L += [f"- {i}: {'; '.join(f)}" for i, f in flags.items()] or ["- none"]
    L.append("")
    if max_cost <= 0:
        return "\n".join(L + ["plan only (max-cost 0)"])

    rows_b, c_b = replay(base, cases, reps, max_cost / 2, cfg, suffix=suffix)
    rows_n, c_n = replay(book, cases, reps, max_cost - c_b, cfg, suffix=suffix)
    key = lambda r: (r["entry"], r["comments"][0])  # noqa: E731
    B, Nw = {key(r): r for r in rows_b}, {key(r): r for r in rows_n}

    def mark(x: bool | None) -> str:
        return {True: "hit", False: "miss", None: "not run"}[x]

    # 2. effect
    per_entry: dict[str, list[str]] = {}
    works, unknown, fair = set(), set(), []
    eff_lines = []
    for i, e in effect:
        b, n = B.get((i, e), {}), Nw.get((i, e), {})
        nc, ba = n.get("passed"), b.get("any")
        if nc is None:
            unknown.add(i)
        if nc:
            works.add(i)
        res = ("not run" if nc is None else "corrected" if nc and ba is False else "both hit" if nc and ba
               else "fires, base not run" if nc else "new finds it, no citation" if n.get("any") else "miss")
        if i in O and b.get("passed"):  # entry existed in base: a base hit citing it is a fair hit
            fair.append((i, e))
        per_entry.setdefault(i, []).append(res)
        eff_lines.append(f"- {i} #{tgt(e)} c{e} ({cm[e]['author']}): {res}; base {mark(ba)}"
                         + (" (base cites it: fair hit)" if (i, e) in fair else ""))
    no_effect = [i for i in per_entry if i not in works and i not in unknown]

    # 3. side effects
    lost, kept, both_miss, side_unknown = [], 0, 0, 0
    for i, e in side:
        b, n = B.get((i, e), {}).get("passed"), Nw.get((i, e), {}).get("passed")
        if b is None or n is None:
            side_unknown += 1
        elif b and not n:
            lost.append((i, e))
        elif b:
            kept += 1
        else:
            both_miss += 1

    verdict = "FAIL" if lost or no_effect else ("INCOMPLETE" if unknown or side_unknown else "PASS")
    L += ["## 2. Effect (leaky: rules on their own source comments)", "",
          f"entries working: {len(works)}/{len(per_entry)}; not working: {no_effect or 'none'}"
          + (f"; fair hits (existing entry on a new PR): {len(fair)}" if fair else ""), ""] + eff_lines + [""]
    L += ["## 3. Side effects", "", f"kept {kept}, lost {len(lost)}, missed by both {both_miss}, not run {side_unknown}"]
    L += [f"- LOST {i} #{tgt(e)} c{e} ({cm[e]['author']}: {cm[e]['body'][:100]!r})" for i, e in lost]
    L = L[:2] + [f"**{verdict}** · cost ${c_b + c_n:.2f}", ""] + L[2:]
    (REPORTS / f"vet_{book}.md").write_text("\n".join(L) + "\n")
    return "\n".join(L)

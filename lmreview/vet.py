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
   a revision, a new link; `--all`: every entry) are replayed on up to SIDE_PER_ENTRY of their own source
   comments (`--all`: every one). NEW runs first; a comment NEW still matches with a citation is kept.
   Only where NEW misses it does BASE run: matched under BASE but not under NEW is a regression. For a
   retired entry, NEW must still match the comment with some finding.
2b. revisions: a revised entry is re-reviewed on the samples whose invalid findings triggered the
   revision; a finding citing it that is judged invalid again means the revision did not fix it.

2, 2b and 3 share the runs: one review per sample with NEW, and with BASE only where needed. Runs are cached under data/runs/<reviewer>/,
so an earlier A/B with the same reviewer names costs nothing here. Single runs are noisy, so each
failing case gets one more run with NEW before it counts (`retry`).

Verdict: PASS if every entry with new evidence works on at least one of its comments, nothing
regressed and every revision fixed its trigger; generality flags are listed for the reader and do not
fail the book. `write` saves NEW without the failing changes, as the next working book.
"""

from __future__ import annotations

import json
import pathlib
import re

from .config import Config
from .state import book_path
from .progress import note
from .regress import EST_RUN, FIELDS, replay

SIDE_PER_ENTRY = 2  # side effects: source comments replayed per affected entry (`--all`: every one)
from .distill import book_meta, write_meta
from .reviewer import load_rules, parse_reviewer, rulecheck_of
from .score import REPORTS, load_gold

LINKS = ("principle", "members")


def _related_ids(rules: list[dict]) -> dict[str, set[str]]:
    """Entry id -> ids linked to it by principle/members in either direction (itself included)."""
    m: dict[str, set[str]] = {r["id"]: {r["id"]} for r in rules}
    for r in rules:
        for x in ([r["principle"]] if r.get("principle") else []) + list(r.get("members") or []) \
                + list(r.get("replaces") or []):
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


def vet(book: str, base: str | None = None, prompt: str | None = None, effort: str | None = None,
        suffix: str | None = None, reps: int = 1,
        max_cost: float = 30.0, everything: bool = False, every_sample: bool = False, retry: bool = True,
        write: str | None = None, cfg: Config | None = None, out: dict | None = None) -> str:
    """Vet rulebook `book` against `base`; see the module docstring.

    Args:
        book: the new rulebook (a distill result).
        base: the rulebook it was built from (default: from rules/<book>.meta.json).
        prompt, effort, suffix: the reviewer is `<prompt>+<book>@<effort><suffix>`, and the same with base.
            Default: those of the runs distill learned from (meta "runs"), so their cached runs and
            scores of base are reused; else v0f, high, -rc.
        reps: runs per sample and book; a comment counts as matched if any run matches it.
        max_cost: cap for all runs together; 0 prints the plan only.
        everything: replay every active entry of base on its sources, not only the affected ones.
        every_sample: test new comments in every sample of a PR, not only the one holding most of them.
        retry: give each failing case one more run with the new book before it counts.
        write: also write rules/<write>.jsonl: the new book without the changes that failed.
        cfg: configuration.
        out: filled with the structured result for state.vet: {"verdict", "J", "effect", "kept", "cost"}.

    Returns:
        The report, also written to reports/vet_<book>.md.
    """
    cfg = cfg or Config()
    meta = book_meta(book)
    base = base or meta.get("base")
    if not base:
        raise ValueError(f"no base for {book}: pass --base (rules/{book}.meta.json names none)")
    if meta.get("runs"):
        version, _, eff = parse_reviewer(meta["runs"].split("#")[0])
        prompt, effort = prompt or version, effort or eff
        suffix = suffix if suffix is not None else ("-rc" if rulecheck_of(meta["runs"]) else "")
    prompt, effort, suffix = prompt or "v0f", effort or "high", "-rc" if suffix is None else suffix
    act = lambda rs: {r["id"]: r for r in rs if r.get("status", "active") == "active"}  # noqa: E731
    new_rules, old_rules = load_rules(book), load_rules(base)
    N, O = act(new_rules), act(old_rules)
    ss, cm = load_gold(cfg)
    where = {int(c): k for k, s in ss.items() for c in s["gold_ids"]}
    tgt = lambda c: f"{where[c][0]}@{where[c][1][:8]}"  # noqa: E731
    w = f"{prompt}@{effort}"

    # what changed: new entries, changed text/scope, changed links, revisions, retirements
    touched = {i for i, r in N.items() if i not in O or any(r.get(k) != O[i].get(k) for k in FIELDS + LINKS)}
    retired = [i for i in O if i not in N]
    revised = [i for i in O if i in N and N[i].get("version", 1) != O[i].get("version", 1)]
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
        def cached(k: tuple) -> int:  # runs already on disk for this sample (ties go to cached ones)
            return sum(any((cfg.data / "runs" / f"{prompt}+{b}@{effort}{suffix}").glob(f"{k[0]}-{k[1][:8]}*.json"))
                       for b in (base, book))
        best = {k[0]: max((x for x in n_in if x[0] == k[0]), key=lambda x: (n_in[x], cached(x))) for k in n_in}
        picked = {best[k[0]] for k in n_in}
        for i in dict.fromkeys(i for i, _ in effect):  # every entry needs one tested comment: add a sample
            if not any(where[e] in picked for j, e in effect if j == i):
                picked.add(max((where[e] for j, e in effect if j == i), key=lambda x: (n_in[x], cached(x))))
        effect = [(i, e) for i, e in effect if where[e] in picked]
    eff_set = set(effect)
    affected = [i for i in O if i not in N or everything or rel.get(i, {i}) & touched]
    # side effects: at most SIDE_PER_ENTRY source comments per entry (whether an entry still works shows
    # on any of them), preferring samples that are reviewed anyway or already have a run with NEW
    have = {tgt(e) for _, e in effect} | {t for i in revised for t in
                                         [x["target"] for x in (N[i].get("revised") or {}).get("signals") or []]}
    def has_new(t: str) -> bool:
        return any((cfg.data / "runs" / f"{prompt}+{book}@{effort}{suffix}").glob(f"{t.replace('@', '-')}*.json"))
    side = []
    for i in affected:
        cs = [e for e in sorted(old_ev[i]) if e in where and (i, e) not in eff_set]
        cs.sort(key=lambda e: (tgt(e) not in have, not has_new(tgt(e))))
        # a retired (replaced) entry: every source comment, since the replacement must keep them all
        side += [(i, e) for e in (cs if everything or i in retired else cs[:SIDE_PER_ENTRY])]
        have |= {tgt(e) for e in cs[:SIDE_PER_ENTRY]}
    fixes = list(dict.fromkeys((i, x["target"]) for i in revised
                               for x in (N[i].get("revised") or {}).get("signals") or []))
    cases = ([(i, {"target": tgt(e), "with": w, "comments": [e]}) for i, e in effect + side]
             + [(i, {"target": t, "with": w, "comments": []}) for i, t in fixes])
    samples = {t["target"] for _, t in cases}

    def run_dir(b: str, k: int) -> pathlib.Path:
        return cfg.data / "runs" / (f"{prompt}+{b}@{effort}{suffix}" + ("" if k == 1 else f"#r{k}"))
    todo = [(book, t, k) for t in samples for k in range(1, reps + 1)
            if not any(run_dir(book, k).glob(f"{t.split('@')[0]}-{t.split('@')[1]}*.json"))]
    est = len(todo) * EST_RUN * (2 if suffix else 1)  # base runs come only where NEW misses a side case
    flags = {i: f for i in sorted(touched) if (f := lint(N[i]))}

    L = [f"# Vet of {book} (from {base})", "",
         f"- reviewer: {prompt}+<book>@{effort}{suffix}, {reps} run(s) per sample and book"
         + ("; failures get one more run" if retry else ""),
         f"- changed entries: {len(touched)} (revised {len(revised)}, retired {len(retired)}); "
         f"evidence comments added: {len(effect)}; base entries replayed for side effects: {len(affected)} "
         f"({len(side)} comments{', all entries' if everything else ''}); revision fixes to check: {len(fixes)}",
         f"- {len(samples)} samples with the new book ({len(todo)} not cached yet, est ${est:.0f}; the old book only "
         f"where the new one misses a side-effect comment), cap ${max_cost:.0f}", "",
         "## 1. Generality flags", ""]
    L += [f"- {i}: {'; '.join(f)}" for i, f in flags.items()] or ["- none"]
    L.append("")
    if max_cost <= 0:
        return "\n".join(L + ["plan only (max-cost 0)"])

    key = lambda r: (r["entry"], r["target"], tuple(r["comments"]))  # noqa: E731
    for x in L[2:5]:
        note(x.lstrip("- "))
    note(f"[1/3] review {len(samples)} samples with the new book {book}")
    rows_n, c_n = replay(book, cases, reps, max_cost, cfg, suffix=suffix)
    Nw = {key(r): r for r in rows_n}
    # the old book: where the new one missed a side-effect comment (lost, or missed by both?), and
    # effect cases whose old run is cached anyway (for the report)
    def cached_old(t: str) -> bool:
        return any(run_dir(base, 1).glob(f"{t.replace('@', '-')}*.json"))
    need_b = ([(i, {"target": tgt(e), "with": w, "comments": [e]}) for i, e in side
               if Nw.get((i, tgt(e), (e,)), {}).get("any" if i in retired else "passed") is False]
              + [(i, {"target": tgt(e), "with": w, "comments": [e]}) for i, e in effect if cached_old(tgt(e))])
    note(f"[2/3] review {len({t['target'] for _, t in need_b})} samples with the old book {base} "
         f"(${c_n:.2f} so far)")
    rows_b, c_b = replay(base, need_b, reps, max(0.0, max_cost - c_n), cfg, suffix=suffix) if need_b else ([], 0.0)
    B = {key(r): r for r in rows_b}
    ck = lambda i, e: (i, tgt(e), (e,))  # noqa: E731
    fk = lambda i, t: (i, t, ())  # noqa: E731

    def judge() -> dict:
        """Classify every case from B and Nw."""
        works, unknown = set(), set()
        for i, e in effect:
            n = Nw.get(ck(i, e), {})
            if n.get("passed") is None:
                unknown.add(i)
            if n.get("passed"):
                works.add(i)
        lost, kept, both_miss, s_unknown = [], 0, 0, 0
        for i, e in side:
            b, n = B.get(ck(i, e), {}), Nw.get(ck(i, e), {})
            nb = n.get("any") if i in retired else n.get("passed")  # a retired entry: caught by anything
            if nb:  # the new book still catches it: nothing lost, whatever the old book does
                kept += 1
            elif b.get("passed") is None or nb is None:
                s_unknown += 1
            elif b["passed"] and not nb:
                lost.append((i, e))
            elif b["passed"]:
                kept += 1
            else:
                both_miss += 1
        not_fixed = [(i, t) for i, t in fixes if (Nw.get(fk(i, t), {}).get("invalid") or 0) > 0]
        f_unknown = [(i, t) for i, t in fixes if Nw.get(fk(i, t), {}).get("invalid") is None]
        no_effect = sorted({i for i, _ in effect} - works - unknown)
        return {"works": works, "unknown": unknown, "no_effect": no_effect, "lost": lost, "kept": kept,
                "both_miss": both_miss, "s_unknown": s_unknown, "not_fixed": not_fixed, "f_unknown": f_unknown}

    J, c_r = judge(), 0.0
    note(f"      first pass: works {sorted(J['works'])}, not working {J['no_effect']}, lost {len(J['lost'])}, "
         f"revisions not fixed {len(J['not_fixed'])}")
    if retry:  # single runs are noisy: a failing case gets one more run with NEW before it counts
        again = ([(i, {"target": tgt(e), "with": w, "comments": [e]}) for i, e in effect if i in J["no_effect"]]
                 + [(i, {"target": tgt(e), "with": w, "comments": [e]}) for i, e in J["lost"]]
                 + [(i, {"target": t, "with": w, "comments": []}) for i, t in J["not_fixed"]])
        if again:
            note(f"[3/3] {len(again)} failing case(s) get one more run with {book} (${c_b + c_n:.2f} so far)")
            rows_r, c_r = replay(book, again, reps + 1, max(0.0, max_cost - c_b - c_n), cfg, suffix=suffix)
            Nw |= {key(r): r for r in rows_r if r["passed"] is not None}
            J = judge()

    def mark(x: bool | None) -> str:
        return {True: "hit", False: "miss", None: "not run"}[x]

    eff_lines, fair = [], 0
    for i, e in effect:
        b, n = B.get(ck(i, e), {}), Nw.get(ck(i, e), {})
        nc, ba = n.get("passed"), b.get("any")
        res = ("not run" if nc is None else "corrected" if nc and ba is False else "both hit" if nc and ba
               else "fires, base not run" if nc else "new finds it, no citation" if n.get("any") else "miss")
        is_fair = i in O and bool(b.get("passed"))  # entry existed in base: a base hit citing it is fair
        fair += is_fair
        eff_lines.append(f"- {i} #{tgt(e)} c{e} ({cm[e]['author']}): {res}; base {mark(ba)}"
                         + (" (base cites it: fair hit)" if is_fair else ""))
    fails = J["no_effect"] or J["lost"] or J["not_fixed"]
    verdict = "FAIL" if fails else ("INCOMPLETE" if J["unknown"] or J["s_unknown"] or J["f_unknown"] else "PASS")
    n_eff = len({i for i, _ in effect})
    L += ["## 2. Effect (leaky: rules on their own source comments)", "",
          f"entries working: {len(J['works'])}/{n_eff}; not working: {J['no_effect'] or 'none'}"
          + (f"; fair hits (existing entry on a new PR): {fair}" if fair else ""), ""] + eff_lines + [""]
    if fixes:
        L += ["## 2b. Revisions: the invalid findings that triggered them", ""]
        L += [f"- {i} #{t}: base {B.get(fk(i, t), {}).get('invalid')} invalid citing finding(s), "
              f"new {Nw.get(fk(i, t), {}).get('invalid')}" for i, t in fixes] + [""]
    L += ["## 3. Side effects", "", f"kept {J['kept']}, lost {len(J['lost'])}, missed by both {J['both_miss']}, "
          f"not run {J['s_unknown']}"]
    L += [f"- LOST {i}{' (retired)' if i in retired else ''} #{tgt(e)} c{e} ({cm[e]['author']}: "
          f"{cm[e]['body'][:100]!r})" for i, e in J["lost"]]
    if out is not None:
        out.update(verdict=verdict, J=J, effect=effect, kept=_passing(new_rules, old_rules, O, J, rel),
                   cost=c_b + c_n + c_r, retired=retired)
    if write:
        kept_book = _passing(new_rules, old_rules, O, J, rel)
        book_path(write).write_text("".join(json.dumps(r) + "\n" for r in kept_book))
        write_meta(write, {**meta, "base": base, "vetted_from": book})  # keeps "seen" for the next distill
        L += ["", f"wrote rules/{write}.jsonl: {len(kept_book)} entries (failing changes dropped or reverted)"]
    L = L[:2] + [f"**{verdict}** · cost ${c_b + c_n + c_r:.2f}", ""] + L[2:]
    note(f"{verdict}: entries working {len(J['works'])}/{n_eff}, lost {len(J['lost'])}, "
         f"revisions not fixed {len(J['not_fixed'])}; ${c_b + c_n + c_r:.2f}; report reports/vet_{book}.md",
         {"PASS": "ok", "FAIL": "err"}.get(verdict, "warn"))
    (REPORTS / f"vet_{book}.md").write_text("\n".join(L) + "\n")
    return "\n".join(L)


def _passing(new_rules: list[dict], old_rules: list[dict], O: dict, J: dict, rel: dict) -> list[dict]:
    """NEW without the changes vet failed: new entries that never worked are dropped; entries that lost
    a source hit or whose revision did not fix its trigger go back to their base version, and new
    entries linked to a lost entry are dropped with it (vet cannot tell which link caused the loss).
    A dropped replacement restores every entry it replaced."""
    old_all = {r["id"]: r for r in old_rules}
    lost = {i for i, _ in J["lost"]} | {i for i, _ in J["not_fixed"]}
    drop = {i for i in J["no_effect"] if i not in O}
    drop |= {x for i in lost for x in rel.get(i, set()) if x not in old_all}
    # a dropped replacement gives back every entry it replaced, not only the one that lost a comment
    lost |= {r["id"] for r in new_rules if (r.get("retired") or {}).get("replaced_by") in drop}
    out = []
    for r in new_rules:
        if r["id"] in drop:
            continue
        r = dict(old_all[r["id"]]) if r["id"] in lost and r["id"] in old_all else dict(r)
        if r.get("principle") in drop:
            r["principle"] = old_all.get(r["id"], {}).get("principle")
        if r.get("members"):
            r["members"] = [m for m in r["members"] if m not in drop]
        out.append(r)
    return out

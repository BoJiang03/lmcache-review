"""`lmreview vet`: check a distill result (rulebook NEW built from BASE) before it becomes the next book.

distill only writes rules; vet decides whether they are kept. Three checks, then a verdict:

1. generality (free, no model): flags in the new or changed entries' text that tie a principle to the
   PR it came from: identifiers or numbers in "when"/"expect", "paths" naming single files.
2. effect: for every comment that NEW adds as evidence (the misses it was distilled from), the
   comment's sample is re-reviewed with BASE and with NEW. The entry works if NEW matches the comment
   with a finding citing it (or a linked principle/member). These runs leak (the entry was written
   from that comment): they show that the reviewer applies the rule, not that it generalizes. An
   existing entry that only gained evidence is replayed too: its comment was missed with that entry in
   the book, so only a run shows whether the miss was noise (resolved) or the entry does not fire on it.
3. side effects: the entries of BASE whose rendering or neighbours changed (a new parent principle,
   a revision, a new link; `--all`: every entry) are replayed on up to SIDE_PER_ENTRY of their own source
   comments (`--all`: every one). NEW runs first; a comment NEW still matches with a citation is kept.
   Only where NEW misses it does BASE run: matched under BASE but not under NEW is a regression. For a
   retired entry, NEW must still match the comment with some finding.
2b. revisions: a revised entry is re-reviewed on the samples whose invalid findings triggered the
   revision; a finding citing it that is judged invalid again means the revision did not fix it.
4. precision: a changed entry must not draw more refuted findings than the text it replaces: on every
   sample where findings citing its new text were judged wrong, BASE runs too, and the entry is reverted
   (a new one dropped) when NEW has more than WIDE_MARGIN more refuted findings citing it than BASE has
   citing the entries it replaces. Recall alone would let a merge or trim widen an entry unchecked.

A replaced or trimmed entry replays the source comments it was proven to correct; its unproven source
comments are not replayed (BASE nearly always misses them too, so they decide nothing; the report counts
them). With no proven comment, every source comment is replayed. A case both
books missed gets one more run with BASE as well as NEW: a single BASE miss by noise would leave it
unprotected.

2, 2b and 3 share the runs: one review per sample with NEW, and with BASE only where needed. By default a
"review" here is the rule check alone (reviewer suffix -ro, see reviewer.ruleonly_of) with a judge that sees
only the comments the cases ask about: a rule change shows in the rule check, so the full review is not
replayed (about $0.8 per sample instead of $3.5). Runs are cached under data/runs/<reviewer>/,
so an earlier A/B with the same reviewer names costs nothing here. Single runs are noisy, so each
failing case gets one more run with NEW before it counts (`retry`).

Verdict, by what the next book takes: ALL KEPT if every entry with new evidence works on at least one
of its comments, nothing regressed and every revision fixed its trigger; PARTLY KEPT if some changes
fail (they are dropped or reverted, the rest promoted); NONE KEPT if none works; INCOMPLETE if any case
was not run (nothing is promoted). Generality flags are listed for the reader and keep nothing out.
`write` saves NEW without the failing changes, as the next working book.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re

from .config import Config
from .annotate import cid_of, norm
from .settings import get
from .state import book_path
from .progress import note
from .regress import EST_RO, EST_RUN, FIELDS, replay, run_tag
from .schema import cites as finding_rules

SIDE_PER_ENTRY = int(get("vet", "side_per_entry"))  # side effects: source comments replayed per affected entry (`--all`: every one)
PRECISION = bool(get("vet", "precision"))  # precision gate on (off: left to human feedback after launch)
WIDE_MARGIN = int(get("vet", "wide_margin"))  # precision: refuted findings a changed entry may add over its base text
from .distill import book_meta, design_flags, write_meta
from .reviewer import load_rules, parse_reviewer
from .score import REPORTS, load_gold, refuted

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
    out = list(design_flags(r))  # OVERRIDE / PACKED: against how entries are written
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
        write: str | None = None, cfg: Config | None = None, out: dict | None = None,
        targets: set | None = None) -> str:
    """Vet rulebook `book` against `base`; see the module docstring.

    Args:
        book: the new rulebook (a distill result).
        base: the rulebook it was built from (default: from rules/<book>.meta.json).
        prompt, effort, suffix: the reviewer is `<prompt>+<book>@<effort><suffix>`, and the same with base.
            Default: prompt and effort of the runs distill learned from (meta "runs"), else v0f and high;
            suffix -ro (the rule check alone, targeted judge; -rc replays the full review as before).
        reps: runs per sample and book; a comment counts as matched if any run matches it.
        max_cost: cap for all runs together; 0 prints the plan only.
        everything: replay every active entry of base on its sources, not only the affected ones.
        every_sample: test new comments in every sample of a PR, not only the one holding most of them.
        retry: give each failing case one more run with the new book before it counts.
        write: also write rules/<write>.jsonl: the new book without the changes that failed.
        cfg: configuration.
        targets: the comments the candidate was distilled for. Every entry that carries one of them as
            evidence is tested on it, even when the base already had that evidence (a revision made for it,
            or one an earlier vet promoted untested).
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
    prompt, effort, suffix = prompt or "v0f", effort or "high", "-ro" if suffix is None else suffix
    act = lambda rs: {r["id"]: r for r in rs if r.get("status", "active") == "active"}  # noqa: E731
    new_rules, old_rules = load_rules(book), load_rules(base)
    N, O = act(new_rules), act(old_rules)
    ss, cm = load_gold(cfg)
    where = {int(c): k for k, s in ss.items() for c in s["gold_ids"]}
    where |= {k: where[cid_of(k)] for k in cm if isinstance(k, str) and cid_of(k) in where}  # points
    tgt = lambda c: f"{where[c][0]}@{where[c][1][:8]}"  # noqa: E731
    w = f"{prompt}@{effort}"

    # what changed: new entries, changed text/scope, changed links, revisions, retirements
    touched = {i for i, r in N.items() if i not in O or any(r.get(k) != O[i].get(k) for k in FIELDS + LINKS)}
    retired = [i for i in O if i not in N]
    revised = [i for i in O if i in N and N[i].get("version", 1) != O[i].get("version", 1)]
    rel = _related_ids(new_rules)
    old_ev = {i: {norm(e) for e in r.get("evidence") or []} for i, r in O.items()}
    in_base = set().union(*old_ev.values()) if old_ev else set()
    tg = {norm(t) for t in targets or ()}
    effect = [(i, norm(e)) for i, r in N.items() for e in r.get("evidence") or []
              if norm(e) in where and (norm(e) not in in_base or norm(e) in tg)]  # comments new to the book (a parent's
    # inherited evidence is not new: its members' source comments are replayed as side effects)
    if not every_sample:  # one sample per PR: the one holding most of the new comments
        n_in: dict = {}
        for _, e in effect:
            n_in[where[e]] = n_in.get(where[e], 0) + 1
        def cached(k: tuple) -> int:  # runs already on disk for this sample (ties go to cached ones)
            return sum(any((cfg.data / "runs").glob(f"{prompt}+{b}@{effort}{suffix}*/{k[0]}-{k[1][:8]}*.json"))
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
        return any((cfg.data / "runs").glob(f"{prompt}+{book}@{effort}{suffix}*/{t.replace('@', '-')}*.json"))
    side, unproven = [], 0
    # a trimmed entry (rewritten shorter, same id) must keep everything it did, as a replaced one must
    full = set(retired) | {i for i in revised if (N[i].get("revised") or {}).get("reason") == "trim"}
    for i in affected:
        cs = [e for e in sorted(old_ev[i], key=str) if e in where and (i, e) not in eff_set]
        cs.sort(key=lambda e: (tgt(e) not in have, not has_new(tgt(e))))
        # a retired (replaced) entry: the comments it was proven to correct (its "corrected" tests), since
        # the replacement must keep what it did; with no such record, every source comment
        # (a test may be on another PR than the entry's sources: take every proven comment in the gold set)
        pr = [e for e in sorted(_proven(O[i]), key=str) if e in where and (i, e) not in eff_set] if i in full else []
        if pr and not everything:  # only the proven ones: an unproven source comment is nearly always missed by
            side += [(i, e) for e in pr]  # BASE too, so it decides nothing and costs runs (2026-11-25, v0030c1)
            unproven += sum(e not in set(pr) for e in cs)
        else:
            side += [(i, e) for e in (cs if everything or i in full else cs[:SIDE_PER_ENTRY])]
        have |= {tgt(e) for e in cs[:SIDE_PER_ENTRY]}
    fixes = list(dict.fromkeys((i, x["target"]) for i in revised
                               for x in (N[i].get("revised") or {}).get("signals") or []))
    cases = ([(i, {"target": tgt(e), "with": w, "comments": [e]}) for i, e in effect + side]
             + [(i, {"target": t, "with": w, "comments": []}) for i, t in fixes])
    samples = {t["target"] for _, t in cases}
    # rule-only replays check only the rules this change is about: the changed and retired entries, the
    # entries the cases test, and everything linked to those in either book (principle / members / replaces)
    only = None
    ruleonly = suffix.startswith("-ro")  # -ro or -ro-sh
    rel_old = _related_ids(old_rules)
    if ruleonly:
        only = set(touched) | set(retired) | {i for i, _ in cases}
        only |= {x for i in list(only) for x in rel.get(i, {i}) | rel_old.get(i, {i})}

    def run_dir(b: str, k: int) -> pathlib.Path:
        return cfg.data / "runs" / (f"{prompt}+{b}@{effort}{suffix}" + run_tag(only) + ("" if k == 1 else f"#r{k}"))
    todo = [(book, t, k) for t in samples for k in range(1, reps + 1)
            if not any(run_dir(book, k).glob(f"{t.split('@')[0]}-{t.split('@')[1]}*.json"))]
    est = len(todo) * (EST_RO if ruleonly else EST_RUN * (2 if suffix else 1))  # base runs: only where NEW misses a side case
    flags = {i: f for i in sorted(touched) if (f := lint(N[i]))}

    L = [f"# Vet of {book} (from {base})", "",
         f"- reviewer: {prompt}+<book>@{effort}{suffix}, {reps} run(s) per sample and book"
         + ("; failures get one more run" if retry else ""),
         f"- changed entries: {len(touched)} (revised {len(revised)}, retired {len(retired)}); "
         f"evidence comments added: {len(effect)}; base entries replayed for side effects: {len(affected)} "
         f"({len(side)} comments{', all entries' if everything else ''}; {unproven} unproven source comments not "
         f"replayed); revision fixes to check: {len(fixes)}",
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
    rows_n, c_n = replay(book, cases, reps, max_cost, cfg, suffix=suffix, only=only)
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
    rows_b, c_b = replay(base, need_b, reps, max(0.0, max_cost - c_n), cfg, suffix=suffix, only=only) if need_b else ([], 0.0)
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
        lost, kept, both_miss, s_unknown, s_which = [], 0, 0, 0, []
        for i, e in side:
            b, n = B.get(ck(i, e), {}), Nw.get(ck(i, e), {})
            nb = n.get("any") if i in retired else n.get("passed")  # a retired entry: caught by anything
            if nb:  # the new book still catches it: nothing lost, whatever the old book does
                kept += 1
            elif b.get("passed") is None or nb is None:
                s_unknown += 1
                s_which.append((i, e, "new" if nb is None else "base"))
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
                "both_miss": both_miss, "s_unknown": s_unknown, "s_which": s_which, "not_fixed": not_fixed, "f_unknown": f_unknown}

    J, c_r = judge(), 0.0
    note(f"      first pass: works {sorted(J['works'])}, not working {J['no_effect']}, lost {len(J['lost'])}, "
         f"revisions not fixed {len(J['not_fixed'])}")
    if retry:  # single runs are noisy: a failing case gets one more run with NEW before it counts
        # a case both books missed gets one more run with BASE too: a BASE miss by noise would leave it unprotected
        both = [(i, e) for i, e in side if B.get(ck(i, e), {}).get("passed") is False
                and (Nw.get(ck(i, e), {}).get("any" if i in retired else "passed") is False)]
        again = ([(i, {"target": tgt(e), "with": w, "comments": [e]}) for i, e in effect if i in J["no_effect"]]
                 + [(i, {"target": tgt(e), "with": w, "comments": [e]}) for i, e in J["lost"] + both]
                 + [(i, {"target": t, "with": w, "comments": []}) for i, t in J["not_fixed"]])
        if both:
            note(f"[3/3] {len(both)} case(s) missed by both get one more run with {base}")
            rows_rb, c_rb = replay(base, [(i, {"target": tgt(e), "with": w, "comments": [e]}) for i, e in both],
                                   reps + 1, max(0.0, max_cost - c_b - c_n), cfg, suffix=suffix, only=only)
            B |= {key(r): r for r in rows_rb if r["passed"] is not None}
            c_b += c_rb
        if again:
            note(f"[3/3] {len(again)} failing case(s) get one more run with {book} (${c_b + c_n:.2f} so far)")
            rows_r, c_r = replay(book, again, reps + 1, max(0.0, max_cost - c_b - c_n), cfg, suffix=suffix, only=only)
            Nw |= {key(r): r for r in rows_r if r["passed"] is not None}
            J = judge()

    # 4. precision: a changed entry must not draw more refuted findings than the text it replaces did, on
    # the samples where its new text drew any (BASE runs only there)
    c_p, wide, p_rows = 0.0, {}, []
    chg = sorted(i for i in touched if i in N) if PRECISION else []
    pred = {i: ({i} if i in O else set(N[i].get("replaces") or []) | set(N[i].get("replaces_new") or [])) & set(O)
            for i in chg}
    new_bad = {i: {t: _citing(run_dir(book, 1), t, rel.get(i, {i}), cfg) or (0, 0) for t in sorted(samples)}
               for i in chg}  # a sample with no NEW run is already INCOMPLETE (J["unknown"] / "s_unknown")
    flagged = {i: [t for t, (_, b) in new_bad[i].items() if b] for i in chg}
    need_p = sorted({(p, t) for i in chg for t in flagged[i] for p in (pred[i] or {i}) if p in O})
    if need_p:
        note(f"[4/4] precision: {len({t for _, t in need_p})} samples with the old book {base} "
             f"(refuted findings citing changed entries)")
        _, c_p = replay(base, [(p, {"target": t, "with": w, "comments": []}) for p, t in need_p], 1,
                        max(0.0, max_cost - c_b - c_n - c_r), cfg, suffix=suffix, only=only)
    p_unknown = []
    for i in chg:
        if not flagged[i]:
            continue
        nb = sum(new_bad[i][t][1] for t in flagged[i])
        ids = set().union(*(rel_old.get(p, {p}) for p in pred[i])) if pred[i] else set()
        old = [_citing(run_dir(base, 1), t, ids, cfg) if ids else (0, 0) for t in flagged[i]]
        if ids and any(o is None for o in old):
            p_unknown.append(i)
            continue
        ob = sum(o[1] for o in old)
        p_rows.append((i, nb, ob, len(flagged[i])))
        if nb > ob + WIDE_MARGIN:
            wide[i] = {"new": nb, "old": ob, "samples": flagged[i],
                       "findings": _refuted_findings(run_dir(book, 1), flagged[i], rel.get(i, {i}), cfg)}
    J["too_wide"], J["p_unknown"], J["wide"] = sorted(wide), p_unknown, wide

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
    today = dt.date.today().isoformat()
    tests: dict[str, list[dict]] = {}
    for i, e in effect:  # an effect comment was missed by the round's review: that miss is the control
        b, n = B.get(ck(i, e), {}), Nw.get(ck(i, e), {})
        if n.get("passed"):
            tests.setdefault(i, []).append(
                {"target": tgt(e), "control": f"{w}{suffix} on {base}" if b.get("any") is not None else "round miss",
                 "with": f"{prompt}+{book}@{effort}{suffix}", "result": "both-hit" if b.get("any") else "corrected",
                 "comments": [e], "date": today, "note": "vet effect"})
    reverted = ({i for i, _ in J["lost"]} | {i for i, _ in J["not_fixed"]} | {i for i in J["no_effect"] if i in O}
                | set(J["too_wide"]))  # back to the base text: untested
    tests = {i: ts for i, ts in tests.items() if i not in reverted}
    fails = J["no_effect"] or J["lost"] or J["not_fixed"] or J["too_wide"]
    # anything left untested (cost cap, a failed run) makes the whole vet INCOMPLETE, even when some entries
    # already failed: promoting then would keep untested entries and skip their side-effect replays
    # otherwise the verdict says what the next book takes: every change, some (the failing ones are dropped
    # or reverted, the rest promoted), or none. A partial result is the normal outcome, not a failure.
    bad = sorted(set(J["no_effect"]) | {i for i, _ in J["lost"]} | {i for i, _ in J["not_fixed"]} | set(J["too_wide"]))
    verdict = ("INCOMPLETE" if J["unknown"] or J["s_unknown"] or J["f_unknown"] or J["p_unknown"] else
               "ALL KEPT" if not fails else "PARTLY KEPT" if J["works"] else "NONE KEPT")
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
    L += [f"- NOT RUN ({side}) {i} #{tgt(e)} c{e}" for i, e, side in J.get("s_which") or []]
    L += ["", "## 4. Precision (refuted findings citing a changed entry: new text vs the text it replaces)",
          f"margin {WIDE_MARGIN}; too wide: {J['too_wide'] or 'none'}"
          + (f"; not run: {J['p_unknown']}" if J["p_unknown"] else "")]
    L += [f"- {i}: {nb} refuted (new) vs {ob} (base) on {k} sample(s)" + (" TOO WIDE" if i in wide else "")
          for i, nb, ob, k in p_rows]
    if out is not None:
        out.update(wide=wide, verdict=verdict, J=J, effect=effect, rows=list(Nw.values()), kept=_with_tests(_passing(new_rules, old_rules, O, J, rel), tests),
                   cost=c_b + c_n + c_r + c_p, retired=retired)
    if write:
        kept_book = _with_tests(_passing(new_rules, old_rules, O, J, rel), tests)
        book_path(write).write_text("".join(json.dumps(r) + "\n" for r in kept_book))
        write_meta(write, {**meta, "base": base, "vetted_from": book})  # keeps "seen" for the next distill
        L += ["", f"wrote rules/{write}.jsonl: {len(kept_book)} entries (failing changes dropped or reverted)"]
    L = L[:2] + [f"**{verdict}** · cost ${c_b + c_n + c_r + c_p:.2f}", ""] + L[2:]
    note(f"{verdict}: entries working {len(J['works'])}/{n_eff}, lost {len(J['lost'])}, "
         f"revisions not fixed {len(J['not_fixed'])}" + (f"; dropped or reverted: {', '.join(bad)}" if bad else "")
         + f"; ${c_b + c_n + c_r + c_p:.2f}; report reports/vet_{book}.md",
         {"ALL KEPT": "ok", "PARTLY KEPT": "ok", "NONE KEPT": "err"}.get(verdict, "warn"))
    (REPORTS / f"vet_{book}.md").write_text("\n".join(L) + "\n")
    return "\n".join(L)


def _citing(d: pathlib.Path, t: str, ids: set, cfg: Config) -> tuple[int, int] | None:
    """(findings citing any of `ids`, those judged refuted) in run dir `d` on sample `t` (#pr@commit8);
    None if the sample has no run there. A run with no score (no findings) counts (0, 0)."""
    f = next(iter(d.glob(f"{t.replace('@', '-')}*.json")), None) if d.exists() else None
    if f is None:
        return None
    cite = {x["id"] for x in json.loads(f.read_text()).get("findings") or [] if finding_rules(x) & ids}
    sp = cfg.data / "scores" / d.name / f.name
    if not cite or not sp.exists():
        return len(cite), 0
    return len(cite), sum(1 for a in json.loads(sp.read_text()).get("ai") or [] if a["id"] in cite and refuted(a))


def _refuted_findings(d: pathlib.Path, ts: list[str], ids: set, cfg: Config, n: int = 4) -> list[dict]:
    """Up to `n` refuted findings citing `ids` in run dir `d` on samples `ts`: {target, title, why}."""
    out = []
    for t in ts:
        f = next(iter(d.glob(f"{t.replace('@', '-')}*.json")), None)
        sp = cfg.data / "scores" / d.name / f.name if f else None
        if not f or not sp.exists():
            continue
        fs = {x["id"]: x for x in json.loads(f.read_text()).get("findings") or [] if finding_rules(x) & ids}
        out += [{"target": t, "title": fs[a["id"]].get("title"), "why": a.get("why")}
                for a in json.loads(sp.read_text()).get("ai") or [] if a["id"] in fs and refuted(a)]
    return out[:n]


def _proven(r: dict) -> set:
    """The comments entry `r` was shown to correct: its "corrected" tests (vet effect or an A/B)."""
    return {norm(c) for t in r.get("tests") or [] if t.get("result") == "corrected" for c in t.get("comments") or []}


def _with_tests(rules: list[dict], tests: dict[str, list[dict]]) -> list[dict]:
    """`rules` with vet's effect records appended to each entry's "tests" (one per target and comments)."""
    out = []
    for r in rules:
        old = r.get("tests") or []
        have = {(t.get("target"), tuple(t.get("comments") or [])) for t in old}
        add = [t for t in tests.get(r["id"], []) if (t["target"], tuple(t["comments"])) not in have]
        out.append({**r, "tests": old + add} if add else r)
    return out


def _passing(new_rules: list[dict], old_rules: list[dict], O: dict, J: dict, rel: dict) -> list[dict]:
    """NEW without the changes vet failed: new entries that never worked are dropped; entries that lost
    a source hit or whose revision did not fix its trigger go back to their base version, and new
    entries linked to a lost entry are dropped with it (vet cannot tell which link caused the loss).
    A dropped replacement restores every entry it replaced. An existing entry that did not fire on a
    comment added to it also goes back to its base version: the comment leaves its evidence (it returns
    to the ledger to be tried again, where it counts as new evidence), and so does any revision made
    in the same change."""
    old_all = {r["id"]: r for r in old_rules}
    lost = {i for i, _ in J["lost"]} | {i for i, _ in J["not_fixed"]}
    back = {i for i in J["no_effect"] if i in O}  # reverted alone: its links did not cause the miss
    drop = {i for i in J["no_effect"] if i not in O}
    lost |= {i for i in J.get("too_wide") or [] if i in old_all}  # too wide: back to the base text
    drop |= {i for i in J.get("too_wide") or [] if i not in old_all}  # a new too-wide entry: dropped
    drop |= {x for i in lost for x in rel.get(i, set()) if x not in old_all}
    # a regroup (n -> m) is kept or undone whole: one dropped entry drops the others of its group
    gids = {r["regroup"] for r in new_rules if r["id"] in drop and r.get("regroup")}
    drop |= {r["id"] for r in new_rules if r.get("regroup") in gids and r["id"] not in old_all}
    # a dropped replacement gives back every entry it replaced, not only the one that lost a comment
    lost |= {r["id"] for r in new_rules if (r.get("retired") or {}).get("replaced_by") in drop
             or ((r.get("retired") or {}).get("regroup") in gids and r["id"] in old_all)}
    out = []
    for r in new_rules:
        if r["id"] in drop:
            continue
        r = dict(old_all[r["id"]]) if r["id"] in lost | back and r["id"] in old_all else dict(r)
        if r.get("principle") in drop:
            r["principle"] = old_all.get(r["id"], {}).get("principle")
        if r.get("members"):
            r["members"] = [m for m in r["members"] if m not in drop]
        out.append(r)
    return out

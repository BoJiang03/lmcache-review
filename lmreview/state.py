"""The review process state: one prompt, one rulebook in use, its versions, and the ledger.

    runs     = review(samples, reviewer=current())                  # cached by reviewer name
    ledger   = judge(runs, human_comments)                          # which comments are still to learn
    cand     = distill(book, ledger.to_distill)                     # a candidate book, not used yet
    book'    = vet(book, cand)                                      # promote what works, record what failed

A sample is one commit of a PR that a human reviewed (`#pr@commit8`), and its human comments are the
ground truth. Layout (lmreview/state/, versioned in git):

    HEAD.json              {"version": N, "updated"}: the book in use is history/vNNNN.jsonl
    book.jsonl             a copy of the book in use (what readers open)
    history/vNNNN.jsonl    every version, never rewritten; vNNNN.meta.json: parent, date, how it was made
    candidate/             at most one distill result waiting for vet: book.jsonl (+ .meta.json, .md), meta.json
    ledger.jsonl           one row per human comment that entered the process (see LEDGER)
    prompts/p<sha8>.md     every reviewer prompt ever used, by content hash (runs name it)
    log.jsonl              one line per step: review / judge / distill / vet / promote / rollback

Configuration lives in git, edited by people: the prompts (lmreview/prompts/reviewer.md, rulecheck.md,
rulepick.md) and lmreview/config.toml (see settings.py). Runs and scores stay in <data>/runs and
<data>/scores (not in git), under the reviewer name `p<sha8>+vNNNN@<effort>-rc`, so a new
prompt, book or review setting never mixes with old runs. Each version's meta records the settings
that made it.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import re
import shutil

from typing import Callable, Iterator

from .config import PROMPTS, RULES, Config
from .annotate import TIERS, cid_of, entry_severity, norm, severities, tier
from .settings import get, settings
from .progress import note, step

STATE = pathlib.Path(os.environ.get("LMREVIEW_STATE") or get("paths", "state")
                     or pathlib.Path(__file__).resolve().parent / "state")
MAX_TRIES = max(get("tiers", "max_tries").values())  # the most distill attempts any point gets (see tier_limit)


def row_tier(r: dict, sev: dict[str, str]) -> str:
    """The severity tier of a ledger row; a point without a severity counts as minor."""
    return tier(sev.get(str(r["comment"]))) or "minor"


def tier_limit(key: str, r: dict, sev: dict[str, str]) -> int:
    """[tiers] `key` for row `r`'s tier."""
    return int(get("tiers", key)[row_tier(r, sev)])

LEDGER = """ledger.jsonl rows: {"comment" (a point key: the comment id, or "<comment id>:<k>" for point k
of a comment that makes several, see annotate.py), "pr", "commit", "status", "reviewer" (whose run judged it),
"tries": [{"book", "entries", "result", "why", "date"}], "resolved_by": {"book", "entry"}, "note"}; a miss
confirmed by a second run (confirm_misses) also has "hits" ("0/2": missed twice; "1/2": found in the second
run) and "flaky": true when found in some run, or "unconfirmed": true when the second run could not be made.
status: covered (the reviewer found it without help) | to_distill | resolved (a book entry makes the
reviewer find it, checked by vet) | not_rulable (distill, two calls agreed: context / not an
issue / declined by the team) | needs_human ([tiers] max_tries distill attempts failed, only the PR author
objected to it: contested, or the two attribution calls disagreed: unclear).
retain adds "retained" ({"reviewer", "hits", "date"}) to a row caught often enough, or "unretained" to a
minor / nit row past its retain requeues (vet adds it to a nit row a new book stops catching: [tiers] vet_tolerate). A row's severity is not stored: it is its point's annotation (annotate.severities), and its tier
(annotate.tier: major+ / minor / nit) is what status and retain report by."""
STATUSES = ("covered", "to_distill", "resolved", "not_rulable", "needs_human")
_VER = re.compile(r"v\d{4}")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _meta(path: pathlib.Path) -> pathlib.Path:
    return path.with_name(path.stem + ".meta.json")


def _write(path: pathlib.Path, text: str) -> None:
    """Atomic write: a crash leaves the old file or the new one, never half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def _jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


@contextlib.contextmanager
def lock() -> Iterator[None]:
    """Only one state-changing step at a time (judge, distill, vet, rollback)."""
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / ".lock", "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f"another lmreview step holds {STATE / '.lock'}") from None
        yield


def log(step: str, **kw: object) -> None:
    """Append one line to log.jsonl."""
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / "log.jsonl", "a") as f:
        f.write(json.dumps({"time": _now(), "step": step, **kw}) + "\n")


# ---- books --------------------------------------------------------------------------------------

def vname(n: int) -> str:
    """Version name: 3 -> v0003."""
    return f"v{n:04d}"


def book_path(name: str) -> pathlib.Path:
    """Where rulebook `name` lives: vNNNN in history, the candidate's name in candidate/, else rules/."""
    if _VER.fullmatch(name):
        return STATE / "history" / f"{name}.jsonl"
    c = STATE / "candidate" / "meta.json"
    if c.exists() and json.loads(c.read_text()).get("name") == name:
        return STATE / "candidate" / "book.jsonl"
    return RULES / f"{name}.jsonl"


def head() -> int:
    """Version number of the book in use (0: none yet)."""
    p = STATE / "HEAD.json"
    return json.loads(p.read_text())["version"] if p.exists() else 0


def load_book(name: str) -> list[dict]:
    """The entries of rulebook `name` (see book_path)."""
    return [json.loads(l) for l in book_path(name).open() if l.strip()]


def version_meta(n: int) -> dict:
    """history/vNNNN.meta.json of version `n` ({} if none)."""
    p = _meta(STATE / "history" / f"{vname(n)}.jsonl")
    return json.loads(p.read_text()) if p.exists() else {}


def book_markdown(rules: list[dict], name: str) -> str:
    """A readable view of a rulebook for people (book.jsonl stays the source): active entries by kind,
    each with when / expect / why, then one line per retired entry."""
    act = [r for r in rules if r.get("status", "active") == "active"]
    sev = severities(Config())
    words = sum(len(f"{r.get('when', '')} {r.get('expect', '')}".split()) for r in act)
    L = [f"# Rulebook {name}", "", f"{len(act)} active entries, {words} words (when + expect; the reviewer sees "
         "these, not why or examples). Generated from book.jsonl; do not edit.", ""]
    for kind in ("principle", "knowledge"):
        ks = sorted((r for r in act if r.get("kind", "principle") == kind), key=lambda r: r["id"])
        if ks:
            L += [f"## {kind.capitalize()} ({len(ks)})", ""]
        for r in ks:
            L += [f"### {r['id']}", "", f"**When** {r.get('when', '')}", "", f"**Expect** {r.get('expect', '')}", ""]
            if r.get("why"):
                L += [f"*Why (record only)*: {r['why']}", ""]
            L += [f"<sub>v{r.get('version', 1)} · {entry_severity(r, sev) or 'no'} severity · area {r.get('area') or 'overall'} · "
                  f"{len(r.get('evidence') or [])} comments from {r.get('n_prs', 0)} PRs</sub>", ""]
    ret = [r for r in rules if r.get("status") == "retired"]
    if ret:
        L += [f"## Retired ({len(ret)})", ""] + [f"- {r['id']}: {r.get('concern') or r.get('when', '')[:100]}"
                                                for r in sorted(ret, key=lambda r: r["id"])]
    return "\n".join(L) + "\n"


def new_version(rules: list[dict], parent: int | None, **meta: object) -> int:
    """Write `rules` as the next version and make it the book in use. Returns its number."""
    n = max([int(p.stem[1:]) for p in (STATE / "history").glob("v*.jsonl")] or [0]) + 1
    _write(STATE / "history" / f"{vname(n)}.jsonl", _jsonl(rules))
    made_with = {k: settings()[k] for k in ("review", "judge", "annotate", "distill", "vet")}
    _write(_meta(STATE / "history" / f"{vname(n)}.jsonl"), json.dumps({"version": n, "parent": parent, "date": _now(),
                                                                "settings": made_with, **meta}, indent=1) + "\n")
    _write(STATE / "book.jsonl", _jsonl(rules))
    _write(STATE / "book.md", book_markdown(rules, vname(n)))
    _write(STATE / "HEAD.json", json.dumps({"version": n, "updated": _now()}, indent=1) + "\n")
    log("promote", version=n, parent=parent, **{k: v for k, v in meta.items() if k in ("by", "from")})
    return n


def rollback(to: int) -> int:
    """Make version `to` the book in use again, as a new version (history is never rewritten)."""
    with lock():
        return new_version(load_book(vname(to)), head(), by="rollback", **{"from": vname(to)})


# ---- the reviewer ---------------------------------------------------------------------------------

def config() -> dict:
    """The [review] settings (config.toml): effort and the rule check's."""
    return dict(settings()["review"])


def suffix(book: bool = True) -> str:
    """The reviewer-name suffix after @<effort>: -rc with a book (no rule check without one)."""
    return "-rc" if book else ""


PARTS = ("rulecheck", "rulepick")  # the other agents' prompts, versioned with reviewer.md


def prompt_id(save: bool = False) -> str:
    """`p<sha8>` of lmreview/prompts/reviewer.md, rulecheck.md and rulepick.md together, so editing any of
    them gives the reviewer a new name. With `save` (before a run uses it), their texts are kept in
    state/prompts/ (<id>.md, <id>.rulecheck.md, <id>.rulepick.md, <id>.params.json) so old runs stay
    reproducible."""
    texts = {"": (PROMPTS / "reviewer.md").read_text(), **{k: (PROMPTS / f"{k}.md").read_text() for k in PARTS}}
    # the staging threshold and the rule check's effort change its verdicts, so they are part of the name too
    stage = f"\0stage={get('review', 'rulecheck_stage_words')}\0rce={get('review', 'rulecheck_effort')}"
    pid = "p" + hashlib.sha256(("\0".join(texts.values()) + stage).encode()).hexdigest()[:8]
    files = {(f"{pid}.{k}.md" if k else f"{pid}.md"): text for k, text in texts.items()}
    files[f"{pid}.params.json"] = json.dumps(_params(), sort_keys=True) + "\n"
    for name, text in files.items():
        p = STATE / "prompts" / name
        if save and not p.exists():
            try:
                _write(p, text)
            except OSError:  # an installed copy may be read-only; the current files are found by hash
                pass
    return pid


PARAMS = ("rulecheck_effort", "rulecheck_stage_words")  # [review] settings hashed into the prompt id


def _params() -> dict:
    """The current values of the [review] settings in PARAMS."""
    return {k: get("review", k) for k in PARAMS}


def prompt_params(version: str) -> dict:
    """The PARAMS values prompt version `version` was named with: kept in state/prompts/<id>.params.json
    when the id was saved; the current config for the current version before it is saved.

    Args:
        version: a prompt version (p<sha8>).

    Returns:
        {setting: value} for every name in PARAMS.
    """
    p = STATE / "prompts" / f"{version}.params.json"
    return {**_params(), **json.loads(p.read_text())} if p.exists() else _params()


def part_path(version: str, part: str) -> pathlib.Path:
    """The `part` prompt ("rulecheck" or "rulepick") of prompt version `version`: kept in state/prompts once
    saved; the current file for the current version."""
    p = STATE / "prompts" / f"{version}.{part}.md"
    if p.exists() or version == prompt_id():
        return p if p.exists() else PROMPTS / f"{part}.md"
    raise FileNotFoundError(f"prompt {version} has no {p.name} in {STATE / 'prompts'}")


def prompt_path(version: str) -> pathlib.Path:
    """The prompt file of prompt version `version` (p<sha8>): from state/prompts, else the current reviewer.md."""
    p = STATE / "prompts" / f"{version}.md"
    if p.exists():
        return p
    if version == prompt_id():
        return PROMPTS / "reviewer.md"
    raise FileNotFoundError(f"prompt {version} is neither in {STATE / 'prompts'} nor the current reviewer.md")


def reviewer(book: str | None = None) -> str:
    """The reviewer name of the current prompt and config with `book` (default: the book in use). Learning
    (round, judge, distill) reviews with it too: it learns from what production misses (2026-11-26)."""
    c = config()
    book = book or (vname(head()) if head() else None)
    return f"{prompt_id()}" + (f"+{book}" if book else "") + f"@{c['effort']}" + suffix(bool(book))


# ---- the ledger -------------------------------------------------------------------------------------

def ledger() -> dict[int, dict]:
    """The ledger rows by comment id (see LEDGER)."""
    p = STATE / "ledger.jsonl"
    return {r["comment"]: r for r in map(json.loads, p.open()) if r} if p.exists() else {}


def save_ledger(rows: dict[int, dict]) -> None:
    """Write the ledger, sorted by sample and comment."""
    _write(STATE / "ledger.jsonl", _jsonl(sorted(rows.values(), key=lambda r: (r["pr"], r["commit"], str(r["comment"])))))


def outcomes() -> dict[str, dict[str, list[str]]]:
    """Per entry: the judged findings of learning reviews that cited it, as "helpful" (judged valid) and
    "harmful" (refuted: the judge and a second opinion agree it is wrong). Keys are
    "<reviewer> <pr>@<commit8> <finding id>", so a run judged again is counted once."""
    p = STATE / "outcomes.json"
    return json.loads(p.read_text()) if p.exists() else {}


def record_outcomes(rv: str, judged: list) -> dict[str, int]:
    """Add the outcomes of the judged runs `judged` ([(run, score)]) of reviewer `rv` to outcomes()."""
    from .schema import cites
    from .score import refuted
    rec, n = outcomes(), {"helpful": 0, "harmful": 0}
    for run, sc in judged:
        verdict = {a["id"]: a for a in sc.get("ai") or []}
        for x in run.get("findings") or []:
            a = verdict.get(x["id"])
            kind = None if a is None else "harmful" if refuted(a) else "helpful" if a.get("valid") is True else None
            if not kind:
                continue  # unsure, or one call against it: not evidence either way
            key = f"{rv} {run['pr']}@{run['commit'][:8]} {x['id']}"
            for r in cites(x):
                ks = rec.setdefault(r, {"helpful": [], "harmful": []})[kind]
                if key not in ks:
                    ks.append(key)
                    n[kind] += 1
    _write(STATE / "outcomes.json", json.dumps(rec, indent=1, sort_keys=True) + "\n")
    return n


def sample(r: dict) -> str:
    """The sample of a ledger row: #pr@commit8."""
    return f"#{r['pr']}@{r['commit'][:8]}"


def to_distill(rows: dict[int, dict] | None = None, prs: set[int] | None = None) -> list[dict]:
    """Ledger rows still to learn (only on `prs`, if given)."""
    rows = ledger() if rows is None else rows
    return [r for r in rows.values() if r["status"] == "to_distill" and (not prs or r["pr"] in prs)]


def distill_order(r: dict) -> tuple:
    """Sort key of to_distill rows: flaky misses (found in some run, see confirm_misses) after the ones
    missed in every run, then by sample and comment."""
    return bool(r.get("flaky")), r["pr"], r["commit"], str(r["comment"])


def tries_note(r: dict) -> str:
    """What earlier distill attempts made of this comment, for the next attempt."""
    def rc(t: dict) -> str:  # the rule check's own verdict on the tried entry, on this comment's sample
        return "".join(f"; the rule check said of {v['entry']}: applies={v.get('applies')}, "
                       f"violated={v.get('violated')}: {v.get('why')}" for v in t.get("rulecheck") or [])
    return " | ".join(f"attempt {i + 1} ({t['book']}, entries {t.get('entries') or 'none'}): {t['result']}"
                      + (f" ({t['why']}{rc(t)})" if t.get("why") else "") for i, t in enumerate(r.get("tries") or []))


MAX_REQUEUES = int(get("distill", "max_requeues"))  # times a parked (needs_human) comment is given another chance


def distill_prompt_id() -> str:
    """Short hash of the prompts that decide what is learned and how (attribute, write, consolidate):
    a parked comment is retried once they change."""
    from . import distill as d
    return hashlib.sha256("\0".join((d.ATTRIBUTE, d.WRITE, d.MERGE_WRITE, d.GENERAL, d.CONSOLIDATE)).encode()).hexdigest()[:8]


NO_EFFECT = "the reviewer did not apply the entry"


def tested_entries(r: dict, book: dict, text: Callable) -> set[str]:
    """Entries of `book` that vet actually ran on ledger row `r`'s comment, without effect, in their
    current text. A try only counts when vet tested the entry there (NO_EFFECT) and the try records the
    book after it ("after", since 2026-11-24) with the same text: an entry that only appeared in a try,
    was promoted untested, or changed since, has not been tried on this comment."""
    done = set()
    for t in r.get("tries") or []:
        ver = t.get("after")
        if t.get("why") != NO_EFFECT or not ver or not book_path(ver).exists():
            continue
        was = {e["id"]: e for e in load_book(ver)}
        done |= {e for e in t.get("entries") or [] if e in book and e in was and text(book[e]) == text(was[e])}
    return done


def requeue_parked(max_cost: float = 0.5, cfg: Config | None = None) -> set[int]:
    """Give parked (needs_human) comments another chance when the workflow has changed where it matters,
    at most MAX_REQUEUES times each; returns the PRs of the comments put back to to_distill.

    - the distill prompts (attribute, write, consolidate) changed since it was parked;
    - parked after failed attempts: the book in use has an entry the attempts did not have. One COVERAGE
      call per batch lists the active entries each comment is an instance of, plus those holding it as
      evidence; a comment is requeued
      when one of them was not actually tested on it in its current text (tested_entries).
    A person's decision (a note starting "human") is never reopened."""
    from .distill import COVERAGE, BATCH, _ask, _fmt, _id
    from .budget import capped_map
    from .score import load_gold
    cfg, rows = cfg or Config(), ledger()
    parked = [r for r in rows.values() if r["status"] == "needs_human" and r.get("requeues", 0) < MAX_REQUEUES
              and not str(r.get("note") or "").startswith("human")]
    if not parked or not head():
        return set()
    book = {r["id"]: r for r in load_book(vname(head())) if r.get("status", "active") == "active"}
    text = lambda r: (r.get("when"), r.get("expect"), r.get("examples"))  # noqa: E731
    back: dict = {}
    pid = distill_prompt_id()
    for r in parked:
        if (r.get("parked") or {}).get("prompt") != pid:
            back[r["comment"]] = "the distill prompts changed since it was parked"
    tried = [r for r in parked if r["comment"] not in back and r.get("tries")]
    if tried and max_cost > 0:
        _, cm = load_gold(cfg)
        cs = [cm[r["comment"]] for r in tried if r["comment"] in cm]
        rtext = "\n".join(f"{i}: when {r.get('when')} -> {r.get('expect')}" for i, r in book.items())
        res, _ = capped_map(lambda b: _ask(COVERAGE.format(rules=rtext, comments="\n\n".join(_fmt(c, False) for c in b)),
                                           "high", cfg), [cs[i:i + BATCH] for i in range(0, len(cs), BATCH)], 2,
                            max_cost, label=lambda b: f"parked coverage {len(b)}")
        hits = {_id(x.get("id")): [e for e in x.get("rules") or [] if e in book]
                for part in res if isinstance(part, list) for x in part if isinstance(x, dict)}
        for r in tried:  # entries that already hold the comment as evidence cover it: no guess needed
            own = [i for i, e in book.items() if norm(r["comment"]) in {norm(x) for x in e.get("evidence") or []}]
            hits[r["comment"]] = list(dict.fromkeys(own + (hits.get(r["comment"]) or [])))
            done = tested_entries(r, book, text)
            new = [e for e in hits.get(r["comment"]) or [] if e not in done]
            if new:
                back[r["comment"]] = f"the book has changed entries for it: {', '.join(new)}"
    if not back:
        return set()
    with lock():  # re-read under the lock: another command may have written the ledger meanwhile
        rows = ledger()
        back = {c: w for c, w in back.items() if c in rows and rows[c]["status"] == "needs_human"}
        for c, why in back.items():
            _requeue(rows[c], why)
        save_ledger(rows)
        log("requeue", comments=[str(c) for c in back])
    return {rows[c]["pr"] for c in back}


def _requeue(r: dict, why: str) -> None:
    """Put a parked ledger row back to to_distill, with a fresh MAX_TRIES budget."""
    r.update(status="to_distill", requeues=r.get("requeues", 0) + 1, requeued_at=len(r.get("tries") or []),
             requeued={"date": _now()[:10], "book": vname(head()), "why": why})
    note(f"  requeued #{r['pr']} c{r['comment']}: {why}")


def judge(split: str = "train", prs: set[int] | None = None, max_cost: float = 10.0, rv: str | None = None,
          cfg: Config | None = None) -> str:
    """Judge the current reviewer's runs on `split` against the human comments and file every
    change-request / nit comment in the ledger: found -> covered, missed -> to_distill. A comment
    already in the ledger keeps its row, except that a to_distill comment found now becomes resolved
    (the book in use found it). Samples without such comments count as no ground truth."""
    from .score import judge_runs
    if split != "train":  # the ledger feeds distill, which must never learn from test / new
        raise ValueError("judge files comments for distill: only the train split")
    cfg, rv = cfg or Config(), rv or reviewer()
    with lock(), step("judge", f"runs of {rv} on {split}" + (f", PRs {sorted(prs)}" if prs else "")
                      + f"; cap ${max_cost:.0f}") as st:
        judged, cost = judge_runs(cfg, rv, prs, split, max_cost)
        st.cost = cost
        rows, n = ledger(), {"covered": 0, "to_distill": 0, "resolved": 0, "no_gt": 0}
        from .score import WANT, hkey, load_gold
        _, cm = load_gold(cfg)
        for run, s in judged:
            hs = [h for h in s["human"] if h["type"] in WANT]
            if not hs:
                n["no_gt"] += 1
            for h in hs:
                c = hkey(s, h)  # a point: the comment id, or "<comment id>:<k>" in a comment of several points
                r = rows.get(c) or rows.get(cid_of(c))  # a row filed before comments were split covers its points
                if r is None:
                    status_ = "covered" if h["matched_ai"] else "to_distill"
                    rows[c] = {"comment": c, "pr": run["pr"], "commit": run["commit"], "status": status_,
                               "reviewer": rv, "tries": []}
                    n[status_] += 1
                elif r["status"] == "to_distill" and h["matched_ai"]:
                    r.update(status="resolved", resolved_by={"book": rv, "entry": None})
                    n["resolved"] += 1
        save_ledger(rows)
        o = record_outcomes(rv, judged)  # what each entry's citations were worth, for distill's signals
        log("judge", reviewer=rv, runs=len(judged), cost=round(cost, 2), **n, **{f"cited_{k}": v for k, v in o.items()})
        st.result = ", ".join(f"{k} {v}" for k, v in n.items()) + f"; rule citations: {o['helpful']} helpful, {o['harmful']} harmful"
    return f"judged {len(judged)} runs of {rv} (${cost:.2f}): " + ", ".join(f"{k} {v}" for k, v in n.items())


def status() -> str:
    """Book in use, candidate, ledger counts by status and by sample."""
    rows, n = ledger(), head()
    by = {s: [r for r in rows.values() if r["status"] == s] for s in STATUSES}
    samples: dict[str, set] = {}
    for r in rows.values():
        samples.setdefault(sample(r), set()).add(r["status"])
    open_ = {k for k, v in samples.items() if "to_distill" in v}
    solved = {k for k, v in samples.items() if "resolved" in v and not v & {"to_distill", "needs_human"}}
    c = STATE / "candidate" / "meta.json"
    cand = json.loads(c.read_text()) if c.exists() else None
    m = version_meta(n)
    L = [f"book in use: {vname(n)} ({len(load_book(vname(n)))} entries; {m.get('by', '')} {m.get('date', '')[:10]})"
         if n else "book in use: none", f"reviewer: {reviewer()}",
         f"candidate: {cand['name']} (attempt {cand.get('attempt')}, {len(cand.get('comments') or [])} comments), "
         f"run `lmreview vet`" if cand else "candidate: none",
         f"ledger: {len(rows)} comments on {len(samples)} samples: "
         + ", ".join(f"{s} {len(by[s])}" for s in STATUSES),
         f"samples: {len(solved)} solved by the book, {len(open_)} with comments to distill"]
    sev = severities(Config())
    for t in TIERS + (None,):
        rs = [r for r in rows.values() if tier(sev.get(str(r["comment"]))) == t]
        if rs:
            L.append(f"  {t or 'no severity'}: {len(rs)}: " + ", ".join(f"{s} {k}" for s in STATUSES
                                                                      if (k := sum(r['status'] == s for r in rs)))
                     + f"; retained {sum(1 for r in rs if r.get('retained'))}")
    if n:
        L.append("size (active entries, words, comments explained; fewer words per comment = more general): "
                 + " | ".join(f"{vname(v)}: " + ", ".join(map(str, book_size(load_book(vname(v)))))
                              for v in range(max(1, n - 3), n + 1)))
    return "\n".join(L)


def book_size(rules: list[dict]) -> tuple[int, int, int]:
    """(active entries, words of their when/expect/why, distinct evidence comments): a book that explains
    the same comments in fewer words generalizes better."""
    act = [r for r in rules if r.get("status", "active") == "active"]
    words = sum(len(str(r.get(k) or "").split()) for r in act for k in ("when", "expect", "why"))
    return len(act), words, len({e for r in act for e in r.get("evidence") or []})


# ---- candidate -----------------------------------------------------------------------------------

def candidate() -> dict | None:
    """candidate/meta.json ({"name", "parent", "comments", "created"}), or None."""
    c = STATE / "candidate" / "meta.json"
    return json.loads(c.read_text()) if c.exists() else None


def candidate_name() -> str:
    """Name of the next candidate: `v<next>c<k>`, k counting the attempts on this book."""
    n, p = head(), STATE / "log.jsonl"
    k = sum(1 for x in map(json.loads, p.open()) if x["step"] in ("distill", "compress") and x.get("parent") == n) \
        if p.exists() else 0
    return f"{vname(n + 1)}c{k + 1}"


def clear_candidate() -> None:
    """Remove candidate/."""
    shutil.rmtree(STATE / "candidate", ignore_errors=True)


def init(book: str, note: str = "") -> int:
    """Start the state as v0001 (only when there is no state yet) from rulebook `book`: a .jsonl path (an
    empty file starts from no entries), or a name under rules/."""
    if head():
        raise RuntimeError(f"state already at {vname(head())}")
    p = pathlib.Path(book) if book.endswith(".jsonl") else RULES / f"{book}.jsonl"
    with lock():
        return new_version([json.loads(l) for l in p.open() if l.strip()], None, by="init", **{"from": str(p)}, note=note)


def discard() -> str:
    """Drop the candidate without vetting it (its comments stay to_distill, no attempt is counted)."""
    with lock():
        c = candidate()
        clear_candidate()
        if c:
            log("discard", name=c["name"])
        return f"discarded {c['name']}" if c else "no candidate"


# ---- the steps -----------------------------------------------------------------------------------

def distill_step(prs: set[int] | None = None, limit: int | None = None, effort: str | None = None, workers: int = 4,
                 max_cost: float | None = None, cfg: Config | None = None, compress: bool = False) -> str:
    """Distill the ledger's to_distill comments (only on `prs`, if given) into a candidate built on the
    book in use. Earlier failed attempts are passed on, so the next one is written differently.
    Comments distill finds not learnable (context, not an issue, declined) become not_rulable."""
    from .distill import distill
    cfg = cfg or Config()
    d = settings()["distill"]
    effort = effort or d["effort"]
    max_cost = get("budget", "distill") if max_cost is None else max_cost
    with lock():
        if not head():
            raise RuntimeError("no book in use: `lmreview init <rules name>` first")
        if candidate():
            raise RuntimeError(f"candidate {candidate()['name']} is waiting: `lmreview vet` it or `lmreview discard`")
        rows = ledger()
        todo = sorted(to_distill(rows, prs), key=distill_order)[:limit]
        if not todo and not compress:
            return "nothing to distill: no to_distill comments" + (f" on {sorted(prs)}" if prs else "")
        name, parent = candidate_name(), head()
        ids = [r["comment"] for r in todo]
        n_retry = sum(bool(r.get("tries")) for r in todo)
        note(f"▶ distill {len(ids)} comments on {len({sample(r) for r in todo})} samples"
             + (f" ({n_retry} retried after a failed attempt)" if n_retry else "")
             + f" into candidate {name} on {vname(parent) if parent else 'an empty book'}; cap ${max_cost:.0f}")
        _write(STATE / "candidate" / "meta.json", json.dumps(
            {"name": name, "parent": parent, "comments": ids, "created": _now()}, indent=1) + "\n")
        try:
            msg = distill(name, vname(parent), reviewer(), effort=effort, workers=workers,
                          max_cost=max_cost, cfg=cfg, comments=ids, prs=sorted({r["pr"] for r in todo}) or None,
                          notes={r["comment"]: tries_note(r) for r in todo if r.get("tries")}, tidy=compress)
        except BaseException:
            clear_candidate()
            raise
        if max_cost <= 0:
            clear_candidate()
            return msg
        att = cfg.data / "distill" / name / "attribution.jsonl"
        n_out = 0
        for a in map(json.loads, att.open()) if att.exists() else []:
            r = rows.get(a.get("id"))
            if r and a.get("kind") in ("context", "not_issue", "rejected"):  # two calls agreed (distill.py)
                r.update(status="not_rulable", note=f"{a['kind']}: {a.get('reason') or a.get('why') or ''}"[:300])
                n_out += 1
            elif r and a.get("kind") in ("contested", "unclear"):  # only the PR author objected, or the two
                # attribution calls disagreed on whether it is learnable: a person decides
                r.update(status="needs_human", note=f"{a['kind']}: {a.get('why') or ''}"[:300],
                         parked={"by": "attribute", "prompt": distill_prompt_id(), "date": _now()[:10]})
                n_out += 1
        save_ledger(rows)
        log("distill", name=name, parent=parent, comments=len(ids), not_rulable=n_out, summary=msg)
        note(f"✓ distill: {msg}; {n_out} not rulable")
        return f"candidate {name}: {msg}; {n_out} comments not rulable. Next: `lmreview vet`"


def compress_feedback() -> list[dict]:
    """Merges and absorbs of compress that vet undid: {group, op, candidate, lost: [{entry, comment, body}], date}."""
    p = STATE / "compress.jsonl"
    return [json.loads(l) for l in p.open() if l.strip()] if p.exists() else []


def book_words(n: int | None = None) -> int:
    """Words in the active entries of a version: what every review loads.

    Args:
        n: the version (default: the book in use).

    Returns:
        The total size in words (when, expect, why) of its active entries.
    """
    from .distill import _size
    return sum(_size(r) for r in load_book(vname(head() if n is None else n)) if r.get("status", "active") == "active")


COMPRESS_STAGES = list(get("compress", "stages"))  # the passes of a round's compress, in order
COMPRESS_TRIES = int(get("compress", "tries"))  # compress + vet runs per round while vet undoes merges


def compress_if_big(vet_cost: float, cfg: Config | None = None) -> list[str]:
    """The last step of a round: when the book in use is over [compress] words, compress it and vet the
    candidate. Skipped when the last compress already ran on this same version (it found what it could).

    Args:
        vet_cost: the cap for vetting the compress candidate.
        cfg: data locations (default: Config()).

    Returns:
        Lines for the round's summary (empty when skipped).
    """
    cap, w = int(get("compress", "words")), book_words()
    if w <= cap:
        note(f"book {vname(head())}: {w} words, not over {cap}: no compress")
        return []
    p = STATE / "log.jsonl"
    tried = p.exists() and any(x["step"] == "compress" and x.get("parent") == head() for x in map(json.loads, p.open()))
    if tried:
        note(f"book {vname(head())}: {w} words, over {cap}, but compress already ran on this version")
        return []
    out = []
    for stage in COMPRESS_STAGES:  # e.g. trim, merge; each one full, then repairs of what vet undid
        for k in range(COMPRESS_TRIES):
            repair = k > 0
            note(f"book {vname(head())}: {book_words()} words: compress {stage}"
                 + (f" (repair {k}/{COMPRESS_TRIES - 1})" if repair else "") + ", then vet")
            res = compress_step(cfg=cfg, stage=stage, repair=repair)
            out.append(f"{stage}{' repair' if repair else ''}: {res}")
            if not candidate():
                break
            name = candidate()["name"]
            out.append(vet_step(vet_cost, cfg=cfg).split("\n\n")[-1])
            if candidate():
                note("vet INCOMPLETE (cost cap): candidate kept; rerun `lmreview vet` with a higher --max-cost")
                out.append(f"book {vname(head())}: {book_words()} words (was {w}); stopped: vet INCOMPLETE")
                return out
            if not [x for x in compress_feedback() if x.get("candidate") == name]:
                break  # vet undid nothing: no repair needed
    out.append(f"book {vname(head())}: {book_words()} words (was {w}; compress at > {cap})")
    return out


def compress_step(max_cost: float | None = None, cfg: Config | None = None, stage: str = "merge",
                  repair: bool = False) -> str:
    """Make the book in use smaller as a candidate; `lmreview vet` then keeps the changes that lose none of
    their entries' proven cases.

    Args:
        stage: "merge" (distill.compress: merge or regroup entries) or "trim" (distill.trim: each long entry
            rewritten shorter in place).
        repair: rewrite only what vet undid on the last candidate of this stage, shown with the rule check's
            reasons (compress.jsonl), instead of a full pass.
    """
    from . import llm
    from . import distill as D
    from .distill import compress
    max_cost = get("budget", "compress") if max_cost is None else max_cost
    with lock(), step("compress", f"book {vname(head())}; cap ${max_cost:.0f}") as st:
        if not head():
            raise RuntimeError("no book in use: `lmreview init <rules name>` first")
        if candidate():
            raise RuntimeError(f"candidate {candidate()['name']} is waiting: `lmreview vet` it or `lmreview discard`")
        name, parent, spent0 = candidate_name(), head(), llm.SPENT
        fb_all = compress_feedback()
        p = STATE / "log.jsonl"  # the last candidate of this stage: a repair redoes only what vet undid there
        last = next((x["name"] for x in reversed([json.loads(l) for l in p.open() if l.strip()] if p.exists() else [])
                     if x.get("step") == "compress" and x.get("stage", "merge") == stage), None)
        fb_last = [x for x in fb_all if x.get("candidate") == last]
        if repair and not fb_last:
            return "nothing to repair"
        _write(STATE / "candidate" / "meta.json", json.dumps(
            {"name": name, "parent": parent, "comments": [], "kind": "compress", "stage": stage, "repair": repair,
             "created": _now()}, indent=1) + "\n")
        effort = str(get("distill", "effort"))
        try:
            if stage == "merge":
                msg, k = compress(name, vname(parent), cfg, effort=effort, max_cost=max_cost, record=outcomes(),
                                  feedback=[x for x in fb_all if x.get("group") and (not repair or x.get("candidate") != last)]
                                  + (fb_last if repair else []),
                                  repair=repair, n=int(get("compress", "drafts")))
            else:
                D.TRIM_BASE, D.TRIM_PER = (int(x) for x in get("compress", "trim_budget"))
                fb = {x["entry"]: {"text": x["text"], "lost": x["lost"]} for x in fb_last} if repair else None
                msg, k = D.trim(name, vname(parent), cfg, effort=effort, max_cost=max_cost,
                                min_words=int(get("compress", "trim_words")), only=set(fb) if fb else None,
                                feedback=fb)
        except BaseException:
            clear_candidate()
            raise
        finally:
            D.TRIM_BASE, D.TRIM_PER = (int(x) for x in get("compress", "trim_budget"))
        st.cost = llm.SPENT - spent0
        log("compress", name=name, parent=parent, stage=stage, repair=repair, retired=k, cost=round(st.cost, 2),
            summary=msg)
        st.result = msg
        if not k:
            clear_candidate()
            return f"nothing to compress: {msg}"
        return f"candidate {name}: {msg}. Next: `lmreview vet`"


def vet_verdict(name: str, rule: str, comment, cfg: Config, where: dict | None = None) -> dict | None:
    """The rule check's verdict on entry `rule` in vet's runs of book `name` on `comment`'s sample: the run
    that shows why it was missed (not applied, or applied with nothing violated) if any, else the last one."""
    from .annotate import cid_of
    if where is None:
        from .score import load_gold
        gss, _ = load_gold(cfg)
        where = {int(x): k for k, sm in gss.items() for x in sm["gold_ids"]}
    k = where.get(cid_of(comment) if not isinstance(comment, int) else comment)
    if not k:
        return None
    vs = [v for d in sorted((cfg.data / "runs").glob(f"*+{name}@*"), key=lambda p: ("#r" in p.name, p.name))
          if (f := d / f"{k[0]}-{k[1][:8]}.json").exists()
          for v in json.loads(f.read_text()).get("verdicts") or [] if v.get("rule") == rule]
    seen = next((v for v in vs if not (v.get("applies") and v.get("violated"))), vs[-1] if vs else None)
    return {x: (str(seen.get(x))[:300] if x == "why" else seen.get(x)) for x in ("applies", "violated", "why")} \
        if seen else None


def compress_undone(name: str, parent_ids: set[str], cand: list[dict], J: dict,
                    cfg: Config) -> tuple[dict[str, list[str]], list[dict]]:
    """The groups of compress candidate `name` (a book whose parent has `parent_ids`) and the rows for those
    vet undid: {group, op, into, candidate, lost: [{entry, comment, body, check}], text}, where "check" is the
    rule check's verdict on the merged entry in vet's runs on that case. Reads only; see _record_compress."""
    from .annotate import cid_of
    from .score import load_gold
    gss, gcm = load_gold(cfg)
    by = {r["id"]: r for r in cand}
    where = {int(x): k for k, sm in gss.items() for x in sm["gold_ids"]}

    def check(t: str, e) -> dict | None:
        return vet_verdict(name, t, e, cfg, where)

    groups: dict[str, list[str]] = {}  # group key (a regroup's id, else the replacing entry) -> retired ids
    for r in cand:
        ret = r.get("retired") or {}
        t = ret.get("regroup") or ret.get("replaced_by")
        if r.get("status") == "retired" and t and ret.get("by") == name:
            groups.setdefault(t, []).append(r["id"])
    members = {t: [r["id"] for r in cand if r.get("regroup") == t] or [t] for t in groups}  # the new entries
    lost: dict[str, list[dict]] = {}
    for old, e in J["lost"]:
        ret = by.get(old, {}).get("retired") or {}
        t = ret.get("regroup") or ret.get("replaced_by")
        if t in groups:
            body = " ".join((gcm.get(cid_of(e)) or {}).get("body", "").split())[:160]
            ck = check(ret.get("replaced_by") or t, e)
            lost.setdefault(t, []).append({"entry": old, "comment": e, "body": body, "by": ret.get("replaced_by"),
                                           **({"check": ck} if ck else {})})
    rows = [{"group": sorted(groups[t] + ([t] if t in parent_ids else [])),
             "op": "absorb" if t in parent_ids else "regroup" if by.get(t, {}).get("regroup") else "merge",
             "into": t, "candidate": name, "lost": v, "date": _now()[:10],
             **({"text": {k: by[t].get(k) for k in ("when", "expect", "examples")}} if t in by else {}),
             **({"texts": [{"id": i, "from": by[i].get("replaces", []) + by[i].get("replaces_new", []),
                            **{k: by[i].get(k) for k in ("when", "expect", "examples")}} for i in members[t]]}
                if len(members[t]) > 1 else {})}
            for t, v in lost.items()]
    return groups, rows


def trim_undone(name: str, cand: list[dict], J: dict, cfg: Config) -> tuple[dict[str, list[str]], list[dict]]:
    """The entries trim candidate `name` rewrote, and rows for those vet put back: {entry, op: "trim",
    candidate, text (the short text that failed), lost: [{comment, body, check}], date}. Reads only."""
    from .annotate import cid_of
    from .score import load_gold
    gss, gcm = load_gold(cfg)
    where = {int(x): k for k, sm in gss.items() for x in sm["gold_ids"]}
    trimmed = {r["id"]: r for r in cand if (r.get("revised") or {}).get("by") == name
               and (r.get("revised") or {}).get("reason") == "trim"}
    lost: dict[str, list[dict]] = {}
    for i, e in J["lost"]:
        if i in trimmed:
            lost.setdefault(i, []).append({"comment": str(e), "check": vet_verdict(name, i, e, cfg, where),
                                           "body": " ".join(str((gcm.get(cid_of(e)) or gcm.get(e) or {})
                                                                .get("body", "")).split())[:200]})
    rows = [{"entry": i, "op": "trim", "candidate": name, "date": _now()[:10], "lost": v,
             "text": {k: trimmed[i].get(k) for k in ("when", "expect", "why")}}
            for i, v in lost.items()]
    return {i: [i] for i in trimmed}, rows


def _record_compress(c: dict, cand: list[dict], J: dict, cfg: Config) -> str:
    """After vet of a compress candidate: file the groups vet undid (compress_undone) for the next compress,
    and count refuted findings citing the new entries in vet's runs (recorded, not a gate).
    Returns a one-line summary."""
    from .schema import cites
    from .score import refuted
    stage = c.get("stage", "merge")
    if stage == "merge":
        groups, rows = compress_undone(c["name"], {r["id"] for r in load_book(vname(c["parent"]))}, cand, J, cfg)
    else:
        groups, rows = trim_undone(c["name"], cand, J, cfg)
    rows = [x | {"stage": stage} for x in rows]
    if rows:
        with (STATE / "compress.jsonl").open("a") as f:
            f.writelines(json.dumps(x) + "\n" for x in rows)
    new = set(groups)
    valid = bad = 0
    for d in (cfg.data / "runs").glob(f"*+{c['name']}@*"):
        for f in d.glob("*.json"):
            sp = cfg.data / "scores" / d.name / f.name
            if not sp.exists():
                continue
            verdict = {a["id"]: a for a in json.loads(sp.read_text()).get("ai") or []}
            for x in json.loads(f.read_text()).get("findings") or []:
                a = verdict.get(x["id"])
                if a and cites(x) & new:
                    bad += refuted(a)
                    valid += a.get("valid") is True
    return (f"compress {stage}: {len(groups) - len(rows)} of {len(groups)} kept; findings citing the new entries in "
            f"vet's runs: {valid} valid, {bad} refuted")


UNTESTED = "its entry was kept but not tested on this comment"


def counted_tries(r: dict) -> int:
    """Failed distill attempts that count toward [tiers] max_tries: those since the last requeue whose entry vet
    actually tested on the comment (an untested one says nothing about whether the comment is learnable)."""
    return sum(1 for t in r.get("tries", [])[r.get("requeued_at", 0):] if t.get("why") != UNTESTED)


def vet_step(max_cost: float | None = None, reps: int | None = None, everything: bool = False, cfg: Config | None = None) -> str:
    """Vet the candidate against the book in use. What works becomes the next version (the rest is
    dropped or reverted, see vet._passing); each comment of the candidate is then resolved, or gets a
    failed attempt (needs_human after its tier's max_tries). INCOMPLETE (cost cap) keeps the candidate for a rerun."""
    from .vet import vet
    max_cost = get("budget", "vet") if max_cost is None else max_cost
    reps = reps or int(get("vet", "reps"))
    sev = severities(cfg or Config())
    with lock():
        c = candidate()
        if not c:
            return "no candidate: run `lmreview distill` first"
        if c["parent"] != head():
            raise RuntimeError(f"the book moved to {vname(head())} since {c['name']} was distilled: `lmreview discard`")
        res: dict = {}
        note(f"▶ vet {c['name']} against {vname(c['parent'])} ({len(c['comments'])} comments); cap ${max_cost:.0f}")
        conf = config()
        report = vet(c["name"], vname(c["parent"]), prompt_id(), conf["effort"], "-ro",
                     reps=reps, max_cost=max_cost, everything=everything, cfg=cfg, out=res,
                     targets=set(c["comments"]))
        if max_cost <= 0 or not res:
            return report
        if res["verdict"] == "INCOMPLETE":
            log("vet", name=c["name"], verdict="INCOMPLETE", cost=round(res["cost"], 2))
            return report + "\n\nINCOMPLETE: candidate kept; rerun `lmreview vet` with a higher --max-cost (cached runs are free)"
        J, kept, cand = res["J"], res["kept"], load_book(c["name"])
        kept_ids = {r["id"] for r in kept if r.get("status", "active") == "active"}
        # what a dropped replacement lost: the next attempt is told, so it can write a broader entry that
        # still raises those points instead of falling back to adding a narrow entry beside the old ones
        from .score import load_gold
        _, gcm = load_gold(cfg or Config())
        replaced_by = {r["id"]: (r.get("retired") or {}).get("replaced_by") for r in cand}
        lost_by: dict[str, list[str]] = {}
        for old, e in J["lost"]:
            body = " ".join((gcm.get(cid_of(e)) or gcm.get(e) or {}).get("body", "").split())[:160]
            lost_by.setdefault(replaced_by.get(old) or "", []).append(f"{old} lost its proven case c{e}: {body!r}")
        ents: dict[int, list[str]] = {}
        par = {r["id"]: r for r in load_book(vname(c["parent"]))}
        old_ev = {norm(e) for r in par.values() for e in r.get("evidence") or []}
        tg = {norm(i) for i in c["comments"]}
        for r in cand:
            # an entry holding a target comment as evidence counts as its entry even when the parent already
            # held it (a revision made for it, or an earlier untested promotion): vet tests it there (targets)
            for e in r.get("evidence") or []:
                if norm(e) not in old_ev or norm(e) in tg:
                    ents.setdefault(norm(e), []).append(r["id"])
        comp = _record_compress(c, cand, J, cfg or Config()) if c.get("kind") == "compress" else ""
        if comp:
            note(comp)
        changed = _jsonl(kept) != _jsonl(load_book(vname(c["parent"])))
        n = new_version(kept, c["parent"], by="vet", **{"from": c["name"]}, verdict=res["verdict"],
                        report=f"reports/vet_{c['name']}.md") if changed else c["parent"]
        rows, out = ledger(), {"resolved": [], "failed": [], "needs_human": []}
        af = (cfg or Config()).data / "distill" / c["name"] / "attribution.jsonl"
        unconfirmed = {norm(a["id"]) for a in map(json.loads, af.open()) if a.get("kind") == "unconfirmed"} \
            if af.exists() else set()
        for i in c["comments"]:
            r = rows.get(i)
            if not r or r["status"] != "to_distill":
                continue
            es = ents.get(i, [])
            ok = [e for e in es if e in J["works"] and e in kept_ids]
            if ok:
                r.update(status="resolved", resolved_by={"book": vname(n), "entry": ok[0]})
                out["resolved"].append(i)
                continue
            why = ("attribution got no second answer (cost cap or unparsable output)" if not es and norm(i) in unconfirmed
                   else "distill made no entry for it" if not es else
                   NO_EFFECT if any(e in J["no_effect"] for e in es) else
                   "dropped: a linked change made an existing entry worse"
                   + ("; " + "; ".join(x for e in es for x in lost_by.get(e, [])) + ". A broader entry must also"
                      " make the reviewer raise these" if any(lost_by.get(e) for e in es) else "")
                   if not any(e in kept_ids for e in es) else
                   UNTESTED)
            tr = {"book": c["name"], "after": vname(n), "entries": es, "result": "failed", "why": why,
                  "date": _now()[:10]}
            # the rule check's own reason on this comment's sample, so the next write sees why it did not fire
            seen = [{"entry": x["entry"], **v} for x in res.get("rows") or [] if x["entry"] in es
                    and norm(i) in {norm(cc) for cc in x["comments"]} for v in x.get("verdicts") or []]
            if seen:
                tr["rulecheck"] = [dict(v, why=str(v.get("why") or "")[:300]) for v in seen[-2:]]
            r.setdefault("tries", []).append(tr)
            if counted_tries(r) >= tier_limit("max_tries", r, sev):
                r["status"] = "needs_human"
                r["parked"] = {"by": "vet", "prompt": distill_prompt_id(), "date": _now()[:10]}
                out["needs_human"].append(i)
            else:
                out["failed"].append(i)
        txt = lambda r: (r.get("status", "active"), r.get("when"), r.get("expect"))  # noqa: E731
        kept_by = {r["id"]: r for r in kept} if changed else {}
        new_text = {r["id"] for r in cand if r["id"] in kept_by and txt(kept_by[r["id"]]) == txt(r)}  # promoted as written
        for i, e in J.get("tolerated") or []:  # a nit the promoted book no longer catches: stays learned, marked
            r = rows.get(norm(e)) if i in new_text else None  # the entry was reverted or dropped: nothing lost
            if r and r["status"] in ("covered", "resolved"):
                r["unretained"] = {"by": "vet", "book": vname(n), "date": _now()[:10]}
                r.pop("retained", None)
        save_ledger(rows)
        clear_candidate()
        log("vet", name=c["name"], verdict=res["verdict"], cost=round(res["cost"], 2), version=n,
            **{k: len(v) for k, v in out.items()})
        note(f"✓ vet {res['verdict']}: " + (f"promoted {vname(n)}" if changed else f"book stays {vname(n)}") + "; "
             + ", ".join(f"{k} {len(v)}" for k, v in out.items()) + f"; ${res['cost']:.2f}",
             "ok" if out["resolved"] and not out["needs_human"] else "warn")
        for i in out["resolved"]:
            note(f"  resolved #{rows[i]['pr']}@{rows[i]['commit'][:8]} c{i} by {rows[i]['resolved_by']['entry']}", "add")
        for i in out["failed"] + out["needs_human"]:
            t = rows[i]["tries"][-1]
            note(f"  {'needs_human' if i in out['needs_human'] else 'retry later'} #{rows[i]['pr']}@{rows[i]['commit'][:8]} "
                 f"c{i}: {t['why']}", "drop" if i in out["needs_human"] else "change")
        return (report + (f"\n\n{comp}" if comp else "") + f"\n\n{'promoted ' + vname(n) if changed else 'no change kept; book stays ' + vname(n)}: "
                + ", ".join(f"{k} {len(v)}" for k, v in out.items())
                + ("; failed comments stay to_distill: `lmreview distill` tries again" if out["failed"] else ""))


def confirm_misses(rv: str, new: list[int | str], max_cost: float, cfg: Config | None = None,
                   found: list[int | str] | None = None) -> tuple[str, float]:
    """Run reviewer `rv` a second time (repeat #r2) on the samples of the misses `new` (ledger keys a judge
    just filed as to_distill) and judge it, so a miss the reviewer finds in some runs is told from one it
    never finds. Every miss stays to_distill (a rule can make a sometimes-found comment found every time);
    a found one gets "flaky" and goes to distill after the others. Counts come from runs.hits, over every
    repeat on disk. A miss whose second run did not happen (cost cap) is marked "unconfirmed".

    Args:
        rv: the reviewer whose runs were judged (round: the learning reviewer).
        new: the ledger keys newly filed as to_distill.
        max_cost: cap for the second runs and their judge; 0 prints the plan (cached runs are still used).
        cfg: configuration.
        found: ledger keys the judge just filed as covered: their samples get the second
            run too, and a point not found in every run goes to to_distill as flaky (found by chance).

    Returns:
        ("confirm: N misses, K flaky, $X" [+ ", U unconfirmed"], cost).
    """
    from .replay import est_cost, replay, run_path
    from .runs import cached, hits
    from .score import EST_COST, judge_runs, load_gold
    cfg = cfg or Config()
    rows = ledger()
    miss = [rows[k] for k in new if k in rows and rows[k]["status"] == "to_distill"]
    hit = [rows[k] for k in found or [] if k in rows and rows[k]["status"] == "covered"]
    if not miss and not hit:
        return "confirm: 0 misses, 0 flaky, $0.00", 0.0
    specs = sorted({f"{r['pr']}:{r['commit'][:8]}" for r in miss + hit})
    ss, _ = load_gold(cfg)
    by = {f"{p}:{c[:8]}": s for (p, c), s in ss.items()}
    todo = [x for x in specs if x in by and not cached(cfg, rv, run_path(cfg, rv, by[x], 2))]
    est = len(todo) * (est_cost(rv) + EST_COST)
    note(f"confirm {len(miss)} misses on {len(specs)} samples: second run of {rv} on {len(todo)} "
         f"(est ${est:.1f}, cap ${max_cost:.0f})")
    cost = replay(rv, "train", None, 4, max(0.0, max_cost - len(todo) * EST_COST), specs, cfg=cfg, rep=2)
    _, jc = judge_runs(cfg, rv, {r["pr"] for r in miss + hit}, "train", max(0.0, max_cost - cost), rep=2)
    cost += jc
    with lock():
        rows = ledger()
        flaky = unconf = 0
        for k in [r["comment"] for r in miss]:
            r = rows.get(k)
            if r is None or r["status"] != "to_distill":
                continue
            h, n = hits(rv, sample(r), k, cfg)
            if n >= 2:
                r.update(hits=f"{h}/{n}")
                r.pop("unconfirmed", None)
                if h:
                    r["flaky"] = True
                    flaky += 1
            else:
                r["unconfirmed"] = True
                unconf += 1
        chance = 0
        for k in [r["comment"] for r in hit]:
            r = rows.get(k)
            if r is None or r["status"] != "covered":
                continue
            h, n = hits(rv, sample(r), k, cfg)
            if n < 2:  # no second run (cost cap): not settled; the next round's confirm asks again
                unconf += 1
                continue
            r["hits"] = f"{h}/{n}"
            if h < n:  # found by chance: production misses it in some runs, so it is learned
                r.update(status="to_distill", flaky=True)
                chance += 1
        save_ledger(rows)
        log("confirm", reviewer=rv, misses=len(miss), flaky=flaky, unconfirmed=unconf, by_chance=chance, cost=round(cost, 2))
    line = (f"confirm: {len(miss)} misses, {flaky} flaky, ${cost:.2f}" + (f", {unconf} unconfirmed" if unconf else "")
            + (f"; {chance} of {len(hit)} finds were by chance (to_distill)" if hit else ""))
    note(line, "warn" if unconf else None)
    return line, cost


def retain_reviewer() -> str:
    """The reviewer `retain` checks with: the current prompt and book, rule check only (-ro). On the 2026-11-26
    pilot the production rule check raised the entry behind 49 of 53 caught resolved points (the main review
    got credit for 26 of them only because the dedupe kept its copy), so the rule check alone, at about half
    the cost of a full review, says whether the book is applied. Its runs are judged against every human point of
    the sample (judge_runs), as production runs are, not only against the point asked about as vet does."""
    return f"{prompt_id()}+{vname(head())}@{config()['effort']}-ro"


def entries_of(r: dict, rules: list[dict]) -> list[str]:
    """Active entries that carry a learned row: one whose tests or evidence name the comment, and the end of
    the replaced_by chain of the entry that resolved it."""
    cid = str(cid_of(r["comment"]))
    by = {e["id"]: e for e in rules}
    active = [e for e in rules if e.get("status", "active") == "active"]
    out = [e["id"] for e in active if any(cid == str(cid_of(x)) for x in e.get("evidence") or [])
           or any(cid in map(str, t.get("comments") or []) for t in e.get("tests") or [])]
    cur, seen = (r.get("resolved_by") or {}).get("entry"), set()
    while cur and cur not in seen:
        seen.add(cur)
        if (by.get(cur) or {}).get("status", "active") == "active" and cur in by:
            out.append(cur)
            break
        cur = ((by.get(cur) or {}).get("retired") or {}).get("replaced_by")
    return list(dict.fromkeys(out))


def _retain_why(rv: str, r: dict, es: list[str], cfg: Config) -> str:
    """What the production runs made of a point they did not catch every time: whether the entry fired,
    and what its findings said, so the next write knows what to change."""
    from .runs import rep_dirs
    from .schema import cites
    name = f"{r['pr']}-{r['commit'][:8]}.json"
    said, fired_runs, n = [], 0, 0
    for _, d in rep_dirs(cfg, rv):
        f = d / name
        if not f.exists():
            continue
        n += 1
        fs = [x for x in json.loads(f.read_text()).get("findings") or [] if cites(x) & set(es)]
        fired_runs += bool(fs)
        said += [" ".join(f"{x.get('title') or ''}: {x.get('body') or ''}".split())[:200] for x in fs]
    if not es:
        return "no entry carries it: the main review found it by chance"
    if not fired_runs:
        return f"the rule check did not raise {', '.join(es)} on this change in any of {n} runs"
    return (f"{', '.join(es)} fired in {fired_runs} of {n} runs, but its findings did not make this point; they said: "
            + " | ".join(dict.fromkeys(said))[:500])


def retain_step(prs: set[int] | None = None, max_cost: float | None = None, reps: int | None = None,
                keys: set | None = None, cfg: Config | None = None, samples: set[str] | None = None,
                statuses: tuple[str, ...] = ("resolved",), reviewer: str | None = None) -> str:
    """Check that what the ledger calls learned is caught every time in production: review the samples of
    its covered / resolved rows (only on `prs` / `samples` "PR:commit8", or only rows `keys`) `reps` times with retain_reviewer(),
    judge, and send each row caught in fewer than all runs back to to_distill. Only resolved rows by default:
    a covered one has no entry behind it, so a rule check cannot catch it, with a try saying how often
    it was caught and what the runs made of it (distill reads it).
    How often it must be caught and how often it goes back depend on its tier ([tiers] retain_need,
    retain_requeues): past its requeues a major+ row goes to a person (needs_human); a minor / nit row stays
    learned, marked "unretained". Rows caught often enough get "retained"."""
    from .replay import replay
    from .runs import hits
    from .score import judge_runs
    cfg = cfg or Config()
    reps = reps or int(get("retain", "reps"))
    max_cost = get("budget", "retain") if max_cost is None else max_cost
    rv = reviewer or retain_reviewer()  # another reviewer of the same prompt and book (e.g. full -rc runs on disk)
    rows = ledger()
    todo = [r for r in rows.values() if r["status"] in statuses and (not prs or r["pr"] in prs)
            and (keys is None or r["comment"] in keys) and (not samples or f"{r['pr']}:{r['commit'][:8]}" in samples)]
    if not todo:
        return "retain: nothing learned on these samples"
    specs = sorted({f"{r['pr']}:{r['commit'][:8]}" for r in todo})
    nums = {r["pr"] for r in todo}
    note(f"▶ retain: {len(todo)} learned points on {len(specs)} samples, {reps} runs of {rv}; cap ${max_cost:.0f}")
    cost = 0.0
    for k in range(1, reps + 1):
        cost += replay(rv, "train", None, 4, max(0.0, max_cost - cost), specs, cfg=cfg, rep=k, learned=True)
    if max_cost <= 0:
        return f"retain: plan only (cached runs: see above); {len(todo)} learned points"
    for k in range(1, reps + 1):
        cost += judge_runs(cfg, rv, nums, "train", max(0.0, max_cost - cost), rep=k)[1]
    book = load_book(vname(head()))
    out = {"retained": [], "requeued": [], "unretained": [], "needs_human": [], "unknown": []}
    sev = severities(cfg)
    with lock():
        rows = ledger()
        for r0 in todo:
            r = rows.get(r0["comment"])
            if not r or r["status"] not in ("covered", "resolved"):
                continue
            h, n = hits(rv, sample(r), r["comment"], cfg)
            if n < reps:
                out["unknown"].append(r["comment"])
                continue
            if h >= (tier_limit("retain_need", r, sev) or n):
                r.pop("unretained", None)
                r["retained"] = {"reviewer": rv, "hits": f"{h}/{n}", "date": _now()[:10]}
                out["retained"].append(r["comment"])
                continue
            es = entries_of(r, book) if r["status"] == "resolved" else []
            why = f"learned ({r['status']}) but caught in {h} of {n} production runs of {rv}: " + _retain_why(rv, r, es, cfg)
            r.setdefault("tries", []).append({"book": vname(head()), "entries": es, "result": "not retained",
                                              "why": why, "date": _now()[:10]})
            r.pop("retained", None)
            spent = r.get("retain_requeues", 0) >= tier_limit("retain_requeues", r, sev)  # its own count, not requeue_parked's
            if spent and row_tier(r, sev) != "major+":  # not worth a person: stays learned, the try records the miss
                r["unretained"] = {"reviewer": rv, "hits": f"{h}/{n}", "date": _now()[:10]}
                out["unretained"].append(r["comment"])
            elif spent:
                r.update(status="needs_human", parked={"by": "retain", "prompt": distill_prompt_id(), "date": _now()[:10]})
                out["needs_human"].append(r["comment"])
            else:  # the not-retained try is information for distill, not a failed attempt: requeued_at is after it
                r.update(status="to_distill", retain_requeues=r.get("retain_requeues", 0) + 1, requeued_at=len(r["tries"]),
                         requeued={"date": _now()[:10], "book": vname(head()), "why": why[:300]})
                out["requeued"].append(r["comment"])
                note(f"  not retained #{r['pr']}@{r['commit'][:8]} c{r['comment']} ({h}/{n})", "change")
        save_ledger(rows)
        tiers = {t or "none": f"{sum(tier(sev.get(str(c))) == t for c in out['retained'])}/"
                              f"{sum(tier(sev.get(str(c))) == t for v in out.values() for c in v)}" for t in TIERS + (None,)}
        log("retain", reviewer=rv, cost=round(cost, 2), **{k: len(v) for k, v in out.items()}, by_tier=tiers)
    line = (f"retain {rv}: " + ", ".join(f"{k} {len(v)}" for k, v in out.items()) + f"; ${cost:.2f}"
            + "; retained by tier: " + ", ".join(f"{t} {v}" for t, v in tiers.items() if not v.endswith("/0")))
    note(line, "warn" if out["requeued"] or out["needs_human"] else "ok")
    return line


def pick_samples(prs: list[int | str], cfg: Config | None = None) -> list[str]:
    """Expand a round's sample specs: "PR:commit" stays as it is; a bare PR number becomes the commits of
    that PR where some judged run on disk (any reviewer) missed a change request / nit that is not in the
    ledger yet or is still to_distill there. A PR with no judged run on any of its samples keeps all of them (nothing is known yet).

    Returns:
        "PR:commit8" specs, in the given order.
    """
    from .score import hkey, load_gold
    cfg = cfg or Config()
    ss, _ = load_gold(cfg)
    rows, out = ledger(), []
    for spec in prs:
        if ":" in str(spec):
            out.append(str(spec))
            continue
        pr = int(spec)
        mine = [(c, s) for (p, c), s in ss.items() if p == pr and s.get("split") == "train"]
        judged, keep = False, []
        for c, s in mine:
            missed = set()
            for f in (cfg.data / "scores").glob(f"*/{pr}-{c[:8]}.json"):
                if f.parent.name.startswith("_"):
                    continue
                judged = True
                sc = json.loads(f.read_text())
                sc["gold_ids"] = sc.get("gold_ids") or s["gold_ids"]
                missed |= {hkey(sc, h) for h in sc.get("human") or []
                           if h.get("type") in ("change_request", "nit") and not h.get("matched_ai")
                           and isinstance(h.get("id"), int) and h["id"] < len(sc["gold_ids"])}
            # still open: not in the ledger yet, or there and waiting to be distilled
            row = lambda k: rows.get(k) or rows.get(cid_of(k))  # noqa: E731
            if any(row(k) is None or row(k)["status"] == "to_distill" for k in missed):
                keep.append(f"{pr}:{c[:8]}")
        picked = keep if judged else [f"{pr}:{c[:8]}" for c, _ in mine]
        note(f"#{pr}: {len(picked)} of {len(mine)} samples" + ("" if judged else " (none judged yet: all)")
             + (f": {', '.join(x.split(':')[1] for x in picked)}" if picked else ""), "dim")
        out += picked
    return out


def round_(prs: list[int | str], review_cost: float | None = None, judge_cost: float | None = None,
           distill_cost: float | None = None, vet_cost: float | None = None, cfg: Config | None = None,
           confirm_cost: float | None = None) -> str:
    """One round on samples `prs` (PR:commit, or PR numbers: see pick_samples): review with the book in use, judge,
    confirm the new misses with a second run (confirm_misses), then distill + vet (together with every comment
    still to_distill from earlier rounds, on any PR) until their comments are all
    resolved / not rulable / needs_human (at most MAX_TRIES); last, compress + vet when the book is over
    [compress] words (compress_if_big)."""
    b = settings()["budget"]["round"]
    review_cost, judge_cost, distill_cost, vet_cost, confirm_cost = (
        b[k] if v is None else v for k, v in (("review", review_cost), ("judge", judge_cost),
                                             ("distill", distill_cost), ("vet", vet_cost),
                                             ("confirm", confirm_cost)))
    from .replay import replay
    rv = reviewer()
    prs = pick_samples(prs, cfg)
    out = []
    from . import llm
    spent0 = llm.SPENT
    with step("round", f"{len(prs)} sample spec(s) {' '.join(map(str, prs))}; book {vname(head())}; caps review "
              f"${review_cost:.0f}, judge ${judge_cost:.0f}, confirm ${confirm_cost:.0f}, distill ${distill_cost:.0f}, vet ${vet_cost:.0f} "
              f"(per attempt, at most {MAX_TRIES})") as st:
        if not prs:  # an empty list would mean every train sample to replay and judge
            note("select kept no samples: nothing to review", "warn")
            st.result = f"book {vname(head())}"
            return "\n".join(out + ["nothing selected", "", status()])
        nums = {int(str(p).split(":")[0]) for p in prs}
        with step("review", rv) as s1:
            s1.cost = replay(rv, "train", None, 4, max(0.0, review_cost), prs, cfg=cfg)
        st.cost += s1.cost
        out.append(f"review {rv}: ${s1.cost:.2f}")
        before = {k for k, r in ledger().items() if r["status"] == "to_distill"}
        out.append(judge("train", nums, judge_cost, rv, cfg))
        new = [k for k, r in ledger().items() if r["status"] == "to_distill" and k not in before]
        found = [k for k, r in ledger().items() if r["status"] == "covered" and r.get("reviewer") == rv
                 and r["pr"] in nums and "hits" not in r]
        with step("confirm", f"{len(new)} new misses, {len(found)} new finds; cap ${confirm_cost:.0f}") as s2:
            line, s2.cost = confirm_misses(rv, new, confirm_cost, cfg, found=found)
            s2.result = line
        out.append(line)
        nums = set(nums) | requeue_parked(cfg=cfg)  # parked comments the changed workflow may now learn
        left = {r["pr"] for r in to_distill()} - nums  # still to learn from earlier rounds: learned here too
        if left:
            note(f"also distilling the comments left to learn on PR {' '.join(map(str, sorted(left)))}")
            nums |= left
        retain_on = bool(get("retain", "on"))
        for k in range(MAX_TRIES):
            left = to_distill(prs=nums)
            if not left:
                note("nothing left to distill on these samples")
                break
            with step(f"attempt {k + 1}/{MAX_TRIES}", f"{len(left)} comments to distill"):
                if candidate():  # left by an INCOMPLETE vet: finish vetting it before distilling again
                    note(f"candidate {candidate()['name']} is waiting: vet it first")
                else:
                    out.append(distill_step(nums, max_cost=distill_cost, cfg=cfg))
                if not candidate():
                    break
                was = {k for k, r in ledger().items() if r["status"] == "resolved"}
                out.append(vet_step(vet_cost, cfg=cfg).split("\n\n")[-1])
                fresh = {k for k, r in ledger().items() if r["status"] == "resolved"} - was
                if retain_on and fresh and not candidate():  # resolved counts only if production catches it every time
                    out.append(retain_step(nums, b["retain"], keys=fresh, cfg=cfg))
                if candidate():  # INCOMPLETE
                    note("vet INCOMPLETE (cost cap): candidate kept; rerun `lmreview vet` with a higher --max-cost")
                    break
        if not candidate():
            out += compress_if_big(vet_cost, cfg)
        st.result = f"book {vname(head())}"
        st.cost = llm.SPENT - spent0  # every paid call of the round: review, judge, distill, vet, compress
        out.append(f"round total: ${st.cost:.2f}")
    return "\n".join(out + ["", status()])

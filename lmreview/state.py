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
merge.md) and lmreview/config.toml (see settings.py). Runs and scores stay in <data>/runs and
<data>/scores (not in git), under the reviewer name `p<sha8>+vNNNN@<effort>[x<n>][-rc][-sh]`, so a new
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

from typing import Iterator

from .config import PROMPTS, RULES, Config
from .annotate import cid_of
from .settings import get, settings
from .progress import note, step

STATE = pathlib.Path(os.environ.get("LMREVIEW_STATE") or get("paths", "state")
                     or pathlib.Path(__file__).resolve().parent / "state")
MAX_TRIES = int(get("distill", "max_tries"))  # distill attempts per comment before it goes to a person

LEDGER = """ledger.jsonl rows: {"comment" (a point key: the comment id, or "<comment id>:<k>" for point k
of a comment that makes several, see annotate.py), "pr", "commit", "status", "reviewer" (whose run judged it),
"tries": [{"book", "entries", "result", "why", "date"}], "resolved_by": {"book", "entry"}, "note"}.
status: covered (the reviewer found it without help) | to_distill | resolved (a book entry makes the
reviewer find it, checked by vet) | not_rulable (distill: context / not an issue / declined) |
needs_human (MAX_TRIES distill attempts failed)."""
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


def new_version(rules: list[dict], parent: int | None, **meta: object) -> int:
    """Write `rules` as the next version and make it the book in use. Returns its number."""
    n = max([int(p.stem[1:]) for p in (STATE / "history").glob("v*.jsonl")] or [0]) + 1
    _write(STATE / "history" / f"{vname(n)}.jsonl", _jsonl(rules))
    made_with = {k: settings()[k] for k in ("review", "judge", "distill", "vet")}
    _write(_meta(STATE / "history" / f"{vname(n)}.jsonl"), json.dumps({"version": n, "parent": parent, "date": _now(),
                                                                "settings": made_with, **meta}, indent=1) + "\n")
    _write(STATE / "book.jsonl", _jsonl(rules))
    _write(STATE / "HEAD.json", json.dumps({"version": n, "updated": _now()}, indent=1) + "\n")
    log("promote", version=n, parent=parent, **{k: v for k, v in meta.items() if k in ("by", "from")})
    return n


def rollback(to: int) -> int:
    """Make version `to` the book in use again, as a new version (history is never rewritten)."""
    with lock():
        return new_version(load_book(vname(to)), head(), by="rollback", **{"from": vname(to)})


# ---- the reviewer ---------------------------------------------------------------------------------

def config() -> dict:
    """The [review] settings (config.toml): effort, rulecheck, parallel, shell."""
    return dict(settings()["review"])


def suffix(book: bool = True) -> str:
    """The reviewer-name suffix the [review] settings ask for after @<effort>: [x<n>][-rc][-sh]
    (no rule check without a book)."""
    c = config()
    return ((f"x{c['parallel']}" if c["parallel"] > 1 else "") + ("-rc" if c["rulecheck"] and book else "")
            + ("-sh" if c["shell"] else ""))


PARTS = ("rulecheck", "merge")  # the other agents' prompts, versioned with reviewer.md


def prompt_id(save: bool = False) -> str:
    """`p<sha8>` of lmreview/prompts/reviewer.md, rulecheck.md and merge.md together, so editing any of
    them gives the reviewer a new name. With `save` (before a run uses it), their texts are kept in
    state/prompts/ (<id>.md, <id>.rulecheck.md, <id>.merge.md) so old runs stay reproducible."""
    texts = {"": (PROMPTS / "reviewer.md").read_text(), **{k: (PROMPTS / f"{k}.md").read_text() for k in PARTS}}
    pid = "p" + hashlib.sha256("\0".join(texts.values()).encode()).hexdigest()[:8]
    for k, text in texts.items():
        p = STATE / "prompts" / (f"{pid}.{k}.md" if k else f"{pid}.md")
        if save and not p.exists():
            try:
                _write(p, text)
            except OSError:  # an installed copy may be read-only; the current files are found by hash
                pass
    return pid


def part_path(version: str, part: str) -> pathlib.Path:
    """The `part` prompt ("rulecheck" or "merge") of prompt version `version`: kept in state/prompts for a
    p<sha8> version; the current file for the current version and for the older named prompts (v0b, ...)."""
    p = STATE / "prompts" / f"{version}.{part}.md"
    if p.exists() or not re.fullmatch(r"p[0-9a-f]{8}", version) or version == prompt_id():
        return p if p.exists() else PROMPTS / f"{part}.md"
    raise FileNotFoundError(f"prompt {version} has no {p.name} in {STATE / 'prompts'}")


def prompt_path(version: str) -> pathlib.Path:
    """The prompt file of prompt version `version` (p<sha8> from state/prompts, else prompts/reviewer_<v>.md)."""
    if re.fullmatch(r"p[0-9a-f]{8}", version):
        p = STATE / "prompts" / f"{version}.md"
        if p.exists():
            return p
        if version == prompt_id():
            return PROMPTS / "reviewer.md"
        raise FileNotFoundError(f"prompt {version} is neither in {STATE / 'prompts'} nor the current reviewer.md")
    return PROMPTS / f"reviewer_{version}.md"


def reviewer(book: str | None = None) -> str:
    """The reviewer name of the current prompt and config with `book` (default: the book in use)."""
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


def sample(r: dict) -> str:
    """The sample of a ledger row: #pr@commit8."""
    return f"#{r['pr']}@{r['commit'][:8]}"


def to_distill(rows: dict[int, dict] | None = None, prs: set[int] | None = None) -> list[dict]:
    """Ledger rows still to learn (only on `prs`, if given)."""
    rows = ledger() if rows is None else rows
    return [r for r in rows.values() if r["status"] == "to_distill" and (not prs or r["pr"] in prs)]


def tries_note(r: dict) -> str:
    """What earlier distill attempts made of this comment, for the next attempt."""
    return " | ".join(f"attempt {i + 1} ({t['book']}, entries {t.get('entries') or 'none'}): {t['result']}"
                      + (f" ({t['why']})" if t.get("why") else "") for i, t in enumerate(r.get("tries") or []))


def judge(split: str = "train", prs: set[int] | None = None, max_cost: float = 10.0, rv: str | None = None,
          cfg: Config | None = None) -> str:
    """Judge the current reviewer's runs on `split` against the human comments and file every
    change-request / nit comment in the ledger: found -> covered, missed -> to_distill. A comment
    already in the ledger keeps its row, except that a to_distill comment found now becomes resolved
    (the book in use found it). Samples without such comments count as no ground truth."""
    from .distill import judge_runs
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
                if cm.get(c, {}).get("addressed_reason") == "file-unchanged":
                    continue  # likely not taken by the author
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
        log("judge", reviewer=rv, runs=len(judged), cost=round(cost, 2), **n)
        st.result = ", ".join(f"{k} {v}" for k, v in n.items())
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
         + ", ".join(f"{s} {len(by[s])}" for s in STATUSES)
         + (f" ({n_leg} of them from before the ledger)" if (n_leg := sum(bool((r.get('resolved_by') or {}).get('legacy'))
                                                                           or 'legacy' in (r.get('note') or '') for r in rows.values())) else ""),
         f"samples: {len(solved)} solved by the book, {len(open_)} with comments to distill"]
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
    k = sum(1 for x in map(json.loads, p.open()) if x["step"] == "distill" and x.get("parent") == n) if p.exists() else 0
    return f"{vname(n + 1)}c{k + 1}"


def clear_candidate() -> None:
    """Remove candidate/."""
    shutil.rmtree(STATE / "candidate", ignore_errors=True)


def init(book: str, note: str = "") -> int:
    """Start the state from rulebook rules/<book>.jsonl as v0001 (only when there is no state yet)."""
    if head():
        raise RuntimeError(f"state already at {vname(head())}")
    with lock():
        return new_version(load_book(book), None, by="init", **{"from": f"rules/{book}.jsonl"}, note=note)


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
                 max_cost: float | None = None, cfg: Config | None = None, induce: bool | None = None,
                 compress: bool = False) -> str:
    """Distill the ledger's to_distill comments (only on `prs`, if given) into a candidate built on the
    book in use. Earlier failed attempts are passed on, so the next one is written differently.
    Comments distill finds not learnable (context, not an issue, declined) become not_rulable."""
    from .distill import distill
    cfg = cfg or Config()
    d = settings()["distill"]
    effort = effort or d["effort"]
    induce = d["induce"] if induce is None else induce
    max_cost = get("budget", "distill") if max_cost is None else max_cost
    with lock():
        if not head():
            raise RuntimeError("no book in use: `lmreview init <rules name>` first")
        if candidate():
            raise RuntimeError(f"candidate {candidate()['name']} is waiting: `lmreview vet` it or `lmreview discard`")
        rows = ledger()
        todo = sorted(to_distill(rows, prs), key=lambda r: (r["pr"], r["commit"], str(r["comment"])))[:limit]
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
                          notes={r["comment"]: tries_note(r) for r in todo if r.get("tries")}, do_induce=induce)
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
            if r and a.get("kind") in ("context", "not_issue", "rejected"):
                r.update(status="not_rulable", note=f"{a['kind']}: {a.get('reason') or a.get('why') or ''}"[:300])
                n_out += 1
        save_ledger(rows)
        log("distill", name=name, parent=parent, comments=len(ids), not_rulable=n_out, summary=msg)
        note(f"✓ distill: {msg}; {n_out} not rulable")
        return f"candidate {name}: {msg}; {n_out} comments not rulable. Next: `lmreview vet`"


def vet_step(max_cost: float | None = None, reps: int | None = None, everything: bool = False, cfg: Config | None = None) -> str:
    """Vet the candidate against the book in use. What works becomes the next version (the rest is
    dropped or reverted, see vet._passing); each comment of the candidate is then resolved, or gets a
    failed attempt (needs_human after MAX_TRIES). INCOMPLETE (cost cap) keeps the candidate for a rerun."""
    from .vet import vet
    max_cost = get("budget", "vet") if max_cost is None else max_cost
    reps = reps or int(get("vet", "reps"))
    with lock():
        c = candidate()
        if not c:
            return "no candidate: run `lmreview distill` first"
        if c["parent"] != head():
            raise RuntimeError(f"the book moved to {vname(head())} since {c['name']} was distilled: `lmreview discard`")
        res: dict = {}
        note(f"▶ vet {c['name']} against {vname(c['parent'])} ({len(c['comments'])} comments); cap ${max_cost:.0f}")
        conf = config()
        report = vet(c["name"], vname(c["parent"]), prompt_id(), conf["effort"], suffix(),
                     reps=reps, max_cost=max_cost, everything=everything, cfg=cfg, out=res)
        if max_cost <= 0 or not res:
            return report
        if res["verdict"] == "INCOMPLETE":
            log("vet", name=c["name"], verdict="INCOMPLETE", cost=round(res["cost"], 2))
            return report + "\n\nINCOMPLETE: candidate kept; rerun `lmreview vet` with a higher --max-cost (cached runs are free)"
        J, kept, cand = res["J"], res["kept"], load_book(c["name"])
        kept_ids = {r["id"] for r in kept if r.get("status", "active") == "active"}
        ents: dict[int, list[str]] = {}
        old_ev = {int(e) for r in load_book(vname(c["parent"])) for e in r.get("evidence") or []}
        for r in cand:
            for e in r.get("evidence") or []:
                if int(e) not in old_ev:
                    ents.setdefault(int(e), []).append(r["id"])
        changed = _jsonl(kept) != _jsonl(load_book(vname(c["parent"])))
        n = new_version(kept, c["parent"], by="vet", **{"from": c["name"]}, verdict=res["verdict"],
                        report=f"reports/vet_{c['name']}.md") if changed else c["parent"]
        rows, out = ledger(), {"resolved": [], "failed": [], "needs_human": []}
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
            why = ("distill made no entry for it" if not es else
                   "the reviewer did not apply the entry" if any(e in J["no_effect"] for e in es) else
                   "dropped: a linked change made an existing entry worse" if not any(e in kept_ids for e in es) else
                   "its entry was kept but not tested on this comment")
            r.setdefault("tries", []).append({"book": c["name"], "entries": es, "result": "failed", "why": why,
                                              "date": _now()[:10]})
            if len(r["tries"]) >= MAX_TRIES:
                r["status"] = "needs_human"
                out["needs_human"].append(i)
            else:
                out["failed"].append(i)
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
        return (report + f"\n\n{'promoted ' + vname(n) if changed else 'no change kept; book stays ' + vname(n)}: "
                + ", ".join(f"{k} {len(v)}" for k, v in out.items())
                + ("; failed comments stay to_distill: `lmreview distill` tries again" if out["failed"] else ""))


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
           induce: bool | None = None) -> str:
    """One round on samples `prs` (PR:commit, or PR numbers: see pick_samples): review with the book in use, judge, then
    distill + vet until their comments are all resolved / not rulable / needs_human (at most MAX_TRIES)."""
    b = settings()["budget"]["round"]
    review_cost, judge_cost, distill_cost, vet_cost = (
        b[k] if v is None else v for k, v in (("review", review_cost), ("judge", judge_cost),
                                             ("distill", distill_cost), ("vet", vet_cost)))
    from .replay import replay
    rv = reviewer()
    prs = pick_samples(prs, cfg)
    nums = {int(str(p).split(":")[0]) for p in prs}
    out = []
    with step("round", f"{len(prs)} sample spec(s) {' '.join(map(str, prs))}; book {vname(head())}; caps review "
              f"${review_cost:.0f}, judge ${judge_cost:.0f}, distill ${distill_cost:.0f}, vet ${vet_cost:.0f} "
              f"(per attempt, at most {MAX_TRIES})") as st:
        with step("review", rv) as s1:
            s1.cost = replay(rv, "train", None, 4, review_cost, prs, cfg=cfg)
        st.cost += s1.cost
        out.append(f"review {rv}: ${s1.cost:.2f}")
        out.append(judge("train", nums, judge_cost, rv, cfg))
        for k in range(MAX_TRIES):
            left = to_distill(prs=nums)
            if not left:
                note("nothing left to distill on these samples")
                break
            with step(f"attempt {k + 1}/{MAX_TRIES}", f"{len(left)} comments to distill"):
                if candidate():  # left by an INCOMPLETE vet: finish vetting it before distilling again
                    note(f"candidate {candidate()['name']} is waiting: vet it first")
                else:
                    out.append(distill_step(nums, max_cost=distill_cost, cfg=cfg, induce=induce))
                if not candidate():
                    break
                out.append(vet_step(vet_cost, cfg=cfg).split("\n\n")[-1])
                if candidate():  # INCOMPLETE
                    note("vet INCOMPLETE (cost cap): candidate kept; rerun `lmreview vet` with a higher --max-cost")
                    break
        st.result = f"book {vname(head())}"
    return "\n".join(out + ["", status()])

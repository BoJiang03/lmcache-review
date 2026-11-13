"""Passive signals: what later happened to the code each AI finding points at. No LLM, free.

For a finding on sample (PR, commit C), per primary location (side "new", lines at C):
  changed_in_pr   the lines were modified by a later commit of the same PR (C..head)
  after_merge     first dev commit after the PR's merge that modified the lines (sha, date,
                  subject, days after merge, fix-like subject or not)
  later_comments  human inline comments made on later commits of the PR whose range overlaps
                  the lines (location overlap only: candidates, not confirmed same-issue)
These only ever *support* a finding; their absence says nothing.

Also: severity the AI gave to findings that a human change request matched (severity check).
Output: <data>/signals/<version>/<pr>-<commit8>.json and reports/signals_<version>.md.
"""

from __future__ import annotations

import collections as C
import json
import re
import subprocess

from .config import Config
from .schema import load_findings
from .score import REPORTS, _normalize, load_gold

FIX_RE = re.compile(r"\b(fix|bug|revert|hotfix|regression|broken|crash)", re.I)
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


def _git(cfg: Config, *a: str) -> str:
    r = subprocess.run(["git", "-C", str(cfg.repo), *a], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _has(cfg: Config, oid: str) -> bool:
    return subprocess.run(["git", "-C", str(cfg.repo), "cat-file", "-e", f"{oid}^{{commit}}"],
                          capture_output=True).returncode == 0


def map_range(diff: str, s: int | None, e: int | None) -> tuple[bool, int | None, int | None]:
    """Carry an old-file line range through a -U0 diff: (touched, new_start, new_end).

    A whole-file range (s is None) is touched by any hunk.
    """
    hunks = [(int(a), int(b or 1), int(c), int(d or 1)) for a, b, c, d in HUNK_RE.findall(diff)]
    if s is None:
        return bool(hunks), None, None
    delta = 0
    for os_, ol, ns, nl in hunks:
        lo, hi = (os_, os_ + ol - 1) if ol else (os_ + 0.5, os_ + 0.5)  # pure insertion sits after os_
        if hi < s:
            delta += nl - ol
        elif lo > e:
            break
        else:
            return True, None, None
    return False, s + delta, e + delta


def _diff(cfg: Config, a: str, b: str, path: str) -> str:
    return _git(cfg, "diff", "-U0", "--no-color", a, b, "--", path)


def merge_commit(cfg: Config, raw: dict) -> str | None:
    """The dev commit that brought the PR in (squash commit, or the head if merged as-is)."""
    if not raw.get("mergedAt"):
        return None
    out = _git(cfg, "log", "origin/dev", "--format=%H", "--fixed-strings", f"--grep=(#{raw['number']})")
    for sha in out.split():
        return sha
    head = raw["headRefOid"]
    ok = subprocess.run(["git", "-C", str(cfg.repo), "merge-base", "--is-ancestor", head, "origin/dev"],
                        capture_output=True).returncode == 0
    return head if ok else None


def after_merge(cfg: Config, commit: str, merge: str, merged_at: str, path: str,
                s: int | None, e: int | None) -> dict | None:
    """First dev commit after `merge` that modifies the lines (tracked from C through the merge)."""
    touched, s2, e2 = map_range(_diff(cfg, commit, merge, path), s, e)
    if touched:
        return None  # already changed before/at merge; not a post-merge signal
    log = _git(cfg, "log", "--first-parent", "--reverse", "--format=%H%x09%cI%x09%s", f"{merge}..origin/dev",
               "--", path)
    for line in log.splitlines():
        sha, date, subj = line.split("\t", 2)
        hit, s2, e2 = map_range(_diff(cfg, f"{sha}^", sha, path), s2, e2)
        if hit:
            days = (_ts(date) - _ts(merged_at)) / 86400
            return {"sha": sha, "date": date, "subject": subj, "days": round(days, 1),
                    "fix_like": bool(FIX_RE.search(subj))}
    return None


def _ts(iso: str) -> float:
    import datetime as dt
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def signals_one(cfg: Config, run: dict, sample: dict, raw: dict, comments: list[dict]) -> dict:
    """Signals for every finding of one run."""
    c0, head = run["commit"], raw["headRefOid"]
    merge = merge_commit(cfg, raw)
    own = set(sample["gold_ids"])  # moved to this sample by samples.commit_at; their "commit" is GitHub's hint
    later = [c for c in comments if c["pr"] == run["pr"] and c["id"] not in own and c["kind"] == "inline" and not c["is_bot"]
             and not c["is_pr_author"] and c["created"] > sample["time"] and c.get("commit")
             and c["commit"] != c0 and c.get("line_lo") and _has(cfg, c["commit"])]
    out = []
    for f in load_findings(run) or []:
        locs = [l for l in f.locations if l.side == "new"]
        prim = [l for l in locs if l.role == "primary"]
        sig = {"id": f.id, "severity": f.severity, "scope": f.scope, "title": f.title,
               "changed_in_pr": False, "after_merge": None, "later_comments": []}
        for l in prim:
            if head != c0 and _has(cfg, head):
                sig["changed_in_pr"] |= map_range(_diff(cfg, c0, head, l.path), l.start, l.end)[0]
            if merge and sig["after_merge"] is None:
                sig["after_merge"] = after_merge(cfg, c0, merge, raw["mergedAt"], l.path, l.start, l.end)
        for l in locs:
            for c in later:
                if c["path"] != l.path:
                    continue
                touched, s2, e2 = map_range(_diff(cfg, c0, c["commit"], l.path), l.start, l.end)
                if l.start is None or touched or (s2 <= c["line_hi"] and c["line_lo"] <= e2):
                    if c["id"] not in sig["later_comments"]:
                        sig["later_comments"].append(c["id"])
        out.append(sig)
    return {"pr": run["pr"], "commit": c0, "state": raw["state"], "merge": merge, "findings": out}


def signals(version: str = "v0", cfg: Config | None = None) -> str:
    """Compute signals for every run of `version`; write the report; return its headline."""
    cfg = cfg or Config()
    ss, cm = load_gold(cfg)
    comments = list(cm.values())
    runs = [json.loads(p.read_text()) for p in sorted((cfg.data / "runs" / version).glob("*.json"))]
    runs = [r for r in runs if r["findings"] is not None]
    sdir, odir = cfg.data / "scores" / version, cfg.data / "signals" / version
    odir.mkdir(parents=True, exist_ok=True)
    rows, sev_matched = [], C.Counter()
    runs = [r for r in runs if (r["pr"], r["commit"]) in ss]  # score() reports the stale ones
    for r in runs:
        raw = json.loads((cfg.data / "raw" / "pr" / f"{r['pr']}.json").read_text())
        res = signals_one(cfg, r, ss[(r["pr"], r["commit"])], raw, comments)
        sp = sdir / f"{r['pr']}-{r['commit'][:8]}.json"
        matched = set()
        if sp.exists():
            sc = _normalize(json.loads(sp.read_text()), r)
            for h in sc["human"]:
                matched |= set(h["matched_ai"])
                if h["type"] == "change_request":
                    for m in h["matched_ai"]:
                        sev_matched[next((f["severity"] for f in res["findings"] if f["id"] == m), "?")] += 1
            judged = {a.get("id"): a.get("valid") for a in sc["ai"]}
        else:
            judged = {}
        for f in res["findings"]:
            f["human_matched"] = f["id"] in matched if sp.exists() else None
            f["judge_valid"] = judged.get(f["id"])
        (odir / f"{r['pr']}-{r['commit'][:8]}.json").write_text(json.dumps(res, indent=1))
        rows += [(res, f) for f in res["findings"]]

    def line(name: str, fs: list) -> str:
        n = len(fs)
        a = sum(f["changed_in_pr"] for _, f in fs)
        m = [f for res, f in fs if res["merge"]]
        b = sum(1 for f in m if f["after_merge"])
        bf = sum(1 for f in m if f["after_merge"] and f["after_merge"]["fix_like"])
        c = sum(1 for _, f in fs if f["later_comments"])
        return f"| {name} | {n} | {a} | {len(m)} | {b} ({bf} fix-like) | {c} |"

    ai_only = [x for x in rows if x[1]["human_matched"] is False]
    L = [f"# Passive signals: reviewer {version}", "",
         f"Samples: {len(runs)} · findings: {len(rows)}. Signals only support a finding; absence means nothing.", "",
         "| findings | n | changed later in PR | on merged PRs | changed after merge | later human comment at same place |",
         "| --- | --- | --- | --- | --- | --- |",
         line("all", rows), line("AI-only", ai_only)]
    for sev in ("blocker", "major", "minor", "nit"):
        L.append(line(f"AI-only {sev}", [x for x in ai_only if x[1]["severity"] == sev]))
    L += ["", "## Severity check", "",
          "AI severity of findings matched by a human change request: "
          + (", ".join(f"{k} {v}" for k, v in sev_matched.most_common()) or "(no scores)"), "",
          "## AI-only blocker/major with a signal", ""]
    for res, f in ai_only:
        if f["severity"] in ("blocker", "major") and (f["changed_in_pr"] or f["after_merge"] or f["later_comments"]):
            bits = []
            if f["changed_in_pr"]:
                bits.append("changed later in PR")
            if f["after_merge"]:
                am = f["after_merge"]
                bits.append(f"after merge: {am['sha'][:8]} +{am['days']}d \"{am['subject'][:70]}\"")
            if f["later_comments"]:
                bits.append(f"later comments {f['later_comments']}")
            L.append(f"- #{res['pr']} [{f['severity']}] {f['title'][:90]} (judge: {f['judge_valid']}): {'; '.join(bits)}")
    (REPORTS / f"signals_{version}.md").write_text("\n".join(L) + "\n")
    return "\n".join(L[:12])

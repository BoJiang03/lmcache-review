"""Compare two first-round reviewers on historical LMCache PR samples: LMCache's own pr-review skill
(run offline) vs lmreview, both graded by the same blinded judge (score.score_one).

Arms (Claude Code's default model, effort high):
  skill     LMCache's `.claude/skills/pr-review` skill and `docs/coding_standards.md` as they are in the
            dev checkout today (data/LMCache), copied into the sample workspace; the agent follows the
            skill offline (PR text as of the sample time, local git diff, no gh, no network) and writes
            the skill's own markdown report, unchanged. A separate tool-less call (low effort) always
            turns that report into the issue list; its cost is recorded apart.
  lmreview  REVIEWER below, run exactly as replay.replay_one does.

Blinding: before judging, every finding of both arms is cut down to {id, path, line, title, body} with
neutral ids F1..Fn, a fixed severity and no rule / stage / source fields; the map back to the original
finding is kept in <arm>/blind/. Both arms are judged with the same prompt version's workspace context.

Everything goes under data/skill_compare/<arm>/{runs,blind,scores}/ (never data/runs or data/scores).

Stopping a run: kill its process group (setsid at launch, then `kill -- -<pgid>`); killing only the python
process leaves its `claude -p` children running and paying.

Usage:
  python scripts/skill_compare.py select                 # print the 20 chosen samples
  python scripts/skill_compare.py pilot [--cap 12]       # first sample of each half, both arms, judged
  python scripts/skill_compare.py report [--n 2]         # metrics of the first n chosen samples per half
  python scripts/skill_compare.py run [--half covered|resolved] [--prs 4729 ...] [--workers 3] [--cap 70]
                                                          # chosen samples (filtered), in parallel; one result
                                                          # file per sample in results/
  python scripts/skill_compare.py summary                # recall etc. per half from results/
"""

from __future__ import annotations

import argparse
import collections as C
import filecmp
import json
import os
import pathlib
import random
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lmreview import llm  # noqa: E402
from lmreview.config import Config  # noqa: E402
from lmreview.reviewer import reviewer_context, run_reviewer  # noqa: E402
from lmreview.runs import run_models  # noqa: E402
from lmreview.schema import load_findings  # noqa: E402
from lmreview.score import WANT, load_gold, score_one  # noqa: E402
from lmreview.settings import get  # noqa: E402
from lmreview.workspace import cached_pr, sample_workspace  # noqa: E402

REVIEWER = "p29f48666+v0032@high-rc"  # the formal review: all Opus, design-doc prompt
EFFORT = "high"
SKILL_TOOLS = "Read,Grep,Glob,Bash,Agent"
EXCLUDE_PRS = {6212}
MAX_SIZE = 2500  # additions + deletions
PER_HALF = 10
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "skill_compare"
SKILL_FILES = (".claude/skills/pr-review/SKILL.md", "docs/coding_standards.md")
# $ looked ahead before each step, so the cap is not crossed by the next call
EST = {"skill": 5.0, "extract": 0.2, "lmreview": 1.5, "judge": 1.2}

SKILL_PROMPT = """Run LMCache's `pr-review` skill on PR #{number}: read `.claude/skills/pr-review/SKILL.md` in
the working directory and follow its review process and output format, with these offline adaptations.

Offline rules (they override the skill where it says to use GitHub):
- There is no network. Do not use `gh`, the GitHub MCP tools, curl, pip or any other network access.
- The PR metadata is below. The PR's head is checked out as HEAD in the working directory and its diff
  is `git diff {base}...HEAD` (use `git diff --stat {base}...HEAD` / `--name-only` for the file list).
  The same diff is also in `PR.diff`. Earlier review discussion on the PR, if any, is in `PR_HISTORY.md`.
- Use git only to read (diff, show, log, grep); do not modify any files in the repository.
- Subagents (Agent tool) are allowed where the skill suggests them; they are under the same rules.

PR #{number}: {title}
PR description:
<<<
{body}
>>>"""

EXTRACT_PROMPT = """Below is a code review report of a pull request. Turn the issues it raises (only issues that ask
the author to change something; not passed checks, summaries or praise) into a JSON list, each
{{"path": "<file>", "line": <int or null>, "title": "<short>", "body": "<what and why, with the fix>",
  "severity": "error" | "warning" | "info"}}, keeping the report's wording and severity. Answer with one
```json block only ([] if it raises no issue).

Report:
<<<
{report}
>>>"""

SKILL_SEV = {"error": "major", "warning": "minor", "info": "nit"}


# ---------------------------------------------------------------- selection

def select_samples(cfg: Config, per_half: int = PER_HALF, seed: int = 0) -> list[dict]:
    """The samples to compare on, deterministic for `seed`.

    Pool: train samples whose PR appears in the ledger and that have >= 2 gold comments; one sample per
    PR (most gold ids, ties: the earliest); not EXCLUDE_PRS; additions + deletions <= MAX_SIZE.
    Halves by the PR's ledger rows: "covered" (more covered than resolved rows) or "resolved" (at least
    as many resolved rows, and at least one); PRs with neither (only not_rulable rows) are left out.
    Each half: shuffled with `seed`, then picked greedily for area diversity (the candidate adding the
    most areas not picked yet; ties in shuffled order).

    Returns:
        [{"half", "sample", "pr_meta"}], covered half first, each half in pick order.
    """
    ledger = [json.loads(l) for l in open(pathlib.Path(__file__).resolve().parent.parent
                                           / "lmreview" / "state" / "ledger.jsonl") if l.strip()]
    st = C.defaultdict(C.Counter)
    for r in ledger:
        st[r["pr"]][r["status"]] += 1
    meta = {p["pr"]: p for p in map(json.loads, (cfg.data / "dataset" / "prs.jsonl").open())}
    ss = [json.loads(l) for l in (cfg.data / "dataset" / "samples.jsonl").open()]
    best: dict[int, dict] = {}
    for s in ss:
        if s["split"] != "train" or s["pr"] not in st or len(s["gold_ids"]) < 2 or s["pr"] in EXCLUDE_PRS:
            continue
        m = meta.get(s["pr"])
        if not m or (m.get("additions") or 0) + (m.get("deletions") or 0) > MAX_SIZE:
            continue
        b = best.get(s["pr"])
        if b is None or (len(s["gold_ids"]), b["time"]) > (len(b["gold_ids"]), s["time"]):
            best[s["pr"]] = s
    halves: dict[str, list[dict]] = {"covered": [], "resolved": []}
    for pr in sorted(best):
        c, r = st[pr]["covered"], st[pr]["resolved"]
        if c > r:
            halves["covered"].append(best[pr])
        elif r:
            halves["resolved"].append(best[pr])
    out = []
    for half, cands in halves.items():
        cands = list(cands)
        random.Random(seed).shuffle(cands)
        seen: set[str] = set()
        for _ in range(min(per_half, len(cands))):
            s = max(cands, key=lambda x: len(set(meta[x["pr"]]["areas"]) - seen))  # first max = shuffled order
            cands.remove(s)
            seen |= set(meta[s["pr"]]["areas"])
            out.append({"half": half, "sample": s, "pr_meta": meta[s["pr"]]})
    return out


def print_selection(sel: list[dict]) -> None:
    for i, x in enumerate(sel):
        s, m = x["sample"], x["pr_meta"]
        print(f"{i:2} {x['half']:8} #{s['pr']:<5} {s['commit'][:8]}  size {m['additions'] + m['deletions']:5}  "
              f"gold {len(s['gold_ids']):2}  areas {','.join(m['areas'])}")


# ---------------------------------------------------------------- budget

class Budget:
    """Running total of every model call this process makes (llm.SPENT), checked before each step."""

    def __init__(self, cap: float):
        self.cap, self.start = cap, llm.SPENT

    @property
    def spent(self) -> float:
        return llm.SPENT - self.start

    def check(self, step: str) -> None:
        if self.spent + EST[step] > self.cap:
            raise BudgetStop(f"stop before {step}: spent ${self.spent:.2f} + est ${EST[step]:.2f} > cap ${self.cap:.2f}")


class BudgetStop(RuntimeError):
    pass


def key_of(s: dict) -> str:
    return f"{s['pr']}-{s['commit'][:8]}"


def save(p: pathlib.Path, obj: object) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1))


# ---------------------------------------------------------------- arm A: the skill

def install_skill(cfg: Config, wt: pathlib.Path) -> dict[str, str]:
    """Copy today's skill files from the dev checkout into workspace `wt` where absent or different.

    Returns:
        {path: "kept" | "added" | "replaced"}.
    """
    out = {}
    for rel in SKILL_FILES:
        src, dst = cfg.repo / rel, wt / rel
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            out[rel] = "kept"
            continue
        out[rel] = "replaced" if dst.exists() else "added"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    return out


def git_head(cfg: Config, wt: pathlib.Path, s: dict, base: str) -> None:
    """Make `wt` a two-commit git repo: the base commit (shallow, no older history) and, as HEAD, a commit
    with the reviewed commit's tree on top of it, so `git diff <base>...HEAD` is the PR's diff. Nothing
    after the sample time is fetched."""
    def g(*a: str) -> str:
        return subprocess.run(["git", "-C", str(wt), *a], check=True, capture_output=True, text=True).stdout.strip()
    g("init", "-q")
    g("fetch", "-q", "--no-tags", "--depth=1",
      "--upload-pack=git -c uploadpack.allowAnySHA1InWant=true upload-pack",
      f"file://{cfg.repo.resolve()}", base, s["commit"])
    head = g("-c", "user.name=pr-author", "-c", "user.email=pr@example.invalid", "commit-tree",
             f"{s['commit']}^{{tree}}", "-p", base, "-m", f"PR #{s['pr']} at {s['commit'][:12]}")
    g("update-ref", "refs/heads/pr", head)
    g("symbolic-ref", "HEAD", "refs/heads/pr")
    g("read-tree", "HEAD")


def transcript_summary(wt: pathlib.Path) -> dict:
    """What the agent did, from Claude Code's session transcripts of workspace `wt`: Bash commands,
    subagent calls, anything that looks like network/GitHub use."""
    d = pathlib.Path.home() / ".claude" / "projects" / ("-" + str(wt.resolve()).strip("/").replace("/", "-").replace(".", "-").replace("_", "-"))
    files = sorted(d.rglob("*.jsonl")) if d.exists() else []
    bash, agents, tools = [], [], C.Counter()
    for f in files:
        for line in f.open():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            for b in ((e.get("message") or {}).get("content") or []) if isinstance((e.get("message") or {}).get("content"), list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    tools[b.get("name")] += 1
                    inp = b.get("input") or {}
                    if b.get("name") == "Bash":
                        bash.append(str(inp.get("command", ""))[:200])
                    elif b.get("name") in ("Agent", "Task"):
                        agents.append(str(inp.get("description") or inp.get("prompt", ""))[:120])
    net = [c for c in bash if re.search(r"(^|[\s;|&(])(gh|curl|wget|pip)\s|git\s+(fetch|pull|clone|push|ls-remote)|https?://", c)]
    return {"transcripts": len(files), "tools": dict(tools), "bash": bash, "agents": agents, "network_attempts": net}


def run_skill(cfg: Config, s: dict, budget: Budget) -> dict:
    """Arm A on sample `s`; cached in skill/runs/."""
    p = OUT / "skill" / "runs" / f"{key_of(s)}.json"
    if p.exists():
        return json.loads(p.read_text())
    raw = cached_pr(cfg, s["pr"], s["time"])
    budget.check("skill")
    t0 = time.time()
    with sample_workspace(cfg, s, "skill") as (wt, base):
        installed = install_skill(cfg, wt)
        git_head(cfg, wt, s, base)
        prompt = SKILL_PROMPT.format(number=raw["number"], title=raw["title"], body=(raw.get("body") or "")[:4000],
                                     base=base)
        r = llm.run(prompt, EFFORT, cwd=str(wt), tools=SKILL_TOOLS, sandbox="replay")
        secs = time.time() - t0
        trace = transcript_summary(wt)
    # the skill runs unchanged (its own markdown report); a separate tool-less call always extracts the issues
    budget.check("extract")
    t1 = time.time()
    e = llm.run(EXTRACT_PROMPT.format(report=r["text"]), "low")
    ext = {"cost": e["cost"], "raw": e["text"], "model": e.get("model"), "usage": e.get("usage"),
           "secs": round(time.time() - t1, 1)}
    items, how = parse_issues(e["text"]), "extracted"
    findings = None if items is None else [
        {"id": f"f{i}", "severity": SKILL_SEV.get(str(x.get("severity", "")).lower(), "minor"),
         "scope": "line" if x.get("path") and isinstance(x.get("line"), int) else "file" if x.get("path") else "pr",
         "title": str(x.get("title", "")), "body": str(x.get("body", "")),
         "locations": [{"path": x["path"], "start": x["line"] if isinstance(x.get("line"), int) else None}]
         if x.get("path") else [], "skill_severity": x.get("severity")}
        for i, x in enumerate(items, 1)]
    run = {"pr": s["pr"], "commit": s["commit"], "base": base, "arm": "skill", "findings": findings,
           "json": how if items is not None else "none", "raw": r["text"], "cost": r["cost"], "turns": r["turns"],
           "denials": r["denials"], "usage": r.get("usage"), "model": r.get("model"), "secs": round(secs, 1),
           "extraction": ext, "installed": installed, "trace": trace, "n_subagents": len(trace["agents"])}
    save(p, run)
    return run


def parse_issues(text: str) -> list[dict] | None:
    """The issue list at the end of a skill report, or None if there is none parsable."""
    try:
        obj = llm.extract_json(text)
    except ValueError:
        return None
    if isinstance(obj, dict):
        obj = obj.get("issues", obj.get("findings"))
    if not isinstance(obj, list) or not all(isinstance(x, dict) for x in obj):
        return None
    return obj


# ---------------------------------------------------------------- arm B: lmreview

def run_lmreview(cfg: Config, s: dict, budget: Budget) -> dict:
    """Arm B on sample `s` as replay.replay_one runs it; cached in lmreview/runs/."""
    p = OUT / "lmreview" / "runs" / REVIEWER.replace("+", "_").replace("@", "_") / f"{key_of(s)}.json"
    if p.exists():
        return json.loads(p.read_text())
    budget.check("lmreview")
    t0 = time.time()
    with sample_workspace(cfg, s, "review", reviewer_context(REVIEWER)) as (wt, base):
        r = run_reviewer(wt, cached_pr(cfg, s["pr"], s["time"]), REVIEWER)
    run = {"pr": s["pr"], "commit": s["commit"], "base": base, **r, "model": run_models(r),
           "arm": "lmreview", "secs": round(time.time() - t0, 1)}
    save(p, run)
    return run


# ---------------------------------------------------------------- blinded judging

def blind(run: dict, seed: int = 0) -> tuple[dict, dict]:
    """The run as the judge sees it, and the map from neutral id to the original finding id.

    Every finding becomes {id, severity, path, line, title, body}: neutral ids F1..Fn in a shuffled order,
    one fixed severity for all (the schema needs one; the arms' scales differ), the primary location's
    path and first line, no rule / support / stage fields. "version" fixes the judge's workspace context
    (the same for both arms)."""
    fs = load_findings(run) or []
    order = list(range(len(fs)))
    random.Random(f"{seed}-{run['pr']}-{run['commit']}-{run['arm']}").shuffle(order)
    out, mp = [], {}
    for n, i in enumerate(order, 1):
        f, loc = fs[i], fs[i].primary()
        out.append({"id": f"F{n}", "severity": "minor", "title": f.title, "body": f.body,
                    **({"path": loc.path, "line": loc.start} if loc else {})})
        mp[f"F{n}"] = f.id
    judged = {"pr": run["pr"], "commit": run["commit"], "version": REVIEWER.split("+")[0],
              "findings": out if run.get("findings") is not None else None}
    return judged, mp


def judge(cfg: Config, s: dict, arm: str, run: dict, budget: Budget) -> dict:
    """Blind `run` and grade it with score.score_one; cached in <arm>/scores/."""
    judged, mp = blind(run)
    save(OUT / arm / "blind" / f"{key_of(s)}.json", {"judged": judged, "map": mp})
    sp = OUT / arm / "scores" / f"{key_of(s)}.json"
    if not sp.exists():
        budget.check("judge")
    _, cm = load_gold(cfg)
    t0 = time.time()
    sc = score_one(cfg, judged, s, [cm[i] for i in s["gold_ids"]], sp, str(get("judge", "effort")))
    sc.setdefault("secs", round(time.time() - t0, 1))
    return sc | {"map": mp}


# ---------------------------------------------------------------- metrics

def pkey(h: dict) -> str:
    return str(h.get("key", f"{h['id']}.{h.get('point', 0)}"))


def metrics(run: dict, sc: dict, arm: str) -> dict:
    want = [h for h in sc["human"] if h["type"] in WANT]
    found = [h for h in want if h["matched_ai"]]
    sev = C.defaultdict(lambda: [0, 0])
    for h in want:
        sev[h.get("severity") or "?"][1] += 1
        sev[h.get("severity") or "?"][0] += bool(h["matched_ai"])
    v = C.Counter(str(a.get("valid")) for a in sc["ai"])
    n_ai = len(run.get("findings") or [])
    m = {"found": len(found), "total": len(want), "by_severity": {k: f"{a}/{b}" for k, (a, b) in sorted(sev.items())},
         "by_type": dict(C.Counter(f"{h['type']}:{'found' if h['matched_ai'] else 'missed'}" for h in want)),
         "n_findings": n_ai, "valid": v["True"], "invalid": v["False"], "unsure": v["unsure"],
         "valid_frac": round(v["True"] / n_ai, 2) if n_ai else None,
         "cost_review": round(run.get("cost") or 0, 3), "cost_judge": round(sc.get("cost") or 0, 3),
         "secs_review": run.get("secs"), "found_keys": sorted(pkey(h) for h in found)}
    if arm == "skill":
        m["cost_extract"] = round((run.get("extraction") or {}).get("cost") or 0, 3)
        m["n_subagents"] = run.get("n_subagents")
        m["models"] = sorted((run.get("usage") or {}))
    if arm == "lmreview":  # points found only through findings that came from a rule (their "rule" field)
        mp, orig = sc["map"], {str(f.get("id")): f for f in run.get("findings") or []}
        ruled = lambda x: bool((orig.get(str(mp.get(x))) or {}).get("rule"))  # noqa: E731
        m["found_via_rulecheck_only"] = sum(all(map(ruled, h["matched_ai"])) for h in found)
        m["n_rulecheck_findings"] = sum(1 for f in orig.values() if f.get("rule"))
    return m


def compare(cfg: Config, s: dict, budget: Budget) -> dict:
    """Both arms on sample `s`, judged; returns per-arm metrics and the overlap of found points."""
    res: dict = {"pr": s["pr"], "commit": s["commit"][:8]}
    runs = {"skill": run_skill(cfg, s, budget), "lmreview": run_lmreview(cfg, s, budget)}
    for arm, run in runs.items():
        if run.get("findings") is None:
            res[arm] = {"error": run.get("error") or "no findings"}
            continue
        res[arm] = metrics(run, judge(cfg, s, arm, run, budget), arm)
    if all("found_keys" in res[a] for a in runs):
        a, b = set(res["skill"]["found_keys"]), set(res["lmreview"]["found_keys"])
        res["overlap"] = {"skill_only": len(a - b), "lmreview_only": len(b - a), "both": len(a & b)}
    return res


def first_per_half(sel: list[dict], n: int) -> list[dict]:
    out, cnt = [], C.Counter()
    for x in sel:
        if cnt[x["half"]] < n:
            out.append(x)
            cnt[x["half"]] += 1
    return out


def run_many(cfg: Config, xs: list[dict], budget: Budget, workers: int) -> None:
    """Compare both arms on samples `xs`, `workers` at a time; each result goes to results/<key>.json."""
    from concurrent.futures import ThreadPoolExecutor

    def one(x: dict) -> str:
        s = x["sample"]
        rp = OUT / "results" / f"{key_of(s)}.json"
        if rp.exists():
            return f"#{s['pr']}: cached"
        try:
            r = compare(cfg, s, budget)
        except BudgetStop as e:
            return f"#{s['pr']}: {e}"
        except Exception as e:  # noqa: BLE001  one sample failing must not stop the others
            return f"#{s['pr']}: error {e!r}"
        save(rp, r | {"half": x["half"]})
        return f"#{s['pr']}: done (spent ${budget.spent:.2f})"
    with ThreadPoolExecutor(workers) as ex:
        for msg in ex.map(one, xs):
            print(msg, flush=True)
    print(f"spent this process: ${budget.spent:.2f}")


def summary() -> None:
    """Recall of human points (by half and severity), findings, valid share, cost and time per arm."""
    rs = [json.loads(p.read_text()) for p in sorted((OUT / "results").glob("*.json"))]
    for half in ("covered", "resolved", "all"):
        xs = [r for r in rs if half == "all" or r["half"] == half]
        if not xs:
            continue
        print(f"\n## {half} ({len(xs)} samples)")
        for arm in ("skill", "lmreview"):
            ms = [r[arm] for r in xs if "found" in r.get(arm, {})]
            if not ms:
                continue
            f, t = sum(m["found"] for m in ms), sum(m["total"] for m in ms)
            sev = C.defaultdict(lambda: [0, 0])
            for m in ms:
                for k, v in m["by_severity"].items():
                    a, b = map(int, v.split("/"))
                    sev[k][0] += a
                    sev[k][1] += b
            n = sum(m["n_findings"] for m in ms)
            line = (f"{arm:9s} recall {f}/{t} = {f / t:.0%} | " + ", ".join(f"{k} {a}/{b}" for k, (a, b) in sorted(sev.items()))
                    + f" | findings {n}"
                    + f" | review ${sum(m['cost_review'] for m in ms):.2f}"
                    + (f" (+extract ${sum(m.get('cost_extract', 0) for m in ms):.2f})" if arm == "skill" else "")
                    + f", {sum(m['secs_review'] or 0 for m in ms) / len(ms):.0f} s/sample")
            if arm == "lmreview":
                line += f" | via rule check only {sum(m['found_via_rulecheck_only'] for m in ms)}"
            print(line)
        ov = [r["overlap"] for r in xs if "overlap" in r]
        if ov:
            print("overlap: " + ", ".join(f"{k} {sum(o[k] for o in ov)}" for k in ("skill_only", "lmreview_only", "both")))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["select", "pilot", "report", "run", "summary"])
    ap.add_argument("--half", choices=["covered", "resolved"])
    ap.add_argument("--prs", type=int, nargs="*")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--cap", type=float, default=12.0)
    ap.add_argument("--n", type=int, default=1, help="samples per half")
    a = ap.parse_args()
    cfg = Config()
    sel = select_samples(cfg)
    print_selection(sel)
    if a.cmd == "select":
        return
    # git inside the sandbox cannot read ~/.gitconfig (reads under $HOME are denied): give it none
    os.environ.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    budget = Budget(a.cap)
    if a.cmd == "summary":
        return summary()
    if a.cmd == "run":
        return run_many(cfg, [x for x in sel if (not a.half or x["half"] == a.half) and (not a.prs or x["sample"]["pr"] in a.prs)],
                        budget, a.workers)
    out = []
    for x in first_per_half(sel, a.n if a.cmd == "report" else 1):
        s = x["sample"]
        print(f"\n== {x['half']} #{s['pr']} {s['commit'][:8]} (spent ${budget.spent:.2f})", flush=True)
        try:
            r = compare(cfg, s, budget)
        except BudgetStop as e:
            print(e, flush=True)
            break
        r["half"] = x["half"]
        out.append(r)
        print(json.dumps(r, indent=1), flush=True)
    save(OUT / f"{a.cmd}_results.json", out)
    print(f"\nspent this process: ${budget.spent:.2f}")


if __name__ == "__main__":
    main()

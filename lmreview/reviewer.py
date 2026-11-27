"""The reviewer agent and the public entry point `review_pr`."""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import pathlib
import re
import subprocess

from . import github, llm
from .annotate import cid_of
from .ensemble import ensemble
from .config import Config
from .settings import get
from .project import NAME, localize_module
from .state import book_path, part_path, prompt_params, prompt_path
from .schema import SCHEMA_VERSION, SEVERITIES, Finding, SchemaError, cites, load_findings, parse_findings, to_dicts
from .workspace import TOOLS, live_workspace, pr_meta


# What people get out of the box: the current prompt and config with the book in use (lmreview/state.py).
def _default_reviewer() -> str:
    from .state import reviewer
    return reviewer()


DEFAULT_REVIEWER = os.environ.get("LMREVIEW_REVIEWER") or _default_reviewer()


# -ms (a retired experiment) is still accepted: older ledger rows name reviewers with it
_NAME = re.compile(r"([\w.-]+?)(?:\+([\w.-]+?))?(?:@([a-z]+))?(-r[co])?(-ms)?")


def parse_reviewer(name: str) -> tuple[str, str | None, str]:
    """A reviewer is named `<prompt>[+<rules>][@<effort>][-rc|-ro]`, e.g. `p990f2d2e+v0032@medium-rc`
    (-rc: see rulecheck_of; -ro: see ruleonly_of).

    A "#<tag>" suffix (a repeat run of the same reviewer, e.g. "#r2") is ignored.

    Returns:
        (prompt version, rulebook name or None, effort; default "high").
    """
    m = _NAME.fullmatch(name.split("#")[0])
    if not m:
        raise ValueError(f"bad reviewer name {name!r}; expected <prompt>[+<rules>][@<effort>][-rc|-ro]")
    if (m[4] or m[5]) and not m[3]:  # else "v0b+foo-rc" is ambiguous: rulebook "foo-rc", or "foo" + rule check
        raise ValueError(f"bad reviewer name {name!r}: -rc / -ro need an explicit @<effort> before them")
    return m[1], m[2], m[3] or "high"


def rulecheck_of(name: str) -> bool:
    """Whether `name` asks for a rule-check run next to the reviews (`-rc` suffix, needs a rulebook):
    one more agent that must give a verdict on every applicable rule, merged with the reviews."""
    m = _NAME.fullmatch(name.split("#")[0])
    return bool(m and m[4] == "-rc" and m[2])


def ruleonly_of(name: str) -> bool:
    """Whether `name` is a rule-only reviewer (`-ro`, needs a rulebook): the rule-check agent alone, without
    the full review. vet uses it to check rule changes: a rule's hits come from the rule check (on the v0007
    runs every matched point found through a rule-citing finding had the rule check among its sources), so
    replaying the full review there only pays for the part no rule change touches."""
    m = _NAME.fullmatch(name.split("#")[0])
    return bool(m and m[4] == "-ro" and m[2])


def prompt_template(version: str) -> tuple[str, tuple[str, ...]]:
    """Prompt text of `version` and the extra workspace context it declares.

    A prompt may start with directive lines that are not sent to the model:
    `<!-- context: vllm -->` (extra workspace context) and `<!-- rules: nowhy -->` (see rule_why).
    """
    text, ctx = prompt_path(version).read_text(), ()
    while m := re.match(r"<!--\s*(context|rules):\s*([\w, .-]*?)\s*-->\n", text):
        if m[1] == "context":
            ctx = tuple(x.strip() for x in m[2].split(",") if x.strip())
        text = text[m.end():]
    return text, ctx


def rule_why(version: str) -> bool:
    """Whether prompt `version` shows each rule's "why" (on unless `<!-- rules: nowhy -->`).

    The why stays in the book as a record of where an entry comes from (like its evidence), but the
    reviewer acts on when + expect; leaving it out shortens every review's rule list (2026-11-25).
    """
    return not re.search(r"^<!--\s*rules:\s*nowhy\s*-->$", prompt_path(version).read_text(), re.M)


def reviewer_context(reviewer: str) -> tuple[str, ...]:
    """Extra workspace context the reviewer's prompt needs (the judge gets the same)."""
    return prompt_template(parse_reviewer(reviewer)[0])[1]


def load_rules(name: str) -> list[dict]:
    """Rulebook rules/<name>.jsonl: {"id", "when", "expect", "why", "examples", "paths": [glob],
    "evidence": [comment ids], "n_prs", "status", "area",
    "kind": "principle" | "knowledge"}."""
    return [json.loads(l) for l in book_path(name).open() if l.strip()]


def rule_evidence(reviewer: str) -> set[int]:
    """Human comments the reviewer's rulebook was distilled from (all entries, retired too).

    A sample whose gold holds one of them cannot test this reviewer: the rule was written from the answer.
    """
    rules = parse_reviewer(reviewer.split("#")[0])[1]
    return {cid_of(e) for r in load_rules(rules) for e in r.get("evidence") or []} if rules else set()  # points: their comment


def changed_paths(wt: pathlib.Path) -> list[str]:
    """Paths touched by PR.diff in workspace `wt`."""
    d = (wt / "PR.diff").read_text(errors="replace") if (wt / "PR.diff").exists() else ""
    return sorted(set(re.findall(r"^diff --git a/\S+ b/(\S+)", d, re.M)))


def applicable(rules: list[dict], paths: list[str]) -> list[dict]:
    """The active rules that apply to `paths` (rules without paths always apply)."""
    use = [r for r in rules if r.get("status", "active") == "active"]
    return [r for r in use if not r.get("paths") or any(fnmatch.fnmatch(p, g) for p in paths for g in r["paths"])]


def rule_lines(use: list[dict], why: bool = True) -> list[str]:
    """One prompt line per rule: id, kind (and principle, if it is a specialization of one), text;
    with `why`, its why (rule_why)."""
    def text(r: dict) -> str:
        t = f"When {r['when']}: {r['expect']}" if r.get("expect") else r.get("rule", "")
        return t.rstrip(".") + "." + (f" Why: {r['why']}" if why and r.get("why") else "")
    return [f"- [{r['id']}] ({r.get('kind', 'principle')}" + (f", under {r['principle']}" if r.get("principle") else "")
            + f") {text(r)}" for r in use]


def rules_section(rules: list[dict], paths: list[str], why: bool = True) -> str:
    """The prompt section with the active rules that apply to `paths` (rules without paths always apply)."""
    use = applicable(rules, paths)
    if not use:
        return ""
    lines = rule_lines(use, why)
    return (f"\n\nTeam rules distilled from past {NAME} reviews. Check the change against the ones "
            "that apply; when a finding follows from a rule, put its id in the finding's \"rule\" "
            "field. A rule finding must be about code this PR adds or changes: do not raise a rule "
            "against behavior the PR leaves as it was.\n"
            + "\n".join(lines) + "\n")


def _primary_path(f: dict) -> str | None:
    locs = [x for x in f.get("locations") or [] if x.get("role") == "primary"] or list(f.get("locations") or [])
    return locs[0].get("path") if locs else None


SAME_PROMPT = """Below are pairs of code review findings on the same file, citing the same team rule. For
each pair, answer whether B raises the same problem as A (so B can be dropped as a repeat), or a
different problem that only falls under the same rule. Answer with one ```json block:
[{{"pair": <n>, "same": true | false}}, ...]

{pairs}"""


def drop_repeats(main: list[dict], rulecheck: list[dict], confirm: bool = True) -> tuple[list[dict], float]:
    """The rule check's findings without those the main review already raised (the main review sees the
    rulebook too). Candidates: same rule and same primary file as a main finding. With `confirm`, one
    small tool-less call ([review] dedupe_model, low effort) checks the candidates and keeps those that
    raise a different problem under a broad rule; on failure every candidate is kept.

    Returns:
        (the rule-check findings kept, the call's cost).
    """
    by_key: dict = {}
    for f in main:
        if f.get("rule"):
            by_key.setdefault((f.get("rule"), _primary_path(f)), []).append(f)
    cand = [(k, f) for k, f in enumerate(rulecheck) if (f.get("rule"), _primary_path(f)) in by_key]
    if not cand:
        return list(rulecheck), 0.0
    drop, cost = {k for k, _ in cand}, 0.0
    if confirm:
        brief = lambda f: f"{f.get('title', '')}: {f.get('body', '')}"  # noqa: E731
        pairs = "\n\n".join(
            f"Pair {n}:\n" + "\n".join(f"A: {brief(g)}" for g in by_key[(f.get('rule'), _primary_path(f))])
            + f"\nB: {brief(f)}" for n, (_, f) in enumerate(cand, 1))
        r = llm.run(SAME_PROMPT.format(pairs=pairs), "low", model=str(get("review", "dedupe_model")))
        cost = r.get("cost") or 0.0
        try:
            same = {int(x["pair"]) for x in llm.extract_json(r.get("text") or "") if x.get("same") is True}
            drop = {k for n, (k, _) in enumerate(cand, 1) if n in same}
        except (ValueError, TypeError, KeyError):
            drop = set()
    return [f for k, f in enumerate(rulecheck) if k not in drop], cost


def run_reviewer(wt: pathlib.Path, raw: dict, reviewer: str = DEFAULT_REVIEWER,
                 only: set[str] | None = None) -> dict:
    """Run `reviewer` (see parse_reviewer) in workspace `wt` for PR `raw`.

    Returns:
        {"schema_version", "findings": list of schema.Finding dicts | None (None = output not
         parsable or not schema-valid, see "error"), "error", "raw": text, "cost", "turns",
         "denials", "effort", "version", "rules", "reviewer"}. With -rc the findings of the main review
        and the rule check stand side by side, each with "support" 1; "parallel" = 2, "runs" = each
        run's findings/error/cost, "cost" = both runs plus the dedupe call.

    `only`: with a rule-only reviewer (-ro), check only these rule ids of the book (vet uses it).
    """
    version, rules, effort = parse_reviewer(reviewer.split("#")[0])
    if re.fullmatch(r"p[0-9a-f]{8}", version):
        from .state import prompt_id
        if version != prompt_id():  # an older id's saved prompts may need tools, a merge agent or other params
            raise ValueError(f"{version} is not the current prompt ({prompt_id()}): its cached runs stay readable, "
                             "but new runs need the current prompt")
        prompt_id(save=True)  # keep the text of every prompt a run used
    prompt = prompt_template(version)[0].format(**pr_meta(raw))
    use = applicable(load_rules(rules), changed_paths(wt)) if rules else []
    if only is not None:  # a rule-only run on some rules of the book (vet: the changed ones and their links)
        if not ruleonly_of(reviewer):
            raise ValueError("only= is for rule-only (-ro) reviewers")
        use = [r for r in use if r["id"] in only]
    if rules:
        sec = rules_section(load_rules(rules), changed_paths(wt), rule_why(version))
        prompt = prompt.replace("\nFinish with one JSON block", sec + "\nFinish with one JSON block", 1) \
            if "\nFinish with one JSON block" in prompt else prompt + sec
    meta = {"schema_version": SCHEMA_VERSION, "effort": effort, "version": version, "rules": rules,
            "reviewer": reviewer}
    n, rc, ro = 1, rulecheck_of(reviewer) and bool(use), ruleonly_of(reviewer)
    tools = TOOLS

    def once() -> dict:
        return _parsed(llm.run(prompt, effort, cwd=str(wt), tools=tools))

    def side_by_side(ok: list[dict]) -> dict:  # no merge call, ids made unique as "<run>.<id>"
        main = [f for x in ok if x.get("kind") != "rulecheck" for f in x["findings"]]
        cost, kept = 0.0, {}
        for i, x in enumerate(ok):
            if x.get("kind") == "rulecheck":
                kept[i], c = drop_repeats(main, x["findings"])
                cost += c
        fs = [{**f, "id": f"{i}.{f.get('id') or k}", "support": 1}
              for i, x in enumerate(ok, 1) for k, f in enumerate(kept.get(i - 1, x["findings"]), 1)]
        return {"findings": fs, "error": None, "raw": "", "cost": cost, "turns": 0, "denials": [], "usage": {}}

    def rulecheck() -> dict:
        """The rule-check agent: a verdict per rule, so a long rulebook cannot crowd rules out. It reads the
        diff and discussion without tools, on a long book after a picking stage (rule_stage)."""
        t = part_path(version, "rulecheck").read_text()
        ctx = rulecheck_context(wt)
        rce = str(prompt_params(version)["rulecheck_effort"])  # its own effort, part of the prompt id
        rsys = None
        if "{shared}" in t:  # the PR and its context go in the system prompt, the same for the picking stage and
            # the check, so the check reads them from the cache the pick wrote instead of paying for them again
            rsys = (SHARED_HEAD.format(**pr_meta(raw)) + ctx).strip()
        def one(rules_: list[dict]) -> dict:
            check, pick = rule_stage(version, rules_, ctx, raw, rce, rsys)
            p = t.format(rules="\n".join(rule_lines(check, rule_why(version))), context=ctx, shared="", **pr_meta(raw))
            r = _parsed(llm.run(p, rce, cwd=str(wt), tools="", system=rsys), rulecheck=True)
            if pick:  # rules left out in stage 1 get a verdict too: not applicable
                left = [x["id"] for x in rules_ if x not in check]
                r["verdicts"] = list(r.get("verdicts") or []) + [
                    {"rule": i, "applies": False, "violated": False, "why": "not picked from its when-line"} for i in left]
                r.update(cost=r["cost"] + pick["cost"], usage=llm.add_usage(r.get("usage"), pick.get("usage")),
                         stage={"picked": [x["id"] for x in check], "left": left, "cost": pick["cost"]})
            return r

        return one(use)

    if ro:  # the rule check alone; no applicable rule: nothing to check, no run
        r = rulecheck() if use else {"findings": [], "error": None, "raw": "", "cost": 0.0, "turns": 0,
                                     "denials": [], "usage": {}, "kind": "rulecheck", "verdicts": []}
        if r["findings"] is not None:
            r["findings"] = [{**f, "support": 1} for f in r["findings"]]
        return {**r, **meta}
    e = ensemble(once, n, side_by_side, ok=lambda x: x["findings"] is not None,
                 extra=[rulecheck] if rc else [])
    if n == 1 and not rc:
        return {**e.result, **meta}
    n += rc  # the rule check counts as a run for "support"
    out = dict(e.result)
    if not e.merged and out["findings"] is not None:  # one usable run, or the merge failed: unmerged
        out["findings"] = [{**f, "support": 1} for f in out["findings"]]
    merge_cost = e.merge["cost"] if e.merge else 0.0
    usage = llm.add_usage(*(x.get("usage") for x in e.runs), e.merge.get("usage") if e.merge else None)
    keep = {"parallel": n, "merged": e.merged, "merge_cost": merge_cost, "usage": usage,
            "merge_error": None if e.merged or not e.merge else e.merge["error"],
            # raw kept per run so scripts/reparse_invalid.py can recover any of them
            "runs": [{k: x[k] for k in ("findings", "error", "raw", "cost", "turns", "kind", "verdicts", "usage", "stage", "model") if k in x}
                     for x in e.runs]}
    return {**out, "cost": sum(x["cost"] for x in e.runs) + merge_cost, **keep, **meta}


SYMBOLS_MAX, SYMBOL_LINES, SYMBOLS_CHARS = 25, 8, 14000  # names looked up, lines per name, section size
SYMBOL_FILES = 12  # files listed per name beyond its shown lines
_SRC = tuple(get("project", "source_globs"))
_COMMON = {"self", "None", "True", "False", "return", "import", "from", "class", "def", "init", "main", "test",
           "args", "kwargs", "data", "value", "name", "type", "list", "dict", "self.", "config"}


def diff_symbols(diff: str) -> list[str]:
    """Names a rule may need to check outside the diff: functions and classes the diff defines or
    changes, and identifiers in backticks on changed lines of docs (what the docs claim about code).
    Doc names first, then definitions, at most SYMBOLS_MAX."""
    docs, defs, path = [], [], ""
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path = line.rsplit(" b/", 1)[-1]
            continue
        if line.startswith(("+++ a/", "+++ b/", "--- a/", "--- b/", "+++ /dev/null", "--- /dev/null")):
            continue
        if line.startswith("@@"):
            m = re.search(r"\b(?:def|class)\s+(\w+)", line)
            if m:
                defs.append(m.group(1))
            continue
        if not line[:1] in "+-" or line[:3] in ("+++", "---"):
            continue
        if path.endswith((".md", ".rst")):
            docs += [x.strip("()") for x in re.findall(r"`([A-Za-z_][\w.]*(?:\(\))?)`", line)]
        else:
            defs += re.findall(r"^[+-]\s*(?:async\s+)?(?:def|class)\s+(\w+)", line)
    out = []
    for x in docs + defs:
        x = x.split(".")[-1]
        # a code name: has an underscore or inner capital (skips words like "cuda", "auto", "torch")
        if len(x) >= 4 and x not in _COMMON and x not in out and ("_" in x.strip("_") or re.search(r"[a-z][A-Z]", x)):
            out.append(x)
    return out[:SYMBOLS_MAX]


def symbol_context(wt: pathlib.Path, diff: str) -> str:
    """Where the diff's names are defined and used in the repository at this commit (grep), so the
    tool-less rule check can verify claims that reach outside the diff (callers, which modes use a
    function). Every name gets the same share of SYMBOLS_CHARS (definitions first, then uses outside
    tests). Empty when the diff names nothing to look up."""
    found = []
    for name in diff_symbols(diff):
        try:
            r = subprocess.run(["grep", "-rnwI", *[f"--include={g}" for g in _SRC], "--exclude-dir=vllm",
                                "--exclude-dir=dev", "--exclude=PR_HISTORY.md", "--", name, "."],
                               cwd=wt, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        hits = [h[2:] if h.startswith("./") else h for h in r.stdout.splitlines()]
        if not hits:
            continue
        hits.sort(key=lambda h: (not re.search(rf"\b(def|class)\s+{re.escape(name)}\b", h), "test" in h.split(":")[0]))
        found.append((name, hits))
    if not found:
        return ""
    per = max(2, min(SYMBOL_LINES, SYMBOLS_CHARS // (len(found) * 150)))  # lines per name, to fit the budget
    lines: list[str] = []
    for n_done, (name, hits) in enumerate(found):
        if sum(len(x) + 1 for x in lines) > SYMBOLS_CHARS:
            lines.append(f"(not shown: {', '.join(x for x, _ in found[n_done:])})")
            break
        files: dict[str, int] = {}
        for h in hits:
            files[h.split(":")[0]] = files.get(h.split(":")[0], 0) + 1
        lines += [f"## {name} ({len(hits)} lines in {len(files)} files)"] + [h[:140] for h in hits[:per]]
        if len(hits) > per:  # the rest as the files they are in: which modules and paths use the name
            rest = sorted(files, key=lambda f: ("test" in f, f))
            lines.append("also in: " + ", ".join(f"{f} ({files[f]})" for f in rest[:SYMBOL_FILES])
                         + (f", ... {len(rest) - SYMBOL_FILES} more files" if len(rest) > SYMBOL_FILES else ""))
    return "\n".join(lines)


SHARED_HEAD = "You review pull request #{number} of LMCache ({title}). Its diff and context:\n\n"


def rulecheck_context(wt: pathlib.Path) -> str:
    """What the tool-less rule check reads: the PR's diff, the review discussion so far, and where the
    names the diff defines or its docs mention are defined and used in the repository (symbol_context).

    Args:
        wt: the sample's workspace (PR.diff, PR_HISTORY.md, the source tree at the commit).

    Returns:
        The prompt text, as markdown sections.
    """
    diff = (wt / "PR.diff").read_text(errors="replace")
    parts = ["# PR.diff\n```diff\n" + diff + "\n```"]
    h = wt / "PR_HISTORY.md"
    if h.exists():
        parts.append("# PR_HISTORY.md (the review discussion so far)\n" + h.read_text(errors="replace"))
    sym = symbol_context(wt, diff)
    if sym:
        parts.append("# SYMBOLS (grep of the repository at this commit: where names from the diff and its docs are "
                     "defined and used; may be incomplete)\n```\n" + sym + "\n```")
    return "\n\n".join(parts)


def rule_stage(version: str, use: list[dict], ctx: str, raw: dict, effort: str,
               system: str | None) -> tuple[list[dict], dict | None]:
    """Stage 1 of a rule check on a long rulebook: when the rules in `use` total more words than [review]
    rulecheck_stage_words, one call picks from their "when" lines the rules this PR could be in.

    Args:
        version: the prompt version (its rulepick.md part).
        use: the rules that apply to the PR's paths.
        ctx: the diff and discussion (rulecheck_context).
        raw: the PR, for its number and title.
        effort: thinking effort of the call.
        system: the system prompt of the rule check (the PR and its context).

    Returns:
        (the rules to check in full, the picking call's {"cost", "usage"} or None when not staged; a
         failed or empty pick checks every rule).
    """
    words = sum(len(f"{r.get('when', '')} {r.get('expect', '')} {r.get('why', '') if rule_why(version) else ''}".split())
                for r in use)
    if words <= int(prompt_params(version)["rulecheck_stage_words"]):
        return use, None
    try:
        t = part_path(version, "rulepick").read_text()
    except FileNotFoundError:  # a prompt version from before staging
        return use, None
    lines = "\n".join(f"- {r['id']}: {r.get('when') or r.get('rule', '')}" for r in use)
    try:
        res = llm.run(t.format(rules=lines, context=ctx, shared="", **pr_meta(raw)), effort, tools="", system=system)
    except Exception:  # a failed pick checks every rule rather than losing the rule check
        return use, None
    try:
        ids = {x for x in (llm.extract_json(res["text"]) or {}).get("picked") or [] if isinstance(x, str)}
    except (ValueError, AttributeError, TypeError):
        ids = set()
    pick = {"cost": res.get("cost") or 0.0, "usage": res.get("usage")}
    chosen = [r for r in use if r["id"] in ids]
    return (chosen or use), pick


def _unfiled(verdicts: object, findings: list) -> list[dict]:
    """PR-level findings for rules judged violated that no rule-check finding cites, built from the
    verdict's `why`, so a violation the model judged but did not write up still reaches the merge."""
    cited = {r for f in findings if isinstance(f, dict) for r in cites(f)}
    vs = [v for v in verdicts or [] if isinstance(v, dict) and v.get("violated") and v.get("rule")
          and v["rule"] not in cited]
    return [{"id": f"rv{i}", "severity": "minor", "scope": "pr", "title": f"Violates team rule {v['rule']}",
             "body": str(v.get("why") or ""), "locations": [], "rule": v["rule"]} for i, v in enumerate(vs, 1)]


def _parsed(r: dict, rulecheck: bool = False) -> dict:
    """One llm.run result as run-file fields: findings (None if unparsable) and the error; a rule check
    (rulecheck.md output: {"verdicts", "findings"}) also keeps its per-rule verdicts."""
    findings, error, verdicts = None, None, None
    try:
        obj = llm.extract_json(r["text"])
        if rulecheck:
            if not isinstance(obj, dict):
                raise SchemaError("rule check output must be an object with verdicts and findings")
            verdicts, obj = obj.get("verdicts"), obj.get("findings") or []
            obj = obj + _unfiled(verdicts, obj)
        findings = to_dicts(parse_findings(obj))
    except (ValueError, SchemaError) as e:  # SchemaError is a ValueError; kept explicit for clarity
        error = str(e)
    out = {"findings": findings, "error": error, "raw": r["text"], "cost": r["cost"], "turns": r["turns"],
           "denials": r["denials"], "usage": r.get("usage") or {}, "model": r.get("model")}
    return out | ({"kind": "rulecheck", "verdicts": verdicts} if rulecheck else {})


def review_pr(pr: int, commit: str | None = None, reviewer: str = DEFAULT_REVIEWER,
              cfg: Config | None = None) -> dict:
    """Review PR `pr` as it is now (or at `commit`). Read-only: nothing is posted to GitHub.

    Returns:
        run_reviewer's dict plus "pr", "title", "commit", "base".
    """
    cfg = cfg or Config()
    missing = [t for t in ("claude", "gh", "git") if not shutil.which(t)]
    if missing:
        raise RuntimeError(f"lmreview needs {', '.join(missing)} on PATH (claude: logged in; gh: `gh auth login`)")
    raw = github.fetch_pr(pr)
    with live_workspace(cfg, raw, commit, reviewer_context(reviewer)) as (wt, c, base):
        out = run_reviewer(wt, raw, reviewer)
    from .state import book_label, book_seed
    return {"pr": pr, "title": raw["title"], "commit": c, "base": base, "repo": f"{github.REPO_OWNER}/{github.REPO_NAME}",
            "rules_label": book_label(parse_reviewer((out.get("reviewer") or reviewer).split("#")[0])[1]),
            "rules_seed": book_seed(), **out}


def github_review(r: dict, inline: bool = True, cfg: Config | None = None) -> dict:
    """review_pr's result `r` as a GitHub review payload (ghreview.build): a summary and inline comments."""
    from . import ghreview
    cfg = cfg or Config()
    book = parse_reviewer(r["reviewer"].split("#")[0])[1] if r.get("reviewer") else None
    rules = {x["id"]: x for x in load_rules(book)} if book else {}
    from .provenance import sources
    rules = {k: x | {"_sources": sources(x, cfg)} for k, x in rules.items()}  # where each rule was learned (ghreview)
    diff = subprocess.run(["git", "-C", str(cfg.repo), "diff", "-U3", "-M", "--no-color", r["base"], r["commit"]],
                          capture_output=True, text=True, check=True).stdout
    # $LMREVIEW_BOOK_URL: where `lmreview watch` publishes this repository's rulebooks (<url>/<vNNNN>.md)
    base = os.environ.get("LMREVIEW_BOOK_URL")
    return ghreview.build(r, load_findings(r) or [], diff, rules, r.get("repo") or f"{github.REPO_OWNER}/{github.REPO_NAME}",
                          inline, f"{base}/{book}.md" if base and book else None)


def to_markdown(r: dict) -> str:
    """Render a review: blocker/major in full, minor/nit folded; each item shows scope and places."""
    head = [f"# AI review of #{r['pr']}: {r.get('title', '')}", "",
            f"commit `{r['commit'][:10]}` vs base `{r['base'][:10]}` · reviewer "
            f"{r.get('reviewer') or str(r.get('version')) + '@' + str(r.get('effort'))}"
            + (f" · rules: {r['rules_label']}" if r.get("rules_label") else "")
            + (f" (seeded from {r['rules_seed']})" if r.get("rules_seed") else "") + f" · ${r['cost']:.2f}", ""]
    fs = load_findings(r)
    if fs is None:
        return "\n".join(head + [f"Could not parse the reviewer output ({r.get('error')}):", "", r["raw"]])
    if not fs:
        return "\n".join(head + ["No findings."])
    fs.sort(key=lambda f: SEVERITIES.index(f.severity))
    book = parse_reviewer(r["reviewer"].split("#")[0])[1] if r.get("reviewer") else None
    rules = {x["id"]: x for x in load_rules(book)} if book else {}
    cited = [f for f in fs if f.rule or f.rules]
    if cited:
        head += [f"{len(cited)} of {len(fs)} findings follow a team rule ({r.get('rules_label') or book or 'no rulebook'}).", ""]

    def rule_line(rule: str) -> str:
        x = rules.get(rule)
        if x is None:  # the model named an id that is not in the reviewer's rulebook
            return f"Rule: `{rule}` (not in {book or 'any rulebook'})"
        return f"Rule: `{rule}` · when {x.get('when') or x.get('rule', '')}"

    n = r.get("parallel") or 1
    if n > 1:  # merged parallel review: within a severity, what more runs agree on comes first
        fs.sort(key=lambda f: (SEVERITIES.index(f.severity), -(f.support or 1)))
        head += ["Main review and rule check side by side; each finding shows how many of them raised it.", ""]

    def item(f: Finding) -> list[str]:
        found = f" · found by {f.support or 1}/{n} runs" if n > 1 else ""
        out = [f"### [{f.severity}] {f.title}", f"*{f.scope}* · `{f.where()}`{found}", "", f.body, ""]
        for rule in f.rules or ([f.rule] if f.rule else []):
            out += [rule_line(rule), ""]
        rel = [l for l in f.locations if l.role == "related"]
        if rel:
            out += ["Related: " + ", ".join(f"`{l.path}" + (f":{l.start}" if l.start else "") + "`" for l in rel), ""]
        if f.suggestion:
            out += ["Suggestion: " + f.suggestion, ""]
        return out

    main = [x for f in fs if f.severity in ("blocker", "major") for x in item(f)]
    rest = [f for f in fs if f.severity not in ("blocker", "major")]
    out = head + (main or ["No blocker/major findings.", ""])
    if rest:
        out += [f"<details><summary>{len(rest)} minor/nit findings</summary>", ""]
        out += [x for f in rest for x in item(f)] + ["</details>"]
    return "\n".join(out)

localize_module(globals())  # the prompts above name the project of [project] (project.py)

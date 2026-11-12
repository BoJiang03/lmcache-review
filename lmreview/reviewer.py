"""The reviewer agent and the public entry point `review_pr`."""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import pathlib
import re

from . import github, llm
from .ensemble import ensemble
from .config import PROMPTS, RULES, Config
from .schema import SCHEMA_VERSION, SEVERITIES, Finding, SchemaError, load_findings, parse_findings, to_dicts
from .workspace import TOOLS, live_workspace, pr_meta


# What people get out of the box. Rulebooks are versioned (team-v1, team-v2, ...): to update, build the
# next version (`lmreview distill team-v2 --base team-v1`) and point this at it; old versions stay.
DEFAULT_REVIEWER = os.environ.get("LMREVIEW_REVIEWER", "v0e+team-v1@high")


_NAME = re.compile(r"([\w.-]+?)(?:\+([\w.-]+?))?(?:@([a-z]+))?(?:x(\d+))?(-rc)?")


def parse_reviewer(name: str) -> tuple[str, str | None, str]:
    """A reviewer is named `<prompt>[+<rules>][@<effort>][x<n>][-rc]`, e.g. `v0b+r1@high` or
    `v0b+r1@highx3` (x3: three runs in parallel, then one merge run; see parallel_of; -rc: see
    rulecheck_of).

    Returns:
        (prompt version, rulebook name or None, effort; default "high").
    """
    m = _NAME.fullmatch(name)
    if not m:
        raise ValueError(f"bad reviewer name {name!r}; expected <prompt>[+<rules>][@<effort>][x<n>][-rc]")
    if m[5] and not m[3]:  # else "v0b+foo-rc" is ambiguous: rulebook "foo-rc", or "foo" with the rule check
        raise ValueError(f"bad reviewer name {name!r}: -rc needs an explicit @<effort> before it")
    return m[1], m[2], m[3] or "high"


def parallel_of(name: str) -> int:
    """How many reviewer runs `name` asks for (its `x<n>` suffix; 1 without one)."""
    m = _NAME.fullmatch(name.split("#")[0])
    return int(m[4]) if m and m[4] else 1


def rulecheck_of(name: str) -> bool:
    """Whether `name` asks for a rule-check run next to the reviews (`-rc` suffix, needs a rulebook):
    one more agent that must give a verdict on every applicable rule, merged with the reviews."""
    m = _NAME.fullmatch(name.split("#")[0])
    return bool(m and m[5] and m[2])


def prompt_template(version: str) -> tuple[str, tuple[str, ...]]:
    """Prompt text of `version` and the extra workspace context it declares.

    A prompt may start with directive lines that are not sent to the model:
    `<!-- context: vllm -->` (extra workspace context), `<!-- system: trimmed -->` (see
    prompt_system) and `<!-- rules: examples -->` (see rule_examples).
    """
    text, ctx = (PROMPTS / f"reviewer_{version}.md").read_text(), ()
    while m := re.match(r"<!--\s*(context|system|rules):\s*([\w, .-]*?)\s*-->\n", text):
        if m[1] == "context":
            ctx = tuple(x.strip() for x in m[2].split(",") if x.strip())
        text = text[m.end():]
    return text, ctx


def prompt_system(version: str) -> str | None:
    """System prompt that prompt `version` asks for with `<!-- system: X -->` (prompts/system_X.md);
    None keeps Claude Code's default."""
    m = re.search(r"^<!--\s*system:\s*([\w.-]+)\s*-->$", (PROMPTS / f"reviewer_{version}.md").read_text(), re.M)
    return (PROMPTS / f"system_{m[1]}.md").read_text() if m else None


def rule_examples(version: str) -> bool:
    """Whether prompt `version` shows each rule's first example (`<!-- rules: examples -->`).

    Off by default: examples carry the source PR's particulars (names, values), which are too specific
    for the reviewer and leak the answer on the source PR. Only the older prompts (v0, v0b, v0c, v0d,
    v0t) keep them, so their cached runs stay valid; v0e/v0f are v0b/v0c without them.
    """
    return bool(re.search(r"^<!--\s*rules:\s*examples\s*-->$", (PROMPTS / f"reviewer_{version}.md").read_text(), re.M))


def reviewer_context(reviewer: str) -> tuple[str, ...]:
    """Extra workspace context the reviewer's prompt needs (the judge gets the same)."""
    return prompt_template(parse_reviewer(reviewer)[0])[1]


def load_rules(name: str) -> list[dict]:
    """Rulebook rules/<name>.jsonl: {"id", "when", "expect", "why", "examples", "paths": [glob],
    "evidence": [comment ids], "n_prs", "status", "area",
    "kind": "principle" | "knowledge"}."""
    return [json.loads(l) for l in (RULES / f"{name}.jsonl").open() if l.strip()]


def rule_evidence(reviewer: str) -> set[int]:
    """Human comments the reviewer's rulebook was distilled from (all entries, retired too).

    A sample whose gold holds one of them cannot test this reviewer: the rule was written from the answer.
    """
    rules = parse_reviewer(reviewer.split("#")[0])[1]
    return {e for r in load_rules(rules) for e in r.get("evidence") or []} if rules else set()


def changed_paths(wt: pathlib.Path) -> list[str]:
    """Paths touched by PR.diff in workspace `wt`."""
    d = (wt / "PR.diff").read_text(errors="replace") if (wt / "PR.diff").exists() else ""
    return sorted(set(re.findall(r"^diff --git a/\S+ b/(\S+)", d, re.M)))


def applicable(rules: list[dict], paths: list[str]) -> list[dict]:
    """The active rules that apply to `paths` (rules without paths always apply)."""
    use = [r for r in rules if r.get("status", "active") == "active"]
    return [r for r in use if not r.get("paths") or any(fnmatch.fnmatch(p, g) for p in paths for g in r["paths"])]


def rule_lines(use: list[dict], examples: bool = False) -> list[str]:
    """One prompt line per rule: id, kind (and principle, if it is a specialization of one), text;
    with `examples`, also the rule's first example (see rule_examples)."""
    def text(r: dict) -> str:
        t = f"When {r['when']}: {r['expect']}" if r.get("expect") else r.get("rule", "")
        t = t.rstrip(".") + "." + (f" Why: {r['why']}" if r.get("why") else "")
        return t + (f" E.g. {r['examples'][0]}" if examples and r.get("examples") else "")
    return [f"- [{r['id']}] ({r.get('kind', 'principle')}" + (f", under {r['principle']}" if r.get("principle") else "")
            + f") {text(r)}" for r in use]


def rules_section(rules: list[dict], paths: list[str], examples: bool = False) -> str:
    """The prompt section with the active rules that apply to `paths` (rules without paths always apply)."""
    use = applicable(rules, paths)
    if not use:
        return ""
    lines = rule_lines(use, examples)
    return ("\n\nTeam rules distilled from past LMCache reviews. Check the change against the ones "
            "that apply; when a finding follows from a rule, put its id in the finding's \"rule\" "
            "field. A rule finding must be about code this PR adds or changes: do not raise a rule "
            "against behavior the PR leaves as it was."
            + (" A rule's example shows one instance, not a checklist item: apply the rule's condition, "
               "not the example's particulars." if examples else "") + "\n"
            + "\n".join(lines) + "\n")


def run_reviewer(wt: pathlib.Path, raw: dict, reviewer: str = DEFAULT_REVIEWER) -> dict:
    """Run `reviewer` (see parse_reviewer) in workspace `wt` for PR `raw`.

    Returns:
        {"schema_version", "findings": list of schema.Finding dicts | None (None = output not
         parsable or not schema-valid, see "error"), "error", "raw": text, "cost", "turns",
         "denials", "effort", "version", "rules", "reviewer"}. With `x<n>` (n > 1) the findings are
        the merge run's, each with "support" (how many runs raised it); "parallel" = n, "runs" = each
        run's findings/error/cost, "cost" = all runs plus the merge.
    """
    version, rules, effort = parse_reviewer(reviewer.split("#")[0])
    prompt = prompt_template(version)[0].format(**pr_meta(raw))
    use = applicable(load_rules(rules), changed_paths(wt)) if rules else []
    if rules:
        sec = rules_section(load_rules(rules), changed_paths(wt), rule_examples(version))
        prompt = prompt.replace("\nFinish with one JSON block", sec + "\nFinish with one JSON block", 1) \
            if "\nFinish with one JSON block" in prompt else prompt + sec
    system = prompt_system(version)
    meta = {"schema_version": SCHEMA_VERSION, "effort": effort, "version": version, "rules": rules,
            "reviewer": reviewer}
    n, rc = parallel_of(reviewer), rulecheck_of(reviewer) and bool(use)

    def once() -> dict:
        return _parsed(llm.run(prompt, effort, cwd=str(wt), tools=TOOLS, system=system))

    def rulecheck() -> dict:  # must give a verdict per rule, so a long rulebook cannot crowd rules out
        p = (PROMPTS / "rulecheck.md").read_text().format(rules="\n".join(rule_lines(use, rule_examples(version))), **pr_meta(raw))
        return _parsed(llm.run(p, effort, cwd=str(wt), tools=TOOLS, system=system), rulecheck=True)

    def merge(ok: list[dict]) -> dict:  # one more agent run on the same workspace: it may read code
        reviews = "\n\n".join(f"Run {i}" + (" (rule check: only team-rule violations, not a full review)"
                                            if x.get("kind") == "rulecheck" else "")
                              + f":\n{json.dumps(x['findings'], indent=1)}" for i, x in enumerate(ok, 1))
        return _parsed(llm.run((PROMPTS / "merge.md").read_text().format(n=len(ok), reviews=reviews,
                                                                         **pr_meta(raw)),
                               effort, cwd=str(wt), tools=TOOLS, system=system))

    e = ensemble(once, n, merge, ok=lambda x: x["findings"] is not None, extra=[rulecheck] if rc else [])
    if n == 1 and not rc:
        return {**e.result, **meta}
    n += rc  # the rule check counts as a run for "support"
    out = dict(e.result)
    if not e.merged and out["findings"] is not None:  # one usable run, or the merge failed: unmerged
        out["findings"] = [{**f, "support": 1} for f in out["findings"]]
    merge_cost = e.merge["cost"] if e.merge else 0.0
    keep = {"parallel": n, "merged": e.merged, "merge_cost": merge_cost,
            "merge_error": None if e.merged or not e.merge else e.merge["error"],
            # raw kept per run so scripts/reparse_invalid.py can recover any of them
            "runs": [{k: x[k] for k in ("findings", "error", "raw", "cost", "turns", "kind", "verdicts") if k in x}
                     for x in e.runs]}
    return {**out, "cost": sum(x["cost"] for x in e.runs) + merge_cost, **keep, **meta}


def _unfiled(verdicts: object, findings: list) -> list[dict]:
    """PR-level findings for rules judged violated that no rule-check finding cites, built from the
    verdict's `why`, so a violation the model judged but did not write up still reaches the merge."""
    cited = {f.get("rule") for f in findings if isinstance(f, dict)}
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
           "denials": r["denials"]}
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
    return {"pr": pr, "title": raw["title"], "commit": c, "base": base, **out}


def to_markdown(r: dict) -> str:
    """Render a review: blocker/major in full, minor/nit folded; each item shows scope and places."""
    head = [f"# AI review of #{r['pr']}: {r.get('title', '')}", "",
            f"commit `{r['commit'][:10]}` vs base `{r['base'][:10]}` · reviewer "
            f"{r.get('reviewer') or str(r.get('version')) + '@' + str(r.get('effort'))} · ${r['cost']:.2f}", ""]
    fs = load_findings(r)
    if fs is None:
        return "\n".join(head + [f"Could not parse the reviewer output ({r.get('error')}):", "", r["raw"]])
    if not fs:
        return "\n".join(head + ["No findings."])
    fs.sort(key=lambda f: SEVERITIES.index(f.severity))
    book = parse_reviewer(r["reviewer"].split("#")[0])[1] if r.get("reviewer") else None
    rules = {x["id"]: x for x in load_rules(book)} if book else {}
    cited = [f for f in fs if f.rule]
    if cited:
        head += [f"{len(cited)} of {len(fs)} findings follow a team rule ({book or 'no rulebook'}).", ""]

    def rule_line(f: Finding) -> str:
        x = rules.get(f.rule)
        if x is None:  # the model named an id that is not in the reviewer's rulebook
            return f"Rule: `{f.rule}` (not in {book or 'any rulebook'})"
        return f"Rule: `{f.rule}` · when {x.get('when') or x.get('rule', '')}"

    n = r.get("parallel") or 1
    if n > 1:  # merged parallel review: within a severity, what more runs agree on comes first
        fs.sort(key=lambda f: (SEVERITIES.index(f.severity), -(f.support or 1)))
        head += [f"{n} parallel runs, merged; each finding shows how many runs raised it.", ""]

    def item(f: Finding) -> list[str]:
        found = f" · found by {f.support or 1}/{n} runs" if n > 1 else ""
        out = [f"### [{f.severity}] {f.title}", f"*{f.scope}* · `{f.where()}`{found}", "", f.body, ""]
        if f.rule:
            out += [rule_line(f), ""]
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

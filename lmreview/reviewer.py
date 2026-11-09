"""The reviewer agent and the public entry point `review_pr`."""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import pathlib
import re

from . import github, llm
from .config import PROMPTS, RULES, Config
from .schema import SCHEMA_VERSION, SEVERITIES, SchemaError, load_findings, parse_findings, to_dicts
from .workspace import TOOLS, live_workspace, pr_meta


DEFAULT_REVIEWER = os.environ.get("LMREVIEW_REVIEWER", "v0b@high")  # the validated reviewer people should use


def parse_reviewer(name: str) -> tuple[str, str | None, str]:
    """A reviewer is named `<prompt>[+<rules>][@<effort>]`, e.g. `v0b+r1@high`.

    Returns:
        (prompt version, rulebook name or None, effort; default "high").
    """
    m = re.fullmatch(r"([\w.-]+?)(?:\+([\w.-]+))?(?:@(\w+))?", name)
    if not m:
        raise ValueError(f"bad reviewer name {name!r}; expected <prompt>[+<rules>][@<effort>]")
    return m[1], m[2], m[3] or "high"


def prompt_template(version: str) -> tuple[str, tuple[str, ...]]:
    """Prompt text of `version` and the extra workspace context it declares.

    A prompt may start with a line `<!-- context: vllm -->`; that line is not sent to the model.
    """
    text = (PROMPTS / f"reviewer_{version}.md").read_text()
    m = re.match(r"<!--\s*context:\s*([\w, ]+?)\s*-->\n", text)
    if not m:
        return text, ()
    return text[m.end():], tuple(x.strip() for x in m[1].split(",") if x.strip())


def reviewer_context(reviewer: str) -> tuple[str, ...]:
    """Extra workspace context the reviewer's prompt needs (the judge gets the same)."""
    return prompt_template(parse_reviewer(reviewer)[0])[1]


def load_rules(name: str) -> list[dict]:
    """Rulebook rules/<name>.jsonl: {"id", "when", "expect", "why", "examples", "paths": [glob],
    "evidence": [comment ids], "n_prs", "status", "area",
    "kind": "principle" | "knowledge"}."""
    return [json.loads(l) for l in (RULES / f"{name}.jsonl").open() if l.strip()]


def changed_paths(wt: pathlib.Path) -> list[str]:
    """Paths touched by PR.diff in workspace `wt`."""
    d = (wt / "PR.diff").read_text(errors="replace") if (wt / "PR.diff").exists() else ""
    return sorted(set(re.findall(r"^diff --git a/\S+ b/(\S+)", d, re.M)))


def rules_section(rules: list[dict], paths: list[str]) -> str:
    """The prompt section with the active rules that apply to `paths` (rules without paths always apply)."""
    use = [r for r in rules if r.get("status", "active") == "active"]
    use = [r for r in use if not r.get("paths")
           or any(fnmatch.fnmatch(p, g) for p in paths for g in r["paths"])]
    if not use:
        return ""
    def text(r: dict) -> str:
        t = f"When {r['when']}: {r['expect']}" if r.get("expect") else r.get("rule", "")
        t = t.rstrip(".") + "." + (f" Why: {r['why']}" if r.get("why") else "")
        return t + (f" E.g. {r['examples'][0]}" if r.get("examples") else "")
    lines = [f"- [{r['id']}] ({r.get('kind', 'principle')}) {text(r)}" for r in use]
    return ("\n\nTeam rules distilled from past LMCache reviews. Check the change against the ones "
            "that apply; when a finding follows from a rule, put its id in the finding's \"rule\" "
            "field.\n" + "\n".join(lines) + "\n")


def run_reviewer(wt: pathlib.Path, raw: dict, reviewer: str = DEFAULT_REVIEWER) -> dict:
    """Run `reviewer` (see parse_reviewer) in workspace `wt` for PR `raw`.

    Returns:
        {"schema_version", "findings": list of schema.Finding dicts | None (None = output not
         parsable or not schema-valid, see "error"), "error", "raw": text, "cost", "turns",
         "denials", "effort", "version", "rules", "reviewer"}.
    """
    version, rules, effort = parse_reviewer(reviewer)
    prompt = prompt_template(version)[0].format(**pr_meta(raw))
    if rules:
        sec = rules_section(load_rules(rules), changed_paths(wt))
        prompt = prompt.replace("\nFinish with one JSON block", sec + "\nFinish with one JSON block", 1) \
            if "\nFinish with one JSON block" in prompt else prompt + sec
    r = llm.run(prompt, effort, cwd=str(wt), tools=TOOLS)
    findings, error = None, None
    try:
        findings = to_dicts(parse_findings(llm.extract_json(r["text"])))
    except (ValueError, SchemaError) as e:  # SchemaError is a ValueError; kept explicit for clarity
        error = str(e)
    return {"schema_version": SCHEMA_VERSION, "findings": findings, "error": error, "raw": r["text"],
            "cost": r["cost"], "turns": r["turns"], "denials": r["denials"], "effort": effort,
            "version": version, "rules": rules, "reviewer": reviewer}


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

    def item(f):
        out = [f"### [{f.severity}] {f.title}", f"*{f.scope}* · `{f.where()}`", "", f.body, ""]
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

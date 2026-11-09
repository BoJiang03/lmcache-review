"""The reviewer agent and the public entry point `review_pr`."""

from __future__ import annotations

import pathlib

from . import github, llm
from .config import PROMPTS, Config
from .schema import SCHEMA_VERSION, SEVERITIES, SchemaError, load_findings, parse_findings, to_dicts
from .workspace import TOOLS, live_workspace, pr_meta


def run_reviewer(wt: pathlib.Path, raw: dict, version: str = "v0", effort: str = "high") -> dict:
    """Run reviewer `version` in workspace `wt` for PR `raw`.

    Returns:
        {"schema_version", "findings": list of schema.Finding dicts | None (None = output not
         parsable or not schema-valid, see "error"), "error", "raw": text, "cost", "turns",
         "denials", "effort", "version"}.
    """
    prompt = (PROMPTS / f"reviewer_{version}.md").read_text().format(**pr_meta(raw))
    r = llm.run(prompt, effort, cwd=str(wt), tools=TOOLS)
    findings, error = None, None
    try:
        findings = to_dicts(parse_findings(llm.extract_json(r["text"])))
    except (ValueError, SchemaError) as e:  # SchemaError is a ValueError; kept explicit for clarity
        error = str(e)
    return {"schema_version": SCHEMA_VERSION, "findings": findings, "error": error, "raw": r["text"],
            "cost": r["cost"], "turns": r["turns"], "denials": r["denials"], "effort": effort,
            "version": version}


def review_pr(pr: int, commit: str | None = None, version: str = "v0", effort: str = "high",
              cfg: Config | None = None) -> dict:
    """Review PR `pr` as it is now (or at `commit`). Read-only: nothing is posted to GitHub.

    Returns:
        run_reviewer's dict plus "pr", "title", "commit", "base".
    """
    cfg = cfg or Config()
    raw = github.fetch_pr(pr)
    with live_workspace(cfg, raw, commit) as (wt, c, base):
        out = run_reviewer(wt, raw, version, effort)
    return {"pr": pr, "title": raw["title"], "commit": c, "base": base, **out}


def to_markdown(r: dict) -> str:
    """Render a review: blocker/major in full, minor/nit folded; each item shows scope and places."""
    head = [f"# AI review of #{r['pr']}: {r.get('title', '')}", "",
            f"commit `{r['commit'][:10]}` vs base `{r['base'][:10]}` · reviewer {r.get('version')} "
            f"({r.get('effort')}) · ${r['cost']:.2f}", ""]
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

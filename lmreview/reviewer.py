"""The reviewer agent and the public entry point `review_pr`."""

from __future__ import annotations

import pathlib

from . import github, llm
from .config import PROMPTS, Config
from .workspace import TOOLS, live_workspace, pr_meta

SEVERITIES = ("blocker", "major", "minor", "nit")


def run_reviewer(wt: pathlib.Path, raw: dict, version: str = "v0", effort: str = "high") -> dict:
    """Run reviewer `version` in workspace `wt` for PR `raw`.

    Returns:
        {"findings": list | None (None = unparsable output), "raw": text, "cost", "turns",
         "denials", "effort", "version"}.
    """
    prompt = (PROMPTS / f"reviewer_{version}.md").read_text().format(**pr_meta(raw))
    r = llm.run(prompt, effort, cwd=str(wt), tools=TOOLS)
    try:
        findings = llm.extract_json(r["text"])
    except ValueError:
        findings = None
    return {"findings": findings, "raw": r["text"], "cost": r["cost"], "turns": r["turns"],
            "denials": r["denials"], "effort": effort, "version": version}


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
    """Render a review: blocker/major first, minor/nit folded."""
    fs = r["findings"]
    head = [f"# AI review of #{r['pr']}: {r['title']}", "",
            f"commit `{r['commit'][:10]}` vs base `{r['base'][:10]}` · reviewer {r['version']} "
            f"({r['effort']}) · ${r['cost']:.2f}", ""]
    if fs is None:
        return "\n".join(head + ["Could not parse the reviewer output:", "", r["raw"]])
    if not fs:
        return "\n".join(head + ["No findings."])
    fs = sorted(fs, key=lambda f: SEVERITIES.index(f.get("severity")) if f.get("severity") in SEVERITIES else 9)
    item = lambda f: [f"### [{f.get('severity')}] {f.get('title')}",  # noqa: E731
                      f"`{f.get('path')}:{f.get('line')}`", "", f.get("body", ""), ""]
    main = [x for f in fs if f.get("severity") in ("blocker", "major") for x in item(f)]
    rest = [f for f in fs if f.get("severity") not in ("blocker", "major")]
    out = head + (main or ["No blocker/major findings.", ""])
    if rest:
        out += [f"<details><summary>{len(rest)} minor/nit findings</summary>", ""]
        out += [x for f in rest for x in item(f)] + ["</details>"]
    return "\n".join(out)

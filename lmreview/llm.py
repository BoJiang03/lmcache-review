"""Thin wrapper around headless `claude -p` (uses the local Claude Code login, no API key)."""

from __future__ import annotations

import json
import os
import re
import pathlib
import shutil
import subprocess
import tempfile

# Env vars that make a nested `claude` think it is a child of this session.
_STRIP = [k for k in os.environ if k.startswith("CLAUDE_CODE_")
          or k in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT")
          # credentials an agent with a shell could use (it must never write to GitHub)
          or re.search(r"TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIAL", k) or k in ("GH_HOST", "SSH_AUTH_SOCK")]


def sandbox_settings(profile: str, cwd: str) -> dict:
    """Claude Code settings for an agent with a shell (Bash), run under Claude Code's sandbox.

    Both profiles: reading is denied under $HOME, /tmp and the roots where data lives (the eval data,
    the human comments, credentials, other sessions' files), writing only in `cwd`, no unsandboxed
    commands. "replay" (historical samples): no network at all, since the PR's later discussion is
    online. "live" (reviewing a PR now): network open. Credentials never reach the agent either way:
    see _STRIP.
    """
    if profile not in ("replay", "live"):
        raise ValueError(f"sandbox profile must be replay or live, not {profile!r}")
    deny = sorted({str(pathlib.Path.home()), "/tmp", "/raid", "/mnt", "/root", "/data"} - {"/"})
    if any(cwd == d or cwd.startswith(d + "/") for d in deny):
        raise ValueError(f"workspace {cwd} is under a denied path; set LMREVIEW_SANDBOX elsewhere")
    net = {"allowedDomains": []} if profile == "replay" else {"allowedDomains": ["*"]}
    return {"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True, "allowUnsandboxedCommands": False,
                        "network": net},
            "permissions": {"deny": [f"Read(/{d}/**)" for d in deny]}}


def run(prompt: str, effort: str, cwd: str | None = None, tools: str = "", timeout: int = 1800,
        system: str | None = None, sandbox: str | None = None) -> dict:
    """Run one headless Claude call.

    Args:
        prompt: the user prompt.
        effort: thinking effort (low|medium|high|xhigh|max); explicit so runs are reproducible.
        cwd: working directory the model sees (e.g. a checked-out PR worktree).
        tools: comma-separated tools that exist for the model; "" means none.
        timeout: seconds.
        system: replaces the default Claude Code system prompt when given. Claude Code still adds
            its one-line SDK identity, an environment block (cwd, platform, today's date) and the
            account e-mail reminder; those are the same with or without `system`.
        sandbox: required when `tools` has Bash: "replay" or "live" (see sandbox_settings). The call
            fails rather than run a shell unsandboxed (Claude Code only warns when it cannot sandbox).

    Returns:
        {"text": final text, "cost": usd, "turns": n, "denials": [blocked tool calls]}.
    """
    env = {k: v for k, v in os.environ.items() if k not in _STRIP}
    # Hard sandbox (verified with a probe): only `tools` exist, file tools are confined to cwd,
    # no shell/web/subagents/MCP, and user settings (e.g. defaultMode=auto) are ignored.
    # --allowedTools alone is NOT enough: user settings auto-approve everything.
    shell = "Bash" in tools.split(",")
    if not shell:
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--restricted",
               "--tools", tools, "--strict-mcp-config", "--permission-mode", "dontAsk",
               "--effort", effort] + (["--system-prompt", system] if system else [])
    else:  # --restricted would remove Bash: the sandbox and the deny rules confine it instead
        missing = [b for b in ("bwrap", "socat") if not shutil.which(b)]
        if missing or not cwd or not sandbox:
            raise RuntimeError(f"a shell needs Claude Code's sandbox: missing {missing or 'cwd/sandbox profile'}")
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--tools", tools,
               "--allowedTools", *tools.split(","), "--strict-mcp-config", "--permission-mode", "dontAsk",
               "--settings", json.dumps(sandbox_settings(sandbox, str(pathlib.Path(cwd).resolve()))),
               "--effort", effort] + (["--system-prompt", system] if system else [])
    tmp = None
    if shell:  # Claude Code keeps its own files (other sessions' too) in $TMPDIR/claude-<uid>: give
        # this call a private, empty one next to the workspace, outside the denied paths
        tmp = tempfile.mkdtemp(prefix="tmp-", dir=pathlib.Path(cwd).resolve().parent)
        env["TMPDIR"] = tmp
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    if shell and re.search(r"Sandbox disabled|WITHOUT sandboxing", p.stderr + p.stdout[:2000]):
        raise RuntimeError(f"Claude Code ran without its sandbox; refusing the result: {p.stderr[:300]}")
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"claude -p failed (exit {p.returncode}): {(p.stderr or p.stdout)[:500]}") from e
    if d.get("is_error"):
        raise RuntimeError(f"claude -p error: {str(d.get('result'))[:500]}")
    return {"text": d.get("result") or "", "cost": d.get("total_cost_usd") or 0.0,
            "turns": d.get("num_turns"), "effort": effort,
            "denials": [{"tool": x.get("tool_name"), "input": str(x.get("tool_input"))[:200]}
                        for x in d.get("permission_denials") or []]}


def extract_json(text: str) -> object:
    """Parse the last ```json block (or the whole text) as JSON."""
    dec = json.JSONDecoder()
    for m in reversed(list(re.finditer(r"```json\s*", text))):  # a JSON string may itself contain ```
        try:
            return dec.raw_decode(text, m.end())[0]
        except json.JSONDecodeError:
            continue
    blocks = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
    for cand in reversed(blocks + [text]):
        try:
            return json.loads(cand.strip())
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON in model output")

"""Thin wrapper around headless `claude -p` (uses the local Claude Code login, no API key)."""

from __future__ import annotations

import json
import os
import re
import subprocess

# Env vars that make a nested `claude` think it is a child of this session.
_STRIP = [k for k in os.environ if k.startswith("CLAUDE_CODE_")
          or k in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT")]


def run(prompt: str, effort: str, cwd: str | None = None, tools: str = "", timeout: int = 1800) -> dict:
    """Run one headless Claude call.

    Args:
        prompt: the user prompt.
        effort: thinking effort (low|medium|high|xhigh|max); explicit so runs are reproducible.
        cwd: working directory the model sees (e.g. a checked-out PR worktree).
        tools: comma-separated tools that exist for the model; "" means none.
        timeout: seconds.

    Returns:
        {"text": final text, "cost": usd, "turns": n, "denials": [blocked tool calls]}.
    """
    env = {k: v for k, v in os.environ.items() if k not in _STRIP}
    # Hard sandbox (verified with a probe): only `tools` exist, file tools are confined to cwd,
    # no shell/web/subagents/MCP, and user settings (e.g. defaultMode=auto) are ignored.
    # --allowedTools alone is NOT enough: user settings auto-approve everything.
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--restricted",
           "--tools", tools, "--strict-mcp-config", "--permission-mode", "dontAsk",
           "--effort", effort]
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
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


def extract_json(text: str):
    """Parse the last ```json block (or the whole text) as JSON."""
    blocks = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
    for cand in reversed(blocks + [text]):
        try:
            return json.loads(cand.strip())
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON in model output")

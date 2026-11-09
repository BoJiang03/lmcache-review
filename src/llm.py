"""Thin wrapper around headless `claude -p` (uses the local Claude Code login, no API key)."""

from __future__ import annotations

import json
import os
import re
import subprocess

# Env vars that make a nested `claude` think it is a child of this session.
_STRIP = [k for k in os.environ if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_PID")]


def run(prompt: str, cwd: str | None = None, tools: str = "", timeout: int = 1800) -> dict:
    """Run one headless Claude call.

    Args:
        prompt: the user prompt.
        cwd: working directory the model sees (e.g. a checked-out PR worktree).
        tools: comma-separated allowed tools; empty means no tools.
        timeout: seconds.

    Returns:
        {"text": final text, "cost": usd, "turns": n}.
    """
    env = {k: v for k, v in os.environ.items() if k not in _STRIP}
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    if tools:  # in -p mode anything not allowed is denied
        cmd += ["--allowedTools", tools]
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    d = json.loads(p.stdout)
    return {"text": d.get("result") or "", "cost": d.get("total_cost_usd") or 0.0,
            "turns": d.get("num_turns")}


def extract_json(text: str):
    """Parse the last ```json block (or the whole text) as JSON."""
    blocks = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
    for cand in reversed(blocks + [text]):
        try:
            return json.loads(cand.strip())
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON in model output")

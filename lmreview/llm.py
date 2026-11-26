"""Thin wrapper around headless `claude -p` (uses the local Claude Code login, no API key)."""

from __future__ import annotations

import json
import os
import re
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

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


SPENT = 0.0  # USD of every call this process made (a caller takes the difference around its work)
_spent_lock = __import__("threading").Lock()


# Record/replay tape for refactor checks: LMREVIEW_TAPE=<file.jsonl>, LMREVIEW_TAPE_MODE=record|replay.
# record appends every call's result; replay answers each call from the tape (calls with the same inputs
# are answered in recorded order) and fails on a call the tape does not hold, so a replay that finishes
# proves the code sent the model exactly the recorded prompts.
TAPE = os.environ.get("LMREVIEW_TAPE")
_tape: dict[str, list[dict]] | None = None
_tape_lock = __import__("threading").Lock()


def _tape_key(prompt: str, effort: str, tools: str, system: str | None, model: str | None) -> str:
    import hashlib
    return hashlib.sha256(json.dumps([prompt, effort, tools, system, model]).encode()).hexdigest()


def _tape_replay(prompt: str, effort: str, tools: str, system: str | None, model: str | None) -> dict | None:
    """In replay mode, the recorded answer to this call (None in record mode); raises on a call the tape
    does not hold, after writing it to <tape>.miss.jsonl."""
    global _tape, SPENT
    if os.environ.get("LMREVIEW_TAPE_MODE") != "replay":
        return None
    k = _tape_key(prompt, effort, tools, system, model)
    with _tape_lock:
        if _tape is None:
            _tape = {}
            for line in pathlib.Path(TAPE).open():
                d = json.loads(line)
                _tape.setdefault(d["key"], []).append(d["out"])
            used = pathlib.Path(TAPE).with_suffix(".used")  # answers earlier replay commands took
            for u in used.read_text().split() if used.exists() else []:
                _tape[u].pop(0)
        if not _tape.get(k):  # same lines in another order (parallel drafts joined as they finish)?
            k = _tape_reordered(prompt, effort, tools, system, model) or _tape_similar(prompt, effort, tools, system, model) or k
        if not _tape.get(k):
            miss = pathlib.Path(TAPE).with_suffix(".miss.jsonl")
            with miss.open("a") as f:
                f.write(json.dumps({"key": k, "caller": _caller(), "effort": effort, "tools": tools,
                                    "model": model, "prompt": prompt}) + "\n")
            raise RuntimeError(f"tape miss {k[:12]} ({_caller()})")
        out = _tape[k].pop(0)
        with pathlib.Path(TAPE).with_suffix(".used").open("a") as f:
            f.write(k + "\n")
        SPENT += float(out.get("cost") or 0)
    return {**out, "effort": effort}


_tape_logged: dict[str, list[str]] | None = None


def _tape_reordered(prompt: str, effort: str, tools: str, system: str | None, model: str | None) -> str | None:
    """The key of a recorded call whose prompt has the same lines in another order, found through the
    prompts the recording run logged (LMREVIEW_TAPE_LOGS: their data/logs dir); each such hit is noted."""
    global _tape_logged
    import hashlib
    logs = os.environ.get("LMREVIEW_TAPE_LOGS")
    if not logs:
        return None
    lines = lambda t: hashlib.sha256("\n".join(sorted(t.splitlines())).encode()).hexdigest()
    if _tape_logged is None:
        _tape_logged = {}
        for f in pathlib.Path(logs).glob("*/calls/*.prompt.md"):
            t = f.read_bytes().decode()  # as written: read_text would turn \r\n into \n
            _tape_logged.setdefault(lines(t), []).append(t)
    for t in _tape_logged.get(lines(prompt), []):
        k = _tape_key(t, effort, tools, system, model)
        if _tape.get(k):
            with pathlib.Path(TAPE).with_suffix(".reordered.jsonl").open("a") as f:
                f.write(json.dumps({"key": k, "caller": _caller()}) + "\n")
            return k
    return None


def _tape_similar(prompt: str, effort: str, tools: str, system: str | None, model: str | None) -> str | None:
    """With LMREVIEW_TAPE_FUZZY: the unused recorded call whose prompt is closest (ratio >= 0.9). Calls with
    the same inputs run in parallel get different answers, and a replay can hand them out in another
    order, so later prompts carry the other answer's text; each such hit is noted with its diff to check."""
    import difflib
    if not os.environ.get("LMREVIEW_TAPE_FUZZY") or not _tape_logged:
        return None
    best = None
    for ts in _tape_logged.values():
        for t in ts:
            if abs(len(t) - len(prompt)) > 0.1 * len(prompt):
                continue
            k = _tape_key(t, effort, tools, system, model)
            if not _tape.get(k):
                continue
            sm = difflib.SequenceMatcher(None, t, prompt, autojunk=False)
            if sm.quick_ratio() < 0.9 or (best and sm.quick_ratio() <= best[0]):
                continue
            r = sm.ratio()
            if r >= 0.9 and (not best or r > best[0]):
                best = (r, k, t)
    if not best:
        return None
    diff = [x for x in difflib.unified_diff(best[2].splitlines(), prompt.splitlines(), lineterm="", n=0)
            if x[:1] in "+-" and x[:3] not in ("+++", "---")]
    with pathlib.Path(TAPE).with_suffix(".fuzzy.jsonl").open("a") as f:
        f.write(json.dumps({"key": best[1], "caller": _caller(), "ratio": round(best[0], 4), "diff": diff}) + "\n")
    return best[1]


def _tape_record(prompt: str, effort: str, tools: str, system: str | None, model: str | None, out: dict) -> None:
    """In record mode, append this call's result to the tape."""
    if os.environ.get("LMREVIEW_TAPE_MODE") != "record":
        return
    with _tape_lock, open(TAPE, "a") as f:
        f.write(json.dumps({"key": _tape_key(prompt, effort, tools, system, model), "caller": _caller(),
                            "out": out}) + "\n")


def run(prompt: str, effort: str, cwd: str | None = None, tools: str = "", timeout: int = 1800,
        system: str | None = None, sandbox: str | None = None, model: str | None = None) -> dict:
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
            The reviewer never has a shell; scripts/skill_compare.py runs its baseline arms with one.
        model: the model id; None = Claude Code's default.

    Returns:
        {"text": final text, "cost": usd, "turns": n, "denials": [blocked tool calls], "usage",
         "model": the model id that did most of the work (see primary_model)}.
    """
    if TAPE:
        hit = _tape_replay(prompt, effort, tools, system, model)
        if hit is not None:
            return hit
    env = {k: v for k, v in os.environ.items() if k not in _STRIP}
    # Hard sandbox (verified with a probe): only `tools` exist, file tools are confined to cwd,
    # no shell/web/subagents/MCP, and user settings (e.g. defaultMode=auto) are ignored.
    # --allowedTools alone is NOT enough: user settings auto-approve everything.
    shell = "Bash" in tools.split(",")
    sys_file = None
    if system and len(system.encode()) > 100_000:  # one argv string is capped at 128 KiB: use a file
        fd, sys_file = tempfile.mkstemp(prefix="lmreview-sys-", suffix=".md")
        with os.fdopen(fd, "w") as f:
            f.write(system)
    sys_args = ["--system-prompt-file", sys_file] if sys_file else ["--system-prompt", system] if system else []
    if not shell:
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--restricted",
               "--tools", tools, "--strict-mcp-config", "--permission-mode", "dontAsk",
               "--effort", effort] + sys_args
    else:  # --restricted would remove Bash: the sandbox and the deny rules confine it instead
        missing = [b for b in ("bwrap", "socat") if not shutil.which(b)]
        if missing or not cwd or not sandbox:
            raise RuntimeError(f"a shell needs Claude Code's sandbox: missing {missing or 'cwd/sandbox profile'}")
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--tools", tools,
               "--allowedTools", *tools.split(","), "--strict-mcp-config", "--permission-mode", "dontAsk",
               "--settings", json.dumps(sandbox_settings(sandbox, str(pathlib.Path(cwd).resolve()))),
               "--effort", effort] + sys_args
    if model:
        cmd += ["--model", model]
    stdin = None
    if len(prompt.encode()) > 100_000:  # one argv string is capped at 128 KiB: pass a long prompt on stdin
        cmd.remove(prompt)
        stdin = prompt
    t0, out, err = time.time(), None, None
    try:
        out = _call(cmd, cwd, env, shell, timeout, stdin)
        if out.get("model"):
            try:
                observe(model or "default", out["model"])
            except OSError as e:  # a bookkeeping failure must not lose a paid result
                print(f"could not record the model: {e}", file=sys.stderr)
        if TAPE:
            _tape_record(prompt, effort, tools, system, model, out)
        return {**out, "effort": effort}
    except BaseException as e:
        err = f"{type(e).__name__}: {e}"[:500]
        raise
    finally:
        if sys_file:
            os.unlink(sys_file)
        global SPENT
        with _spent_lock:
            SPENT += float((out or {}).get("cost") or 0)
        from .progress import record_call
        record_call(prompt, (out or {}).get("text", ""), {
            "caller": _caller(), "model": model or "default", "effort": effort, "tools": tools, "system": bool(system),
            "cwd": pathlib.Path(cwd).name if cwd else None, "secs": round(time.time() - t0, 1),
            "cost": (out or {}).get("cost"), "turns": (out or {}).get("turns"), "usage": (out or {}).get("usage"),
            "error": err})


def _caller(depth: int = 3) -> str:
    """What the call was for: the innermost `depth` lmreview functions outside this module, innermost first,
    e.g. "distill._ask < distill.consolidate < distill.distill" (shared helpers alone say little)."""
    out, f = [], sys._getframe(1)
    while f and len(out) < depth:
        mod = f.f_globals.get("__name__", "")
        if mod != __name__ and not f.f_code.co_name.startswith("<") and mod.split(".")[0] in ("lmreview", "__main__"):
            out.append(f"{mod.split('.')[-1]}.{f.f_code.co_name}")
        f = f.f_back
    return " < ".join(out) or "?"


def _call(cmd: list[str], cwd: str | None, env: dict, shell: bool, timeout: int, stdin: str | None) -> dict:
    """Run the built `claude -p` command and parse its JSON result."""
    tmp = None
    if shell:  # Claude Code keeps its own files (other sessions' too) in $TMPDIR/claude-<uid>: give
        # this call a private, empty one next to the workspace, outside the denied paths
        tmp = tempfile.mkdtemp(prefix="tmp-", dir=pathlib.Path(cwd).resolve().parent)
        env["TMPDIR"] = tmp
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, input=stdin)
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
            "turns": d.get("num_turns"), "usage": usage_of(d), "model": primary_model(d),
            "denials": [{"tool": x.get("tool_name"), "input": str(x.get("tool_input"))[:200]}
                        for x in d.get("permission_denials") or []]}


def primary_model(d: dict) -> str | None:
    """The model id of a `claude -p` result: the `modelUsage` key with the highest cost (Claude Code may
    also make small calls on another model); None if it lists none."""
    mu = d.get("modelUsage") or {}
    return max(mu, key=lambda m: (mu[m] or {}).get("costUSD") or 0) if mu else None


_models_lock = __import__("threading").Lock()
_seen: dict[str, str] = {}


def observe(requested: str, actual: str, path: pathlib.Path | None = None) -> None:
    """Note that model name `requested` ("default" or an id) resolved to `actual`, in <data>/models.json
    (runs.models_path), so cached runs made with an older model are not reused (runs.cached). Written
    only when the resolution changes."""
    from .config import Config
    from .runs import models_path
    path = path or models_path(Config())
    with _models_lock:
        if _seen.get(str(path) + "|" + requested) == actual:
            return
        cur = json.loads(path.read_text()) if path.exists() else {}
        if cur.get(requested) != actual:
            cur[requested] = actual
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cur, indent=1, sort_keys=True) + "\n")
            tmp.replace(path)
        _seen[str(path) + "|" + requested] = actual


def usage_of(d: dict) -> dict:
    """Tokens and cost per model of one `claude -p` result, to see where the money goes:
    {model: {"input", "cache_write", "cache_read", "output", "thinking", "cost"}}."""
    keys = {"input": "inputTokens", "cache_write": "cacheCreationInputTokens", "cache_read": "cacheReadInputTokens",
            "output": "outputTokens", "thinking": "thinkingTokens", "cost": "costUSD"}
    return {m: {k: u.get(v) or 0 for k, v in keys.items()} for m, u in (d.get("modelUsage") or {}).items()}


def add_usage(*us: dict | None) -> dict:
    """Sum usage_of() dicts."""
    out: dict = {}
    for u in us:
        for m, x in (u or {}).items():
            o = out.setdefault(m, {})
            for k, v in x.items():
                o[k] = o.get(k, 0) + v
    return out


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

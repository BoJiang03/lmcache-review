"""Progress output: timestamped (Pacific) lines, nested steps with duration and cost, and a log file.

    with step("vet v0002c1", "4 samples x 2 books, cap $30") as s:
        ...
        s.cost += 5.2
    -> 14:02:11 ▶ vet v0002c1: 4 samples x 2 books, cap $30
       14:09:40 ✓ vet v0002c1 (7m29s, $5.20)

`tee(cmd)` copies everything printed to <data>/logs/<date>-<time>-<cmd>.log (cli.main calls it) and opens the
run's record dir <data>/logs/<date>-<time>-<cmd>/: steps.jsonl gets one line per finished step (path, time,
duration, cost, result, ok), and llm.run files every call under calls/ (see record_call).

Colors (terminal only; NO_COLOR=1 turns them off, the log file never has them): step starts bold cyan,
done green, failures red, warnings / cost caps yellow, heartbeats and cached work dim, rule additions
green, rule changes yellow, retirements red. `note` picks the level from the line's marker unless given.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import sys
import threading
import pathlib
import time
from typing import Iterator, TextIO
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
_depth = threading.local()
_main_path: list[str] = []  # step names open in the main thread; worker threads report under them
RUN: pathlib.Path | None = None  # this command's record dir (set by tee)
_rec_lock = threading.Lock()
_n_calls = [0]


def step_path() -> str:
    """The open steps, outermost first, e.g. "round/distill" (a worker thread: its own, else the main thread's)."""
    return "/".join(getattr(_depth, "path", None) or _main_path)


def _record(name: str, row: dict) -> None:
    if RUN is not None:
        with _rec_lock, open(RUN / name, "a") as f:
            f.write(json.dumps(row) + "\n")


def record_call(prompt: str, text: str, row: dict) -> None:
    """File one LLM call of this run: calls/<n>.prompt.md, calls/<n>.out.md and a line in calls.jsonl with
    `row` plus the step path and n. No-op outside a tee'd command."""
    if RUN is None:
        return
    with _rec_lock:
        _n_calls[0] += 1
        n = _n_calls[0]
    d = RUN / "calls"
    d.mkdir(exist_ok=True)
    (d / f"{n:05d}.prompt.md").write_text(prompt)
    (d / f"{n:05d}.out.md").write_text(text)
    _record("calls.jsonl", {"n": n, "time": dt.datetime.now(PT).isoformat(timespec="seconds"), "step": step_path(), **row})
_C = {"head": "1;36", "ok": "32", "err": "31", "warn": "33", "dim": "2", "add": "32", "change": "33",
      "drop": "31", "info": ""}
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _color() -> bool:
    out = getattr(sys.stdout, "a", sys.stdout)  # under tee, the terminal side decides
    return not os.environ.get("NO_COLOR") and hasattr(out, "isatty") and out.isatty()


def _level(msg: str) -> str:
    """The level a line gets when none is given, from its marker."""
    m = msg.lstrip()
    if m.startswith("▶"):
        return "head"
    if m.startswith("✓"):
        return "ok"
    if m.startswith(("✗", "FAIL")) or ": FAIL " in m:
        return "err"
    if m.startswith(("…", "skipping")) or ": cached" in m:
        return "dim"
    if "cost cap" in m or m.startswith(("note:", "INCOMPLETE", "warning")):
        return "warn"
    return "info"


def paint(text: str, level: str) -> str:
    """`text` in the color of `level` when the terminal shows colors."""
    code = _C.get(level, "")
    return f"\x1b[{code}m{text}\x1b[0m" if code and _color() else text


def now() -> str:
    """Current Pacific time as HH:MM:SS."""
    return dt.datetime.now(PT).strftime("%H:%M:%S")


def dur(sec: float) -> str:
    """A duration as 42s, 3m05s or 1h20m."""
    sec = int(sec)
    return f"{sec // 3600}h{sec % 3600 // 60:02d}m" if sec >= 3600 else f"{sec // 60}m{sec % 60:02d}s" if sec >= 60 else f"{sec}s"


def note(msg: str, level: str | None = None) -> None:
    """One timestamped line, indented under the current step, colored by `level` (default: from its marker)."""
    print(paint(now(), "dim") + " " + "  " * getattr(_depth, "n", 0) + paint(msg, level or _level(msg)), flush=True)


class _Step:
    def __init__(self) -> None:
        self.cost, self.result = 0.0, ""


@contextlib.contextmanager
def step(name: str, detail: str = "") -> Iterator[_Step]:
    """A named step: a start line, the lines inside indented, an end line with duration, cost and
    `s.result`; on an exception, a FAILED line (the exception propagates)."""
    note(f"▶ {name}" + (f": {detail}" if detail else ""))
    _depth.n = getattr(_depth, "n", 0) + 1
    main = threading.current_thread() is threading.main_thread()
    path = _main_path if main else _depth.__dict__.setdefault("path", [])
    path.append(name)
    here = step_path()
    s, t0 = _Step(), time.time()
    start = dt.datetime.now(PT).isoformat(timespec="seconds")
    try:
        yield s
    except BaseException as e:
        _depth.n -= 1
        path.pop()
        note(f"✗ {name} FAILED after {dur(time.time() - t0)}: {type(e).__name__}: {e}")
        _record("steps.jsonl", {"step": here, "detail": detail, "start": start, "secs": round(time.time() - t0, 1),
                                "cost": round(s.cost, 4), "ok": False, "error": f"{type(e).__name__}: {e}"[:500]})
        raise
    _depth.n -= 1
    path.pop()
    _record("steps.jsonl", {"step": here, "detail": detail, "start": start, "secs": round(time.time() - t0, 1),
                            "cost": round(s.cost, 4), "ok": True, "result": str(s.result)[:2000]})
    note(f"✓ {name} ({dur(time.time() - t0)}" + (f", ${s.cost:.2f}" if s.cost else "") + ")"
         + (f": {s.result}" if s.result else ""))


class _Tee:
    def __init__(self, a: TextIO, b: TextIO) -> None:
        self.a, self.b = a, b

    def write(self, x: str) -> int:
        """Write to both streams (no color codes in the file)."""
        self.b.write(_ANSI.sub("", x))
        return self.a.write(x)

    def flush(self) -> None:
        """Flush both streams."""
        self.a.flush()
        self.b.flush()

    def __getattr__(self, k: str):
        return getattr(self.a, k)


def tee(cmd: str, data: pathlib.Path) -> str:
    """Copy stdout to <data>/logs/<YYYYMMDD-HHMMSS>-<cmd>.log; returns the path."""
    d = data / "logs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{dt.datetime.now(PT):%Y%m%d-%H%M%S}-{cmd}.log"
    sys.stdout = _Tee(sys.stdout, open(p, "a", buffering=1))
    global RUN
    RUN = p.with_suffix("")
    RUN.mkdir(exist_ok=True)
    return str(p)

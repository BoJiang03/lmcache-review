"""Progress output: timestamped (Pacific) lines, nested steps with duration and cost, and a log file.

    with step("vet v0002c1", "4 samples x 2 books, cap $30") as s:
        ...
        s.cost += 5.2
    -> 14:02:11 ▶ vet v0002c1: 4 samples x 2 books, cap $30
       14:09:40 ✓ vet v0002c1 (7m29s, $5.20)

`tee(cmd)` copies everything printed to <data>/logs/<date>-<time>-<cmd>.log (cli.main calls it).

Colors (terminal only; NO_COLOR=1 turns them off, the log file never has them): step starts bold cyan,
done green, failures red, warnings / cost caps yellow, heartbeats and cached work dim, rule additions
green, rule changes yellow, retirements red. `note` picks the level from the line's marker unless given.
"""

from __future__ import annotations

import contextlib
import datetime as dt
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
    s, t0 = _Step(), time.time()
    try:
        yield s
    except BaseException as e:
        _depth.n -= 1
        note(f"✗ {name} FAILED after {dur(time.time() - t0)}: {type(e).__name__}: {e}")
        raise
    _depth.n -= 1
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
    return str(p)

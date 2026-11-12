"""Progress output: timestamped (Pacific) lines, nested steps with duration and cost, and a log file.

    with step("vet v0002c1", "4 samples x 2 books, cap $30") as s:
        ...
        s.cost += 5.2
    -> 14:02:11 ▶ vet v0002c1: 4 samples x 2 books, cap $30
       14:09:40 ✓ vet v0002c1 (7m29s, $5.20)

`tee(cmd)` copies everything printed to <data>/logs/<date>-<time>-<cmd>.log (cli.main calls it).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import sys
import threading
import time
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
_depth = threading.local()


def now() -> str:
    return dt.datetime.now(PT).strftime("%H:%M:%S")


def dur(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}h{sec % 3600 // 60:02d}m" if sec >= 3600 else f"{sec // 60}m{sec % 60:02d}s" if sec >= 60 else f"{sec}s"


def note(msg: str) -> None:
    """One timestamped line, indented under the current step."""
    print(f"{now()} {'  ' * getattr(_depth, 'n', 0)}{msg}", flush=True)


class _Step:
    def __init__(self) -> None:
        self.cost, self.result = 0.0, ""


@contextlib.contextmanager
def step(name: str, detail: str = ""):
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
    def __init__(self, a, b) -> None:
        self.a, self.b = a, b

    def write(self, x: str) -> int:
        self.b.write(x)
        return self.a.write(x)

    def flush(self) -> None:
        self.a.flush()
        self.b.flush()

    def __getattr__(self, k: str):
        return getattr(self.a, k)


def tee(cmd: str, data) -> str:
    """Copy stdout to <data>/logs/<YYYYMMDD-HHMMSS>-<cmd>.log; returns the path."""
    d = data / "logs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{dt.datetime.now(PT):%Y%m%d-%H%M%S}-{cmd}.log"
    sys.stdout = _Tee(sys.stdout, open(p, "a", buffering=1))
    return str(p)

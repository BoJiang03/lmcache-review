"""Run paid jobs in parallel under a spending cap, with progress lines."""

from __future__ import annotations

import concurrent.futures as cf
import time
from typing import Callable, Iterable

from .progress import dur, note

HEARTBEAT = 60.0  # seconds between "still running" lines while nothing finishes


def capped_map(fn: Callable[[object], tuple[object, float]], items: Iterable, workers: int,
               max_cost: float, label: Callable[[object], str] = str,
               show: Callable[[object], str] | None = None, est: float = 0.0) -> tuple[list, float]:
    """Run `fn(item) -> (result, cost)` over items, at most `workers` at a time.

    No new job starts once the spent total, plus `est` (expected cost of one job) for each job still
    running, would reach `max_cost`; jobs already running finish. With `est` 0 the total can overshoot
    by up to `workers` jobs; with a fair `est`, by about the estimate's error. Failures are printed and skipped. Prints one line per
    finished job ([done/total], cost so far against the cap, ETA) and a heartbeat while jobs run.

    Returns:
        (results in completion order, total cost). `show(result)` -> text for the progress line.
    """
    items, spent, out = list(items), 0.0, []
    total, done_n, failed, t0 = len(items), 0, 0, time.time()
    if not total:
        return out, spent
    with cf.ThreadPoolExecutor(workers) as ex:
        running: dict = {}
        started: dict = {}
        while items or running:
            while items and len(running) < workers and spent + est * (len(running) + 1) <= max(max_cost, est) \
                    and spent < max_cost:
                it = items.pop(0)
                f = ex.submit(fn, it)
                running[f], started[f] = it, time.time()
            if not running:
                note(f"cost cap ${max_cost:.2f} reached; {len(items)} of {total} not run")
                break
            done, _ = cf.wait(running, timeout=HEARTBEAT, return_when=cf.FIRST_COMPLETED)
            if not done:
                ages = ", ".join(f"{label(it)} {dur(time.time() - started[f])}" for f, it in running.items())
                cap = f" of ${max_cost:.0f}" if max_cost != float("inf") else ""
                note(f"… running {len(running)} ({ages}); {len(items)} queued; ${spent:.2f}{cap}")
                continue
            for f in done:
                it = running.pop(f)
                took = time.time() - started.pop(f)
                done_n += 1
                left = total - done_n
                eta = (time.time() - t0) / done_n * left  # completions so far already reflect the parallelism
                tail = f"[{done_n}/{total}] ${spent:.2f}" + (f" of ${max_cost:.0f}" if max_cost != float("inf") else "") \
                    + (f", ~{dur(eta)} left" if left else "")
                try:
                    res, cost = f.result()
                    spent += cost
                    out.append(res)
                    tail = f"[{done_n}/{total}] ${spent:.2f}" + (f" of ${max_cost:.0f}" if max_cost != float("inf") else "") \
                    + (f", ~{dur(eta)} left" if left else "")
                    what = show(res) if show else res if isinstance(res, str) else "done"
                    note(f"{label(it)}: {what} (${cost:.2f}, {dur(took)}) {tail}")
                except Exception as e:  # keep going
                    failed += 1
                    note(f"{label(it)}: FAIL {type(e).__name__}: {e} {tail}")
    if failed:
        note(f"{failed} of {total} failed")
    return out, spent

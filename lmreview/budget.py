"""Run paid jobs in parallel under a spending cap."""

from __future__ import annotations

import concurrent.futures as cf
from typing import Callable, Iterable


def capped_map(fn: Callable[[object], tuple[object, float]], items: Iterable, workers: int,
               max_cost: float, label: Callable[[object], str] = str) -> tuple[list, float]:
    """Run `fn(item) -> (result, cost)` over items, at most `workers` at a time.

    No new job starts once the spent total reaches `max_cost`; jobs already running finish, so the
    total can overshoot by up to `workers` jobs. Failures are printed and skipped.

    Returns:
        (results in completion order, total cost).
    """
    items, spent, out = list(items), 0.0, []
    with cf.ThreadPoolExecutor(workers) as ex:
        running: dict = {}
        while items or running:
            while items and len(running) < workers and spent < max_cost:
                it = items.pop(0)
                running[ex.submit(fn, it)] = it
            if not running:
                print(f"  cost cap ${max_cost:.2f} reached; {len(items)} not run", flush=True)
                break
            done, _ = cf.wait(running, return_when=cf.FIRST_COMPLETED)
            for f in done:
                it = running.pop(f)
                try:
                    res, cost = f.result()
                    spent += cost
                    out.append(res)
                    note = f"{res} " if isinstance(res, str) else ""
                    print(f"  {label(it)}: {note}${cost:.2f} (total ${spent:.2f})", flush=True)
                except Exception as e:  # keep going
                    print(f"  {label(it)}: FAIL {e}", flush=True)
    return out, spent

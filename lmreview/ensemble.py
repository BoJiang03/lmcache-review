"""Run a randomized LLM step several times at once, then merge: a generic way to cut run-to-run noise.

Used by the reviewer (`x<n>` reviewers: n reviews, then a merge agent) and by distill (n abstractions
of the same groups, then a merge that picks the level the human comments support).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Generic, TypeVar

R = TypeVar("R")


class Ensemble(Generic[R]):
    """The outcome of ensemble().

    Attributes:
        result: the merged result; a single usable run when nothing was merged or the merge failed.
        runs: the runs that returned (failed ones raised and are not here).
        merge: the merge's own result, also when it was unusable and `result` fell back to a run
            (so its cost can still be counted); None if no merge ran or it raised.
        merged: whether `result` is the merge's.
    """

    def __init__(self, result: R, runs: list[R], merge: R | None = None, merged: bool = False) -> None:
        self.result, self.runs, self.merge, self.merged = result, runs, merge, merged


def ensemble(once: Callable[[], R], n: int, merge: Callable[[list[R]], R],
             ok: Callable[[R], bool] = lambda r: True) -> Ensemble[R]:
    """Call `once` n times in parallel and merge the usable results.

    A run that raises or is not `ok` is left out; a merge that raises or is not `ok` falls back to the
    first usable run, so one bad call never loses the good ones.

    Args:
        once: one run of the step (an LLM call and its parsing).
        n: how many runs; 1 = just `once()`, no merge (exceptions propagate as before).
        merge: combines >= 2 usable results into one (usually one more LLM call).
        ok: whether a result is usable (e.g. its output parsed).

    Returns:
        An Ensemble. With fewer than 2 usable runs nothing is merged: the result is the usable run, or
        the first returned run if none is usable.

    Raises:
        Exception: the first run's exception, when every run raised.
    """
    if n <= 1:
        r = once()
        return Ensemble(r, [r])

    def safe() -> R | Exception:
        try:
            return once()
        except Exception as e:  # one failed call must not sink the others
            return e

    with ThreadPoolExecutor(n) as ex:
        out = list(ex.map(lambda _: safe(), range(n)))
    runs = [r for r in out if not isinstance(r, Exception)]
    if not runs:
        raise out[0]
    good = [r for r in runs if ok(r)]
    if len(good) <= 1:
        return Ensemble((good or runs)[0], runs)
    try:
        m = merge(good)
    except Exception:
        return Ensemble(good[0], runs)
    return Ensemble(m, runs, m, True) if ok(m) else Ensemble(good[0], runs, m)

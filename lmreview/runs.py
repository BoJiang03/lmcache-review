"""Run records: repeat runs, the model each run used, and hit counts over the repeats (all free).

Repeats: run k of reviewer R on a sample is stored under <data>/runs/R/ for k = 1 and under
<data>/runs/R#r<k>/ for k > 1, with its score under <data>/scores/<the same dir name>/. Every repeat is
cached like a first run, so no (reviewer, sample, rep) is paid for twice.

Model: Claude Code may move its default model to a new version while a reviewer's name stays the same.
Each run json records the models its calls used ("model": the model ids, comma-separated; "" when the
run made no call). llm.run notes the model every requested model name ("default" or an id) resolved to
in <data>/models.json; a cached run whose recorded model is no longer what its reviewer's calls resolve
to is not reused (`cached`). A run without "model" (older runs) is of unknown model: still reused, and
counted as unknown in `stability`.

Hits: `hits` counts, over every repeat of a reviewer, the judged runs on a sample that cover a comment
and those that match it. vet's sequential check and round's miss confirmation read their counts here.
"""

from __future__ import annotations

import json
import pathlib
import re

from .annotate import cid_of
from .config import Config
from .progress import note


def run_dir(cfg: Config, reviewer: str, k: int = 1) -> pathlib.Path:
    """The run dir of repeat `k` of `reviewer` (k = 1: the reviewer's own dir).

    Args:
        cfg: configuration.
        reviewer: a reviewer name, possibly with a cache tag such as "#o<hash>" (regress.run_tag).
        k: the repeat, from 1.

    Returns:
        <data>/runs/<reviewer> or <data>/runs/<reviewer>#r<k>.
    """
    return cfg.data / "runs" / (reviewer + ("" if k == 1 else f"#r{k}"))


def rep_dirs(cfg: Config, reviewer: str) -> list[tuple[int, pathlib.Path]]:
    """The existing run dirs of every repeat of `reviewer`, as (k, dir), by k."""
    root = cfg.data / "runs"
    if not root.exists():
        return []
    pat = re.compile(re.escape(reviewer) + r"(?:#r(\d+))?")
    out = []
    for d in root.iterdir():
        m = pat.fullmatch(d.name)
        if m and d.is_dir():
            out.append((int(m[1] or 1), d))
    return sorted(out)


def sample_file(sample: dict | str) -> str:
    """The run file name of a sample: a sample dict ({"pr", "commit"}) or "#pr@commit8" / "pr@commit8"."""
    if isinstance(sample, dict):
        return f"{sample['pr']}-{sample['commit'][:8]}.json"
    pr, _, c = str(sample).lstrip("#").partition("@")
    return f"{int(pr)}-{c[:8]}.json"


# ---- models -----------------------------------------------------------------------------------------

def models_path(cfg: Config) -> pathlib.Path:
    """<data>/models.json: {requested model name: the model id it last resolved to} (llm.run fills it)."""
    return cfg.data / "models.json"


def run_models(r: dict) -> str:
    """The models a run_reviewer result used: its own call's and its sub-runs' ("" when it made no call)."""
    ms = {m for x in [r, *(r.get("runs") or [])] for m in str(x.get("model") or "").split(",") if m}
    return ",".join(sorted(ms))


def expected_models(cfg: Config, reviewer: str) -> set[str] | None:
    """The model ids the calls of `reviewer` resolve to now (from models.json); None if not known yet."""
    p = models_path(cfg)
    seen = json.loads(p.read_text()) if p.exists() else {}
    slots = ["default"]
    if any(s not in seen for s in slots):
        return None
    return {seen[s] for s in slots}


def model_ok(cfg: Config, reviewer: str, run: dict, where: str = "") -> bool:
    """Whether a cached run may be reused: its models are among those its reviewer resolves to now. A run
    of unknown model (no "model" field), one that made no call, or a reviewer whose models are not known
    yet is reused. Warns when a run is not reused."""
    m = run.get("model")
    if not m:
        return True
    want = expected_models(cfg, reviewer)
    if want is None or set(m.split(",")) <= want:
        return True
    note(f"{where or 'run'}: made with {m}, the reviewer now runs {','.join(sorted(want))}: not reused", "warn")
    return False


def cached(cfg: Config, reviewer: str, path: pathlib.Path, rerun_failed: bool = False) -> bool:
    """Whether the run at `path` (of `reviewer`) can be reused instead of run again.

    Args:
        cfg: configuration.
        reviewer: the reviewer that made it (its model slots).
        path: the run file.
        rerun_failed: a failed run (findings None with an error) is not reused.

    Returns:
        False if it is missing, failed (with `rerun_failed`), or made with a model the reviewer no longer uses.
    """
    if not path.exists():
        return False
    run = json.loads(path.read_text())
    if rerun_failed and run.get("findings") is None and run.get("error"):
        return False
    return model_ok(cfg, reviewer, run, f"{path.parent.name}/{path.name}")


def save_run(cfg: Config, path: pathlib.Path, run: dict) -> None:
    """Write a run file; a score of the run it replaces is moved to <data>/scores/_replaced/, so it is
    judged again rather than read for the new run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sp = cfg.data / "scores" / path.parent.name / path.name
    if sp.exists():
        old = cfg.data / "scores" / "_replaced" / path.parent.name / path.name
        old.parent.mkdir(parents=True, exist_ok=True)
        sp.replace(old)
    path.write_text(json.dumps(run, indent=1))


def unknown_model(cfg: Config, reviewer: str, samples: list[dict | str]) -> int:
    """Runs of `reviewer` (every repeat) on `samples` that record no model (made before models were recorded)."""
    names = {sample_file(x) for x in samples}
    return sum(1 for _, d in rep_dirs(cfg, reviewer) for n in names
               if (d / n).exists() and "model" not in json.loads((d / n).read_text()))


# ---- hits -------------------------------------------------------------------------------------------

def _one(cfg: Config, d: pathlib.Path, name: str, comment: int | str, cites: set[str] | None) -> bool | None:
    """Whether the run in dir `d` on sample file `name` matches `comment`; None if it has no judged
    result covering the comment (no run, a failed run, not judged, or judged for other comments only)."""
    from .schema import cites as finding_rules
    from .score import JUDGE, _normalize, hkey
    f = d / name
    if not f.exists():
        return None
    run = json.loads(f.read_text())
    if run.get("findings") is None:
        return None
    sp = cfg.data / "scores" / d.name / name
    if not sp.exists():  # a rule-only run with no findings is scored without a judge call (regress.replay)
        return False if run["findings"] == [] else None
    s = json.loads(sp.read_text())
    if s.get("judge", "j1") != JUDGE:
        return None
    try:
        s = _normalize(s, run)  # older scores matched findings by index
    except ValueError:
        pass
    mine = [h for h in s.get("human") or [] if comment in (hkey(s, h), cid_of(hkey(s, h)))]
    if not mine:
        return None
    ok = None if cites is None else {x["id"] for x in run["findings"] if finding_rules(x) & cites}
    return any(set(h.get("matched_ai") or []) & ok if ok is not None else bool(h.get("matched_ai")) for h in mine)


def hits(reviewer_base: str, sample: dict | str, comment: int | str, cfg: Config | None = None,
         cites: set[str] | None = None) -> tuple[int, int]:
    """How often the repeats of a reviewer matched a human comment on a sample (free: judged runs only).

    Args:
        reviewer_base: the reviewer name without "#r<k>" (a cache tag such as "#o<hash>" stays).
        sample: a sample dict or "#pr@commit8".
        comment: a point key (comment id, or "<comment id>:<k>"); a comment id is matched by any of its points.
        cfg: configuration.
        cites: count a match only when a matching finding cites one of these rule ids (vet: the entry
            and its links); None: any matching finding.

    Returns:
        (runs that matched it, runs with a judged result covering it), summed over every repeat.
    """
    cfg = cfg or Config()
    name = sample_file(sample)
    got = [_one(cfg, d, name, comment, cites) for _, d in rep_dirs(cfg, reviewer_base)]
    got = [x for x in got if x is not None]
    return sum(got), len(got)


def stability(reviewer: str, cfg: Config | None = None) -> str:
    """The comments `reviewer` has judged in at least two repeats and their hit rate p = hit/n, with how
    many fall at p = 0, 0 < p < 1 and p = 1 (free); plus how many runs record no model.

    Returns:
        The report text.
    """
    from .score import JUDGE, WANT, hkey
    cfg = cfg or Config()
    dirs = rep_dirs(cfg, reviewer)
    keys: dict[str, set] = {}  # sample file -> point keys judged in some repeat
    unknown, models, n_runs = 0, {}, 0
    for _, d in dirs:
        for f in d.glob("*.json"):
            run = json.loads(f.read_text())
            n_runs += 1
            if "model" not in run:
                unknown += 1
            elif run["model"]:
                models[run["model"]] = models.get(run["model"], 0) + 1
            sp = cfg.data / "scores" / d.name / f.name
            if sp.exists() and (s := json.loads(sp.read_text())).get("judge", "j1") == JUDGE:
                keys.setdefault(f.name, set()).update(hkey(s, h) for h in s.get("human") or [] if h.get("type") in WANT)
    rows = []
    for name, ks in sorted(keys.items()):
        pr, c = name[:-5].split("-")
        for k in sorted(ks, key=str):
            h, n = hits(reviewer, f"{pr}@{c}", k, cfg)
            if n >= 2:
                rows.append((f"#{pr}@{c}", k, h, n))
    zero = sum(h == 0 for *_, h, n in rows)
    one = sum(h == n for *_, h, n in rows)
    L = [f"# Stability of {reviewer}", "",
         f"- repeats on disk: {', '.join(f'r{k}' for k, _ in dirs) or 'none'}; runs {n_runs}; models: "
         + (", ".join(f"{m} {c}" for m, c in sorted(models.items())) or "none recorded")
         + (f"; unknown model (older runs) {unknown}" if unknown else ""),
         f"- comments judged in >= 2 runs: {len(rows)}; p = 0: {zero}, 0 < p < 1: {len(rows) - zero - one}, p = 1: {one}", ""]
    L += [f"- {s} c{k}: {h}/{n}" for s, k, h, n in rows if 0 < h < n]
    return "\n".join(L)

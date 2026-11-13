"""Compare two reviewer versions per human comment (flips), not by aggregate rate.

On the samples both versions have judge results for, each human change request / nit is:
  fixed   missed by A, matched by B
  broken  matched by A, missed by B
  both / neither
Run-to-run variance is large (about ±15 points on 10 samples), so read the flips, not the rate.
Uses the judge results only; free.
"""

from __future__ import annotations

import json

from .config import Config
from .schema import load_findings
from .score import REPORTS, _normalize, hkey, load_gold


def _load(cfg: Config, version: str) -> dict:
    out = {}
    for p in sorted((cfg.data / "scores" / version).glob("*.json")):
        run = json.loads((cfg.data / "runs" / version / p.name).read_text())
        out[p.stem] = (_normalize(json.loads(p.read_text()), run), run)
    return out


def compare(a: str, b: str, cfg: Config | None = None) -> str:
    """Write reports/compare_<a>_vs_<b>.md; return its headline."""
    cfg = cfg or Config()
    _, cm = load_gold(cfg)
    A, B = _load(cfg, a), _load(cfg, b)
    keys = sorted(A.keys() & B.keys())
    flips = {"fixed": [], "broken": [], "both": [], "neither": []}
    nfind = {a: 0, b: 0}
    for k in keys:
        (sa, ra), (sb, rb) = A[k], B[k]
        nfind[a] += len(load_findings(ra) or [])
        nfind[b] += len(load_findings(rb) or [])
        hb = {hkey(sb, h): h for h in sb["human"]}
        for ha in sa["human"]:
            hb_ = hb.get(hkey(sa, ha))
            if hb_ is None or ha["type"] not in ("change_request", "nit"):
                continue
            ma, mb = bool(ha["matched_ai"]), bool(hb_["matched_ai"])
            kind = "both" if ma and mb else "fixed" if mb else "broken" if ma else "neither"
            c = cm[sa["gold_ids"][ha["id"]]]
            flips[kind].append((sa["pr"], ha["type"], c))
    L = [f"# Compare {a} vs {b}", "",
         f"Samples in both: {len(keys)} · findings {a} {nfind[a]}, {b} {nfind[b]}", "",
         f"- fixed (missed by {a}, matched by {b}): {len(flips['fixed'])}",
         f"- broken (matched by {a}, missed by {b}): {len(flips['broken'])}",
         f"- matched by both: {len(flips['both'])} · missed by both: {len(flips['neither'])}",
         f"- net: {len(flips['fixed']) - len(flips['broken']):+d}", ""]
    for kind in ("fixed", "broken", "neither"):
        L += [f"## {kind}", ""]
        for pr, t, c in flips[kind]:
            where = f"{c['path']}:{c['line_lo']}" if c["kind"] == "inline" else "overall review"
            L.append(f"- #{pr} ({t}) `{where}` {c['author']}: {c['body'][:150].replace(chr(10), ' ')}")
        L.append("")
    (REPORTS / f"compare_{a}_vs_{b}.md").write_text("\n".join(L) + "\n")
    return "\n".join(L[:8])

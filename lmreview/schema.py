"""The finding format shared by reviewer output, run files, judge input and rendering.

A finding is about a line range, a file, or the whole PR, and may point at several places,
including places outside the diff ("this should also change").
"""

from __future__ import annotations

import dataclasses

SCHEMA_VERSION = 2
SEVERITIES = ("blocker", "major", "minor", "nit")
SCOPES = ("line", "file", "pr")


@dataclasses.dataclass
class Location:
    """A place in the code. Lines are 1-based and inclusive; None for a whole-file location.

    side: "new" = the file at the reviewed commit, "old" = the base version (deleted code).
    role: "primary" = where the problem is, "related" = other places involved.
    """

    path: str
    start: int | None = None
    end: int | None = None
    side: str = "new"
    role: str = "primary"


@dataclasses.dataclass
class Finding:
    """One review finding."""

    id: str
    severity: str
    scope: str
    title: str
    body: str
    locations: list[Location] = dataclasses.field(default_factory=list)
    suggestion: str | None = None
    rule: str | None = None

    def primary(self) -> Location | None:
        """The first primary location, if any."""
        return next((l for l in self.locations if l.role == "primary"), None)

    def where(self) -> str:
        """Short human-readable location, e.g. `a.py:10-12` (+2 related)."""
        p = self.primary()
        if p is None:
            return "whole PR" if self.scope == "pr" else "-"
        s = p.path + (f":{p.start}" if p.start else "") + (f"-{p.end}" if p.end and p.end != p.start else "")
        n = len(self.locations) - 1
        return s + (f" (+{n} related)" if n else "")


class SchemaError(ValueError):
    """The reviewer output does not follow the finding schema."""


def _loc(d: dict) -> Location:
    if not isinstance(d, dict) or not d.get("path"):
        raise SchemaError(f"location needs a path: {d!r}")
    start = d.get("start", d.get("line"))
    end = d.get("end", start)
    if start is not None and end is not None and end < start:
        start, end = end, start
    side = d.get("side", "new")
    role = d.get("role", "primary")
    if side not in ("new", "old") or role not in ("primary", "related"):
        raise SchemaError(f"bad side/role: {d!r}")
    return Location(d["path"], start, end, side, role)


def parse_findings(obj: object) -> list[Finding]:
    """Validate reviewer output into Findings. Accepts the legacy v1 shape {path, line, ...}.

    Raises:
        SchemaError: on anything that cannot be interpreted unambiguously.
    """
    if not isinstance(obj, list):
        raise SchemaError("findings must be a JSON list")
    out, seen = [], set()
    for i, d in enumerate(obj, 1):
        if not isinstance(d, dict):
            raise SchemaError(f"finding {i} is not an object")
        if "locations" in d:
            locs = [_loc(x) for x in d["locations"] or []]
        elif d.get("path"):  # legacy: one path + one line
            locs = [_loc({"path": d["path"], "start": d.get("line")})]
        else:
            locs = []
        scope = d.get("scope") or ("line" if locs and locs[0].start else "file" if locs else "pr")
        sev = d.get("severity")
        if sev not in SEVERITIES or scope not in SCOPES:
            raise SchemaError(f"finding {i}: bad severity/scope {sev!r}/{scope!r}")
        if scope != "pr" and not locs:
            raise SchemaError(f"finding {i}: scope {scope} needs a location")
        if locs and not any(l.role == "primary" for l in locs):
            locs[0].role = "primary"
        fid = str(d.get("id") or f"f{i}")
        if fid in seen:
            fid = f"f{i}"
        seen.add(fid)
        out.append(Finding(fid, sev, scope, str(d.get("title", "")).strip(), str(d.get("body", "")).strip(),
                           locs, d.get("suggestion") or None, d.get("rule") or None))
    return out


def to_dicts(fs: list[Finding]) -> list[dict]:
    """Findings as plain JSON-able dicts (what run files store)."""
    return [dataclasses.asdict(f) for f in fs]


def load_findings(run: dict) -> list[Finding] | None:
    """Findings from a stored run, upgrading legacy run files on the fly."""
    return None if run.get("findings") is None else parse_findings(run["findings"])

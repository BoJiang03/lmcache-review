"""Re-parse runs whose reviewer output failed the schema, from the saved raw text (free, no model call).

Usage: python3 scripts/reparse_invalid.py <reviewer>
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lmreview import llm  # noqa: E402
from lmreview.config import Config  # noqa: E402
from lmreview.schema import SchemaError, parse_findings, to_dicts  # noqa: E402


def main() -> None:
    """Re-parse every invalid run of the reviewer named on the command line; print what changed."""
    d = Config().data / "runs" / sys.argv[1]
    for p in sorted(d.glob("*.json")):
        r = json.loads(p.read_text())
        if r.get("findings") is not None:
            continue
        try:
            f = to_dicts(parse_findings(llm.extract_json(r["raw"])))
        except (ValueError, SchemaError) as e:
            print(f"{p.name}: still invalid ({str(e)[:100]})")
            continue
        r.update(findings=f, error=None, reparsed=r.get("error"))
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(r, indent=1))
        tmp.rename(p)
        print(f"{p.name}: {len(f)} findings")


if __name__ == "__main__":
    main()

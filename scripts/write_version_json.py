"""Write version.json (repository root): the version and code fingerprint that the "Check for updates" button reads.

Run it from the repository root after the last code change of a release, then commit and push version.json:

    .venv/Scripts/python scripts/write_version_json.py --notes "what is new, one line"

version.json sits outside the folders the build id is computed from, so committing it does not change the id.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import __version__  # noqa: E402
from app.buildid import build_id  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notes", default="", help="one line about what is new")
    args = ap.parse_args()
    data = {"version": __version__, "build": build_id(), "released": date.today().isoformat(), "notes": args.notes}
    (ROOT / "version.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

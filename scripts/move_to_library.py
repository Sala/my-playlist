#!/usr/bin/env python3
"""CLI wrapper: import downloads/ into the music library (see app.import_library)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.import_library import (  # noqa: E402
    DEFAULT_DOWNLOADS,
    DEFAULT_MUSIC,
    run_import,
)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(description="Move cleaned downloads into music artist folders")
    ap.add_argument("--downloads", type=Path, default=DEFAULT_DOWNLOADS)
    ap.add_argument("--music", type=Path, default=DEFAULT_MUSIC)
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Write tags, move files, and delete sources/dupes (default is dry-run)",
    )
    ap.add_argument("--limit", type=int, default=0, help="Process only first N files")
    args = ap.parse_args()

    try:
        run_import(
            args.downloads,
            args.music,
            apply=bool(args.apply),
            limit=int(args.limit or 0),
            quiet=False,
            write_report=True,
        )
    except FileNotFoundError as exc:
        print(str(exc), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

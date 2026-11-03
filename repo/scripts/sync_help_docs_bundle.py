#!/usr/bin/env python3
"""Keep the copies of the help documents in step with the originals.

The technical documents of the in-app help live in the project root, above
``repo/``.  The container image is built from ``repo/`` alone, so it has no
project root and the documents would be missing there.  This script keeps a
copy of every document of the project root in ``repo/help_docs_bundle/``, at
the same relative path, so that the image shows the same documents as the
checkout.

Run it after editing any of the documents:

    python scripts/sync_help_docs_bundle.py

``--check`` reports the documents that differ and exits 1, which is how the
test suite keeps the copies from drifting away from the originals.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REPO_DIR.parent
BUNDLE_DIR = REPO_DIR / "help_docs_bundle"
CONFIG_PATH = REPO_DIR / "config" / "help_content.json"


def project_documents(config_path: Path = CONFIG_PATH) -> list[str]:
    """The relative paths of the documents the help takes from the project root."""
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return [
        str(entry["path"])
        for entry in data["technical"]["documents"]
        if entry.get("root") == "project"
    ]


def bundle_documents(bundle_dir: Path = BUNDLE_DIR) -> list[str]:
    """The relative paths of the files the bundle holds."""
    if not bundle_dir.is_dir():
        return []
    return sorted(
        str(path.relative_to(bundle_dir))
        for path in bundle_dir.rglob("*")
        if path.is_file()
    )


def sync(project_root: Path, bundle_dir: Path, config_path: Path, check: bool) -> int:
    """Copy every project-root document into the bundle, or report the differences.

    With ``check`` nothing is written: the documents that differ are named and
    the exit status is 1.
    """
    documents = project_documents(config_path)
    differences: list[str] = []
    for relative in documents:
        original = project_root / relative
        copy = bundle_dir / relative
        if not original.is_file():
            differences.append(f"{relative}: missing in the project root")
            continue
        if not copy.is_file():
            if check:
                differences.append(f"{relative}: missing in the bundle")
                continue
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(original.read_bytes())
            print(f"copied {relative}")
            continue
        if copy.read_bytes() == original.read_bytes():
            continue
        if check:
            differences.append(f"{relative}: the copy differs from the original")
            continue
        copy.write_bytes(original.read_bytes())
        print(f"updated {relative}")
    for relative in bundle_documents(bundle_dir):
        if relative not in documents:
            differences.append(f"{relative}: in the bundle, but not a document of the project root")
    if differences:
        for line in differences:
            print(f"DIFFERENT: {line}", file=sys.stderr)
        return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report the documents that differ, and exit 1, without writing anything",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = sync(PROJECT_ROOT, BUNDLE_DIR, CONFIG_PATH, args.check)
    if status == 0 and not args.check:
        print(f"the help documents of the project root are in {BUNDLE_DIR}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())

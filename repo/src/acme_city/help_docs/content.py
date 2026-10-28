"""The content of the in-app help: loaded from config, never written in code.

The tutorial, the how-to guides and the list of technical documents live in
``config/help_content.json``.  The technical documents are files of the
repository; their paths are resolved at run time from the position of this
module, and a file that is not there gives a plain message instead of an error.
"""
# REQUIRES: UX-01, SEC-01
# The help pages read their words from config and their documents from the
# repository, and a missing document is reported in plain words.

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

#: ``repo/`` (the Python project) and the folder above it (the project root).
REPO_DIR = Path(__file__).resolve().parents[3]
PROJECT_ROOT = REPO_DIR.parent
CONTENT_PATH = REPO_DIR / "config" / "help_content.json"

#: The persona labels, by the id the session uses.
PERSONA_LABELS = {
    "persona_applicant": "Applicant",
    "persona_permit_reviewer": "Permit Reviewer",
    "persona_data_steward": "Data Steward",
    "persona_city_administrator": "City Administrator",
}

#: Documents larger than this are not read.
MAX_BYTES = 3_000_000


@lru_cache(maxsize=1)
def _content() -> dict[str, Any]:
    return json.loads(CONTENT_PATH.read_text(encoding="utf-8"))


def reload() -> None:
    """Drop the cached configuration (used by tests)."""
    _content.cache_clear()


def hub() -> dict[str, Any]:
    return dict(_content()["hub"])


def tutorial() -> dict[str, Any]:
    return dict(_content()["tutorial"])


def guides(persona_id: str | None = None) -> list[dict[str, Any]]:
    """Return the how-to guides, those for ``persona_id`` first.

    The order inside each group is the order of the configuration.
    """
    items = [dict(item) for item in _content()["howto"]["guides"]]
    if persona_id:
        items.sort(key=lambda item: persona_id not in item["persona_ids"])
    return items


def guide(slug: str) -> dict[str, Any] | None:
    for item in _content()["howto"]["guides"]:
        if item["slug"] == slug:
            return dict(item)
    return None


def howto_intro() -> str:
    return str(_content()["howto"]["intro"])


def technical() -> dict[str, Any]:
    return dict(_content()["technical"])


def document(slug: str) -> dict[str, Any] | None:
    for item in _content()["technical"]["documents"]:
        if item["slug"] == slug:
            return dict(item)
    return None


@dataclass(frozen=True)
class Loaded:
    """A document read from disk, or the plain reason it could not be."""

    text: str | None
    message: str = ""


def read_document(entry: dict[str, Any]) -> Loaded:
    """Read the file a technical-document entry names.

    The path is joined to its root and must stay inside it.  A missing,
    unreadable or oversized file gives a plain message.
    """
    root = (PROJECT_ROOT if entry.get("root") == "project" else REPO_DIR).resolve()
    candidate = (root / str(entry["path"])).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return Loaded(None, "This document is outside the repository and is not shown.")
    if not candidate.is_file():
        return Loaded(
            None,
            "This document is not available in this copy of the application. "
            "It is part of the full repository.",
        )
    if candidate.stat().st_size > MAX_BYTES:
        return Loaded(None, "This document is too large to show here.")
    try:
        return Loaded(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return Loaded(None, "This document could not be read.")


__all__ = [
    "CONTENT_PATH",
    "PERSONA_LABELS",
    "PROJECT_ROOT",
    "REPO_DIR",
    "Loaded",
    "document",
    "guide",
    "guides",
    "howto_intro",
    "hub",
    "read_document",
    "reload",
    "technical",
    "tutorial",
]

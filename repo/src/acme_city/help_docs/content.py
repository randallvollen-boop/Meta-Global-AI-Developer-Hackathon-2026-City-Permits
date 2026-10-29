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
#: Optional overlay files, merged on top of the base file in name order.
OVERLAY_DIR = REPO_DIR / "config" / "help_content.d"

#: The key that identifies an item of a list of objects, tried in this order.
_ID_KEYS = ("slug", "key", "persona_id")

#: The persona labels, by the id the session uses.
PERSONA_LABELS = {
    "persona_applicant": "Applicant",
    "persona_permit_reviewer": "Permit Reviewer",
    "persona_data_steward": "Data Steward",
    "persona_city_administrator": "City Administrator",
    "persona_agent_operator": "Agent Operator",
}

#: Documents larger than this are not read.
MAX_BYTES = 3_000_000


def _claim(owners: dict[str, str], path: str, owner: str, value: Any) -> None:
    """Record that ``owner`` wrote every leaf under ``path``; a second owner is an error."""
    if isinstance(value, dict):
        for key, item in value.items():
            _claim(owners, f"{path}/{key}", owner, item)
    elif isinstance(value, list):
        for n, item in enumerate(value):
            _claim(owners, f"{path}/{n}", owner, item)
    else:
        if owners.setdefault(path, owner) != owner:
            raise ValueError(f"help overlay {owner}: {path} is also set by {owners[path]}")


def _merge(base: Any, over: Any, owners: dict[str, str], owner: str, where: str = "") -> Any:
    """Return ``base`` with ``over`` laid on top; nothing can be deleted.

    Objects merge key by key, and a new key is added.  A list of objects with an
    id (slug, key or persona_id) merges by id, and an overlay item with no match
    is appended.  A list without ids (the steps) is addressed by position: the
    overlay gives an object such as ``{"2": "new text"}``, and the index equal to
    the length appends.  A plain list in an overlay must be at least as long as
    the base list.  A value never changes kind (null, a string or a different
    container cannot replace what is there), and two overlay files may not set
    the same value.
    """
    if over is None:
        raise ValueError(f"help overlay {owner} {where}: null would delete content")
    if isinstance(base, dict):
        if not isinstance(over, dict):
            raise ValueError(f"help overlay {owner} {where}: expected an object")
        merged = dict(base)
        for key, value in over.items():
            if key in base:
                merged[key] = _merge(base[key], value, owners, owner, f"{where}/{key}")
            else:
                if value is None:
                    raise ValueError(f"help overlay {owner} {where}/{key}: null is not content")
                _claim(owners, f"{where}/{key}", owner, value)
                merged[key] = value
        return merged
    if isinstance(base, list):
        if isinstance(over, dict):
            merged = list(base)
            for key in sorted(over, key=lambda k: int(k) if k.isdigit() else -1):
                if not key.isdigit() or int(key) > len(merged):
                    raise ValueError(f"help overlay {owner} {where}: no item {key}")
                index = int(key)
                if index == len(merged):
                    if over[key] is None:
                        raise ValueError(f"help overlay {owner} {where}/{key}: null is not content")
                    _claim(owners, f"{where}/{key}", owner, over[key])
                    merged.append(over[key])
                else:
                    merged[index] = _merge(merged[index], over[key], owners, owner, f"{where}/{key}")
            return merged
        if not isinstance(over, list):
            raise ValueError(f"help overlay {owner} {where}: expected a list")
        id_key = next(
            (k for k in _ID_KEYS if base and all(isinstance(i, dict) and k in i for i in base)),
            None,
        )
        if id_key is None:
            if len(over) < len(base):
                raise ValueError(f"help overlay {owner} {where}: a step cannot be removed")
            merged = [
                _merge(b, o, owners, owner, f"{where}/{n}") for n, (b, o) in enumerate(zip(base, over))
            ]
            for n, item in enumerate(over[len(base):], start=len(base)):
                if item is None:
                    raise ValueError(f"help overlay {owner} {where}/{n}: null is not content")
                _claim(owners, f"{where}/{n}", owner, item)
                merged.append(item)
            return merged
        merged = list(base)
        for item in over:
            if not isinstance(item, dict) or id_key not in item:
                raise ValueError(f"help overlay {owner} {where}: an item needs a {id_key}")
            index = next((n for n, b in enumerate(merged) if b[id_key] == item[id_key]), None)
            if index is None:
                _claim(owners, f"{where}/{item[id_key]}", owner, item)
                merged.append(item)
            else:
                merged[index] = _merge(merged[index], item, owners, owner, f"{where}/{item[id_key]}")
        return merged
    if isinstance(over, (dict, list)):
        raise ValueError(f"help overlay {owner} {where}: expected a plain value")
    if type(over) is not type(base):
        raise ValueError(f"help overlay {owner} {where}: the value changes kind")
    _claim(owners, where, owner, over)
    return over


@lru_cache(maxsize=1)
def _content() -> dict[str, Any]:
    data = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    owners: dict[str, str] = {}
    for path in sorted(OVERLAY_DIR.glob("*.json")):
        data = _merge(data, json.loads(path.read_text(encoding="utf-8")), owners, path.stem)
    return data


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
    "OVERLAY_DIR",
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

"""Readable display values for the steward screens.

The stored keys stay as they are (``business_license``, ``acme_city``, long
source-system strings).  This module turns them into the words a person reads
and a timestamp into a readable date, and keeps the precise value for the
hover text and for the details drawer.  The words come from
``config/ui_display.json`` and from the registered source systems and
contracts; nothing is hard-coded in a template.
"""
# REQUIRES: UX-01

from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from markupsafe import Markup, escape
from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.fixtures.loader import REPO_ROOT
from acme_city.persistence.models import governance, source

DISPLAY_PATH = REPO_ROOT / "config" / "ui_display.json"

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@lru_cache(maxsize=1)
def _values() -> dict[str, str]:
    return dict(json.loads(Path(DISPLAY_PATH).read_text(encoding="utf-8")).get("values", {}))


def reload() -> None:
    """Drop the cached configuration (used by tests)."""
    _values.cache_clear()


def pretty(value: Any) -> str:
    """Return the readable form of a stored key or value."""
    if value is None or value == "":
        return ""
    text = str(value)
    known = _values().get(text)
    if known is not None:
        return known
    if text.replace("_", "").replace("-", "").isalpha() and text == text.lower():
        spaced = text.replace("_", " ").replace("-", " ")
        return spaced[:1].upper() + spaced[1:]
    return text


def _as_datetime(value: Any) -> datetime | date | None:
    if isinstance(value, (datetime, date)):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def readable_date(value: Any) -> str:
    """Return ``7 Sep 2026`` for a timestamp or ISO string; empty when unknown."""
    moment = _as_datetime(value)
    if moment is None:
        return ""
    return f"{moment.day} {_MONTHS[moment.month - 1]} {moment.year}"


def precise_time(value: Any) -> str:
    """Return the precise time for hover text and details."""
    moment = _as_datetime(value)
    if moment is None:
        return ""
    if isinstance(moment, datetime):
        return moment.strftime("%Y-%m-%d %H:%M:%S") + (" UTC" if moment.tzinfo else "")
    return moment.isoformat()


def time_tag(value: Any, empty: str = "unknown") -> Markup:
    """Return a ``<time>`` element: readable date, precise time on hover."""
    text = readable_date(value)
    if not text:
        return Markup(escape(empty))
    iso = value.isoformat() if isinstance(value, (datetime, date)) else str(value)
    return Markup(
        '<time datetime="{iso}" title="{title}">{text}</time>'.format(
            iso=escape(iso), title=escape(precise_time(value)), text=escape(text)
        )
    )


def source_name(session: Session, system_id: str | None, dataset_key: str | None = None) -> str:
    """Return ``Permitting: Applicant contact profiles`` for a source and dataset."""
    if not system_id:
        return "Not declared"
    system = session.execute(
        select(source.SourceSystem).where(source.SourceSystem.source_system_id == system_id)
    ).scalar_one_or_none()
    system_label = system.label if system is not None else pretty(system_id)
    if not dataset_key:
        return system_label
    contract = session.execute(
        select(governance.SourceContract).where(
            governance.SourceContract.source_system_id == system_id,
            governance.SourceContract.dataset_key == dataset_key,
        )
    ).scalars().first()
    dataset_label = contract.label if contract is not None else pretty(dataset_key)
    return f"{system_label}: {dataset_label}"


def issuer_name(session: Session, issuer: str | None) -> str:
    """Return a readable issuer for ``system:dataset`` strings and plain labels."""
    if not issuer:
        return "Not declared"
    if ":" in issuer and " " not in issuer:
        system_id, _, dataset_key = issuer.partition(":")
        return source_name(session, system_id, dataset_key)
    return issuer


def install(templates: Any) -> None:
    """Add the filters and globals the steward templates use."""
    templates.env.filters["pretty"] = pretty
    templates.env.filters["rdate"] = readable_date
    templates.env.globals["ui_time"] = time_tag


__all__ = [
    "install",
    "issuer_name",
    "precise_time",
    "pretty",
    "readable_date",
    "reload",
    "source_name",
    "time_tag",
]

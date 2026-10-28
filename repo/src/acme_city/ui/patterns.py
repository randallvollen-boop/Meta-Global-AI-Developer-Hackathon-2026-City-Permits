"""Shared interface patterns: information popover, help and the detail flyout.

Three patterns are built once and every screen uses them:

* the information popover reads its text from ``config/ui_glossary.json``;
* the help flyout reads one entry per screen from the same file;
* the detail flyout is addressed by ``?detail=<kind>:<id>``.  A *kind* is
  registered here with a resolver, and the resolver is the only code that
  reads the data.  The registry checks the grants of the kind first, the
  resolver then checks the record, and a refusal carries no data.

The page and the fragment route share one resolution path, so the server
renders the same permission checks for a page opened with ``?detail=`` and
for the fragment the script fetches.
"""
# REQUIRES: UX-01, UX-02, SEC-01

from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from fastapi import Request
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.fixtures.loader import REPO_ROOT

#: The glossary and help configuration.
GLOSSARY_PATH = REPO_ROOT / "config" / "ui_glossary.json"

#: The query-string parameter that opens the detail flyout.
DETAIL_PARAM = "detail"

_KIND = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_ITEM = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")


# ------------------------------------------------------------------ glossary


@lru_cache(maxsize=1)
def _glossary() -> dict[str, Any]:
    return json.loads(Path(GLOSSARY_PATH).read_text(encoding="utf-8"))


def reload_glossary() -> None:
    """Drop the cached configuration (used by tests and by a config edit)."""
    _glossary.cache_clear()


def term(key: str) -> dict[str, str] | None:
    """Return the glossary entry of one information popover, or ``None``."""
    entry = _glossary().get("terms", {}).get(key)
    return dict(entry) if isinstance(entry, dict) else None


def term_keys() -> list[str]:
    """Return every glossary key."""
    return sorted(_glossary().get("terms", {}))


def screen_help(screen: str) -> dict[str, Any] | None:
    """Return the help entry of one screen, or ``None``."""
    entry = _glossary().get("screens", {}).get(screen)
    return dict(entry) if isinstance(entry, dict) else None


def help_screens() -> list[str]:
    """Return every screen key that has a help entry."""
    return sorted(_glossary().get("screens", {}))


_uid = itertools.count(1)


def next_uid() -> int:
    """Return a number that keeps the ids of repeated popovers unique."""
    return next(_uid)


# ----------------------------------------------------------------- detail view


@dataclass(frozen=True)
class Row:
    """One label and value of a detail section.

    ``info`` is an optional glossary key rendered as an information popover
    next to the label.  ``mono`` sets the value in a monospace face (ids and
    hashes).
    """

    label: str
    value: str
    mono: bool = False
    info: str | None = None


@dataclass(frozen=True)
class Section:
    """A headed group of rows, or of plain lines."""

    heading: str
    rows: tuple[Row, ...] = ()
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class DetailView:
    """What a resolver returns: plain data, rendered by ``_ui.html``."""

    title: str
    subtitle: str = ""
    sections: tuple[Section, ...] = ()
    links: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class DetailContext:
    """What a resolver may read.  The actor comes from the server session."""

    session: Session
    actor: ActorContext
    request: Request


class DetailForbidden(Exception):
    """Raised by a resolver when the persona may not read the record."""


Resolver = Callable[[DetailContext, str], "DetailView | None"]


@dataclass(frozen=True)
class DetailKind:
    kind: str
    label: str
    resolver: Resolver
    any_grant: tuple[tuple[str, str | None], ...]
    public: bool


_REGISTRY: dict[str, DetailKind] = {}


def register_detail(
    kind: str,
    resolver: Resolver,
    *,
    label: str,
    any_grant: tuple[tuple[str, str | None], ...] = (),
    public: bool = False,
) -> None:
    """Register one detail kind.

    Args:
        kind: Lower-case key used in ``?detail=<kind>:<id>``.
        resolver: ``resolver(ctx, item_id)`` returns a ``DetailView``, ``None``
            when the record does not exist or is outside the persona's scope,
            or raises ``DetailForbidden``.  It does the record-level checks.
        label: Short name shown in the refusal text.
        any_grant: ``(permission, domain_id)`` pairs, the same predicate as
            ``view_models.SCREEN_PERMISSIONS``; the persona must hold one.
        public: ``True`` only for a kind that reads no governed record (help).
            A kind with neither grants nor ``public`` is refused at
            registration, so a new kind cannot be added without a decision.
    """
    if not _KIND.match(kind):
        raise ValueError(f"invalid detail kind {kind!r}")
    if not any_grant and not public:
        raise ValueError(f"detail kind {kind!r} needs any_grant or public=True")
    _REGISTRY[kind] = DetailKind(kind, label, resolver, tuple(any_grant), public)


def unregister_detail(kind: str) -> None:
    """Remove a kind (used by tests that register a temporary one)."""
    _REGISTRY.pop(kind, None)


def registered_kinds() -> list[str]:
    return sorted(_REGISTRY)


def parse_detail(raw: str | None) -> tuple[str, str] | None:
    """Split ``kind:id``; ``None`` when it is not well formed."""
    if not raw or ":" not in raw:
        return None
    kind, item = raw.split(":", 1)
    if not _KIND.match(kind) or not _ITEM.match(item):
        return None
    return kind, item


@dataclass(frozen=True)
class Resolution:
    """The outcome of resolving one detail address.

    ``status`` is 200, 403, 404 or 401.  ``view`` is set only for 200: a
    refusal never carries data.
    """

    status: int
    kind: str
    item_id: str
    view: DetailView | None = None
    message: str = ""


_MESSAGES = {
    401: "Choose a persona to see this detail.",
    403: "Your persona may not see this detail.",
    404: "That detail is not available.",
}


def resolve(
    request: Request, session: Session, actor: ActorContext | None, kind: str, item_id: str
) -> Resolution:
    """Resolve one detail address under the persona's grants."""
    from acme_city.ui import view_models

    def refuse(status: int) -> Resolution:
        return Resolution(status, kind, item_id, None, _MESSAGES[status])

    entry = _REGISTRY.get(kind)
    if entry is None or not _ITEM.match(item_id):
        return refuse(404)
    if actor is None:
        return refuse(401)
    if not entry.public and not any(
        view_models.holds_grant(session, actor, permission, domain)
        for permission, domain in entry.any_grant
    ):
        return refuse(403)
    try:
        view = entry.resolver(DetailContext(session, actor, request), item_id)
    except DetailForbidden:
        return refuse(403)
    if view is None:
        return refuse(404)
    return Resolution(200, kind, item_id, view)


def current_query(request: Request, **changes: str | None) -> str:
    """Return the request path with the query changed (``None`` removes a key)."""
    pairs = [(k, v) for k, v in request.query_params.multi_items() if k not in changes]
    pairs.extend((k, v) for k, v in changes.items() if v is not None)
    query = urlencode(pairs, safe=":")
    return f"{request.url.path}?{query}" if query else request.url.path


def detail_href(request: Request, kind: str, item_id: str) -> str:
    """Return the address of the current page with one detail open."""
    return current_query(request, **{DETAIL_PARAM: f"{kind}:{item_id}"})


def drawer_state(
    request: Request, session: Session, actor: ActorContext | None
) -> dict[str, Any] | None:
    """Return the drawer state of a page request, or ``None`` when closed.

    The content is resolved here, on the server, under the same checks as the
    fragment route.  A refused detail renders a refusal and no data.
    """
    parsed = parse_detail(request.query_params.get(DETAIL_PARAM))
    if parsed is None:
        return None
    outcome = resolve(request, session, actor, *parsed)
    return {
        "status": outcome.status,
        "kind": outcome.kind,
        "id": outcome.item_id,
        "view": outcome.view,
        "message": outcome.message,
        "close_href": current_query(request, **{DETAIL_PARAM: None}),
    }


def install(templates: Any) -> None:
    """Add the template globals the macros use."""
    templates.env.globals.update(
        ui_term=term,
        ui_screen_help=screen_help,
        ui_detail_href=detail_href,
        ui_uid=next_uid,
    )


__all__ = [
    "DETAIL_PARAM",
    "DetailContext",
    "DetailForbidden",
    "DetailView",
    "Resolution",
    "Row",
    "Section",
    "detail_href",
    "drawer_state",
    "install",
    "parse_detail",
    "register_detail",
    "resolve",
    "screen_help",
    "term",
]

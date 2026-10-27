"""Stable identifier primitives.

Generated identifiers are prefixed and UUID-compatible so that a display number
is never mistaken for an identity key.  Seeded fixture identifiers are stable
literal strings authored in the committed fixture files.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable

_PREFIX_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_GENERATED_RE = re.compile(r"^(?P<prefix>[a-z][a-z0-9_]{0,31})_(?P<hex>[0-9a-f]{32})$")

#: Prefixes used by the application.  Keeping them in one place makes it easy
#: to see which object families exist without scanning the schema.
ID_PREFIXES: frozenset[str] = frozenset(
    {
        "actor",
        "act",
        "agentstep",
        "addr",
        "alloc",
        "app",
        "assess",
        "assign",
        "audit",
        "authpol",
        "canonical",
        "case",
        "cmd",
        "cons",
        "contact",
        "cred",
        "crosswalk",
        "decision",
        "delivery",
        "dep",
        "doc",
        "domain",
        "err",
        "eval",
        "evidence",
        "facct",
        "fee",
        "inrun",
        "issue",
        "line",
        "obs",
        "obsv",
        "outbox",
        "party",
        "permittype",
        "permit",
        "proposal",
        "prov",
        "queue",
        "recon",
        "rec",
        "rev",
        "rule",
        "rulever",
        "sched",
        "session",
        "snap",
        "srcsys",
        "task",
        "contract",
        "alias",
        "parcel",
        "payment",
        "payeve",
        "perm",
        "site",
        "appparty",
        "modelrun",
        "modelin",
        "modelout",
        "impact",
    }
)


def new_id(prefix: str, *, uuid_factory: Callable[[], uuid.UUID] | None = None) -> str:
    """Return a new prefixed, UUID-compatible identifier.

    The result has the shape ``<prefix>_<32 hex digits>``.  The hexadecimal
    part is a valid UUID in compact form, so callers may reconstruct the UUID
    when a standard identifier is required.
    """
    normalized = prefix.strip().lower()
    if not _PREFIX_RE.match(normalized):
        raise ValueError(f"invalid id prefix: {prefix!r}")
    factory = uuid_factory or uuid.uuid4
    return f"{normalized}_{factory().hex}"


def is_generated_id(value: str) -> bool:
    """Return whether ``value`` was produced by :func:`new_id`."""
    return _GENERATED_RE.match(value) is not None


def id_prefix(value: str) -> str:
    """Return the prefix of a generated identifier."""
    match = _GENERATED_RE.match(value)
    if match is None:
        raise ValueError(f"not a generated identifier: {value!r}")
    return match.group("prefix")


def uuid_from_id(value: str) -> uuid.UUID:
    """Return the UUID carried by a generated identifier."""
    match = _GENERATED_RE.match(value)
    if match is None:
        raise ValueError(f"not a generated identifier: {value!r}")
    return uuid.UUID(hex=match.group("hex"))


__all__ = ["ID_PREFIXES", "id_prefix", "is_generated_id", "new_id", "uuid_from_id"]

"""The resolved actor and the resource an action touches.

``ActorContext`` is derived from the server-held session and the persisted
grants.  A client never supplies any part of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActorContext:
    """Who is acting, and what the server says they may act on."""

    actor_id: str
    role_ids: frozenset[str] = frozenset()
    domain_scope: frozenset[str] = frozenset()
    record_scope: frozenset[str] = frozenset()
    session_id: str | None = None
    active: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "role_ids": sorted(self.role_ids),
            "domain_scope": sorted(self.domain_scope),
            "record_scope": sorted(self.record_scope),
        }


@dataclass(frozen=True)
class ResourceContext:
    """The governed record an action touches."""

    domain_id: str | None = None
    record_ids: tuple[str, ...] = ()
    record_type: str | None = None
    record_scope: frozenset[str] = field(default_factory=frozenset)

    def to_dict(self) -> dict[str, object]:
        return {
            "domain_id": self.domain_id,
            "record_ids": list(self.record_ids),
            "record_type": self.record_type,
        }


__all__ = ["ActorContext", "ResourceContext"]

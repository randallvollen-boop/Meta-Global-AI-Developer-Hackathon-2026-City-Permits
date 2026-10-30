"""Permission resolution.

Permissions come from persisted grants.  A role label is recorded for
attribution, but it never authorizes an action on its own, and a value that
arrives in a request body is never consulted.
"""
# REQUIRES: SEC-01, SEC-02, SEC-03
# Permission resolution reads persisted grants. A role label, a client-supplied role
# field or a screen never authorizes an action, and a domain or record scope narrows
# every grant.


from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.core.clock import utc_now
from acme_city.core.errors import PermissionDeniedError
from acme_city.persistence.models import governance


def _managed_agent_grants(session: Session, actor_id: str) -> tuple[Grant, ...]:
    """Return the operational bundle enabled for an actor's entitled roles."""
    from acme_city.agents.bundle import AGENT_OPERATION_DOMAINS, AGENT_OPERATIONS
    from acme_city.persistence.models import agent_ops

    entitled = session.execute(
        select(governance.ActorRole.role_id)
        .join(
            agent_ops.AgentRoleEntitlement,
            agent_ops.AgentRoleEntitlement.role_id == governance.ActorRole.role_id,
        )
        .where(
            governance.ActorRole.actor_id == actor_id,
            agent_ops.AgentRoleEntitlement.can_run_agents.is_(True),
        )
    ).first()
    if entitled is None:
        return ()
    grants: list[Grant] = []
    for action in sorted(AGENT_OPERATIONS):
        grants.append(
            Grant(
                permission_id=action,
                action=action,
                domain_id=AGENT_OPERATION_DOMAINS[action],
                record_scope=frozenset(),
                sensitive=False,
            )
        )
    return tuple(grants)


@dataclass(frozen=True)
class Grant:
    """One persisted grant of one permission to one actor."""

    permission_id: str
    action: str
    domain_id: str | None
    record_scope: frozenset[str]
    sensitive: bool

    def covers_domain(self, domain_id: str | None) -> bool:
        if self.domain_id is None:
            return True
        if domain_id is None:
            return False
        return self.domain_id == domain_id

    def covers_records(self, record_ids: tuple[str, ...]) -> bool:
        if not self.record_scope:
            return True
        return any(record_id in self.record_scope for record_id in record_ids)


class PermissionResolver:
    """Resolves the effective permissions of an actor."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()

    def grants_for(self, actor_id: str) -> tuple[Grant, ...]:
        """Return the grants that are effective for ``actor_id`` right now."""
        rows = self._session.execute(
            select(
                governance.ActorGrant.permission_id,
                governance.ActorGrant.domain_id,
                governance.ActorGrant.record_scope,
                governance.Permission.action,
                governance.Permission.sensitive,
            )
            .join(
                governance.Permission,
                governance.Permission.permission_id == governance.ActorGrant.permission_id,
            )
            .join(governance.Actor, governance.Actor.actor_id == governance.ActorGrant.actor_id)
            .where(
                governance.ActorGrant.actor_id == actor_id,
                governance.Actor.active.is_(True),
                governance.ActorGrant.effective_from <= self._now,
                (
                    governance.ActorGrant.effective_to.is_(None)
                    | (governance.ActorGrant.effective_to > self._now)
                ),
            )
        ).all()
        persisted = tuple(
            Grant(
                permission_id=permission_id,
                action=action,
                domain_id=domain_id,
                record_scope=frozenset(record_scope or ()),
                sensitive=bool(sensitive),
            )
            for permission_id, domain_id, record_scope, action, sensitive in rows
        )
        # The saved role entitlement is an explicit managed grant bundle.  It
        # applies to existing people and users added later without trusting a
        # role string from the request.
        managed = _managed_agent_grants(self._session, actor_id)
        if not managed:
            return persisted
        existing = {(grant.action, grant.domain_id) for grant in persisted}
        return persisted + tuple(
            grant for grant in managed if (grant.action, grant.domain_id) not in existing
        )

    def permissions_for(self, actor_id: str) -> frozenset[str]:
        """Return the permission identifiers the actor currently holds."""
        return frozenset(grant.permission_id for grant in self.grants_for(actor_id))

    def allows(self, actor: ActorContext, action: str, resource: ResourceContext) -> bool:
        """Return whether the actor may perform ``action`` on ``resource``."""
        if not actor.active:
            return False
        for grant in self.grants_for(actor.actor_id):
            if grant.action != action:
                continue
            if not grant.covers_domain(resource.domain_id):
                continue
            if not grant.covers_records(resource.record_ids):
                continue
            return True
        return False

    def authorize(self, actor: ActorContext, action: str, resource: ResourceContext) -> None:
        """Raise :class:`PermissionDeniedError` when the action is not allowed."""
        if self.allows(actor, action, resource):
            return
        raise PermissionDeniedError(
            f"actor {actor.actor_id} may not perform {action}",
            actor_id=actor.actor_id,
            action=action,
            domain_id=resource.domain_id,
        )


def authorize(
    actor: ActorContext, action: str, resource: ResourceContext, resolver: PermissionResolver
) -> None:
    """Raise :class:`PermissionDeniedError` when the action is not allowed.

    This is the module-level entry point for the authorization check.  It
    always consults the persisted grants; a role label or a client-supplied
    field never authorizes an action.
    """
    resolver.authorize(actor, action, resource)


__all__ = ["Grant", "PermissionResolver", "authorize"]

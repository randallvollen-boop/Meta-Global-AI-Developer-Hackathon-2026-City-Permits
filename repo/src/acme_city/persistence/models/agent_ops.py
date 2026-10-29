"""Agent operations models of the agent operator lane.

The lane adds its tables here without editing the models package.  The
``agent_role_entitlements`` table is the authoritative record of which role
may wake and run the agents: the seeded grants of a persona are the default,
and this table is what the City Administrator changes when it grants or
revokes that role.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import (
    Base,
    CorrelationMixin,
    CreatedAtMixin,
    IdMixin,
    VersionMixin,
)
from acme_city.persistence.types import UTCDateTime


class AgentRoleEntitlement(IdMixin, CorrelationMixin, CreatedAtMixin, VersionMixin, Base):
    """The entitlement of one role to wake and run the agents.

    One row per role.  ``can_run_agents`` is the single source of truth for
    the agent operation grants of every actor of that role, so a role change
    reaches the people who already hold the role and the people who receive
    it later.
    """

    __tablename__ = "agent_role_entitlements"

    role_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    can_run_agents: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    changed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


__all__ = ["AgentRoleEntitlement"]

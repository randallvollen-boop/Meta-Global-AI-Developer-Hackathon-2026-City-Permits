"""Governance, identity and configuration objects.

Ownership is resolved from effective-dated assignments rather than copied onto
each record.  Steward queues carry an active primary, a delegate, an escalation
owner and a configurable response target.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import Base, CreatedAtMixin, IdMixin, VersionMixin
from acme_city.persistence.types import UTCDateTime


class Role(IdMixin, Base):
    """A role label with an explicit permission boundary."""

    __tablename__ = "roles"

    role_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    boundary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Permission(IdMixin, Base):
    """An action that may be granted explicitly to an actor."""

    __tablename__ = "permissions"

    permission_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    action: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RolePermission(IdMixin, Base):
    """The default permission set of a role.

    A role label never authorizes by itself: an actor needs an explicit grant.
    """

    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[str] = mapped_column(
        String(96), ForeignKey("permissions.permission_id", ondelete="CASCADE"), nullable=False
    )
    __table_args__ = (UniqueConstraint("role_id", "permission_id"),)


class Actor(IdMixin, CreatedAtMixin, Base):
    """A fictional demo actor that can hold a server-held session."""

    __tablename__ = "actors"

    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fictional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    selectable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    deactivated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The department a person works in.  It is display information only: it
    #: never grants anything.
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: The persona role a user follows.  The grants of that role are copied
    #: onto the user when the user is created; the label itself never
    #: authorizes an action.
    persona_role: Mapped[str | None] = mapped_column(String(48), nullable=True)


class ActorRole(IdMixin, Base):
    """The roles an actor holds, used for attribution and display."""

    __tablename__ = "actor_roles"

    actor_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("actors.actor_id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("roles.role_id", ondelete="CASCADE"), nullable=False
    )
    __table_args__ = (UniqueConstraint("actor_id", "role_id"),)


class ActorGrant(IdMixin, CreatedAtMixin, Base):
    """An explicit, scope-limited permission granted to an actor.

    ``domain_id`` limits the grant to one governed domain.  ``record_scope``
    lists the specific record identifiers the grant covers; an empty list means
    every record in the domain scope.
    """

    __tablename__ = "actor_grants"

    actor_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("actors.actor_id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_id: Mapped[str] = mapped_column(
        String(96), ForeignKey("permissions.permission_id", ondelete="CASCADE"), nullable=False
    )
    domain_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    record_scope: Mapped[list[Any]] = mapped_column(JSON, nullable=True)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    granted_by_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="seed_config")


class Domain(IdMixin, VersionMixin, Base):
    """A governed domain with its accountable owner, steward queue and custodian."""

    __tablename__ = "domains"

    domain_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    accountable_owner_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    steward_queue_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    system_custodian_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_source_system_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_dataset_key: Mapped[str | None] = mapped_column(String(96), nullable=True)
    owner_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    __table_args__ = (
        CheckConstraint(
            "steward_queue_id IS NULL OR accountable_owner_actor_id IS NOT NULL",
            name="owner_present_when_queue_bound",
        ),
    )


class StewardQueue(IdMixin, VersionMixin, Base):
    """A stewardship queue with primary, delegate, escalation and a response target."""

    __tablename__ = "steward_queues"

    queue_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    domain_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("domains.domain_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    primary_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delegate_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    escalation_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cross_domain_escalation_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_review_target_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_review_target_unit: Mapped[str] = mapped_column(
        String(32), nullable=False, default="business_day"
    )
    first_review_target_calendar_basis: Mapped[str] = mapped_column(
        String(64), nullable=False, default="configured_demo_calendar"
    )
    configurable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    service_promise: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Assignment(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """An effective-dated responsibility assignment.

    Assignments are never deleted when they end: ``effective_to`` is set and a
    later assignment supersedes it, so historical attribution survives.
    """

    __tablename__ = "assignments"

    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    responsibility: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    queue_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    supersedes_assignment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    superseded_by_assignment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="seed_config")
    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('domain', 'dataset')", name="subject_type_allowed"
        ),
        CheckConstraint(
            "responsibility IN ('owner', 'steward', 'delegate', 'custodian', 'escalation')",
            name="responsibility_allowed",
        ),
    )


class SourceContract(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """The registration of a source dataset.

    A dataset that lacks a required binding may stage raw snapshots but cannot
    publish trusted facts.
    """

    __tablename__ = "source_contracts"

    contract_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    source_system_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dataset_key: Mapped[str] = mapped_column(String(96), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    domain_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accountable_owner_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    steward_queue_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    system_custodian_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authority_policy_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    correction_route: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_key_fields: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    required_fields: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    allowed_values: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    date_meanings: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    field_classes: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    registration_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="complete"
    )
    registered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("source_system_id", "dataset_key"),
        CheckConstraint(
            "registration_state IN ('complete', 'incomplete')", name="registration_state_allowed"
        ),
    )


class AuthorityPolicy(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """Field-level authority: which source owns a field group and where it changes."""

    __tablename__ = "authority_policies"

    policy_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    field_group: Mapped[str] = mapped_column(String(200), nullable=False)
    domain_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    authoritative_source_system_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authoritative_component_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authoritative_dataset_key: Mapped[str | None] = mapped_column(String(96), nullable=True)
    change_destination: Mapped[str] = mapped_column(String(240), nullable=False)
    user_action: Mapped[str] = mapped_column(String(240), nullable=False)
    requires_source_ack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    decision_relevant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed_demo_default")
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    approver_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authoritative_action_roles: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Session(IdMixin, CreatedAtMixin, Base):
    """A server-held session.

    The browser holds a signed cookie that carries a random session identifier.
    The identifier itself is meaningless without the server-side record, so a
    client-supplied role or actor field can never authorize an action.
    """

    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    actor_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("actors.actor_id", ondelete="CASCADE"), nullable=False, index=True
    )
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    user_agent_hint: Mapped[str | None] = mapped_column(String(240), nullable=True)


class DemoEnvironment(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """Marks a database as the disposable fictional demonstration environment.

    The destructive reset only accepts a database whose marker says
    ``fictional_demo`` is true.
    """

    __tablename__ = "demo_environment"

    environment_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    fictional_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fixture_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False, default="local demo")
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


__all__ = [
    "Actor",
    "ActorGrant",
    "ActorRole",
    "Assignment",
    "AuthorityPolicy",
    "DemoEnvironment",
    "Domain",
    "Permission",
    "Role",
    "RolePermission",
    "Session",
    "SourceContract",
    "StewardQueue",
]

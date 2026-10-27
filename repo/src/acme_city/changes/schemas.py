"""Command and view models for the change lifecycle.

The state names are the ones the correction paths declare: a factual change
travels to the source and comes back acknowledged, a registry change travels
through the registry and is committed there.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChangeModel(BaseModel):
    """A model that ignores unknown request fields.

    A client-supplied actor, role or permission field is ignored: the server
    resolves the actor and its grants.
    """

    model_config = ConfigDict(extra="ignore")


class ChangeRequestCommand(ChangeModel):
    """Ask for a correction of a source fact or an identity link.

    A request never changes a source fact, a link, a decision, an amount or a
    published rule.  It creates the work and routes it to the responsible
    steward.
    """

    target_type: str
    target_id: str
    title: str
    reason: str
    change_kind: str = "factual"
    proposed_value: dict[str, Any] = Field(default_factory=dict)
    old_value: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    domain_id: str | None = None
    destination: str | None = None
    assignee_actor_id: str | None = None
    approver_actor_id: str | None = None
    expected_version: int | None = None
    scenario_id: str | None = None


class ChangeTransitionCommand(ChangeModel):
    """Move a change case to the next permitted state.

    The case may be named in the path; the identifier in the body is only
    used when the caller sends one.
    """

    change_case_id: str = ""
    to_status: str
    expected_version: int | None = None
    reason: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    approver_actor_id: str | None = None
    assignee_actor_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ImpactPreviewCommand(ChangeModel):
    """Ask which records a change would affect."""

    target_type: str
    target_id: str
    change_case_id: str | None = None
    domain_id: str | None = None


class SourceCommandView(ChangeModel):
    """One command that was sent to a source."""

    source_command_id: str
    source_system_id: str
    operation: str
    expected_source_version: str | None = None
    accepted_source_version: str | None = None
    retry_key: str
    status: str = "pending"
    response: dict[str, Any] | None = None


class ReviewTaskView(ChangeModel):
    """One assigned review task."""

    task_id: str
    task_type: str
    target_type: str | None = None
    target_id: str | None = None
    assignee_actor_id: str | None = None
    status: str = "open"
    deduplication_key: str


class ChangeDependencyView(ChangeModel):
    """One consumer that depends on the changed record."""

    dependency_id: str
    consumer_type: str
    consumer_id: str
    invalidation_state: str = "affected"
    task_id: str | None = None


class ChangeCaseView(ChangeModel):
    """One change case and everything the server knows about it."""

    change_case_id: str
    target_type: str
    target_id: str
    change_kind: str = "factual"
    title: str
    status: str = "requested"
    old_value: dict[str, Any] = Field(default_factory=dict)
    proposed_value: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    requester_actor_id: str | None = None
    assignee_actor_id: str | None = None
    approver_actor_id: str | None = None
    destination: str | None = None
    expected_version: int | None = None
    due_at: datetime | None = None
    version: int = 1
    scenario_id: str | None = None
    created_at: datetime
    allowed_transitions: list[str] = Field(default_factory=list)
    source_commands: list[SourceCommandView] = Field(default_factory=list)
    dependencies: list[ChangeDependencyView] = Field(default_factory=list)
    tasks: list[ReviewTaskView] = Field(default_factory=list)


class ImpactPreview(ChangeModel):
    """What a change would affect before it is approved."""

    target_type: str
    target_id: str
    change_case_id: str | None = None
    applications: list[str] = Field(default_factory=list)
    evaluations: list[str] = Field(default_factory=list)
    assessments: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    permits: list[str] = Field(default_factory=list)
    affected_applications: list[str] = Field(default_factory=list)
    rechecks: list[str] = Field(default_factory=list)
    total_affected: int = 0


class DispatchSummary(ChangeModel):
    """What one dispatch run did.

    ``dispatched`` counts the commands that were sent to a source,
    ``acknowledged`` the commands a source accepted, and ``published`` the
    deliveries a consumer acknowledged.
    """

    dispatched: int = 0
    acknowledged: int = 0
    published: int = 0
    rejected: int = 0
    timed_out: int = 0
    conflicts: int = 0
    skipped: int = 0
    late: int = 0
    delivery_ids: list[str] = Field(default_factory=list)
    command_ids: list[str] = Field(default_factory=list)
    change_case_ids: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)


__all__ = [
    "ChangeCaseView",
    "ChangeDependencyView",
    "ChangeModel",
    "ChangeRequestCommand",
    "ChangeTransitionCommand",
    "DispatchSummary",
    "ImpactPreview",
    "ImpactPreviewCommand",
    "ReviewTaskView",
    "SourceCommandView",
]

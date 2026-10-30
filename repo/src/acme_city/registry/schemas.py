"""Command and view models for the registry.

A proposal records the evidence it was built from.  The score it carries is
labeled uncalibrated: no evidence in this demonstration proves that the score
is calibrated against a measured outcome.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: The decisions a steward may record on a source-to-canonical link.
DECISION_OUTCOMES: tuple[str, ...] = ("approve", "reject", "no_match", "correct", "remove")

#: The label every proposal score carries until calibration is proven.
UNCALIBRATED_SCORE_LABEL = "uncalibrated_heuristic"


class RegistryModel(BaseModel):
    """A model that ignores unknown request fields.

    A client-supplied actor, role, permission or score field is ignored: the
    server resolves the actor, and the score belongs to the server.
    """

    model_config = ConfigDict(extra="ignore")


class MatchEvidenceView(RegistryModel):
    """One piece of comparison evidence behind a proposal."""

    field: str
    source_snapshot_id: str | None = None
    raw_value: Any = None
    normalized_value: Any = None
    direction: str = "supporting"
    method: str = ""
    detail: str = ""


class MatchProposalCommand(RegistryModel):
    """Ask the registry for candidate links of one source record."""

    source_system_id: str
    dataset_key: str
    source_record_id: str
    entity_type: str | None = None
    candidate_entity_ids: list[str] = Field(default_factory=list)
    notes: str | None = None
    scenario_id: str | None = None


class MatchProposalView(RegistryModel):
    """A proposed link and the evidence it was built from."""

    proposal_id: str
    source_snapshot_id: str
    source_system_id: str
    source_dataset_key: str
    source_record_id: str
    entity_id: str | None = None
    entity_type: str = "party"
    disposition: str = "unresolved"
    method: str = "deterministic"
    proposal_score: float | None = None
    score_is_calibrated: bool = False
    score_label: str = UNCALIBRATED_SCORE_LABEL
    candidate_ids: list[str] = Field(default_factory=list)
    compared_fields: list[str] = Field(default_factory=list)
    supporting_evidence: list[MatchEvidenceView] = Field(default_factory=list)
    conflicting_evidence: list[MatchEvidenceView] = Field(default_factory=list)
    created_by_actor_id: str | None = None
    scenario_id: str | None = None
    created_at: datetime


class MatchDecisionCommand(RegistryModel):
    """Record a steward decision on a source-to-canonical link."""

    decision: str
    reason: str
    crosswalk_id: str | None = None
    source_system_id: str | None = None
    dataset_key: str | None = None
    source_record_id: str | None = None
    entity_id: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    expected_version: int | None = None
    scenario_id: str | None = None


class AutomaticLinkCommand(RegistryModel):
    """Ask the registry to apply one eligible link to a canonical entity."""

    source_system_id: str
    dataset_key: str
    source_record_id: str
    entity_id: str
    reason: str = ""


class AutomaticApplicationView(RegistryModel):
    """One link the service applied and the evidence of that decision.

    The view names the service that applied the link and the steward whose
    policy authorized it, so the trail never shows an unnamed decision.
    """

    application_id: str
    evaluation_id: str
    crosswalk_id: str | None = None
    entity_id: str
    entity_type: str = "party"
    source_system_id: str
    source_dataset_key: str | None = None
    source_record_id: str
    status: str = "applied"
    score: float | None = None
    score_scale: str = ""
    decision: str = ""
    policy_version: int | None = None
    applied_by_actor_id: str
    authorized_by_actor_id: str | None = None
    applied_at: datetime
    reviewed_by_actor_id: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    reasons: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)


class CrosswalkView(RegistryModel):

    crosswalk_id: str
    entity_id: str
    entity_type: str = "party"
    source_system_id: str
    source_dataset_key: str | None = None
    source_record_id: str
    link_status: str = "proposed"
    decision: str | None = None
    decision_actor_id: str | None = None
    decided_at: datetime | None = None
    expected_version: int | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    superseded_by_crosswalk_id: str | None = None
    supersedes_crosswalk_id: str | None = None
    version: int = 1
    scenario_id: str | None = None


class TrustedFieldView(RegistryModel):
    """One displayed value and where it came from."""

    attribute_path: str
    value: Any = None
    raw_value: Any = None
    source_system_id: str | None = None
    source_dataset_key: str | None = None
    source_record_id: str | None = None
    source_snapshot_id: str | None = None
    authority_policy_id: str | None = None
    state: str = "absent"
    reasons: list[str] = Field(default_factory=list)


class TrustedView(RegistryModel):
    """The trusted view of one canonical entity."""

    entity_id: str
    entity_type: str = "party"
    label: str | None = None
    fields: list[TrustedFieldView] = Field(default_factory=list)
    disagreements: list[TrustedFieldView] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    crosswalks: list[CrosswalkView] = Field(default_factory=list)
    generated_at: datetime


__all__ = [
    "AutomaticApplicationView",
    "AutomaticLinkCommand",
    "CrosswalkView",
    "DECISION_OUTCOMES",
    "MatchDecisionCommand",
    "MatchEvidenceView",
    "MatchProposalCommand",
    "MatchProposalView",
    "RegistryModel",
    "TrustedFieldView",
    "TrustedView",
    "UNCALIBRATED_SCORE_LABEL",
]

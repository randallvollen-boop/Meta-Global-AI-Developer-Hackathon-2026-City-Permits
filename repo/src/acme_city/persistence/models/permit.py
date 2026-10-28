"""Permit workflow objects.

The applicant profile, the submitted application, the review decision and the
issued permit are separate records.  Approval and issuance are separate
authorized actions and an issued snapshot is never rewritten in place.
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
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import Base, CorrelationMixin, CreatedAtMixin, IdMixin, VersionMixin
from acme_city.persistence.types import UTCDateTime


class PermitType(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """One fictional permit-type configuration.

    A type names its review area, its process category (simple, with plans or
    formal review), whether the type is discretionary, the fields and the
    documents it requires and the fee schedule that applies to it.
    """

    __tablename__ = "permit_types"

    permit_type_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    review_route: Mapped[str] = mapped_column(String(160), nullable=False)
    required_fields: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    required_documents: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    icon_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("permit_type_icons.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    #: The review area the intake router sends a ready case to.
    review_area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: ``simple``, ``with_plans`` or ``formal_review``.
    process_category: Mapped[str | None] = mapped_column(String(48), nullable=True)
    #: A discretionary type is always held for a person or a board.
    discretionary: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The fee schedule key that applies to this type.
    fee_schedule_key: Mapped[str | None] = mapped_column(String(96), nullable=True)


class PermitTypeIcon(IdMixin, CreatedAtMixin, Base):
    """One icon image for a permit type: a seeded asset or a saved generation.

    A generated candidate stays pending (``is_current`` false) until an
    administrator saves it; saving flips the previous current icon off.
    The image bytes live in the database so the icon survives with the
    record it decorates; the type row points at its current icon.
    """

    __tablename__ = "permit_type_icons"

    permit_type_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("permit_types.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="seed")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (
        CheckConstraint("source IN ('seed', 'generated')", name="source_allowed"),
    )


class Application(IdMixin, VersionMixin, CorrelationMixin, CreatedAtMixin, Base):
    """A permit application.

    ``initial_submitted_at`` is immutable; each later submission records its
    own ``revision_submitted_at``.
    """

    __tablename__ = "applications"

    source_application_number: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    permit_type_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("permit_types.id", ondelete="RESTRICT"), nullable=False
    )
    initial_submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revision_submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_facts: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    applicant_party_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("parties.id", ondelete="SET NULL"), nullable=True
    )
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    #: The review area the intake router recorded for this case.  It is set
    #: once, when the case is routed, so that a later configuration change
    #: cannot move an already-submitted case.
    review_area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: The permit-type requirements that were in force when the case was
    #: received.  A later configuration change takes effect for new intake
    #: only; it never rewrites what an already-submitted case was measured
    #: against.
    requirements_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: The priority a person set on the case: ``normal`` or ``high``.  The
    #: intake agent records the priority the intake record carried; a Data
    #: Steward may change it.
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    #: The staff member the case is routed to.  This is routing metadata only:
    #: an owner gains no authority and never becomes a selectable persona.
    owner_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    #: The status the case held when it was archived, so a restore returns it
    #: to exactly that status.
    status_before_archive: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: When the case was archived, by whom, and why.
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    archived_by_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    archive_reason_code_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    archive_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'submitted', 'needs_information', 'revisions_requested', "
            "'ready_for_review', 'under_review', 'approved', 'denied', 'withdrawn', "
            "'issued', 'returned', 'archived')",
            name="status_allowed",
        ),
        CheckConstraint(
            "priority IN ('normal', 'high')",
            name="priority_allowed",
        ),
    )


class ApplicationRevision(IdMixin, CreatedAtMixin, Base):
    """An immutable submitted revision of an application."""

    __tablename__ = "application_revisions"

    application_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    submitted_by_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    date_basis: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ApplicationParty(IdMixin, CreatedAtMixin, Base):
    """A party in a role on an application."""

    __tablename__ = "application_parties"

    application_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    party_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("parties.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    party_role: Mapped[str] = mapped_column(String(48), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    authority_evidence_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)


class ApplicationSite(IdMixin, CreatedAtMixin, Base):
    """The site of an application, resolved against the official parcel record."""

    __tablename__ = "application_sites"

    application_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parcel_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("parcels.id", ondelete="SET NULL"), nullable=True
    )
    address_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unresolved")
    submitted_address_text: Mapped[str | None] = mapped_column(String(320), nullable=True)


class Document(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """A stored document version.  A label alone does not demonstrate reading."""

    __tablename__ = "documents"

    application_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    file_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    uploaded_by_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fictional_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: The scan-quality flags carried by the intake record, for example
    #: ``rotated``, ``low_res``, ``handwritten``, ``unreadable`` and
    #: ``duplicate_page``.
    quality: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)


class ApplicationFinding(IdMixin, CorrelationMixin, CreatedAtMixin, VersionMixin, Base):
    """One finding an intake or adjudication agent recorded on a case.

    A finding is evidence for a person, never a decision: it names what is
    wrong, the rule that applies, what the applicant must do and whether it
    blocks the case or only asks a person to look.

    A finding belongs to the application revision and the agent run that
    produced it.  It is ``current`` while it is the live statement about the
    case, ``resolved`` when a later run showed the condition is gone, and
    ``superseded`` when a later run or a resubmission replaced it.  The
    history is kept: a finding is never deleted.
    """

    __tablename__ = "application_findings"

    application_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    finding_type: Mapped[str] = mapped_column(String(48), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    rule: Mapped[str | None] = mapped_column(String(160), nullable=True)
    applicant_must: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="review")
    source_node: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_application_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: ``current``, ``resolved`` or ``superseded``.
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="current")
    #: The application revision the finding was recorded against.
    revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The agent run that recorded the finding.
    agent_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    #: When the finding stopped being the live statement about the case.
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: The waiver a Data Steward recorded against the finding.  A waiver
    #: never clears a deterministic rule failure or an identity, credential,
    #: finance or parcel-clearance check.
    waived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    waived_by_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    waiver_reason_code_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    waiver_reason_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    waiver_reason_code_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    waiver_reason_code_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    waiver_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "finding_type IN ('missing_field', 'missing_document', 'unreadable', "
            "'wrong_type', 'duplicate', 'conflict', 'fee', 'low_confidence_extraction', "
            "'judgment')",
            name="finding_type_allowed",
        ),
        CheckConstraint(
            "severity IN ('block', 'review')",
            name="severity_allowed",
        ),
        CheckConstraint(
            "state IN ('current', 'resolved', 'superseded')",
            name="state_allowed",
        ),
    )


class ApplicationComment(IdMixin, CorrelationMixin, CreatedAtMixin, VersionMixin, Base):
    """One comment a member of the City wrote on a case.

    A comment is either ``applicant`` visible or ``internal``.  The visibility
    is enforced by the server on every surface that shows a comment; it is
    never a client-supplied display choice.
    """

    __tablename__ = "application_comments"

    application_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: ``applicant`` or ``internal``.
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    author_actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('applicant', 'internal')",
            name="visibility_allowed",
        ),
    )


class ApplicationAction(IdMixin, CorrelationMixin, CreatedAtMixin, Base):
    """One recorded lifecycle action on an application.

    The action record is the snapshot of the case action: it names the actor,
    the time, the reason code as it was at that moment (code, label and
    version) and, when a comment was written, the comment it wrote.
    """

    __tablename__ = "application_actions"

    application_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The action name, for example ``return`` or ``request_revisions``.
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    #: The reason code as it was when the action was recorded.
    reason_code_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    reason_code_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reason_code_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The comment the action wrote, when it wrote one.
    comment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ExtractionObservation(IdMixin, CreatedAtMixin, Base):
    """A proposed value extracted from a document version."""

    __tablename__ = "extraction_observations"

    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    field_path: Mapped[str] = mapped_column(String(160), nullable=False)
    proposed_value: Mapped[str | None] = mapped_column(String(320), nullable=True)
    page_region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    evidence_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validation_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="proposed"
    )


class Evaluation(IdMixin, VersionMixin, CorrelationMixin, CreatedAtMixin, Base):
    """A versioned evaluation of an application revision."""

    __tablename__ = "evaluations"

    application_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("application_revisions.id", ondelete="SET NULL"), nullable=True
    )
    source_versions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    registry_versions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    rule_versions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    date_basis: Mapped[str | None] = mapped_column(String(64), nullable=True)
    results: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    performed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    performed_by_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="current")
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)


class Recommendation(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """An advisory recommendation.  It never populates a reviewer identity."""

    __tablename__ = "recommendations"

    application_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evaluation_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("evaluations.id", ondelete="SET NULL"), nullable=True
    )
    proposed_outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_refs: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    run_ref: Mapped[str | None] = mapped_column(String(96), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    #: Deterministic plain-language rationale citing each rule. Written by the
    #: recommendation agent step; a Muse summary, when present, never replaces it.
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Optional Muse explanatory summary. Advisory wording only; validated
    #: to carry no outcome different from ``proposed_outcome``.
    muse_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The model run that produced ``muse_summary``, when one ran.
    muse_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The conditions of approval the agent collected, when it proposed any.
    conditions: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    #: The person who confirmed the recommendation, and when.
    confirmed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: The person who reverted the recommendation, when and why.
    reverted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reverted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revert_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The decision that confirmed this recommendation, when it was confirmed.
    decision_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: A recommendation goes stale when a later revision of the case makes it
    #: advisory no longer.  A stale recommendation is never confirmed.
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Decision(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """An actual authorized reviewer decision."""

    __tablename__ = "decisions"

    application_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evaluation_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("evaluations.id", ondelete="SET NULL"), nullable=True
    )
    decision_type: Mapped[str] = mapped_column(String(48), nullable=False, default="review")
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_by_actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_versions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    rule_versions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="current")
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    #: The conditions of approval that were recorded with this decision.  The
    #: decision outcome vocabulary is unchanged; a confirmed recommendation
    #: with conditions is still an ``approved`` decision.
    conditions: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    #: The denial reason code as it was when the decision was recorded: the
    #: code, its label and its version.  The snapshot is kept so the history
    #: of a decision stays readable after a code is retired.
    reason_code_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    reason_code_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reason_code_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The waivers that applied to the case when the decision was recorded.
    waivers: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('approved', 'denied', 'modified', 'information_requested')",
            name="outcome_allowed",
        ),
    )


class ReasonCode(IdMixin, CorrelationMixin, CreatedAtMixin, VersionMixin, Base):
    """One ACME reason code.

    A reason code names why a case was returned, denied, waived, sent back
    for revisions or archived.  Its ``code_type`` says which of those uses it
    may serve, so a denial code can never be used to return a case.  The
    codes are configuration: an administrator adds and retires them, and
    every change is audited.  A retired code keeps its label and its history;
    it is never overwritten.
    """

    __tablename__ = "reason_codes"

    code: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The use the code serves: ``return``, ``denial``, ``waiver``,
    #: ``revision`` or ``archive``.
    code_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="return", server_default="return"
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    changed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "code_type IN ('return', 'denial', 'waiver', 'revision', 'archive')",
            name="code_type_allowed",
        ),
    )


class Permit(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """An issued simulated permit with an immutable snapshot."""

    __tablename__ = "permits"

    application_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("applications.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    decision_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("decisions.id", ondelete="RESTRICT"), nullable=False
    )
    permit_number: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="issued")
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issuance_command_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    issued_by_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fictional_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ImpactReview(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """A review opened because a change affects an existing decision or permit."""

    __tablename__ = "impact_reviews"

    target_type: Mapped[str] = mapped_column(String(48), nullable=False)
    target_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)


__all__ = [
    "Application",
    "ApplicationAction",
    "ApplicationComment",
    "ApplicationFinding",
    "ApplicationParty",
    "ApplicationRevision",
    "ApplicationSite",
    "Decision",
    "Document",
    "Evaluation",
    "ExtractionObservation",
    "ImpactReview",
    "Permit",
    "PermitType",
    "PermitTypeIcon",
    "ReasonCode",
    "Recommendation",
]

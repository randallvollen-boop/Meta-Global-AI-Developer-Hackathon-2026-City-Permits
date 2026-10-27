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
    """One of the five preserved fictional permit-type configurations."""

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
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'submitted', 'needs_information', 'ready_for_review', "
            "'under_review', 'approved', 'denied', 'withdrawn', 'issued')",
            name="status_allowed",
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
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('approved', 'denied', 'modified', 'information_requested')",
            name="outcome_allowed",
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
    "Recommendation",
]

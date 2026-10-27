"""Registry MDM objects.

Canonical identities are stable and typed.  Source-to-identity links are
versioned and every decision keeps its prior history, so a link can be
corrected without destroying the earlier decision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import Base, CorrelationMixin, CreatedAtMixin, IdMixin, VersionMixin
from acme_city.persistence.types import UTCDateTime


class CanonicalEntity(IdMixin, CreatedAtMixin, Base):
    """A typed canonical identity owned by the registry.

    The primary key column is ``id``; ``entity_type`` records the entity
    family so that crosswalks, provenance and proposals can reference any
    entity type without a schema change.
    """

    __tablename__ = "canonical_entities"

    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    label: Mapped[str | None] = mapped_column(String(240), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class Party(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """A person or organization: the reusable canonical identity."""

    __tablename__ = "parties"

    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("canonical_entities.entity_id", ondelete="RESTRICT"), nullable=False
    )
    party_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    source_system_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_record_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    __table_args__ = (
        CheckConstraint("party_type IN ('person', 'organization')", name="party_type_allowed"),
    )


class PartyAlias(IdMixin, CreatedAtMixin, Base):
    """An alias, former name or original spelling of a party."""

    __tablename__ = "party_aliases"

    party_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("parties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias_value: Mapped[str] = mapped_column(String(240), nullable=False)
    alias_type: Mapped[str] = mapped_column(String(48), nullable=False, default="alias")
    source_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class PartyContact(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """A contact point of a party.  A contact address is not a site address."""

    __tablename__ = "party_contacts"

    party_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("parties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_type: Mapped[str] = mapped_column(String(48), nullable=False)
    value: Mapped[str] = mapped_column(String(320), nullable=False)
    verification_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unverified"
    )
    source_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Parcel(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """An official GIS parcel."""

    __tablename__ = "parcels"

    parcel_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    jurisdiction_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_parcel_number: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    source_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Synthetic Local Government Information Model (LGIM) style attributes that
    # the simulated parcel feature service serves.  They live on the one parcel
    # table, so the registry and the simulated GIS never disagree.
    owner_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    use_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    use_description: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zoning_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subdivision: Mapped[str | None] = mapped_column(String(120), nullable=True)
    area_acres: Mapped[float | None] = mapped_column(Float, nullable=True)
    land_value_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    improvement_value_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tax_district: Mapped[str | None] = mapped_column(String(48), nullable=True)
    school_district: Mapped[str | None] = mapped_column(String(120), nullable=True)
    flood_zone: Mapped[str | None] = mapped_column(String(24), nullable=True)
    #: The outline as ``[[x, y], ...]`` rings on the local grid.
    geometry: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    #: Synthetic signals the simulated subscriber departments show.
    department_signals: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Address(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """An official structured address, including its unit distinction."""

    __tablename__ = "addresses"

    address_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    street_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    street_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    street_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    unit_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    unit_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    municipality: Mapped[str | None] = mapped_column(String(96), nullable=True)
    region: Mapped[str | None] = mapped_column(String(48), nullable=True)
    postcode: Mapped[str | None] = mapped_column(String(24), nullable=True)
    source_string: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    source_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The address point on the local grid of the simulated GIS.
    x: Mapped[float | None] = mapped_column(Float, nullable=True)
    y: Mapped[float | None] = mapped_column(Float, nullable=True)


class ParcelAddress(IdMixin, CreatedAtMixin, Base):
    """A parcel to address relationship with its own effective dates."""

    __tablename__ = "parcel_addresses"

    parcel_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("parcels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    address_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("addresses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relationship_type: Mapped[str] = mapped_column(String(48), nullable=False, default="official")
    effective_from: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)


class Credential(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """A business licence or a contractor registration.

    The two credential types belong to different source systems and keep their
    own issuer, number, status and validity dates.
    """

    __tablename__ = "credentials"

    credential_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    holder_party_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("parties.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    credential_type: Mapped[str] = mapped_column(String(48), nullable=False)
    issuing_authority_id: Mapped[str] = mapped_column(String(96), nullable=False)
    number: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    source_system_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_record_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    source_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)


class FinanceAccount(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """An ERP finance account and its relationship to a party.

    An account is not itself a party identity: legacy account identifiers are
    preserved and the link to a party is an explicit decision.
    """

    __tablename__ = "finance_accounts"

    account_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_account_id: Mapped[str] = mapped_column(String(96), nullable=False)
    source_system_id: Mapped[str] = mapped_column(String(64), nullable=False, default="erp_finance")
    party_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("parties.id", ondelete="SET NULL"), nullable=True, index=True
    )
    account_role: Mapped[str] = mapped_column(String(48), nullable=False, default="payer")
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    link_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unlinked")
    link_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)


class Crosswalk(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """A source-to-canonical link and the decision that produced it."""

    __tablename__ = "crosswalks"

    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("canonical_entities.entity_id", ondelete="RESTRICT"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source_system_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_dataset_key: Mapped[str | None] = mapped_column(String(96), nullable=True)
    source_record_id: Mapped[str] = mapped_column(String(128), nullable=False)
    link_status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    expected_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    superseded_by_crosswalk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    __table_args__ = (
        CheckConstraint(
            "link_status IN ('proposed', 'approved', 'rejected', 'superseded', 'removed', 'no_match')",
            name="link_status_allowed",
        ),
    )


class MatchProposal(IdMixin, CorrelationMixin, CreatedAtMixin, Base):
    """A proposed link produced by deterministic comparison or a model run."""

    __tablename__ = "match_proposals"

    source_snapshot_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("source_snapshots.source_snapshot_id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    compared_fields: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    supporting_evidence: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    conflicting_evidence: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    method: Mapped[str] = mapped_column(String(48), nullable=False, default="deterministic")
    model_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proposal_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_is_calibrated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    disposition: Mapped[str] = mapped_column(String(32), nullable=False, default="unresolved")
    created_by_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)


class Provenance(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """Why a displayed value comes from a particular source snapshot."""

    __tablename__ = "provenance"

    entity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("canonical_entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    attribute_path: Mapped[str] = mapped_column(String(200), nullable=False)
    source_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_field: Mapped[str | None] = mapped_column(String(160), nullable=True)
    authority_policy_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


__all__ = [
    "Address",
    "CanonicalEntity",
    "Credential",
    "Crosswalk",
    "FinanceAccount",
    "MatchProposal",
    "Parcel",
    "ParcelAddress",
    "Party",
    "PartyAlias",
    "PartyContact",
    "Provenance",
]

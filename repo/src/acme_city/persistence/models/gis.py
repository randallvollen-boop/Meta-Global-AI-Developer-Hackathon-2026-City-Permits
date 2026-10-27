"""The shared property master: GIS streets, zoning, the parcel match of a case.

The parcels, addresses and parcel-address relationships themselves live in the
registry tables (``parcels``, ``addresses``, ``parcel_addresses``) and are the
one source of truth that the simulated ArcGIS services read.  This module adds
what hangs off them:

* ``gis_streets``: the street centrelines of the fictional town;
* ``zoning_districts``: the zoning register;
* ``application_parcel_matches``: the locator evidence for one application and
  the state of its parcel link (the steward approves it, the reviewer confirms
  it);
* ``dataset_subscribers``: the simulated departments that consume the published
  "Property master" dataset;
* ``application_drafts`` and ``draft_documents``: an applicant's saved draft.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import (
    Base,
    CorrelationMixin,
    CreatedAtMixin,
    IdMixin,
    VersionMixin,
)
from acme_city.persistence.types import UTCDateTime
from datetime import datetime

#: The states of the parcel link of one application.
MATCH_PROPOSED = "proposed"
MATCH_NEEDS_CHOICE = "needs_choice"
MATCH_NOT_FOUND = "not_found"
MATCH_APPROVED = "approved"
MATCH_REJECTED = "rejected"
MATCH_STATES: tuple[str, ...] = (
    MATCH_PROPOSED,
    MATCH_NEEDS_CHOICE,
    MATCH_NOT_FOUND,
    MATCH_APPROVED,
    MATCH_REJECTED,
)


class GisStreet(IdMixin, CreatedAtMixin, Base):
    """One street centreline of the fictional town."""

    __tablename__ = "gis_streets"

    street_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    road_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    #: The centreline as a list of ``[x, y]`` points on the local grid.
    path: Mapped[list[Any]] = mapped_column(JSON, nullable=False)


class ZoningDistrict(IdMixin, CreatedAtMixin, Base):
    """One zoning district of the zoning register."""

    __tablename__ = "zoning_districts"

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ApplicationParcelMatch(IdMixin, VersionMixin, CorrelationMixin, CreatedAtMixin, Base):
    """The locator evidence and the parcel link of one application.

    The intake agent proposes; the Data Steward approves the link; the Permit
    Reviewer confirms the parcel before deciding.  ``confirmed_*`` is cleared
    whenever the link changes.
    """

    __tablename__ = "application_parcel_matches"

    application_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    submitted_text: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    matched_address: Mapped[str | None] = mapped_column(String(320), nullable=True)
    address_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True
    )
    parcel_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("parcels.id", ondelete="SET NULL"), nullable=True
    )
    #: The parcel number the GIS reported, kept even when the registry does not
    #: hold that parcel yet.
    parcel_number: Mapped[str | None] = mapped_column(String(96), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    locator_status: Mapped[str] = mapped_column(String(2), nullable=False, default="U")
    x: Mapped[float | None] = mapped_column(Float, nullable=True)
    y: Mapped[float | None] = mapped_column(Float, nullable=True)
    candidates: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    method: Mapped[str] = mapped_column(String(64), nullable=False, default="locator")
    link_state: Mapped[str] = mapped_column(String(24), nullable=False, default=MATCH_PROPOSED)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "link_state IN ('proposed', 'needs_choice', 'not_found', 'approved', 'rejected')",
            name="link_state_allowed",
        ),
        CheckConstraint("locator_status IN ('M', 'T', 'U')", name="locator_status_allowed"),
    )


class DatasetSubscriber(IdMixin, VersionMixin, CreatedAtMixin, Base):
    """A simulated department that subscribes to a published dataset."""

    __tablename__ = "dataset_subscribers"

    dataset_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    department_key: Mapped[str] = mapped_column(String(64), nullable=False)
    department_label: Mapped[str] = mapped_column(String(160), nullable=False)
    consumed_fields: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    contract_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    signal_key: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_label: Mapped[str] = mapped_column(String(160), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ApplicationDraft(IdMixin, VersionMixin, CorrelationMixin, CreatedAtMixin, Base):
    """An applicant's saved draft of a per-type application form."""

    __tablename__ = "application_drafts"

    reference: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    permit_type_key: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_actor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    application_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    __table_args__ = (
        CheckConstraint("status IN ('open', 'submitted')", name="status_allowed"),
    )


class DraftDocument(IdMixin, CreatedAtMixin, Base):
    """A file an applicant added to a draft, stored before submission."""

    __tablename__ = "draft_documents"

    draft_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("application_drafts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(120), nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


__all__ = [
    "MATCH_APPROVED",
    "MATCH_NEEDS_CHOICE",
    "MATCH_NOT_FOUND",
    "MATCH_PROPOSED",
    "MATCH_REJECTED",
    "MATCH_STATES",
    "ApplicationDraft",
    "ApplicationParcelMatch",
    "DatasetSubscriber",
    "DraftDocument",
    "GisStreet",
    "ZoningDistrict",
]

"""Commands for simulated outside intake.

A record is what the outside application gathered before this system saw it.
It carries no authority: the server resolves the submitting actor, stages the
raw record through the registered contract, and only then turns it into a
Permitting application through the existing services.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IntakeModel(BaseModel):
    """A model that ignores unknown request fields (never an authority)."""

    model_config = ConfigDict(extra="ignore")


class IntakeApplicant(IntakeModel):
    """The applicant as the outside application recorded them."""

    name: str = ""
    email: str = ""
    phone: str = ""


class IntakeDocument(IntakeModel):
    """One submitted document, by type, with its text."""

    document_type: str
    text: str = ""


class IntakeRecordCommand(IntakeModel):
    """One application gathered by the outside intake application."""

    channel: Literal["portal", "counter_scan", "email"]
    received_at: datetime | None = None
    portal_reference: str = Field(min_length=1, max_length=96)
    applicant: IntakeApplicant = Field(default_factory=IntakeApplicant)
    site_address: str = ""
    parcel_text: str = ""
    permit_type_key: str = Field(min_length=1, max_length=64)
    submitted_facts: dict[str, Any] = Field(default_factory=dict)
    documents: list[IntakeDocument] = Field(default_factory=list)
    #: Free-standing document text (used when no typed documents are given).
    document_text: str = ""


class IntakeSubmitResult(IntakeModel):
    """What happened to one intake record."""

    portal_reference: str
    status: str  # created | duplicate
    application_id: str | None = None
    source_application_number: str | None = None
    snapshot_id: str | None = None
    triage_outcome: str | None = None


__all__ = [
    "IntakeApplicant",
    "IntakeDocument",
    "IntakeModel",
    "IntakeRecordCommand",
    "IntakeSubmitResult",
]

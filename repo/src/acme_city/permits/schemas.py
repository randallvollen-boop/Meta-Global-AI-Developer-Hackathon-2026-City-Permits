"""Command and view models for the permit workflow.

The submitted revision, the current profile, the evaluation, the decision and
the issued snapshot are separate records with separate versions.  A command
never carries authority: the server resolves the actor and its scope.
"""
# REQUIRES: PER-01, PER-02, PER-03, PER-06, EDIT-05
# An application keeps its submitted facts separate from the shared party and
# GIS facts, every revision is immutable, and the evaluation records the
# versions it used.

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from acme_city.rules.schemas import RuleResult

#: The date basis the P0 demonstration uses for rule and fee selection.
DEFAULT_DATE_BASIS = "initial_submitted_at"


class PermitModel(BaseModel):
    """A model that ignores unknown request fields.

    A client-supplied role, actor or permission field is ignored rather than
    honoured: the server resolves the actor and the scope itself.
    """

    model_config = ConfigDict(extra="ignore")


class ApplicationPartyInput(PermitModel):
    """A party in a role on an application."""

    party_id: str
    party_role: str
    is_primary: bool = False
    authority_evidence_ref: str | None = None


class ApplicationSiteInput(PermitModel):
    """The site of an application."""

    parcel_number: str | None = None
    address_text: str | None = None
    parcel_id: str | None = None
    address_id: str | None = None


class SubmitApplicationCommand(PermitModel):
    """Submit an application and create its first immutable revision."""

    permit_type_key: str
    facts: dict[str, Any] = Field(default_factory=dict)
    applicant_party_id: str | None = None
    source_application_number: str | None = None
    parties: list[ApplicationPartyInput] = Field(default_factory=list)
    site: ApplicationSiteInput | None = None
    reason: str | None = None


class ReviseApplicationCommand(PermitModel):
    """Create a new submitted revision of an application."""

    application_id: str
    facts: dict[str, Any] = Field(default_factory=dict)
    parties: list[ApplicationPartyInput] | None = None
    site: ApplicationSiteInput | None = None
    reason: str = ""
    expected_version: int | None = None


class ApplicationPartyView(PermitModel):
    """A party in a role on an application."""

    party_id: str
    party_role: str
    is_primary: bool = False
    authority_evidence_ref: str | None = None


class ApplicationSiteView(PermitModel):
    """The site of an application."""

    parcel_id: str | None = None
    address_id: str | None = None
    resolution_status: str = "unresolved"
    submitted_address_text: str | None = None


class ApplicationRevisionView(PermitModel):
    """One submitted revision of an application.

    The submitted facts of a revision never change.  A later profile update
    changes the current profile, not this snapshot.
    """

    application_id: str
    source_application_number: str
    permit_type_key: str
    revision_id: str
    revision_number: int
    submitted_at: datetime
    submitted_by_actor_id: str | None = None
    initial_submitted_at: datetime | None = None
    revision_submitted_at: datetime | None = None
    date_basis: str = DEFAULT_DATE_BASIS
    status: str = "submitted"
    application_version: int = 1
    snapshot: dict[str, Any] = Field(default_factory=dict)
    parties: list[ApplicationPartyView] = Field(default_factory=list)
    site: ApplicationSiteView | None = None


class Blocker(PermitModel):
    """One unresolved condition that blocks a dependent action."""

    code: str
    detail: str
    subject_type: str | None = None
    subject_id: str | None = None


class EvaluationView(PermitModel):
    """A versioned evaluation of an application revision."""

    evaluation_id: str
    application_id: str
    revision_id: str | None = None
    version: int = 1
    performed_at: datetime
    performed_by_actor_id: str | None = None
    date_basis: str = DEFAULT_DATE_BASIS
    rule_versions: dict[str, str] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    results: list[RuleResult] = Field(default_factory=list)
    outcome: str = "review"
    blockers: list[Blocker] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    dependency_versions: dict[str, str] = Field(default_factory=dict)
    status: str = "current"
    stale: bool = False


class DocumentVersionView(PermitModel):
    """One stored document version."""

    document_id: str
    application_id: str | None = None
    document_type: str
    version: int
    file_ref: str
    content_hash: str
    byte_length: int
    media_type: str
    received_at: datetime
    uploaded_by_actor_id: str | None = None
    fictional_demo: bool = True


__all__ = [
    "DEFAULT_DATE_BASIS",
    "ApplicationPartyInput",
    "ApplicationPartyView",
    "ApplicationRevisionView",
    "ApplicationSiteInput",
    "ApplicationSiteView",
    "Blocker",
    "DocumentVersionView",
    "EvaluationView",
    "PermitModel",
    "ReviseApplicationCommand",
    "SubmitApplicationCommand",
]

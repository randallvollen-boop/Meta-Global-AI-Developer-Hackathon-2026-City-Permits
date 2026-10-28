"""Pure intake producers: the statements the intake graph makes about a case.

Each function takes frozen facts and returns finding specs and plain notes.
The intake agent calls them with facts read from stored rows and writes the
specs as findings; the policy simulation calls them with frozen case inputs.
Nothing here reads a row, writes a finding or changes a status.
"""
# REQUIRES: AI-03, AI-04, PER-04, REF-01
# The classifier, document QC, completeness, duplicate and router producers
# are pure functions of the facts they are given.

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from acme_city.kernel.findings import FindingSpec, is_blocking, is_judging

#: The document-quality flags the document QC node reads.  Only an unreadable
#: page blocks the case; the others ask a person to look.
BLOCKING_QUALITY_FLAGS: frozenset[str] = frozenset({"unreadable"})
DUPLICATE_QUALITY_FLAGS: frozenset[str] = frozenset({"duplicate_page"})
JUDGMENT_QUALITY_FLAGS: frozenset[str] = frozenset({"rotated", "low_res", "handwritten"})


@dataclass(frozen=True)
class TypeFacts:
    """The configuration of a permit type that the intake producers read."""

    key: str
    label: str
    active: bool
    fee_schedule_key: str | None
    review_area: str | None
    review_route: str
    required_fields: tuple[str, ...]
    required_documents: tuple[str, ...]


@dataclass(frozen=True)
class ClassifierResult:
    """What the classifier node says about the type of a case."""

    findings: tuple[FindingSpec, ...]
    status: str
    notes: tuple[str, ...]
    review_area: str


def classify_type(
    permit_type: TypeFacts,
    *,
    channel: str,
    declared_type_key: str,
    fee_schedule_id: str | None,
    requirements_review_area: str = "",
) -> ClassifierResult:
    """Return the classifier findings for the type of a case.

    ``fee_schedule_id`` is the identifier of the published fee schedule in
    force on the case's basis date, or ``None`` when there is none.
    """
    status = "ok"
    notes = [f"Permit type {permit_type.key} confirmed; received by the {channel} channel."]
    findings: list[FindingSpec] = []
    if declared_type_key and declared_type_key != permit_type.key:
        status = "warn"
        findings.append(
            FindingSpec(
                finding_type="wrong_type",
                message=(
                    f"The intake record asked for {declared_type_key!r} but the case was "
                    f"created as {permit_type.key!r}. A person must confirm which permit "
                    "type applies."
                ),
                rule="ACME Code §13-101",
                applicant_must="Confirm the permit type of this application.",
                severity="review",
            )
        )
        notes.append("The declared type differs from the recorded type.")
    if not permit_type.active:
        status = "block"
        findings.append(
            FindingSpec(
                finding_type="conflict",
                message=(
                    f"The permit type {permit_type.key!r} is no longer active, so the "
                    "case cannot be routed to a review area."
                ),
                rule="ACME Code §13-102",
                applicant_must="Ask the City which permit type applies now.",
                severity="block",
            )
        )
        notes.append("The permit type is not active.")
    fee_findings, fee_note = fee_schedule_findings(permit_type, fee_schedule_id)
    findings.extend(fee_findings)
    notes.append(fee_note)
    review_area = (
        requirements_review_area or permit_type.review_area or permit_type.review_route
    )
    return ClassifierResult(
        findings=tuple(findings),
        status=status,
        notes=tuple(notes),
        review_area=review_area,
    )


def fee_schedule_findings(
    permit_type: TypeFacts, fee_schedule_id: str | None
) -> tuple[tuple[FindingSpec, ...], str]:
    """Return the fee finding when the City cannot price the case, and a note."""
    applicant_must = (
        "Ask the City which fee applies to this permit type; the fee schedule "
        "is being updated."
    )
    if not permit_type.fee_schedule_key:
        return (
            (
                FindingSpec(
                    finding_type="fee",
                    message=(
                        f"The permit type {permit_type.key!r} names no fee schedule, so the "
                        "City cannot price this case."
                    ),
                    rule="ACME Code §13-105",
                    applicant_must=applicant_must,
                    severity="block",
                ),
            ),
            "The permit type names no fee schedule.",
        )
    if fee_schedule_id is not None:
        return (), f"Fee schedule {fee_schedule_id} is in force."
    return (
        (
            FindingSpec(
                finding_type="fee",
                message=(
                    f"No published fee schedule is in force for the permit type "
                    f"{permit_type.key!r} on the recorded basis date, so the City cannot "
                    "price this case."
                ),
                rule="ACME Code §13-105",
                applicant_must=applicant_must,
                severity="block",
            ),
        ),
        "No fee schedule is in force for the permit type.",
    )


@dataclass(frozen=True)
class QualityResult:
    """What the document QC node says about the received pages."""

    findings: tuple[FindingSpec, ...]
    status: str
    notes: tuple[str, ...]


def document_quality(documents: Iterable[tuple[str, Sequence[str]]]) -> QualityResult:
    """Return the scan-quality findings of ``(document_type, flags)`` pairs."""
    status = "ok"
    notes: list[str] = []
    findings: list[FindingSpec] = []
    for document_type, raw_flags in documents:
        for flag in (str(item) for item in (raw_flags or [])):
            if flag in BLOCKING_QUALITY_FLAGS:
                status = "block"
                findings.append(
                    FindingSpec(
                        finding_type="unreadable",
                        message=(
                            f"The {document_type} page cannot be read, so the "
                            "case cannot be assessed until a readable copy arrives."
                        ),
                        rule="ACME Code §13-302",
                        applicant_must=f"Provide a readable copy of the {document_type}.",
                        severity="block",
                    )
                )
                notes.append(f"{document_type}: {flag}.")
            elif flag in DUPLICATE_QUALITY_FLAGS:
                status = "warn" if status == "ok" else status
                findings.append(
                    FindingSpec(
                        finding_type="duplicate",
                        message=(
                            f"The {document_type} page repeats an earlier page "
                            "of the same document."
                        ),
                        rule="ACME Code §13-303",
                        applicant_must=(
                            f"Confirm that the {document_type} has no repeated page."
                        ),
                        severity="review",
                    )
                )
                notes.append(f"{document_type}: {flag}.")
            elif flag in JUDGMENT_QUALITY_FLAGS:
                status = "warn" if status == "ok" else status
                findings.append(
                    FindingSpec(
                        finding_type="judgment",
                        message=(
                            f"The {document_type} page was received {flag.replace('_', ' ')}, "
                            "so a person should read it before the case is assessed."
                        ),
                        rule="ACME Code §13-304",
                        applicant_must=f"Provide a clearer copy of the {document_type}.",
                        severity="review",
                    )
                )
                notes.append(f"{document_type}: {flag}.")
    if not notes:
        notes.append("No scan-quality problem was reported on the received documents.")
    return QualityResult(findings=tuple(findings), status=status, notes=tuple(notes))


def requirements_of(
    snapshot: Mapping[str, Any] | None,
    type_required_fields: Iterable[str] | None,
    type_required_documents: Iterable[str] | None,
) -> dict[str, list[str]]:
    """Return the requirements a case is measured against.

    A case received through intake carries the requirements that were in force
    when it arrived.  A case without a snapshot is measured against the
    current configuration of its type.
    """
    recorded = dict(snapshot or {})
    return {
        "required_fields": list(
            recorded.get("required_fields")
            if recorded.get("required_fields") is not None
            else (type_required_fields or [])
        ),
        "required_documents": list(
            recorded.get("required_documents")
            if recorded.get("required_documents") is not None
            else (type_required_documents or [])
        ),
    }


@dataclass(frozen=True)
class CompletenessResult:
    """What the completeness node says about a case."""

    findings: tuple[FindingSpec, ...]
    missing_fields: tuple[str, ...]
    missing_documents: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not (self.missing_fields or self.missing_documents)


def completeness(
    *,
    type_key: str,
    required_fields: Iterable[str],
    required_documents: Iterable[str],
    facts: Mapping[str, Any],
    present_document_types: Iterable[str],
) -> CompletenessResult:
    """Return the missing fields and documents of a case and their findings."""
    present = set(present_document_types)
    missing_fields = [
        field
        for field in required_fields
        if facts.get(field) is None
        or (isinstance(facts.get(field), str) and not str(facts.get(field)).strip())
    ]
    missing_documents = [document for document in required_documents if document not in present]
    findings: list[FindingSpec] = []
    for field in missing_fields:
        findings.append(
            FindingSpec(
                finding_type="missing_field",
                message=f"The application does not state {field.replace('_', ' ')}.",
                rule=f"ACME Code §13-501 ({type_key} required fields)",
                applicant_must=f"State {field.replace('_', ' ')} on the application.",
                severity="block",
            )
        )
    declared_value = facts.get("documents_sent_separately")
    declared = (
        {str(item) for item in declared_value} if isinstance(declared_value, list) else set()
    )
    for document in missing_documents:
        label = document.replace("_", " ")
        if document in declared:
            # The applicant said it was sent separately; no file is on this case,
            # so it is still not received.
            findings.append(
                FindingSpec(
                    finding_type="missing_document",
                    message=(
                        f"The applicant declared the {label} sent separately; it has not "
                        "been received with this application."
                    ),
                    rule=f"ACME Code §13-502 ({type_key} required documents)",
                    applicant_must=f"Send the {label} to the City, or upload it with your answer.",
                    severity="block",
                )
            )
            continue
        findings.append(
            FindingSpec(
                finding_type="missing_document",
                message=f"The application does not include the {label}.",
                rule=f"ACME Code §13-502 ({type_key} required documents)",
                applicant_must=f"Provide the {label}.",
                severity="block",
            )
        )
    return CompletenessResult(
        findings=tuple(findings),
        missing_fields=tuple(missing_fields),
        missing_documents=tuple(missing_documents),
    )


@dataclass(frozen=True)
class PeerFacts:
    """The facts of another live case that decide whether it is a duplicate."""

    reference: str
    number: str
    permit_type_id: str
    applicant: str
    address: str
    description: str


def duplicate_key(facts: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return the ``(applicant, address, description)`` of an intake record."""
    return (
        str(facts.get("applicant_name") or "").strip().lower(),
        str(facts.get("submitted_site_text") or facts.get("site_address") or "").strip().lower(),
        str(facts.get("project_description") or "").strip().lower(),
    )


def first_duplicate(
    facts: Mapping[str, Any], permit_type_id: str, peers: Iterable[PeerFacts]
) -> PeerFacts | None:
    """Return the first peer that asks for the same project.

    A duplicate is the same applicant asking for the same project at the same
    address for the same permit type.  Two different projects of the same
    applicant (a front fence and a rear fence, say) are not duplicates.
    """
    applicant, address, description = duplicate_key(facts)
    if not applicant or not address:
        return None
    for peer in peers:
        if peer.applicant != applicant or peer.address != address:
            continue
        if peer.permit_type_id != permit_type_id:
            continue
        if description and peer.description and peer.description != description:
            continue
        return peer
    return None


def duplicate_finding(number: str, reference: str) -> FindingSpec:
    """Return the finding for a duplicate of the case ``number``."""
    return FindingSpec(
        finding_type="duplicate",
        message=(
            "The same applicant asked for the same project at the same address "
            f"for the same permit type in {number}. "
            "A person must confirm whether this is a resubmission."
        ),
        rule="ACME Code §13-401",
        applicant_must=(
            "Tell the City whether this is a new application or a resubmission of "
            f"{number}."
        ),
        severity="review",
        related_application_id=reference,
    )


@dataclass(frozen=True)
class RouteResult:
    """Where the router sends a case."""

    status: str
    outcome: str
    reason: str
    blocking: int
    judging: int


def route(findings: Iterable[FindingSpec], review_area: str | None) -> RouteResult:
    """Route a case to early resolution or to review."""
    specs = list(findings)
    blocking = [item for item in specs if is_blocking(item.severity)]
    judging = [item for item in specs if is_judging(item.severity, item.finding_type)]
    if blocking:
        return RouteResult(
            status="needs_information",
            outcome="needs_information",
            reason=(
                f"Route to early resolution: {len(blocking)} blocking finding(s) must be "
                "cleared first."
            ),
            blocking=len(blocking),
            judging=len(judging),
        )
    if judging:
        return RouteResult(
            status="needs_information",
            outcome="needs_information",
            reason=(
                "Verify before review: "
                f"{len(judging)} finding(s) need a person's judgement."
            ),
            blocking=0,
            judging=len(judging),
        )
    return RouteResult(
        status="ready_for_review",
        outcome="completed",
        reason=f"Ready for review in the {review_area or 'assigned'} area.",
        blocking=0,
        judging=0,
    )


__all__ = [
    "BLOCKING_QUALITY_FLAGS",
    "DUPLICATE_QUALITY_FLAGS",
    "JUDGMENT_QUALITY_FLAGS",
    "ClassifierResult",
    "CompletenessResult",
    "PeerFacts",
    "QualityResult",
    "RouteResult",
    "TypeFacts",
    "classify_type",
    "completeness",
    "document_quality",
    "duplicate_finding",
    "duplicate_key",
    "fee_schedule_findings",
    "first_duplicate",
    "requirements_of",
    "route",
]

"""Read-only loading of stored cases as frozen :class:`CaseInput` values.

This is the second module of the package that touches a session, and it only
reads.  It builds the populations "all current applications" and "decided
applications in a date range" and the case inputs the parity tests compare
with production.  Historical populations are a **retrospective re-scoring**
of frozen inputs; they are not a reconstruction of the decisions made then.
"""
# REQUIRES: PER-02
# Stored cases are frozen into case inputs without writing anything.

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.agents.intake import find_duplicate
from acme_city.kernel.findings import FindingSpec
from acme_city.persistence.models import permit
from acme_city.permits.service import PermitService
from acme_city.policy.population import (
    KIND_CURRENT,
    KIND_DECIDED_RANGE,
    CaseInput,
    Population,
    PopulationDefinition,
)

#: The citations of the findings that come from steps needing the outside
#: world (extraction, the address locator, the parcel conflict check and the
#: precedent check).  They do not depend on policy, so a re-score carries them.
CARRIED_FINDING_RULES: frozenset[str] = frozenset(
    {
        "ACME Code §13-204",
        "ACME Code §13-701",
        "ACME Code §13-702",
        "ACME Code §13-703",
        "ACME Code §13-604",
    }
)

#: Statuses of a case that is not a live case.
_NOT_CURRENT = frozenset({"draft", "archived", "returned"})


def case_input_from_application(
    session: Session,
    application: permit.Application,
    *,
    carried: Iterable[FindingSpec] | None = None,
    use_receipt_requirements: bool = False,
    now: datetime | None = None,
) -> CaseInput:
    """Freeze one stored application into a case input (reads only).

    ``use_receipt_requirements`` keeps the requirements the case carried when
    it was received (the production behaviour).  The default measures the case
    against the configuration being scored, which is what a what-if needs.
    """
    with session.no_autoflush:
        permits = PermitService(session, now=now)
        revision = permits.current_revision(application.id)
        documents = session.execute(
            select(permit.Document)
            .where(permit.Document.application_id == application.id)
            .order_by(permit.Document.document_type, permit.Document.version)
        ).scalars().all()
        permit_type = permits.permit_type(application)
        inputs = dict(revision.snapshot or {})
        blockers = list(permits.site_blockers(application))
        blockers.extend(
            permits.credential_blockers(
                application, inputs, now or application.initial_submitted_at or revision.submitted_at
            )
        )
        duplicate = find_duplicate(session, application)
        if carried is None:
            rows = session.execute(
                select(permit.ApplicationFinding).where(
                    permit.ApplicationFinding.application_id == application.id,
                    permit.ApplicationFinding.state == "current",
                )
            ).scalars().all()
            carried = [
                FindingSpec(
                    finding_type=row.finding_type,
                    message=row.message,
                    rule=row.rule,
                    applicant_must=row.applicant_must,
                    severity=row.severity,
                    related_application_id=row.related_application_id,
                )
                for row in rows
                if row.rule in CARRIED_FINDING_RULES
            ]
        return CaseInput.create(
            case_ref=application.source_application_number,
            permit_type_key=permit_type.key,
            basis_at=application.initial_submitted_at or revision.submitted_at,
            facts=inputs,
            intake_record=dict(application.submitted_facts or {}),
            documents=[(d.document_type, list(d.quality or [])) for d in documents],
            requirements_snapshot=(
                dict(application.requirements_snapshot or {})
                if use_receipt_requirements and application.requirements_snapshot
                else None
            ),
            parcel_inputs=permits.parcel_inputs(application),
            duplicate_of=(
                None if duplicate is None else (duplicate.id, duplicate.source_application_number)
            ),
            carried_findings=carried,
            safeguard_blockers=[blocker.code for blocker in blockers],
        )


def current_applications_population(
    session: Session, *, use_receipt_requirements: bool = False
) -> Population:
    """Return the live applications as a population (reads only)."""
    rows = session.execute(
        select(permit.Application).order_by(permit.Application.source_application_number)
    ).scalars().all()
    cases = [
        case_input_from_application(
            session, row, use_receipt_requirements=use_receipt_requirements
        )
        for row in rows
        if row.status not in _NOT_CURRENT
    ]
    return Population(PopulationDefinition(kind=KIND_CURRENT), tuple(cases))


def decided_range_population(
    session: Session,
    start: datetime,
    end: datetime,
    *,
    use_receipt_requirements: bool = False,
) -> Population:
    """Return the applications decided in ``[start, end)`` (reads only).

    Labelled a retrospective re-scoring of frozen inputs.
    """
    decisions = session.execute(
        select(permit.Decision).where(
            permit.Decision.status == "current",
            permit.Decision.decided_at >= start,
            permit.Decision.decided_at < end,
        )
    ).scalars().all()
    ids = sorted({decision.application_id for decision in decisions})
    applications = [session.get(permit.Application, item) for item in ids]
    cases = [
        case_input_from_application(
            session, row, use_receipt_requirements=use_receipt_requirements
        )
        for row in sorted(
            (a for a in applications if a is not None),
            key=lambda a: a.source_application_number,
        )
    ]
    return Population(
        PopulationDefinition(
            kind=KIND_DECIDED_RANGE,
            range_start=start.date().isoformat(),
            range_end=end.date().isoformat(),
        ),
        tuple(cases),
    )


__all__ = [
    "CARRIED_FINDING_RULES",
    "case_input_from_application",
    "current_applications_population",
    "decided_range_population",
]

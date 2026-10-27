"""The findings an agent records on a case.

A finding is evidence for a person: what is wrong, the rule that applies,
what the applicant must do and whether it blocks the case or only asks a
person to look.  A finding never decides anything and never approves.

Findings accumulate across runs.  Each one records the application revision
and the agent run that produced it, and each one carries a state:

* ``current`` — the live statement about the case;
* ``resolved`` — a later run showed that the condition is gone;
* ``superseded`` — a later run or a resubmission replaced it.

The history is kept: a finding is never deleted.  A Data Steward may waive a
current finding of a waivable type, and the waiver is recorded on the
finding itself.  A waiver never clears a deterministic rule failure and never
clears an identity, credential, finance or parcel-clearance check: those keep
blocking a decision exactly as they did before.
"""
# REQUIRES: PER-04, AI-03
# Every finding names its type, its rule, the line the applicant must satisfy
# and whether it blocks the case.  A finding belongs to the revision and the
# run that produced it, and only a current finding of a waivable type may be
# waived.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.core.clock import utc_now
from acme_city.core.ids import new_id
from acme_city.persistence.models import permit

#: The finding types an agent may record.
FINDING_TYPES: tuple[str, ...] = (
    "missing_field",
    "missing_document",
    "unreadable",
    "wrong_type",
    "duplicate",
    "conflict",
    "fee",
    "low_confidence_extraction",
    "judgment",
)

#: The severities a finding may carry.
SEVERITIES: tuple[str, ...] = ("block", "review")

#: The finding types that ask a person to judge the case rather than block
#: it.  They route the case to early resolution for verification.
HUMAN_JUDGMENT_TYPES: frozenset[str] = frozenset(
    {"duplicate", "conflict", "low_confidence_extraction", "judgment"}
)

#: The finding types a Data Steward may waive.  A missing field, a missing
#: document, an unreadable page and a fee question are not waivable: the
#: applicant must supply them, and money is never waived.
WAIVABLE_TYPES: frozenset[str] = frozenset(
    {"wrong_type", "duplicate", "conflict", "low_confidence_extraction", "judgment"}
)

#: The stable order the finding types are grouped by.  The primary finding of
#: a case is the blocking one, or else the first of these types.
FINDING_CATEGORY_ORDER: tuple[str, ...] = (
    "missing_field",
    "missing_document",
    "unreadable",
    "wrong_type",
    "duplicate",
    "conflict",
    "fee",
    "low_confidence_extraction",
    "judgment",
)

#: The states a finding may hold.
FINDING_STATES: tuple[str, ...] = ("current", "resolved", "superseded")


class FindingWriter:
    """Writes the findings of one agent run."""

    def __init__(
        self,
        session: Session,
        *,
        application_id: str,
        correlation_id: str,
        source_node: str = "",
        revision_number: int | None = None,
        run_id: str | None = None,
    ) -> None:
        self._session = session
        self._application_id = application_id
        self._correlation_id = correlation_id
        self._source_node = source_node
        self._revision_number = revision_number
        self._run_id = run_id
        self.findings: list[permit.ApplicationFinding] = []

    def add(
        self,
        *,
        finding_type: str,
        message: str,
        rule: str | None = None,
        applicant_must: str | None = None,
        severity: str = "review",
        related_application_id: str | None = None,
        source_node: str | None = None,
    ) -> permit.ApplicationFinding:
        """Record one finding on the application."""
        if finding_type not in FINDING_TYPES:
            raise ValueError(f"unknown finding type: {finding_type!r}")
        if severity not in SEVERITIES:
            raise ValueError(f"unknown finding severity: {severity!r}")
        row = permit.ApplicationFinding(
            id=new_id("finding"),
            correlation_id=self._correlation_id,
            application_id=self._application_id,
            finding_type=finding_type,
            message=message,
            rule=rule,
            applicant_must=applicant_must,
            severity=severity,
            source_node=source_node or self._source_node,
            related_application_id=related_application_id,
            version=1,
            state="current",
            revision_number=self._revision_number,
            agent_run_id=self._run_id,
        )
        self._session.add(row)
        self.findings.append(row)
        self._session.flush()
        return row

    @property
    def blocking(self) -> list[permit.ApplicationFinding]:
        """Return the findings that block the case."""
        return [row for row in self.findings if row.severity == "block"]

    @property
    def judging(self) -> list[permit.ApplicationFinding]:
        """Return the findings that ask a person to judge the case."""
        return [
            row
            for row in self.findings
            if row.severity == "review" and row.finding_type in HUMAN_JUDGMENT_TYPES
        ]


def findings_for(session: Session, application_id: str) -> list[permit.ApplicationFinding]:
    """Return the recorded findings of one application, oldest first."""
    return list(
        session.execute(
            select(permit.ApplicationFinding)
            .where(permit.ApplicationFinding.application_id == application_id)
            .order_by(
                permit.ApplicationFinding.created_at,
                permit.ApplicationFinding.id,
            )
        ).scalars().all()
    )


def current_findings(
    session: Session, application_id: str
) -> list[permit.ApplicationFinding]:
    """Return the current findings of one application, oldest first."""
    return [
        row
        for row in findings_for(session, application_id)
        if row.state == "current"
    ]


def blocking_findings(
    session: Session, application_id: str
) -> list[permit.ApplicationFinding]:
    """Return the current findings that still block the case.

    A waived finding does not block: the waiver is a recorded decision of a
    Data Steward that the finding no longer stands in the way.  This never
    touches the deterministic blockers a decision is refused for.
    """
    return [
        row
        for row in current_findings(session, application_id)
        if row.severity == "block" and row.waived_at is None
    ]


def category_rank(finding_type: str) -> int:
    """Return the stable grouping rank of one finding type."""
    try:
        return FINDING_CATEGORY_ORDER.index(finding_type)
    except ValueError:
        return len(FINDING_CATEGORY_ORDER)


def primary_finding(
    rows: list[permit.ApplicationFinding],
) -> permit.ApplicationFinding | None:
    """Return the finding a case is grouped by.

    A blocking finding comes first.  Among findings of the same severity the
    stable category order decides, and the finding identifier breaks a tie.
    """
    if not rows:
        return None
    return sorted(
        rows,
        key=lambda row: (
            0 if row.severity == "block" else 1,
            category_rank(row.finding_type),
            row.id,
        ),
    )[0]


def is_waived(row: permit.ApplicationFinding) -> bool:
    """Return whether the finding was waived."""
    return row.waived_at is not None


def supersede_findings_before(
    session: Session,
    application_id: str,
    *,
    revision_number: int,
    at: datetime | None = None,
) -> int:
    """Supersede the current findings of the revisions before a new one.

    A resubmission replaces the findings of the earlier revisions: the
    history is kept, but the findings of the prior versions are no longer
    the live statement about the case.
    """
    moment = at or utc_now()
    count = 0
    for row in findings_for(session, application_id):
        if row.state != "current":
            continue
        found = row.revision_number
        if found is not None and found >= revision_number:
            continue
        row.state = "superseded"
        row.superseded_at = moment
        count += 1
    session.flush()
    return count


def resolve_replaced_findings(
    session: Session,
    application_id: str,
    *,
    revision_number: int,
    produced: list[tuple[str, str]],
    exclude_run_id: str | None = None,
    at: datetime | None = None,
) -> tuple[int, int]:
    """Settle the findings of a rerun of the same revision.

    A finding the rerun recorded again is superseded by the new one; a
    finding the rerun did not record again is resolved, because the
    condition it described is gone.  The history is kept either way.  The
    findings of the run that is doing the settling are left alone.
    """
    moment = at or utc_now()
    superseded = 0
    resolved = 0
    keys = {(str(kind), str(message)) for kind, message in produced}
    for row in findings_for(session, application_id):
        if row.state != "current":
            continue
        if row.revision_number != revision_number:
            continue
        if exclude_run_id is not None and row.agent_run_id == exclude_run_id:
            continue
        if (row.finding_type, row.message) in keys:
            row.state = "superseded"
            row.superseded_at = moment
            superseded += 1
        else:
            row.state = "resolved"
            row.resolved_at = moment
            resolved += 1
    session.flush()
    return superseded, resolved


def waiver_snapshot(
    session: Session, application_id: str
) -> list[dict[str, Any]]:
    """Return the waivers that apply to a case, as a decision would snapshot them."""
    return [
        {
            "finding_id": row.id,
            "finding_type": row.finding_type,
            "message": row.message,
            "waived_at": row.waived_at.isoformat() if row.waived_at else "",
            "waived_by_actor_id": row.waived_by_actor_id or "",
            "reason_code": row.waiver_reason_code or "",
            "reason_code_label": row.waiver_reason_code_label or "",
            "reason_code_version": row.waiver_reason_code_version,
            "reason": row.waiver_reason or "",
        }
        for row in findings_for(session, application_id)
        if row.waived_at is not None
    ]


def finding_view(row: permit.ApplicationFinding) -> dict[str, Any]:
    """Return the view of one finding."""
    return {
        "finding_id": row.id,
        "finding_type": row.finding_type,
        "message": row.message,
        "rule": row.rule or "",
        "applicant_must": row.applicant_must or "",
        "severity": row.severity,
        "source_node": row.source_node or "",
        "related_application_id": row.related_application_id or "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "state": row.state,
        "revision_number": row.revision_number,
        "agent_run_id": row.agent_run_id or "",
        "waived": is_waived(row),
        "waived_at": row.waived_at.isoformat() if row.waived_at else "",
        "waived_by_actor_id": row.waived_by_actor_id or "",
        "waiver_reason_code": row.waiver_reason_code or "",
        "waiver_reason_code_label": row.waiver_reason_code_label or "",
        "waiver_reason_code_version": row.waiver_reason_code_version,
        "waiver_reason": row.waiver_reason or "",
        "waivable": row.finding_type in WAIVABLE_TYPES and row.state == "current",
    }


__all__ = [
    "FINDING_CATEGORY_ORDER",
    "FINDING_STATES",
    "FINDING_TYPES",
    "HUMAN_JUDGMENT_TYPES",
    "SEVERITIES",
    "WAIVABLE_TYPES",
    "FindingWriter",
    "blocking_findings",
    "category_rank",
    "current_findings",
    "finding_view",
    "findings_for",
    "is_waived",
    "primary_finding",
    "resolve_replaced_findings",
    "supersede_findings_before",
    "waiver_snapshot",
]

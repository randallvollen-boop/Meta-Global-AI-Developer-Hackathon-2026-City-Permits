"""The findings an agent records on a case.

A finding is evidence for a person: what is wrong, the rule that applies,
what the applicant must do and whether it blocks the case or only asks a
person to look.  A finding never decides anything and never approves.
"""
# REQUIRES: PER-04, AI-03
# Every finding names its type, its rule, the line the applicant must satisfy
# and whether it blocks the case.

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.core.ids import new_id
from acme_city.persistence.models import permit

#: The finding types an agent may record.
FINDING_TYPES: tuple[str, ...] = (
    "missing_field",
    "missing_document",
    "unreadable",
    "duplicate",
    "conflict",
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


class FindingWriter:
    """Writes the findings of one agent run."""

    def __init__(
        self,
        session: Session,
        *,
        application_id: str,
        correlation_id: str,
        source_node: str = "",
    ) -> None:
        self._session = session
        self._application_id = application_id
        self._correlation_id = correlation_id
        self._source_node = source_node
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
    }


__all__ = [
    "FINDING_TYPES",
    "HUMAN_JUDGMENT_TYPES",
    "SEVERITIES",
    "FindingWriter",
    "finding_view",
    "findings_for",
]

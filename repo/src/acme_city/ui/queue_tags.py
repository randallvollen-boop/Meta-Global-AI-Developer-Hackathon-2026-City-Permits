"""Recommendation tags for the work queue and the review queue.

Each tag is one compact pill: what an agent recommends, or why it cannot.
The tooltip sentence comes from ``plain_reason`` only, so a shared helper
can replace that function later without a search through the queues.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.kernel.findings import FindingSpec
from acme_city.kernel.intake import route
from acme_city.persistence.models import gis, permit

#: Display order. The tone is the pill colour already used on these screens.
TAGS: tuple[tuple[str, str, str], ...] = (
    ("agent_approve", "Agent: approve", "ok"),
    ("agent_deny", "Agent: deny", "bad"),
    ("agent_verify", "Agent: verify", "warn"),
    ("intake_early", "Intake: early resolution", "warn"),
    ("intake_duplicate", "Intake: duplicate?", "warn"),
    ("parcel_unconfirmed", "Cannot recommend: parcel not confirmed", "bad"),
)
TAG_KEYS = frozenset(key for key, _label, _tone in TAGS)
_TAG_BY_KEY = {key: (label, tone) for key, label, tone in TAGS}

#: Adjudication outcomes, including approval with conditions, as one pill.
_AGENT = {
    "approve": "agent_approve",
    "approve_with_conditions": "agent_approve",
    "deny": "agent_deny",
    "hold": "agent_verify",
}

#: A parcel link that exists and is not yet confirmed by the reviewer.
_PARCEL_OPEN = frozenset({"proposed", "approved", "needs_choice"})


def normalize_tag(value: str | None) -> str:
    """Return a known tag key, or nothing when the value is not one."""
    key = " ".join(str(value or "").split())
    return key if key in TAG_KEYS else ""


def plain_reason(*parts: str) -> str:
    """Return one short sentence from a reason or a rule message.

    This is the only place a queue tag looks up that sentence. A shared
    plain-reason helper can replace the body later.
    """
    for part in parts:
        text = " ".join(str(part or "").split())
        if not text:
            continue
        for index, char in enumerate(text):
            if char in ".?!" and (index + 1 == len(text) or text[index + 1].isspace()):
                return text[: index + 1]
        return text
    return ""


def _tag(key: str, title: str) -> dict[str, str]:
    label, tone = _TAG_BY_KEY[key]
    return {"key": key, "label": label, "tone": tone, "title": title}


def _agent_tag(recommendation: permit.Recommendation) -> dict[str, str] | None:
    key = _AGENT.get(str(recommendation.proposed_outcome or ""))
    if key is None:
        return None
    messages: list[str] = []
    for ref in recommendation.evidence_refs or []:
        if isinstance(ref, dict):
            messages.append(str(ref.get("message") or ""))
    return _tag(key, plain_reason(str(recommendation.rationale or ""), *messages))


def _finding_specs(findings: list[permit.ApplicationFinding]) -> list[FindingSpec]:
    specs: list[FindingSpec] = []
    for finding in findings:
        try:
            specs.append(
                FindingSpec(
                    finding_type=finding.finding_type,
                    message=finding.message,
                    rule=finding.rule,
                    applicant_must=finding.applicant_must,
                    severity=finding.severity or "review",
                )
            )
        except ValueError:
            continue
    return specs


def _intake_tags(
    status: str, findings: list[permit.ApplicationFinding]
) -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    if status == "needs_information":
        specs = _finding_specs(findings)
        routed = route(specs, None).reason if specs else ""
        tags.append(
            _tag(
                "intake_early",
                plain_reason(routed, *(finding.message for finding in findings)),
            )
        )
    for finding in findings:
        if finding.finding_type == "duplicate":
            tags.append(_tag("intake_duplicate", plain_reason(finding.message)))
            break
    return tags


def _parcel_tag(match: gis.ApplicationParcelMatch | None) -> dict[str, str] | None:
    if match is None or match.confirmed_at is not None:
        return None
    if match.link_state not in _PARCEL_OPEN:
        return None
    if match.link_state == "approved":
        detail = "the Permit Reviewer has not confirmed that this is the right property"
    else:
        detail = (
            "the parcel link proposed by the address locator has not been approved "
            "by the Data Steward"
        )
    # The second sentence is the one the adjudication agent records when it
    # cannot read the parcel. ``plain_reason`` keeps the first real sentence.
    return _tag(
        "parcel_unconfirmed",
        plain_reason(detail, "The parcel is not confirmed yet, so none were used."),
    )


def tags_for(
    *,
    status: str,
    recommendation: permit.Recommendation | None,
    findings: list[permit.ApplicationFinding],
    parcel_match: gis.ApplicationParcelMatch | None,
) -> list[dict[str, str]]:
    """Return the tags of one case, in display order."""
    tags: list[dict[str, str]] = []
    if recommendation is not None and recommendation.status != "superseded":
        agent = _agent_tag(recommendation)
        if agent is not None:
            tags.append(agent)
    tags.extend(_intake_tags(status, findings))
    parcel = _parcel_tag(parcel_match)
    if parcel is not None:
        tags.append(parcel)
    order = {key: index for index, (key, _label, _tone) in enumerate(TAGS)}
    tags.sort(key=lambda tag: order[tag["key"]])
    return tags


def tag_chips(
    rows: list[list[dict[str, str]]], href_for: Any
) -> list[dict[str, Any]]:
    """Return a chip for every tag that at least one row carries."""
    counts: dict[str, int] = defaultdict(int)
    for tags in rows:
        seen: set[str] = set()
        for tag in tags:
            key = tag["key"]
            if key in seen:
                continue
            seen.add(key)
            counts[key] += 1
    chips: list[dict[str, Any]] = []
    for key, label, tone in TAGS:
        count = counts.get(key, 0)
        if count <= 0:
            continue
        chips.append(
            {
                "key": key,
                "label": label,
                "tone": tone,
                "count": count,
                "href": href_for(key),
            }
        )
    return chips


def load_tags(session: Session, cases: list[tuple[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Return the tags of each case.

    ``cases`` is ``(application id, status)``. A superseded recommendation
    is ignored. The newest remaining recommendation is the one shown.
    """
    ids = [application_id for application_id, _status in cases if application_id]
    if not ids:
        return {}
    latest: dict[str, permit.Recommendation] = {}
    recommendations = session.execute(
        select(permit.Recommendation)
        .where(permit.Recommendation.application_id.in_(ids))
        .order_by(permit.Recommendation.created_at.desc(), permit.Recommendation.id.desc())
    ).scalars()
    for recommendation in recommendations:
        if recommendation.status == "superseded":
            continue
        latest.setdefault(recommendation.application_id, recommendation)
    grouped: dict[str, list[permit.ApplicationFinding]] = defaultdict(list)
    findings = session.execute(
        select(permit.ApplicationFinding)
        .where(
            permit.ApplicationFinding.application_id.in_(ids),
            permit.ApplicationFinding.state == "current",
        )
        .order_by(permit.ApplicationFinding.created_at, permit.ApplicationFinding.id)
    ).scalars()
    for finding in findings:
        grouped[finding.application_id].append(finding)
    matches = {
        match.application_id: match
        for match in session.execute(
            select(gis.ApplicationParcelMatch).where(
                gis.ApplicationParcelMatch.application_id.in_(ids)
            )
        ).scalars()
    }
    return {
        application_id: tags_for(
            status=status,
            recommendation=latest.get(application_id),
            findings=grouped.get(application_id, []),
            parcel_match=matches.get(application_id),
        )
        for application_id, status in cases
        if application_id
    }


__all__ = [
    "TAG_KEYS",
    "TAGS",
    "load_tags",
    "normalize_tag",
    "plain_reason",
    "tag_chips",
    "tags_for",
]

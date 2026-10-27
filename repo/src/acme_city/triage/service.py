"""The shared recommendation helpers.

The intake agent and the adjudication agent each write their own run trace,
but they share the way a recommendation is explained: the outcome comes only
from the deterministic rule results, and the rationale cites each rule once,
with its observed value, its unit, its limit and its citation.

The pipeline itself no longer lives here.  Build 2 ran one fixed chain on
arrival; the two agents of the demonstration are graphs a person runs, and
they live in :mod:`acme_city.agents`.
"""
# REQUIRES: PER-04, AI-04
# The outcome comes only from the deterministic rule results, and the
# rationale cites each rule with its observed value, its unit and its limit.

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import permit

#: The recommendation statuses.
STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_REVERTED = "reverted"
STATUS_SUPERSEDED = "superseded"


def service_actor(session: Session, actor_id: str) -> ActorContext:
    """Return the server-resolved context of a seeded service identity."""
    from acme_city.auth.permissions import PermissionResolver

    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        role_ids=frozenset(),
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record for grant in grants for record in grant.record_scope
        ),
    )


def recommendation_outcome(results: list[dict[str, Any]]) -> str:
    """Return the deterministic recommendation outcome of rule results.

    Any ``fail`` denies (or requests information when the failure comes from
    missing/blank inputs); any ``condition`` approves with conditions; any
    ``review`` (the evaluator's judgment state) needs reviewer judgment; all
    pass approves.
    """
    statuses = [str(r.get("status", "")) for r in results]
    reasons = [str(r.get("reason", "")) for r in results]
    if "fail" in statuses:
        fail_reasons = [
            reason for status, reason in zip(statuses, reasons) if status == "fail"
        ]
        if fail_reasons and all(
            reason in {"missing_input", "missing_condition_input"} for reason in fail_reasons
        ):
            return "request_information"
        return "deny"
    if "condition" in statuses:
        return "approve_with_conditions"
    if "review" in statuses:
        review_reasons = [
            reason for status, reason in zip(statuses, reasons) if status == "review"
        ]
        if review_reasons and all(
            reason in {"missing_input", "missing_condition_input"} for reason in review_reasons
        ):
            return "request_information"
        return "needs_reviewer_judgment"
    return "approve"


def _with_unit(value: Any, unit: str | None) -> str:
    """Return the observed or limit value with its unit."""
    if value is None:
        return ""
    text = str(value).strip()
    if not unit:
        return text
    unit = unit.strip()
    if not unit:
        return text
    if text.lower().endswith(unit.lower()):
        return text
    return f"{text} {unit}"


#: The units a field name may carry.  The field name is the only place a
#: baseline rule states its unit, so the unit is read from the name and a
#: rationale never leaves a bare number where a measurement belongs.
FIELD_UNITS: tuple[tuple[str, str], ...] = (
    ("_sqft", "sq ft"),
    ("_sqm", "sq m"),
    ("_ft", "ft"),
    ("_pct", "%"),
    ("_days", "days"),
    ("_hours", "hours"),
)


def unit_for_field(field_path: str | None) -> str | None:
    """Return the unit a field name carries, when it carries one."""
    if not field_path:
        return None
    name = str(field_path).strip().lower()
    for suffix, unit in FIELD_UNITS:
        if name.endswith(suffix):
            return unit
    return None


def build_rationale(
    results: list[dict[str, Any]],
    outcome: str,
    units: dict[str, str] | None = None,
) -> str:
    """Return the plain-language rationale citing each rule once.

    Each applicable rule is cited with its observed value and its limit, for
    example "DF-1: front-yard fence 6 ft is above the 4 ft maximum, ACME
    Code §14-305".  A rule that carries a unit is stated with that unit, so
    a rationale never leaves a bare number where a measurement belongs.
    """
    unit_map = units or {}
    lines: list[str] = []
    for result in results:
        rule_id = str(result.get("rule_id", "rule"))
        citation = str(result.get("citation", ""))
        status = str(result.get("status", ""))
        operator = str(result.get("operator", ""))
        unit = (
            unit_map.get(rule_id)
            or result.get("unit")
            or unit_for_field(result.get("field_path"))
        )
        observed = _with_unit(result.get("observed_value"), unit)
        limit = _with_unit(result.get("limit_value"), unit)
        message = str(result.get("message") or result.get("detail") or "")
        if status == "pass":
            lines.append(
                f"{rule_id}: passed (observed {observed}, limit {limit}, {citation})."
            )
        elif status == "fail" and operator == "required":
            lines.append(
                f"{rule_id}: {message} No value was supplied for "
                f"{result.get('field_path')}, {citation}."
            )
        elif status == "fail":
            relation = (
                "above" if operator == "max" else "below" if operator == "min" else "differs from"
            )
            bound = "maximum" if operator == "max" else "minimum" if operator == "min" else "limit"
            lines.append(
                f"{rule_id}: {message} Observed {observed} is {relation} the {limit} "
                f"{bound}, {citation}."
            )
        elif status == "condition":
            lines.append(
                f"{rule_id}: condition applies (observed {observed}, limit {limit}, "
                f"{citation}). {result.get('condition_note') or message}"
            )
        else:
            lines.append(
                f"{rule_id}: needs reviewer judgment (observed {observed}, limit "
                f"{limit}, {citation}). {message}"
            )
    if not lines:
        lines.append("No executable rule applied to the submitted facts.")
    return " ".join(lines)


def list_steps(session: Session, application_id: str) -> list[agent_models.AgentStep]:
    """Return the recorded agent steps of one application, in run order."""
    return list(
        session.execute(
            select(agent_models.AgentStep)
            .where(agent_models.AgentStep.application_id == application_id)
            .order_by(agent_models.AgentStep.created_at, agent_models.AgentStep.id)
        ).scalars().all()
    )


def current_recommendation(
    session: Session, application_id: str
) -> permit.Recommendation | None:
    """Return the pending advisory recommendation of an application."""
    return session.execute(
        select(permit.Recommendation)
        .where(
            permit.Recommendation.application_id == application_id,
            permit.Recommendation.status == STATUS_PENDING,
        )
        .order_by(permit.Recommendation.created_at.desc())
    ).scalars().first()


__all__ = [
    "FIELD_UNITS",
    "STATUS_CONFIRMED",
    "STATUS_PENDING",
    "STATUS_REVERTED",
    "STATUS_SUPERSEDED",
    "build_rationale",
    "current_recommendation",
    "list_steps",
    "recommendation_outcome",
    "service_actor",
    "unit_for_field",
]

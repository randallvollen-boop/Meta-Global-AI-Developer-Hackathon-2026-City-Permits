"""Score one frozen case under one frozen configuration.

``evaluate_case`` is a pure function.  It runs the same intake producers, the
same rule evaluator and the same disposition that the agents run in
production, over a :class:`CaseInput`, and returns a :class:`CaseOutcome`.  It
reads no row, records no finding and changes no status.
"""
# REQUIRES: AI-03, PER-02, PER-04, REF-01
# The simulation scores a case with the production kernels and records nothing.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from acme_city.kernel import adjudication as adjudication_kernel
from acme_city.kernel import intake as intake_kernel
from acme_city.kernel.findings import FindingSpec
from acme_city.kernel.inputs import build_inputs, missing_required_fields
from acme_city.kernel.selection import select_schedule_for_type
from acme_city.policy.config import PolicyConfig
from acme_city.policy.population import CaseInput
from acme_city.rules.evaluator import evaluate, overall_status

RulesAt = Literal["analysis", "case"]

#: A decision always belongs to a person.  This is a constant of the outcome,
#: not a value any change can turn off.
HUMAN_DECISION_REQUIRED = True


class UnknownPermitType(ValueError):
    """Raised when a case names a permit type the configuration does not hold."""


@dataclass(frozen=True)
class CaseOutcome:
    """The outcome of one case under one configuration."""

    case_ref: str
    permit_type_key: str
    #: Where the intake router sends the case.
    route_status: str
    route_reason: str
    findings: tuple[FindingSpec, ...]
    missing_fields: tuple[str, ...]
    missing_documents: tuple[str, ...]
    #: Evaluated rule results (JSON-ready dictionaries), in catalogue order.
    rule_results: tuple[dict[str, Any], ...]
    rule_overall: str
    rule_count: int
    #: The inputs the evaluator was given.
    inputs: tuple[tuple[str, Any], ...]
    #: Required inputs that were missing at evaluation (blockers of the evaluation).
    missing_required_inputs: tuple[str, ...]
    #: Site, identity, credential and finance safeguards; never policy-dependent.
    safeguards: tuple[str, ...]
    #: Findings the adjudication rule loader records for a held type.
    hold_findings: tuple[FindingSpec, ...]
    conditions: tuple[str, ...]
    recommendation: str
    recommendation_reason: str
    hold_reason: str | None
    human_decision_required: bool = HUMAN_DECISION_REQUIRED

    @property
    def is_hold(self) -> bool:
        return self.recommendation == adjudication_kernel.OUTCOME_HOLD

    @property
    def needs_information(self) -> bool:
        return self.route_status == "needs_information"

    @property
    def all_findings(self) -> tuple[FindingSpec, ...]:
        return self.findings + self.hold_findings

    def failing_rules(self) -> tuple[str, ...]:
        return tuple(str(r["rule_id"]) for r in self.rule_results if r.get("status") == "fail")

    def canonical(self) -> dict[str, Any]:
        return {
            "case_ref": self.case_ref,
            "permit_type_key": self.permit_type_key,
            "route_status": self.route_status,
            "findings": [
                [f.finding_type, f.message, f.rule, f.severity, f.related_application_id]
                for f in self.findings
            ],
            "missing_fields": list(self.missing_fields),
            "missing_documents": list(self.missing_documents),
            "rule_results": [dict(r) for r in self.rule_results],
            "rule_overall": self.rule_overall,
            "missing_required_inputs": list(self.missing_required_inputs),
            "safeguards": list(self.safeguards),
            "hold_findings": [
                [f.finding_type, f.message, f.rule, f.severity] for f in self.hold_findings
            ],
            "conditions": list(self.conditions),
            "recommendation": self.recommendation,
            "hold_reason": self.hold_reason,
            "human_decision_required": self.human_decision_required,
        }


def evaluate_case(
    case: CaseInput, config: PolicyConfig, *, rules_at: RulesAt = "analysis"
) -> CaseOutcome:
    """Score ``case`` under ``config``.

    ``rules_at="analysis"`` selects the rules in force at the configuration's
    ``analysis_at`` (a retrospective re-score under one effective
    configuration).  ``rules_at="case"`` selects them at the case's own basis
    date, exactly as production does, for parity checks.
    """
    permit_type = config.type_config(case.permit_type_key)
    if permit_type is None:
        raise UnknownPermitType(case.permit_type_key)
    intake_record = case.intake_map
    facts = case.facts_map

    # --- intake: the same producers the intake agent calls -----------------
    schedule = select_schedule_for_type(config.fee_schedules, case.basis_at, permit_type.key)
    requirements_snapshot = case.requirements_map
    classified = intake_kernel.classify_type(
        permit_type.facts(),
        channel=str(intake_record.get("channel") or "unknown"),
        declared_type_key=str(intake_record.get("permit_type_key") or ""),
        fee_schedule_id=(
            None
            if schedule is None or not permit_type.fee_schedule_key
            else schedule.fee_schedule_id
        ),
        requirements_review_area=str((requirements_snapshot or {}).get("review_area") or ""),
    )
    quality = intake_kernel.document_quality(
        (document.document_type, document.quality) for document in case.documents
    )
    requirements = intake_kernel.requirements_of(
        requirements_snapshot, permit_type.required_fields, permit_type.required_documents
    )
    completeness = intake_kernel.completeness(
        type_key=permit_type.key,
        required_fields=requirements["required_fields"],
        required_documents=requirements["required_documents"],
        facts=facts,
        present_document_types={document.document_type for document in case.documents},
    )
    findings: list[FindingSpec] = list(classified.findings)
    findings.extend(case.carried_findings)
    findings.extend(quality.findings)
    findings.extend(completeness.findings)
    if case.duplicate_of is not None:
        reference, number = case.duplicate_of
        findings.append(intake_kernel.duplicate_finding(number, reference))
    routed = intake_kernel.route(findings, classified.review_area)

    # --- adjudication: the same evaluator and disposition -------------------
    inputs = build_inputs(facts, strict=False)
    inputs.update(case.parcel_map)
    moment = config.analysis_at if rules_at == "analysis" else case.basis_at
    rule_set = config.rule_set(permit_type.key, moment)
    results = evaluate(inputs, rule_set)
    result_rows = [result.model_dump(mode="json") for result in results]
    missing_inputs = missing_required_fields(permit_type.required_fields, inputs)
    conditions = adjudication_kernel.conditions_of(result_rows)
    holds = adjudication_kernel.hold_findings(
        type_label=permit_type.label,
        discretionary=permit_type.discretionary,
        rule_count=len(rule_set.rules),
    )
    chosen = adjudication_kernel.disposition(
        type_label=permit_type.label,
        discretionary=permit_type.discretionary,
        rule_count=len(rule_set.rules),
        results=result_rows,
        conditions=conditions,
        precedent_outcome=case.precedent_outcome,
    )
    return CaseOutcome(
        case_ref=case.case_ref,
        permit_type_key=permit_type.key,
        route_status=routed.status,
        route_reason=routed.reason,
        findings=tuple(findings),
        missing_fields=completeness.missing_fields,
        missing_documents=completeness.missing_documents,
        rule_results=tuple(result_rows),
        rule_overall=overall_status(results),
        rule_count=len(rule_set.rules),
        inputs=tuple(sorted(inputs.items(), key=lambda pair: pair[0])),
        missing_required_inputs=tuple(missing_inputs),
        safeguards=tuple(case.safeguard_blockers),
        hold_findings=holds,
        conditions=tuple(conditions),
        recommendation=chosen.outcome,
        recommendation_reason=chosen.reason,
        hold_reason=chosen.hold_reason,
    )


__all__ = [
    "HUMAN_DECISION_REQUIRED",
    "CaseOutcome",
    "RulesAt",
    "UnknownPermitType",
    "evaluate_case",
]

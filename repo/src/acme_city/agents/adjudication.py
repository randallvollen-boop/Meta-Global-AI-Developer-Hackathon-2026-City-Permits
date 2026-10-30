"""The adjudication agent.

The adjudication agent is a second dependency graph:

1. the rule loader finds the published rules of the permit type and flags a
   discretionary type;
2. the rule evaluator runs the existing deterministic evaluator;
3. in parallel, the condition builder collects the conditions of approval and
   the precedent check looks for an earlier decided case of the same type on
   the same parcel;
4. the disposition chooses the recommendation: hold, deny, approve with
   conditions, or approve.

The agent recommends.  A person with the ``permit.decide`` grant confirms or
reverts the recommendation, and only that person becomes the decider of
record.
"""
# REQUIRES: AI-03, AI-04, PER-04, REF-01, REF-02
# The disposition comes only from the deterministic rule results, the
# rationale cites each rule once, and a discretionary type is always held for
# a person.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.agents import graphs
from acme_city.agents.control import AgentControlService
from acme_city.agents.intake import service_actor
from acme_city.agents.findings import FindingWriter
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.core.clock import utc_now
from acme_city.core.ids import new_id
from acme_city.kernel import adjudication as kernel
from acme_city.kernel.adjudication import (
    OUTCOME_APPROVE,
    OUTCOME_CONDITIONS,
    OUTCOME_DENY,
    OUTCOME_HOLD,
)
from acme_city.permits.guard import require_mutable, require_not_returned
from acme_city.permits.service import PermitService
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import permit
from acme_city.rules.catalog import select_rule_versions, version_label as rule_version_label
from acme_city.triage.service import build_rationale, unit_for_field

#: The service identity the adjudication agent acts as.
ADJUDICATION_AGENT_ID = "service_agent_adjudication"

#: The recommendation statuses.
STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_REVERTED = "reverted"
#: A recommendation that a later revision of the case made advisory only.
STATUS_SUPERSEDED = "superseded"


class AdjudicationAgent:
    """Runs the adjudication graph on one application."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Any = None,
        now: datetime | None = None,
        live_muse: bool = False,
        muse_client: Any = None,
        document_root: Any = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._now = now or utc_now()
        self._live_muse = live_muse
        self._muse_client = muse_client
        self._document_root = document_root
        self._audit = AuditService(session, now=self._now)
        self._control = AgentControlService(session, now=self._now)

    # ------------------------------------------------------------------ public

    def run(
        self,
        application_id: str,
        *,
        triggered_by: str,
        work_id: str | None = None,
        require_awake: bool = True,
    ) -> agent_models.AgentRun:
        """Run the adjudication graph on one application.

        The ``work_id`` names the row of the work queue this run is the
        attempt of, so the queue and the run evidence name each other.  The
        automatic worker passes ``require_awake=False``: the processing
        policy of the City is the authority of that run.
        """
        if require_awake:
            self._control.require_awake(agent_models.AGENT_ADJUDICATION)
        permits = PermitService(self._session, now=self._now)
        application = permits.load_application(application_id)
        # An archived case is closed: no agent may reopen it.
        require_mutable(application, action="running the adjudication agent")
        # A returned case is terminal: it is not adjudicated again.
        require_not_returned(application, action="running the adjudication agent")
        correlation_id = application.correlation_id or new_id("corr")
        run = agent_models.AgentRun(
            id=new_id("agentrun"),
            correlation_id=correlation_id,
            agent_key=agent_models.AGENT_ADJUDICATION,
            application_id=application.id,
            service_identity_id=ADJUDICATION_AGENT_ID,
            triggered_by=triggered_by,
            started_at=self._now,
            finished_at=None,
            outcome="recorded",
            inputs={
                "permit_type_id": application.permit_type_id,
                **({"work_id": work_id} if work_id else {}),
            },
        )
        self._session.add(run)
        self._session.flush()

        actor = service_actor(self._session, ADJUDICATION_AGENT_ID)
        findings = FindingWriter(
            self._session,
            application_id=application.id,
            correlation_id=correlation_id,
            revision_number=application.revision,
            run_id=run.id,
        )

        rules = self._node_rule_loader(run, application, findings)
        results = self._node_rule_evaluator(run, application, actor)
        conditions = self._node_condition_builder(run, results)
        precedent = self._node_precedent_check(run, application, findings)
        self._node_disposition(run, application, rules, results, conditions, precedent)

        run.finished_at = utc_now()
        self._session.flush()
        return run

    def candidates(self) -> list[permit.Application]:
        """Return the cases the adjudication agent may run on.

        A case is a candidate when it is in review and carries no pending
        recommendation.
        """
        pending = {
            row.application_id
            for row in self._session.execute(
                select(permit.Recommendation).where(
                    permit.Recommendation.status == STATUS_PENDING
                )
            ).scalars().all()
        }
        rows = self._session.execute(
            select(permit.Application)
            .where(
                permit.Application.status.in_(["ready_for_review", "under_review"]),
                permit.Application.scenario_id.is_(None),
            )
            .order_by(permit.Application.source_application_number)
        ).scalars().all()
        return [row for row in rows if row.id not in pending]

    # ------------------------------------------------------------------- nodes

    def _begin(
        self, run: agent_models.AgentRun, node: graphs.GraphNode
    ) -> agent_models.AgentRunNode:
        """Record the start of one node of the graph."""
        row = agent_models.AgentRunNode(
            id=new_id("agentnode"),
            agent_run_id=run.id,
            node_id=node.node_id,
            label=node.label,
            dependency_level=node.level,
            status="ok",
            note="",
            position=node.position,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def _finish(
        self,
        run: agent_models.AgentRun,
        row: agent_models.AgentRunNode,
        *,
        status: str,
        note: str,
        actor: ActorContext | None = None,
    ) -> None:
        """Record the outcome of one node of the graph."""
        row.status = status
        row.note = note
        self._session.flush()
        self._audit.append(
            action=f"agent.adjudication.{row.node_id}",
            actor=actor or ADJUDICATION_AGENT_ID,
            target_type="application",
            target_id=run.application_id or "",
            reason=note,
            references=[run.id],
            correlation_id=run.correlation_id,
            metadata={
                "agent": agent_models.AGENT_ADJUDICATION,
                "node_id": row.node_id,
                "status": status,
            },
        )

    def _node_rule_loader(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        findings: FindingWriter,
    ) -> list[LoadedRule]:
        """Find the published rules of the permit type."""
        node = graphs.ADJUDICATION_GRAPH[0]
        row = self._begin(run, node)
        permits = PermitService(self._session, now=self._now)
        permit_type = permits.permit_type(application)
        revision = permits.current_revision(application.id)
        basis_at = application.initial_submitted_at or revision.submitted_at
        rows = select_rule_versions(self._session, permit_type.id, basis_at)
        rules = [
            LoadedRule(
                rule_id=item.rule_id,
                version_label=rule_version_label(item),
                citation=item.citation,
                title=item.title,
                unit=(item.source_mapping or {}).get("unit"),
            )
            for item in rows
        ]
        notes = [
            f"Loaded {len(rules)} published rule(s) for {permit_type.key}: "
            + (", ".join(rule.rule_id for rule in rules) or "none")
            + "."
        ]
        status = "ok"
        from acme_city.gis.matching import ParcelMatchService

        parcel_service = ParcelMatchService(self._session, now=self._now)
        if parcel_service.for_application(application.id) is not None:
            confirmed = parcel_service.confirmed_parcel(application.id)
            if confirmed is not None:
                notes.append(
                    f"Parcel inputs come from the confirmed parcel {confirmed.source_parcel_number}: "
                    f"zoning {confirmed.zoning_code}, flood zone {confirmed.flood_zone}."
                )
            else:
                status = "warn"
                notes.append(
                    "Parcel inputs (zoning, flood zone) are read from the confirmed parcel "
                    "only. The parcel is not confirmed yet, so none were used."
                )
        if permit_type.discretionary:
            status = "warn"
            notes.append(
                f"{permit_type.label} is a discretionary type and is held for a person "
                "or a board."
            )
        if not rules:
            notes.append("The type has no published rule, so the case is held.")
        findings.add_specs(
            kernel.hold_findings(
                type_label=permit_type.label,
                discretionary=bool(permit_type.discretionary),
                rule_count=len(rules),
            )
        )
        self._finish(run, row, status=status, note=" ".join(notes))
        return rules

    def _node_rule_evaluator(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        actor: ActorContext,
    ) -> list[dict[str, Any]]:
        """Run the deterministic evaluator against the submitted facts."""
        node = graphs.ADJUDICATION_GRAPH[1]
        row = self._begin(run, node)
        permits = PermitService(self._session, now=self._now)
        previous_status = application.status
        try:
            permits.evaluate(application.id, actor)
        except Exception as exc:  # noqa: BLE001 - a failed node is recorded
            self._finish(
                run,
                row,
                status="warn",
                note=f"The rule evaluation failed: {exc}",
                actor=actor,
            )
            return []
        evaluation = permits.current_evaluation(application.id)
        results = [dict(item) for item in (evaluation.results or [])] if evaluation else []
        if previous_status == "under_review":
            application.status = "under_review"
            self._session.flush()
        statuses = ", ".join(
            f"{item.get('rule_id')} {item.get('status')}" for item in results
        )
        self._finish(
            run,
            row,
            status="ok",
            note=(
                f"The deterministic evaluator returned {len(results)} result(s): "
                f"{statuses or 'none'}."
            ),
            actor=actor,
        )
        return results

    def _node_condition_builder(
        self, run: agent_models.AgentRun, results: list[dict[str, Any]]
    ) -> list[str]:
        """Collect the conditions of approval from the condition results."""
        node = graphs.ADJUDICATION_GRAPH[2]
        row = self._begin(run, node)
        conditions = kernel.conditions_of(results)
        self._finish(
            run,
            row,
            status="ok",
            note=(
                f"Collected {len(conditions)} condition(s) of approval."
                if conditions
                else "No condition of approval applies."
            ),
        )
        return conditions

    def _node_precedent_check(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        findings: FindingWriter,
    ) -> dict[str, Any] | None:
        """Find an earlier decided case of the same type on the same parcel."""
        node = graphs.ADJUDICATION_GRAPH[3]
        row = self._begin(run, node)
        parcel = self._parcel_of(application)
        precedent: dict[str, Any] | None = None
        if parcel:
            rows = self._session.execute(
                select(permit.Decision)
                .where(permit.Decision.status == "current")
                .order_by(permit.Decision.decided_at)
            ).scalars().all()
            for decision in rows:
                other = self._session.get(permit.Application, decision.application_id)
                if other is None or other.id == application.id:
                    continue
                if other.permit_type_id != application.permit_type_id:
                    continue
                if decision.decided_at is not None and decision.decided_at >= self._now:
                    continue
                if self._parcel_of(other) != parcel:
                    continue
                precedent = {
                    "application_id": other.id,
                    "source_application_number": other.source_application_number,
                    "decision_id": decision.id,
                    "outcome": decision.outcome,
                    "decided_at": decision.decided_at.isoformat()
                    if decision.decided_at
                    else "",
                    "decided_by_actor_id": decision.decided_by_actor_id,
                }
                break
        if precedent is not None:
            findings.add(
                finding_type="judgment",
                message=(
                    f"{precedent['source_application_number']} on the same parcel was "
                    f"already {precedent['outcome']}."
                ),
                rule="ACME Code §13-604",
                applicant_must="Wait for a person to compare the two cases.",
                severity="review",
                related_application_id=precedent["application_id"],
            )
            self._finish(
                run,
                row,
                status="warn",
                note=(
                    f"Found an earlier decided case on the same parcel: "
                    f"{precedent['source_application_number']} "
                    f"({precedent['outcome']})."
                ),
            )
            return precedent
        self._finish(run, row, status="ok", note="No earlier decided case on this parcel.")
        return None

    def _node_disposition(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        rules: list[LoadedRule],
        results: list[dict[str, Any]],
        conditions: list[str],
        precedent: dict[str, Any] | None,
    ) -> permit.Recommendation:
        """Choose the recommendation and record it."""
        node = graphs.ADJUDICATION_GRAPH[4]
        row = self._begin(run, node)
        permits = PermitService(self._session, now=self._now)
        permit_type = permits.permit_type(application)
        explicit_units = {rule.rule_id: rule.unit for rule in rules if rule.unit}
        units: dict[str, str] = {}
        for result in results:
            rule_id = str(result.get("rule_id") or "")
            units[rule_id] = (
                explicit_units.get(rule_id)
                or unit_for_field(result.get("field_path"))
                or ""
            )
        rationale = build_rationale(results, "", units=units)

        chosen = kernel.disposition(
            type_label=permit_type.label,
            discretionary=bool(permit_type.discretionary),
            rule_count=len(rules),
            results=results,
            conditions=conditions,
            precedent_outcome=None if precedent is None else str(precedent["outcome"]),
        )
        outcome = chosen.outcome
        reason = chosen.reason

        # A pending recommendation of an earlier run is superseded, so the
        # case never carries two live recommendations.
        for row in self._session.execute(
            select(permit.Recommendation).where(
                permit.Recommendation.application_id == application.id,
                permit.Recommendation.status == STATUS_PENDING,
            )
        ).scalars().all():
            row.status = "superseded"
            row.version += 1

        recommendation = permit.Recommendation(
            id=new_id("rec"),
            application_id=application.id,
            evaluation_id=(
                permits.current_evaluation(application.id).id
                if permits.current_evaluation(application.id)
                else None
            ),
            proposed_outcome=outcome,
            evidence_refs=[
                {
                    "rule_id": result.get("rule_id"),
                    "citation": result.get("citation"),
                    "status": result.get("status"),
                    "observed_value": result.get("observed_value"),
                    "limit_value": result.get("limit_value"),
                    "unit": units.get(str(result.get("rule_id"))),
                    "message": result.get("message") or "",
                    "condition_note": result.get("condition_note") or "",
                }
                for result in results
            ],
            run_ref=run.id,
            status=STATUS_PENDING,
            rationale=f"{reason} {rationale}".strip(),
            muse_summary=None,
            muse_run_id=None,
            conditions=list(conditions),
        )
        self._session.add(recommendation)
        self._session.flush()
        run.outcome = "held" if outcome == OUTCOME_HOLD else "recommended"
        run.outcome_detail = reason
        self._finish(run, row, status="ok", note=f"{reason} The recommendation is pending.")
        return recommendation

    # ----------------------------------------------------------------- helpers

    def _parcel_of(self, application: permit.Application) -> str:
        """Return the parcel reference of one application."""
        facts = dict(application.submitted_facts or {})
        return str(
            facts.get("parcel_number") or facts.get("submitted_parcel") or ""
        ).strip().lower()


class LoadedRule:
    """One loaded rule of the adjudication agent.

    The rule is a small carrier: the agent needs its identifier, its
    citation and its unit, not the whole catalogue row.
    """

    __slots__ = ("rule_id", "version_label", "citation", "title", "unit")

    def __init__(
        self,
        *,
        rule_id: str,
        version_label: str,
        citation: str,
        title: str,
        unit: str | None,
    ) -> None:
        self.rule_id = rule_id
        self.version_label = version_label
        self.citation = citation
        self.title = title
        self.unit = unit


__all__ = [
    "ADJUDICATION_AGENT_ID",
    "OUTCOME_APPROVE",
    "OUTCOME_CONDITIONS",
    "OUTCOME_DENY",
    "OUTCOME_HOLD",
    "STATUS_CONFIRMED",
    "STATUS_PENDING",
    "STATUS_REVERTED",
    "STATUS_SUPERSEDED",
    "AdjudicationAgent",
    "LoadedRule",
]

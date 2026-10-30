"""The intake agent.

The intake agent is a dependency graph of six nodes:

1. the classifier confirms the permit type and the channel and sets the
   review area;
2. in parallel, the field extractor proposes values from the received
   documents (Muse Spark, replay by default) and the document QC flags the
   scan-quality problems the intake record carried;
3. in parallel, the duplicate finder looks for a duplicate case and proposes
   the identity links, and the completeness check compares the case with the
   required fields and documents of the type;
4. the router routes the case to early resolution or to review.

The agent only proposes.  It never approves a permit, never sets money and
never issues anything, and it only runs when a person runs it.
"""
# REQUIRES: AI-03, AI-04, PER-01, PER-04, REF-01
# Every node of the graph is recorded with its outcome, the findings it wrote
# are evidence for a person, and the router only routes.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.agents import graphs
from acme_city.agents.control import AgentControlService
from acme_city.agents.extraction import builtin_extraction
from acme_city.agents.findings import FindingWriter, resolve_replaced_findings
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.documents.service import DocumentService
from acme_city.gis.matching import (
    AMBIGUOUS_MESSAGE,
    NOT_FOUND_MESSAGE,
    ParcelMatchService,
)
from acme_city.permits.guard import require_mutable, require_not_returned
from acme_city.permits.service import PermitService
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import permit, registry
from acme_city.registry.candidates import generate_candidates
from acme_city.registry.schemas import MatchProposalCommand
from acme_city.registry.service import RegistryService
from acme_city.kernel import intake as kernel
from acme_city.kernel.intake import (
    BLOCKING_QUALITY_FLAGS,
    DUPLICATE_QUALITY_FLAGS,
    JUDGMENT_QUALITY_FLAGS,
)
from acme_city.rules.catalog import select_fee_schedule

#: The service identity the intake agent acts as.
INTAKE_AGENT_ID = "service_agent_intake"

#: The statuses a case may hold and still be a duplicate candidate.
LIVE_STATUSES: frozenset[str] = frozenset(
    {
        "submitted",
        "needs_information",
        "ready_for_review",
        "under_review",
        "approved",
        "issued",
    }
)


def type_facts_of(permit_type: permit.PermitType) -> kernel.TypeFacts:
    """Return the frozen facts of a stored permit type that the producers read."""
    return kernel.TypeFacts(
        key=permit_type.key,
        label=permit_type.label,
        active=bool(permit_type.active),
        fee_schedule_key=permit_type.fee_schedule_key,
        review_area=permit_type.review_area,
        review_route=permit_type.review_route,
        required_fields=tuple(permit_type.required_fields or ()),
        required_documents=tuple(permit_type.required_documents or ()),
    )


def find_duplicate(
    session: Session, application: permit.Application
) -> permit.Application | None:
    """Return another live case that asks for the same project.

    A duplicate is the same applicant asking for the same project at the same
    address for the same permit type.  Two different projects of the same
    applicant (a front fence and a rear fence, say) are not duplicates of each
    other.  The stored cases are read here; the decision is the pure
    :func:`acme_city.kernel.intake.first_duplicate`.
    """
    facts = dict(application.submitted_facts or {})
    applicant, address, _description = kernel.duplicate_key(facts)
    if not applicant or not address:
        return None
    rows = session.execute(
        select(permit.Application).where(
            permit.Application.id != application.id,
            permit.Application.status.in_(sorted(LIVE_STATUSES)),
        )
    ).scalars().all()
    peers = []
    by_id: dict[str, permit.Application] = {}
    for row in rows:
        other_applicant, other_address, other_description = kernel.duplicate_key(
            dict(row.submitted_facts or {})
        )
        by_id[row.id] = row
        peers.append(
            kernel.PeerFacts(
                reference=row.id,
                number=row.source_application_number,
                permit_type_id=row.permit_type_id,
                applicant=other_applicant,
                address=other_address,
                description=other_description,
            )
        )
    match = kernel.first_duplicate(facts, application.permit_type_id, peers)
    return None if match is None else by_id[match.reference]


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


def waiting_applications(session: Session) -> list[permit.Application]:
    """Return the applications that wait for the intake agent.

    A case waits when it arrived from outside the City and still waits for
    the agent.  A seeded demonstration case carries a scenario id and is
    never waiting: it is part of the fixed fixture, not an arrival.  The
    clause is the one of the eligibility query, so the waiting cases and the
    cases the agents may pick up on their own never drift apart.
    """
    from acme_city.agents.eligibility import waiting_clause

    rows = session.execute(
        select(permit.Application)
        .where(waiting_clause())
        .order_by(permit.Application.source_application_number)
    ).scalars().all()
    return list(rows)


class IntakeAgent:
    """Runs the intake graph on one application."""

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
        self, application_id: str, *, triggered_by: str, work_id: str | None = None
    ) -> agent_models.AgentRun:
        """Run the intake graph on one application.

        The ``work_id`` names the row of the work queue this run is the
        attempt of, so the queue and the run evidence name each other.
        """
        self._control.require_awake(agent_models.AGENT_INTAKE)
        permits = PermitService(self._session, now=self._now)
        application = permits.load_application(application_id)
        # An archived case is closed: no agent may reopen it.
        require_mutable(application, action="running the intake agent")
        # A returned case is terminal: the applicant starts a new one.
        require_not_returned(application, action="running the intake agent")
        correlation_id = application.correlation_id or new_id("corr")
        run = agent_models.AgentRun(
            id=new_id("agentrun"),
            correlation_id=correlation_id,
            agent_key=agent_models.AGENT_INTAKE,
            application_id=application.id,
            service_identity_id=INTAKE_AGENT_ID,
            triggered_by=triggered_by,
            started_at=self._now,
            finished_at=None,
            outcome="recorded",
            inputs={
                "permit_type_id": application.permit_type_id,
                # The revision the run was made against.  A run of an earlier
                # revision is history: the case was answered again since.
                "revision": application.revision,
                **({"work_id": work_id} if work_id else {}),
            },
        )
        self._session.add(run)
        self._session.flush()

        findings = FindingWriter(
            self._session,
            application_id=application.id,
            correlation_id=correlation_id,
            revision_number=application.revision,
            run_id=run.id,
        )
        actor = service_actor(self._session, INTAKE_AGENT_ID)

        self._node_classifier(run, application, findings)
        self._node_field_extractor(run, application, findings, actor)
        self._node_document_qc(run, application, findings)
        self._node_address_locator(run, application, findings, actor)
        self._node_completeness(run, application, findings)
        self._node_duplicate_finder(run, application, findings, actor)
        self._node_router(run, application, findings)

        # A rerun replaces the findings of the same revision: a finding the
        # run recorded again is superseded by the new one, and a finding the
        # run did not record again is resolved.
        resolve_replaced_findings(
            self._session,
            application.id,
            revision_number=application.revision,
            produced=[(row.finding_type, row.message) for row in findings.findings],
            exclude_run_id=run.id,
            at=self._now,
        )
        run.finished_at = utc_now()
        self._session.flush()
        return run

    def waiting_applications(self) -> list[permit.Application]:
        """Return the applications that wait for the intake agent.

        A case waits when it arrived from outside and still waits for the
        agent.  A seeded demonstration case carries a scenario id and is
        never waiting: it is part of the fixed fixture, not an arrival.
        """
        return waiting_applications(self._session)

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
            action=f"agent.intake.{row.node_id}",
            actor=actor or INTAKE_AGENT_ID,
            target_type="application",
            target_id=run.application_id or "",
            reason=note,
            references=[run.id],
            correlation_id=run.correlation_id,
            metadata={
                "agent": agent_models.AGENT_INTAKE,
                "node_id": row.node_id,
                "status": status,
            },
        )

    def _node_classifier(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        findings: FindingWriter,
    ) -> None:
        """Confirm the permit type and the channel and set the review area.

        The node also records the two findings that belong to the type of the
        case: a declared type that differs from the recorded one, and a case
        the City cannot price because no fee schedule is in force for its
        type.
        """
        node = graphs.node_for('intake', graphs.INTAKE_CLASSIFIER)
        row = self._begin(run, node)
        permits = PermitService(self._session, now=self._now)
        permit_type = permits.permit_type(application)
        facts = dict(application.submitted_facts or {})
        classified = kernel.classify_type(
            type_facts_of(permit_type),
            channel=str(facts.get("channel") or "unknown"),
            declared_type_key=str(facts.get("permit_type_key") or ""),
            fee_schedule_id=self._fee_schedule_in_force(application, permit_type),
            requirements_review_area=str(
                (application.requirements_snapshot or {}).get("review_area") or ""
            ),
        )
        findings.add_specs(classified.findings)
        status = classified.status
        notes = list(classified.notes)
        review_area = classified.review_area
        application.review_area = review_area
        application.priority = self._priority_of(facts, application.priority)
        self._session.flush()
        notes.append(f"Review area: {review_area}.")
        self._finish(run, row, status=status, note=" ".join(notes))

    @staticmethod
    def _priority_of(facts: dict[str, Any], current: str) -> str:
        """Return the priority the intake record carried.

        The intake record may state that the case is high priority.  A record
        that says nothing leaves the priority as it is.
        """
        stated = str(facts.get("priority") or "").strip().lower()
        if stated in {"high", "normal"}:
            return stated
        return current if current in {"normal", "high"} else "normal"

    def _fee_schedule_in_force(
        self, application: permit.Application, permit_type: permit.PermitType
    ) -> str | None:
        """Return the id of the published fee schedule in force for the case.

        The fee facts are the fee schedule the permit type names and the
        published schedule in force on the recorded basis date.  ``None`` means
        the City cannot price the case.
        """
        if not permit_type.fee_schedule_key:
            return None
        basis_at = application.initial_submitted_at or self._now
        schedule = select_fee_schedule(self._session, basis_at, permit_type.key)
        return None if schedule is None else schedule.fee_schedule_id

    def _node_field_extractor(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        findings: FindingWriter,
        actor: ActorContext,
    ) -> None:
        """Propose field values from the received documents."""
        node = graphs.node_for('intake', graphs.INTAKE_FIELD_EXTRACTOR)
        row = self._begin(run, node)
        try:
            result = builtin_extraction(
                self._session, application, actor, agent_run_id=run.id
            )
        except Exception as exc:  # noqa: BLE001 - a failed node is recorded
            self._finish(
                run,
                row,
                status="warn",
                note=f"Extraction failed; a person must read the documents: {exc}",
                actor=actor,
            )
            return
        state = str(result.get("state"))
        observations = list(result.get("observations") or [])
        # The run names the model run that read the documents, so the two
        # records of one attempt point at each other.
        model_run_id = str(result.get("run_id") or "")
        if model_run_id:
            inputs = dict(run.inputs or {})
            inputs["model_run_id"] = model_run_id
            run.inputs = inputs
        if state == "failed":
            issues = result.get("issues") or []
            detail = "; ".join(
                f"{issue.get('code')}: {issue.get('message')}" for issue in issues
            )
            findings.add(
                finding_type="low_confidence_extraction",
                message=(
                    "The extraction output did not pass validation, so the proposed "
                    f"values need a person's eyes. {detail}".strip()
                ),
                rule="ACME Code §13-204",
                applicant_must="Confirm the values a person read from your documents.",
                severity="review",
            )
            self._finish(
                run,
                row,
                status="warn",
                note=(
                    "The validator rejected the extraction output: "
                    f"{detail or 'no issue was recorded'}"
                ),
                actor=actor,
            )
            return
        if state == "skipped":
            self._finish(
                run,
                row,
                status="warn",
                note="No document line proposed a value; a person must read the documents.",
                actor=actor,
            )
            return
        fields = ", ".join(str(item.get("field")) for item in observations)
        self._finish(
            run,
            row,
            status="ok",
            note=(
                f"Proposed {len(observations)} value(s) for a person to accept: {fields}."
            ),
            actor=actor,
        )

    def _node_address_locator(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        findings: FindingWriter,
        actor: ActorContext,
    ) -> None:
        """Correct the typed address to the closest official one and find its parcel.

        The node asks the city locator for candidates, then asks the parcel
        layer which parcel the best point falls in.  It only proposes: the
        Data Steward approves the parcel link and the Permit Reviewer confirms
        the parcel before a decision.
        """
        node = graphs.node_for("intake", graphs.INTAKE_ADDRESS_LOCATOR)
        row = self._begin(run, node)
        try:
            outcome = ParcelMatchService(
                self._session, settings=self._settings, now=self._now
            ).locate(application, actor)
        except Exception as exc:  # noqa: BLE001 - a failed node is recorded
            findings.add(
                finding_type="judgment",
                message=f"{AMBIGUOUS_MESSAGE}: the city locator could not be used ({exc}).",
                rule="ACME Code §13-701",
                applicant_must="Confirm which property the work is for.",
                severity="block",
            )
            self._finish(
                run,
                row,
                status="warn",
                note=f"The city locator failed; a person must find the property: {exc}",
                actor=actor,
            )
            return
        match = outcome.match
        if outcome.kind == "reused":
            self._finish(
                run,
                row,
                status="ok",
                note=(
                    f"The parcel link ({match.parcel_number}) is already approved, so the "
                    "locator was not asked again."
                ),
                actor=actor,
            )
            return
        typed = match.submitted_text or "(no address text)"
        if outcome.kind == "proposed":
            status = "ok"
            note = (
                f"Corrected {typed!r} to {match.matched_address!r} (score {match.score:g}, "
                f"status {match.locator_status}); the point falls in parcel "
                f"{match.parcel_number}. Proposed for the Data Steward to approve."
            )
            if outcome.parcel_conflict:
                status = "warn"
                findings.add(
                    finding_type="conflict",
                    message=outcome.parcel_conflict
                    + " A person must confirm which parcel is meant.",
                    rule="ACME Code §13-702",
                    applicant_must="Confirm the parcel number or the street address of the work.",
                    severity="review",
                )
                note += " " + outcome.parcel_conflict
        elif outcome.kind == "needs_choice":
            status = "warn"
            findings.add(
                finding_type="judgment",
                message=(
                    f"{AMBIGUOUS_MESSAGE}. The locator returned {len(match.candidates or [])} "
                    f"candidate(s) for {typed!r} and none was clearly the best. {match.note}"
                ),
                rule="ACME Code §13-701",
                applicant_must="Confirm which property the work is for.",
                severity="block",
            )
            note = f"{AMBIGUOUS_MESSAGE}: {match.note}"
        else:
            status = "block"
            findings.add(
                finding_type="conflict",
                message=(
                    f"{NOT_FOUND_MESSAGE}. Nothing in the official address list matches "
                    f"{typed!r}."
                ),
                rule="ACME Code §13-703",
                applicant_must=(
                    "Give the street address of the property, or its parcel number."
                ),
                severity="block",
            )
            note = f"{NOT_FOUND_MESSAGE} ({typed!r})."
        self._finish(run, row, status=status, note=note, actor=actor)

    def _node_document_qc(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        findings: FindingWriter,
    ) -> None:
        """Flag the scan-quality problems the intake record carried."""
        node = graphs.node_for('intake', graphs.INTAKE_DOCUMENT_QC)
        row = self._begin(run, node)
        documents = self._session.execute(
            select(permit.Document).where(permit.Document.application_id == application.id)
        ).scalars().all()
        quality = kernel.document_quality(
            (document.document_type, list(document.quality or [])) for document in documents
        )
        findings.add_specs(quality.findings)
        status = quality.status
        notes = list(quality.notes)
        self._finish(run, row, status=status, note=" ".join(notes))

    def _node_duplicate_finder(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        findings: FindingWriter,
        actor: ActorContext,
    ) -> None:
        """Find a duplicate case and propose the identity links."""
        node = graphs.node_for('intake', graphs.INTAKE_DUPLICATE_FINDER)
        row = self._begin(run, node)
        notes: list[str] = []
        status = "ok"
        duplicate = self._find_duplicate(application)
        if duplicate is not None:
            status = "warn"
            findings.add_spec(
                kernel.duplicate_finding(duplicate.source_application_number, duplicate.id)
            )
            notes.append(f"Duplicate of {duplicate.source_application_number}.")
        proposals, matched, failures = self._propose_links(application, actor)
        notes.append(
            f"Proposed {len(proposals)} identity link(s) for a person to approve."
        )
        if matched:
            notes.append("Matched " + "; ".join(matched) + ".")
        if failures:
            notes.append("Could not propose: " + "; ".join(failures) + ".")
        self._finish(run, row, status=status, note=" ".join(notes), actor=actor)

    def _find_duplicate(
        self, application: permit.Application
    ) -> permit.Application | None:
        """Return another live case that asks for the same project."""
        return find_duplicate(self._session, application)

    def _propose_links(
        self, application: permit.Application, actor: ActorContext
    ) -> tuple[list[str], list[str], list[str]]:
        """Propose the applicant, parcel and contractor links of the case.

        The identity matcher runs for the applicant, the parcel and the
        contractor.  The registry holds one proposed link per source record,
        so the link that is proposed is the canonical link the case needs:
        the applicant.  The matches are reported either way.
        """
        facts = dict(application.submitted_facts or {})
        registry_service = RegistryService(self._session, now=self._now)
        snapshot = self._intake_snapshot(application)
        targets: list[tuple[str, dict[str, Any], str]] = []
        applicant_name = str(facts.get("applicant_name") or "")
        if applicant_name:
            targets.append(("party", {"display_name": applicant_name}, "applicant"))
        parcel_text = str(facts.get("parcel_number") or facts.get("submitted_parcel") or "")
        if parcel_text:
            targets.append(("parcel", {"parcel_number": parcel_text}, "parcel"))
        contractor = str(facts.get("contractor_license") or "")
        if contractor:
            targets.append(("party", {"license_number": contractor}, "contractor"))
        proposal_ids: list[str] = []
        matched: list[str] = []
        failures: list[str] = []
        for entity_type, payload, label in targets:
            try:
                candidate_set = generate_candidates(self._session, payload, entity_type, None)
            except Exception as exc:  # noqa: BLE001 - a failed match is not a link
                failures.append(f"{label} match failed ({exc})")
                continue
            if candidate_set.best is None:
                continue
            matched.append(f"{label} ({len(candidate_set.candidates)} candidate(s))")
            if snapshot is None or proposal_ids:
                continue
            try:
                view = registry_service.propose(
                    MatchProposalCommand(
                        source_system_id=snapshot.source_system_id,
                        dataset_key=snapshot.source_dataset_id,
                        source_record_id=snapshot.source_record_id,
                        entity_type=entity_type,
                        candidate_entity_ids=[
                            candidate.entity_id for candidate in candidate_set.candidates
                        ],
                        notes="proposed by the intake agent during the duplicate check",
                    ),
                    actor,
                )
            except Exception as exc:  # noqa: BLE001 - a failed proposal is not a link
                failures.append(f"{label} link not proposed ({exc})")
                continue
            proposal_ids.append(view.proposal_id)
        return proposal_ids, matched, failures

    def _intake_snapshot(self, application: permit.Application):
        """Return the staged intake record that created the application."""
        from acme_city.persistence.models import source as source_models

        rows = self._session.execute(
            select(source_models.SourceSnapshot).where(
                source_models.SourceSnapshot.source_system_id == "intake_portal",
                source_models.SourceSnapshot.source_dataset_id == "submitted_applications",
            )
        ).scalars().all()
        for row in rows:
            payload = dict(row.raw_payload or {})
            if payload.get("application_id") == application.id:
                return row
        return None

    def _node_completeness(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        findings: FindingWriter,
    ) -> None:
        """Check the required fields and documents of the permit type.

        The requirements are the ones that were in force when the case was
        received, so a later configuration change never rewrites what this
        case was measured against.
        """
        node = graphs.node_for('intake', graphs.INTAKE_COMPLETENESS)
        row = self._begin(run, node)
        permits = PermitService(self._session, now=self._now)
        permit_type = permits.permit_type(application)
        requirements = self._requirements(application, permit_type)
        revision = permits.current_revision(application.id)
        facts = dict(revision.snapshot or {})
        documents = DocumentService(self._session, root=self._document_root).list_versions(
            application.id
        )
        result = kernel.completeness(
            type_key=permit_type.key,
            required_fields=requirements["required_fields"],
            required_documents=requirements["required_documents"],
            facts=facts,
            present_document_types={document.document_type for document in documents},
        )
        findings.add_specs(result.findings)
        missing_fields = list(result.missing_fields)
        missing_documents = list(result.missing_documents)
        if missing_fields or missing_documents:
            self._finish(
                run,
                row,
                status="block",
                note=(
                    f"Missing fields {missing_fields}, missing documents "
                    f"{missing_documents}."
                ),
            )
            return
        self._finish(
            run,
            row,
            status="ok",
            note=(
                f"Complete against {permit_type.key}: every required field and document "
                "is present."
            ),
        )

    @staticmethod
    def _requirements(
        application: permit.Application, permit_type: permit.PermitType
    ) -> dict[str, Any]:
        """Return the requirements the case is measured against.

        A case received through intake carries the requirements that were in
        force at that moment.  A case that was seeded directly carries none,
        so the current configuration of its type applies.
        """
        return kernel.requirements_of(
            application.requirements_snapshot,
            permit_type.required_fields,
            permit_type.required_documents,
        )

    def _node_router(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        findings: FindingWriter,
    ) -> None:
        """Route the case to early resolution or to review."""
        node = graphs.node_for('intake', graphs.INTAKE_ROUTER)
        row = self._begin(run, node)
        routed = kernel.route(findings.findings, application.review_area)
        application.status = routed.status
        outcome = routed.outcome
        note = routed.reason
        self._session.flush()
        run.outcome = outcome
        self._finish(run, row, status="ok", note=note)


__all__ = [
    "BLOCKING_QUALITY_FLAGS",
    "DUPLICATE_QUALITY_FLAGS",
    "INTAKE_AGENT_ID",
    "JUDGMENT_QUALITY_FLAGS",
    "LIVE_STATUSES",
    "IntakeAgent",
    "find_duplicate",
    "service_actor",
    "type_facts_of",
    "waiting_applications",
]

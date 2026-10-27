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
from acme_city.agents.extraction import replay_extraction
from acme_city.agents.findings import FindingWriter
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.documents.service import DocumentService
from acme_city.permits.service import PermitService
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import permit, registry
from acme_city.registry.candidates import generate_candidates
from acme_city.registry.schemas import MatchProposalCommand
from acme_city.registry.service import RegistryService

#: The service identity the intake agent acts as.
INTAKE_AGENT_ID = "service_agent_intake"

#: The document-quality flags the document QC node reads.  Only an unreadable
#: page blocks the case; the others ask a person to look.
BLOCKING_QUALITY_FLAGS: frozenset[str] = frozenset({"unreadable"})
DUPLICATE_QUALITY_FLAGS: frozenset[str] = frozenset({"duplicate_page"})
JUDGMENT_QUALITY_FLAGS: frozenset[str] = frozenset({"rotated", "low_res", "handwritten"})

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

    A case waits when it arrived from outside the City and no intake run has
    routed it yet.  A seeded demonstration case carries a scenario id and is
    never waiting: it is part of the fixed fixture, not an arrival.
    """
    rows = session.execute(
        select(permit.Application)
        .where(
            permit.Application.status == "submitted",
            permit.Application.scenario_id.is_(None),
        )
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

    def run(self, application_id: str, *, triggered_by: str) -> agent_models.AgentRun:
        """Run the intake graph on one application."""
        self._control.require_awake(agent_models.AGENT_INTAKE)
        permits = PermitService(self._session, now=self._now)
        application = permits.load_application(application_id)
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
            inputs={"permit_type_id": application.permit_type_id},
        )
        self._session.add(run)
        self._session.flush()

        findings = FindingWriter(
            self._session,
            application_id=application.id,
            correlation_id=correlation_id,
        )
        actor = service_actor(self._session, INTAKE_AGENT_ID)

        self._node_classifier(run, application, findings)
        self._node_field_extractor(run, application, findings, actor)
        self._node_document_qc(run, application, findings)
        self._node_duplicate_finder(run, application, findings, actor)
        self._node_completeness(run, application, findings)
        self._node_router(run, application, findings)

        run.finished_at = utc_now()
        self._session.flush()
        return run

    def waiting_applications(self) -> list[permit.Application]:
        """Return the applications that wait for the intake agent.

        A case waits when it arrived from outside and no intake run has
        routed it yet.  A seeded demonstration case carries a scenario id
        and is never waiting: it is part of the fixed fixture, not an
        arrival.
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
        """Confirm the permit type and the channel and set the review area."""
        node = graphs.INTAKE_GRAPH[0]
        row = self._begin(run, node)
        permits = PermitService(self._session, now=self._now)
        permit_type = permits.permit_type(application)
        facts = dict(application.submitted_facts or {})
        channel = str(facts.get("channel") or "unknown")
        declared = str(facts.get("permit_type_key") or "")
        status = "ok"
        notes = [
            f"Permit type {permit_type.key} confirmed; received by the {channel} channel."
        ]
        if declared and declared != permit_type.key:
            status = "warn"
            findings.add(
                finding_type="conflict",
                message=(
                    f"The intake record asked for {declared!r} but the case was created as "
                    f"{permit_type.key!r}. A person must confirm which permit type applies."
                ),
                rule="ACME Code §13-101",
                applicant_must="Confirm the permit type of this application.",
                severity="review",
            )
            notes.append("The declared type differs from the recorded type.")
        if not permit_type.active:
            status = "block"
            findings.add(
                finding_type="conflict",
                message=(
                    f"The permit type {permit_type.key!r} is no longer active, so the "
                    "case cannot be routed to a review area."
                ),
                rule="ACME Code §13-102",
                applicant_must="Ask the City which permit type applies now.",
                severity="block",
            )
            notes.append("The permit type is not active.")
        review_area = (
            str((application.requirements_snapshot or {}).get("review_area") or "")
            or permit_type.review_area
            or permit_type.review_route
        )
        application.review_area = review_area
        self._session.flush()
        notes.append(f"Review area: {review_area}.")
        self._finish(run, row, status=status, note=" ".join(notes))

    def _node_field_extractor(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        findings: FindingWriter,
        actor: ActorContext,
    ) -> None:
        """Propose field values from the received documents."""
        node = graphs.INTAKE_GRAPH[1]
        row = self._begin(run, node)
        try:
            result = replay_extraction(self._session, application, actor)
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

    def _node_document_qc(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        findings: FindingWriter,
    ) -> None:
        """Flag the scan-quality problems the intake record carried."""
        node = graphs.INTAKE_GRAPH[2]
        row = self._begin(run, node)
        documents = self._session.execute(
            select(permit.Document).where(permit.Document.application_id == application.id)
        ).scalars().all()
        status = "ok"
        notes: list[str] = []
        for document in documents:
            flags = [str(flag) for flag in (document.quality or [])]
            for flag in flags:
                if flag in BLOCKING_QUALITY_FLAGS:
                    status = "block"
                    findings.add(
                        finding_type="unreadable",
                        message=(
                            f"The {document.document_type} page cannot be read, so the "
                            "case cannot be assessed until a readable copy arrives."
                        ),
                        rule="ACME Code §13-302",
                        applicant_must=(
                            f"Provide a readable copy of the {document.document_type}."
                        ),
                        severity="block",
                    )
                    notes.append(f"{document.document_type}: {flag}.")
                elif flag in DUPLICATE_QUALITY_FLAGS:
                    status = "warn" if status == "ok" else status
                    findings.add(
                        finding_type="duplicate",
                        message=(
                            f"The {document.document_type} page repeats an earlier page "
                            "of the same document."
                        ),
                        rule="ACME Code §13-303",
                        applicant_must=(
                            f"Confirm that the {document.document_type} has no repeated page."
                        ),
                        severity="review",
                    )
                    notes.append(f"{document.document_type}: {flag}.")
                elif flag in JUDGMENT_QUALITY_FLAGS:
                    status = "warn" if status == "ok" else status
                    findings.add(
                        finding_type="judgment",
                        message=(
                            f"The {document.document_type} page was received {flag.replace('_', ' ')}, "
                            "so a person should read it before the case is assessed."
                        ),
                        rule="ACME Code §13-304",
                        applicant_must=(
                            f"Provide a clearer copy of the {document.document_type}."
                        ),
                        severity="review",
                    )
                    notes.append(f"{document.document_type}: {flag}.")
        if not notes:
            notes.append("No scan-quality problem was reported on the received documents.")
        self._finish(run, row, status=status, note=" ".join(notes))

    def _node_duplicate_finder(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        findings: FindingWriter,
        actor: ActorContext,
    ) -> None:
        """Find a duplicate case and propose the identity links."""
        node = graphs.INTAKE_GRAPH[3]
        row = self._begin(run, node)
        notes: list[str] = []
        status = "ok"
        duplicate = self._find_duplicate(application)
        if duplicate is not None:
            status = "warn"
            findings.add(
                finding_type="duplicate",
                message=(
                    "The same applicant asked for the same project at the same address "
                    f"for the same permit type in {duplicate.source_application_number}. "
                    "A person must confirm whether this is a resubmission."
                ),
                rule="ACME Code §13-401",
                applicant_must=(
                    "Tell the City whether this is a new application or a resubmission of "
                    f"{duplicate.source_application_number}."
                ),
                severity="review",
                related_application_id=duplicate.id,
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
        """Return another live case that asks for the same project.

        A duplicate is the same applicant asking for the same project at the
        same address for the same permit type.  Two different projects of the
        same applicant (a front fence and a rear fence, say) are not
        duplicates of each other.
        """
        facts = dict(application.submitted_facts or {})
        applicant = str(facts.get("applicant_name") or "").strip().lower()
        address = str(
            facts.get("submitted_site_text") or facts.get("site_address") or ""
        ).strip().lower()
        description = str(facts.get("project_description") or "").strip().lower()
        if not applicant or not address:
            return None
        rows = self._session.execute(
            select(permit.Application).where(
                permit.Application.id != application.id,
                permit.Application.status.in_(sorted(LIVE_STATUSES)),
            )
        ).scalars().all()
        for row in rows:
            other = dict(row.submitted_facts or {})
            if str(other.get("applicant_name") or "").strip().lower() != applicant:
                continue
            other_address = str(
                other.get("submitted_site_text") or other.get("site_address") or ""
            ).strip().lower()
            if other_address != address:
                continue
            if row.permit_type_id != application.permit_type_id:
                continue
            other_description = str(other.get("project_description") or "").strip().lower()
            if description and other_description and other_description != description:
                continue
            return row
        return None

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
        node = graphs.INTAKE_GRAPH[4]
        row = self._begin(run, node)
        permits = PermitService(self._session, now=self._now)
        permit_type = permits.permit_type(application)
        requirements = self._requirements(application, permit_type)
        revision = permits.current_revision(application.id)
        facts = dict(revision.snapshot or {})
        documents = DocumentService(self._session, root=self._document_root).list_versions(
            application.id
        )
        present_types = {document.document_type for document in documents}
        missing_fields = [
            field
            for field in requirements["required_fields"]
            if facts.get(field) is None
            or (isinstance(facts.get(field), str) and not str(facts.get(field)).strip())
        ]
        missing_documents = [
            document
            for document in requirements["required_documents"]
            if document not in present_types
        ]
        for field in missing_fields:
            findings.add(
                finding_type="missing_field",
                message=f"The application does not state {field.replace('_', ' ')}.",
                rule=f"ACME Code §13-501 ({permit_type.key} required fields)",
                applicant_must=f"State {field.replace('_', ' ')} on the application.",
                severity="block",
            )
        for document in missing_documents:
            findings.add(
                finding_type="missing_document",
                message=f"The application does not include the {document.replace('_', ' ')}.",
                rule=f"ACME Code §13-502 ({permit_type.key} required documents)",
                applicant_must=f"Provide the {document.replace('_', ' ')}.",
                severity="block",
            )
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
        snapshot = dict(application.requirements_snapshot or {})
        return {
            "required_fields": list(
                snapshot.get("required_fields")
                if snapshot.get("required_fields") is not None
                else (permit_type.required_fields or [])
            ),
            "required_documents": list(
                snapshot.get("required_documents")
                if snapshot.get("required_documents") is not None
                else (permit_type.required_documents or [])
            ),
        }

    def _node_router(
        self,
        run: agent_models.AgentRun,
        application: permit.Application,
        findings: FindingWriter,
    ) -> None:
        """Route the case to early resolution or to review."""
        node = graphs.INTAKE_GRAPH[5]
        row = self._begin(run, node)
        blocking = findings.blocking
        judging = findings.judging
        if blocking:
            application.status = "needs_information"
            outcome = "needs_information"
            note = (
                f"Route to early resolution: {len(blocking)} blocking finding(s) must be "
                "cleared first."
            )
        elif judging:
            application.status = "needs_information"
            outcome = "needs_information"
            note = (
                "Verify before review: "
                f"{len(judging)} finding(s) need a person's judgement."
            )
        else:
            application.status = "ready_for_review"
            outcome = "completed"
            note = (
                "Ready for review in the "
                f"{application.review_area or 'assigned'} area."
            )
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
    "service_actor",
    "waiting_applications",
]

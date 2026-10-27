"""The agent triage pipeline.

When an intake record becomes an application, five named steps run
synchronously, server-side, each as a seeded service identity and each
recorded as an auditable agent step:

1. intake (completeness), 2. identity (proposed links), 3. extraction
(Muse, replay by default), 4. rules (deterministic evaluation),
5. recommendation (deterministic outcome + rationale, optional Muse
explanation).

Agents propose; people decide.  No step approves a permit, sets money or
issues anything, and a recommendation never supplies a reviewer identity.
"""
# REQUIRES: PER-02, PER-04, AI-03, AI-04, MDM-02
# Each step runs as a named service identity, is recorded with its inputs and
# outcome, and writes proposals only.  The recommendation outcome comes from
# the deterministic rule results and the rationale cites each rule.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.core.clock import utc_now
from acme_city.core.errors import AcmeError, ValidationError
from acme_city.core.ids import new_id
from acme_city.documents.service import DocumentService
from acme_city.muse.client import MuseClient
from acme_city.muse.service import MuseRunCommand, MuseService
from acme_city.muse.validation import validate_extraction_output
from acme_city.muse.payloads import VisibleEvidenceBundle
from acme_city.permits.service import PermitService
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import permit, registry
from acme_city.registry.candidates import generate_candidates
from acme_city.registry.schemas import MatchProposalCommand
from acme_city.registry.service import RegistryService
from acme_city.triage.summary import (
    build_summary_payload,
    deterministic_summary,
    validate_summary,
)

#: The service identity that runs the completeness step.  Seeded in
#: ``config/actors.json`` with intake grants (submit/stage/document view).
INTAKE_AGENT_ID = "service_delegate_steward"
#: The service identity that proposes identity links.
IDENTITY_AGENT_ID = "service_delegate_steward"
#: The service identity that runs Muse extraction.
EXTRACTION_AGENT_ID = "service_delegate_steward"
#: The service identity that runs the deterministic evaluator, via the
#: steward identity's evaluate grant (see ``_step_rules``).
RULES_AGENT_ID = "service_delegate_steward"
#: The service identity that writes the advisory recommendation.
RECOMMENDATION_AGENT_ID = "service_delegate_steward"

#: The step names, in pipeline order.
STEP_INTAKE = "intake"
STEP_IDENTITY = "identity"
STEP_EXTRACTION = "extraction"
STEP_RULES = "rules"
STEP_RECOMMENDATION = "recommendation"
STEP_NAMES: tuple[str, ...] = (
    STEP_INTAKE,
    STEP_IDENTITY,
    STEP_EXTRACTION,
    STEP_RULES,
    STEP_RECOMMENDATION,
)

#: Recommendation outcomes (advisory only).
OUTCOME_APPROVE = "approve"
OUTCOME_DENY = "deny"
OUTCOME_CONDITIONS = "approve_with_conditions"
OUTCOME_JUDGMENT = "needs_reviewer_judgment"
OUTCOME_INFORMATION = "request_information"


def service_actor(session: Session, actor_id: str) -> ActorContext:
    """Return the server-resolved context of a seeded service identity."""
    from acme_city.auth.permissions import PermissionResolver

    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        role_ids=frozenset(),
        domain_scope=frozenset(g.domain_id for g in grants if g.domain_id),
        record_scope=frozenset(r for g in grants for r in g.record_scope),
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
            return OUTCOME_INFORMATION
        return OUTCOME_DENY
    if "condition" in statuses:
        return OUTCOME_CONDITIONS
    if "review" in statuses:
        # A review caused only by missing inputs is an information request.
        review_reasons = [
            reason for status, reason in zip(statuses, reasons) if status == "review"
        ]
        if review_reasons and all(
            reason in {"missing_input", "missing_condition_input"} for reason in review_reasons
        ):
            return OUTCOME_INFORMATION
        return OUTCOME_JUDGMENT
    return OUTCOME_APPROVE


def build_rationale(results: list[dict[str, Any]], outcome: str) -> str:
    """Return the plain-language rationale citing each rule.

    Each applicable rule is cited with its observed value and its limit, for
    example "DF-1: front-yard fence 6 ft is above the 4 ft maximum, ACME
    Code §14-305".
    """
    lines: list[str] = []
    for result in results:
        rule_id = result.get("rule_id", "rule")
        citation = result.get("citation", "")
        status = result.get("status", "")
        observed = result.get("observed_value")
        limit = result.get("limit_value")
        operator = result.get("operator", "")
        message = result.get("message") or result.get("detail") or ""
        if status == "pass":
            lines.append(
                f"{rule_id}: passed (observed {observed}, limit {limit}, {citation})."
            )
        elif status == "fail":
            relation = "above" if operator == "max" else "below" if operator == "min" else "differs from"
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


class TriageService:
    """Runs the five agent steps for one application, synchronously."""

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

    # ------------------------------------------------------------------ public

    def run(
        self, application_id: str, *, triggered_by: str
    ) -> list[agent_models.AgentStep]:
        """Run every step for one application and return the step records."""
        application = PermitService(self._session, now=self._now).load_application(
            application_id
        )
        correlation_id = application.correlation_id or new_id("corr")
        steps: list[agent_models.AgentStep] = []
        missing = self._step_intake(application, correlation_id, triggered_by, steps)
        self._step_identity(application, correlation_id, triggered_by, steps)
        self._step_extraction(application, correlation_id, triggered_by, steps)
        evaluation = self._step_rules(application, correlation_id, triggered_by, steps)
        self._step_recommendation(
            application, correlation_id, triggered_by, steps, evaluation, missing
        )
        # The rules step moves a complete case to ready_for_review; a case
        # the intake step found incomplete stays needs_information until the
        # applicant supplies what is missing.
        if missing and (missing.get("fields") or missing.get("documents")):
            if application.status != "needs_information":
                application.status = "needs_information"
                self._session.flush()
        return steps

    # ------------------------------------------------------------------- steps

    def _begin(
        self,
        application: permit.Application,
        *,
        step_name: str,
        identity: str,
        correlation_id: str,
        triggered_by: str,
        inputs: dict[str, Any],
    ) -> agent_models.AgentStep:
        step = agent_models.AgentStep(
            id=new_id("agentstep"),
            correlation_id=correlation_id,
            application_id=application.id,
            step_name=step_name,
            service_identity_id=identity,
            started_at=utc_now(),
            ended_at=None,
            inputs=inputs,
            outcome="recorded",
            triggered_by=triggered_by,
        )
        self._session.add(step)
        self._session.flush()
        return step

    def _finish_step(
        self,
        step: agent_models.AgentStep,
        *,
        outcome: str,
        detail: str,
        actor: ActorContext,
        references: tuple[str, ...] = (),
    ) -> None:
        step.ended_at = utc_now()
        step.outcome = outcome
        step.outcome_detail = detail
        self._session.flush()
        self._audit.append(
            action=f"agent.{step.step_name}",
            actor=actor,
            target_type="application",
            target_id=step.application_id,
            reason=detail,
            references=list(references),
            correlation_id=step.correlation_id,
            metadata={
                "step_name": step.step_name,
                "service_identity_id": step.service_identity_id,
                "outcome": outcome,
            },
        )

    def _step_intake(self, application, correlation_id, triggered_by, steps):
        actor = service_actor(self._session, INTAKE_AGENT_ID)
        permits = PermitService(self._session, now=self._now)
        permit_type = permits.permit_type(application)
        revision = permits.current_revision(application.id)
        facts = dict(revision.snapshot or {})
        documents = DocumentService(self._session, root=self._document_root).list_versions(
            application.id
        )
        present_types = {doc.document_type for doc in documents}
        missing_fields = [
            field
            for field in (permit_type.required_fields or [])
            if facts.get(field) is None
            or (isinstance(facts.get(field), str) and not str(facts.get(field)).strip())
        ]
        missing_documents = [
            doc for doc in (permit_type.required_documents or []) if doc not in present_types
        ]
        step = self._begin(
            application,
            step_name=STEP_INTAKE,
            identity=INTAKE_AGENT_ID,
            correlation_id=correlation_id,
            triggered_by=triggered_by,
            inputs={
                "permit_type_key": permit_type.key,
                "required_fields": list(permit_type.required_fields or []),
                "required_documents": list(permit_type.required_documents or []),
                "document_types_present": sorted(present_types),
            },
        )
        steps.append(step)
        missing = {"fields": missing_fields, "documents": missing_documents}
        if missing_fields or missing_documents:
            application.status = "needs_information"
            self._session.flush()
            detail = (
                f"Missing for the applicant: fields {missing_fields}, documents "
                f"{missing_documents}. Routed as needs-information."
            )
            step.inputs = {**(step.inputs or {}), "missing": missing}
            self._finish_step(
                step, outcome="needs_information", detail=detail, actor=actor,
                references=(application.id,),
            )
        else:
            detail = (
                f"Complete against {permit_type.key}. Routed to "
                f"{permit_type.review_route}."
            )
            step.inputs = {
                **(step.inputs or {}),
                "missing": missing,
                "review_route": permit_type.review_route,
            }
            self._finish_step(
                step, outcome="completed", detail=detail, actor=actor,
                references=(application.id,),
            )
        return missing

    def _step_identity(self, application, correlation_id, triggered_by, steps):
        actor = service_actor(self._session, IDENTITY_AGENT_ID)
        step = self._begin(
            application,
            step_name=STEP_IDENTITY,
            identity=IDENTITY_AGENT_ID,
            correlation_id=correlation_id,
            triggered_by=triggered_by,
            inputs={"application_id": application.id},
        )
        steps.append(step)
        proposal_ids: list[str] = []
        try:
            intake_row = self._session.execute(
                select(permit.Application).where(permit.Application.id == application.id)
            ).scalar_one()
            snapshot = self._intake_snapshot(application)
            registry = RegistryService(self._session, now=self._now)
            targets: list[tuple[str, dict[str, Any], str]] = []
            facts = dict(intake_row.submitted_facts or {})
            applicant_name = str(facts.get("applicant_name") or "")
            if snapshot is not None:
                payload = dict(snapshot.raw_payload or {})
                applicant = payload.get("applicant") or {}
                if isinstance(applicant, dict) and applicant.get("name"):
                    applicant_name = str(applicant["name"])
            if applicant_name:
                targets.append(("party", {"display_name": applicant_name}, "applicant"))
            parcel_text = str(facts.get("parcel_number") or facts.get("submitted_parcel") or "")
            if parcel_text:
                targets.append(("parcel", {"parcel_number": parcel_text}, "parcel"))
            contractor = str(facts.get("contractor_license") or "")
            if contractor:
                targets.append(
                    ("party", {"license_number": contractor}, "contractor")
                )
            for entity_type, payload, _role in targets:
                candidate_set = generate_candidates(
                    self._session, payload, entity_type, None
                )
                if snapshot is not None and candidate_set.best is not None:
                    view = registry.propose(
                        MatchProposalCommand(
                            source_system_id=snapshot.source_system_id,
                            dataset_key=snapshot.source_dataset_id,
                            source_record_id=snapshot.source_record_id,
                            entity_type=entity_type,
                            candidate_entity_ids=[
                                c.entity_id for c in candidate_set.candidates
                            ],
                            notes="proposed by the identity agent during triage",
                        ),
                        actor,
                    )
                    proposal_ids.append(view.proposal_id)
            step.proposal_ids = proposal_ids
            detail = (
                f"Proposed {len(proposal_ids)} identity link(s) for steward decision. "
                "No link is approved by an agent."
            )
            self._finish_step(
                step, outcome="completed", detail=detail, actor=actor,
                references=tuple(proposal_ids),
            )
        except Exception as exc:  # noqa: BLE001 - a failed step is recorded, never hidden
            self._finish_step(
                step, outcome="failed", detail=f"Identity proposals failed: {exc}",
                actor=actor,
            )

    def _intake_snapshot(self, application):
        from acme_city.persistence.models import source as source_models

        # The intake snapshot payload names the application it created.
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

    def _step_extraction(self, application, correlation_id, triggered_by, steps):
        actor = service_actor(self._session, EXTRACTION_AGENT_ID)
        step = self._begin(
            application,
            step_name=STEP_EXTRACTION,
            identity=EXTRACTION_AGENT_ID,
            correlation_id=correlation_id,
            triggered_by=triggered_by,
            inputs={"application_id": application.id, "mode": "live" if self._live_muse else "replay"},
        )
        steps.append(step)
        documents = DocumentService(self._session, root=self._document_root).list_versions(
            application.id
        )
        if not documents:
            self._finish_step(
                step, outcome="skipped", detail="No document version to extract from.",
                actor=actor,
            )
            return
        if self._settings is None:
            self._finish_step(
                step, outcome="skipped",
                detail="No Muse settings are configured; extraction skipped in replay.",
                actor=actor,
            )
            return
        try:
            service = MuseService(
                self._session,
                self._settings,
                client=self._muse_client,
                now=self._now,
            )
            if self._live_muse:
                view = service.run(
                    MuseRunCommand(
                        task="extraction", mode="live", application_id=application.id
                    ),
                    actor,
                )
                step.model_run_id = view.run_id
                outcome = "completed" if view.status == "succeeded" else "failed"
                self._finish_step(
                    step, outcome=outcome,
                    detail=f"Muse extraction ({view.mode}) {view.status}: "
                    f"{len(view.proposals)} proposed value(s) for steward review.",
                    actor=actor, references=(view.run_id,),
                )
                return
            # Replay by default: build the recorded output from the intake
            # document itself, validate it like a model output, and record a
            # replay-labelled run.  Nothing is sent to a provider.
            run_id = self._replay_extraction(application, documents, actor, step)
            step.model_run_id = run_id
            self._finish_step(
                step, outcome="completed",
                detail="Muse extraction replayed from the received document text; "
                "proposed values await steward acceptance.",
                actor=actor, references=(run_id,) if run_id else (),
            )
        except Exception as exc:  # noqa: BLE001
            self._session.rollback()
            step2 = self._begin(
                application,
                step_name=STEP_EXTRACTION,
                identity=EXTRACTION_AGENT_ID,
                correlation_id=correlation_id,
                triggered_by=triggered_by,
                inputs={"application_id": application.id, "mode": "replay"},
            )
            steps[-1] = step2
            self._finish_step(
                step2, outcome="failed",
                detail=f"Extraction failed; manual steward fallback: {exc}",
                actor=service_actor(self._session, EXTRACTION_AGENT_ID),
            )

    def _replay_extraction(self, application, documents, actor, step) -> str | None:
        """Record a replay-labelled extraction from the received document text.

        The recorded output is constructed deterministically from lines the
        document actually contains and then passed through the same
        extraction validation a live output passes through.  Only validated
        observations are written, as proposals for the steward.
        """
        from acme_city.muse.schemas import EXTRACTION_TASK, TASK_CONFIG
        from acme_city.persistence.models import model_run as model_run_models

        bundle = VisibleEvidenceBundle.for_actor(
            application.id, actor, session=self._session
        )
        observations: list[dict[str, Any]] = []
        # Deterministic field lines the intake documents carry, mapped to the
        # extractable vocabulary.  A value is proposed only when its line is
        # present verbatim in a visible document.
        patterns = (
            ("project_description", "Project description:"),
            ("parcel_reference", "Parcel reference:"),
        )
        for reference in bundle.documents:
            lines = bundle.lines_of(reference.document_id)
            for field, marker in patterns:
                for index, line in enumerate(lines, start=1):
                    if marker.lower() in line.lower():
                        value = line.split(":", 1)[1].strip() if ":" in line else line.strip()
                        if value:
                            observations.append(
                                {
                                    "field": field,
                                    "proposed_value": value[:320],
                                    "evidence": {
                                        "line_start": index,
                                        "line_end": index,
                                        "excerpt": line.strip()[:400],
                                    },
                                }
                            )
                        break
            if observations:
                output = {
                    "application_id": application.id,
                    "document_id": reference.document_id,
                    "document_version": reference.version,
                    "observations": observations,
                }
                outcome = validate_extraction_output(
                    output, bundle=bundle, application_id=application.id
                )
                config = TASK_CONFIG[EXTRACTION_TASK]
                now = utc_now()
                row = model_run_models.ModelRun(
                    id=new_id("modelrun"),
                    correlation_id=new_id("corr"),
                    mode="replay",
                    provider="meta",
                    model="muse-spark-1.3",
                    prompt_version=config["prompt_version"],
                    schema_version=config["schema_version"],
                    input_refs={
                        "task": EXTRACTION_TASK,
                        "application_id": application.id,
                        "source_application_number": application.source_application_number,
                        "documents": [
                            {
                                "document_id": r.document_id,
                                "version": r.version,
                                "content_hash": r.content_hash,
                            }
                            for r in bundle.documents
                        ],
                    },
                    output=output if outcome.ok else None,
                    validation_result={
                        **outcome.to_dict(),
                        "status": "succeeded" if outcome.ok else "failed",
                        "provider": {"response_id": None, "response_status": "replayed"},
                        "replay_note": "replayed from the received document text; no provider call was sent",
                    },
                    usage={},
                    latency_ms=None,
                    error=None if outcome.ok else "the replayed extraction failed validation",
                    started_at=now,
                    completed_at=now,
                    actor_id=actor.actor_id,
                    replay_of_run_id="intake-document-replay",
                )
                self._session.add(row)
                self._session.flush()
                if outcome.ok:
                    from acme_city.muse.service import MuseService

                    MuseService(self._session, self._settings, now=self._now)._write_extraction(  # noqa: SLF001
                        row, bundle, output
                    )
                self._audit.append(
                    action="muse.run",
                    actor=actor,
                    target_type="model_run",
                    target_id=row.id,
                    reason="extraction run in replay mode: "
                    + ("succeeded" if outcome.ok else "failed"),
                    references=[application.id],
                    correlation_id=row.correlation_id,
                    outcome="accepted" if outcome.ok else "denied",
                    metadata={"task": "extraction", "mode": "replay"},
                )
                return row.id
        return None

    def _step_rules(self, application, correlation_id, triggered_by, steps):
        actor = service_actor(self._session, RULES_AGENT_ID)
        step = self._begin(
            application,
            step_name=STEP_RULES,
            identity=RULES_AGENT_ID,
            correlation_id=correlation_id,
            triggered_by=triggered_by,
            inputs={"application_id": application.id},
        )
        steps.append(step)
        try:
            view = PermitService(self._session, now=self._now).evaluate(
                application.id, actor
            )
            evaluation = PermitService(self._session, now=self._now).current_evaluation(
                application.id
            )
            step.evaluation_id = evaluation.id if evaluation else None
            self._finish_step(
                step, outcome="completed",
                detail=f"Deterministic evaluation outcome '{view.outcome}' with "
                f"{len(view.results)} rule result(s).",
                actor=actor,
                references=(step.evaluation_id,) if step.evaluation_id else (),
            )
            return evaluation
        except Exception as exc:  # noqa: BLE001
            self._finish_step(
                step, outcome="failed", detail=f"Rule evaluation failed: {exc}",
                actor=actor,
            )
            return None

    def _step_recommendation(
        self, application, correlation_id, triggered_by, steps, evaluation, missing
    ):
        actor = service_actor(self._session, RECOMMENDATION_AGENT_ID)
        step = self._begin(
            application,
            step_name=STEP_RECOMMENDATION,
            identity=RECOMMENDATION_AGENT_ID,
            correlation_id=correlation_id,
            triggered_by=triggered_by,
            inputs={"application_id": application.id},
        )
        steps.append(step)
        results: list[dict[str, Any]] = []
        if evaluation is not None:
            results = [dict(item) for item in (evaluation.results or [])]
        if missing and (missing.get("fields") or missing.get("documents")):
            outcome = OUTCOME_INFORMATION
        else:
            outcome = recommendation_outcome(results)
        rationale = build_rationale(results, outcome)
        if missing and (missing.get("fields") or missing.get("documents")):
            rationale = (
                f"Information is missing for the applicant: fields "
                f"{missing.get('fields')}, documents {missing.get('documents')}. "
                + rationale
            )
        muse_summary: str | None = None
        muse_run_id: str | None = None
        if self._live_muse and self._settings is not None:
            muse_summary, muse_run_id = self._live_summary(
                application, outcome, rationale, actor
            )
        if muse_summary is None:
            muse_summary = deterministic_summary(outcome, rationale)
        # Supersede any earlier advisory recommendation for this application.
        for row in self._session.execute(
            select(permit.Recommendation).where(
                permit.Recommendation.application_id == application.id,
                permit.Recommendation.status == "proposed",
            )
        ).scalars().all():
            row.status = "superseded"
            row.version += 1
        recommendation = permit.Recommendation(
            id=new_id("rec"),
            application_id=application.id,
            evaluation_id=evaluation.id if evaluation else None,
            proposed_outcome=outcome,
            evidence_refs=[
                {"rule_id": r.get("rule_id"), "citation": r.get("citation"),
                 "status": r.get("status"), "observed_value": r.get("observed_value"),
                 "limit_value": r.get("limit_value")}
                for r in results
            ],
            run_ref=step.id,
            status="proposed",
            rationale=rationale,
            muse_summary=muse_summary,
            muse_run_id=muse_run_id,
        )
        self._session.add(recommendation)
        self._session.flush()
        step.recommendation_id = recommendation.id
        step.model_run_id = muse_run_id
        self._finish_step(
            step, outcome="completed",
            detail=f"Advisory recommendation '{outcome}'. The Permit Reviewer decides.",
            actor=actor, references=(recommendation.id,),
        )
        return recommendation

    def _live_summary(self, application, outcome, rationale, actor):
        """Return a validated live Muse summary, or ``(None, run_id)``."""
        from acme_city.persistence.models import model_run as model_run_models

        settings = self._settings
        client = self._muse_client or MuseClient(settings)
        now = utc_now()
        row = model_run_models.ModelRun(
            id=new_id("modelrun"),
            correlation_id=new_id("corr"),
            mode="live",
            provider="meta",
            model="muse-spark-1.3",
            prompt_version="acme-summary-prompt-v1",
            schema_version="acme-summary-schema-v1",
            input_refs={
                "task": "case_summary",
                "application_id": application.id,
                "source_application_number": application.source_application_number,
            },
            output=None,
            validation_result=None,
            usage={},
            latency_ms=None,
            error=None,
            started_at=now,
            completed_at=None,
            actor_id=actor.actor_id,
        )
        self._session.add(row)
        self._session.flush()
        try:
            payload = build_summary_payload(
                model="muse-spark-1.3",
                outcome=outcome,
                rationale=rationale,
                application_ref=application.source_application_number,
            )
            response = client.create_response(payload)
            summary = validate_summary(response.output_text, expected_outcome=outcome)
            row.output = {"summary": summary} if summary else None
            row.error = response.error or (
                None if summary else "the summary named a different outcome or failed validation"
            )
            row.usage = dict(response.usage or {})
            row.latency_ms = response.latency_ms
        except Exception as exc:  # noqa: BLE001
            summary = None
            row.error = str(exc)
        row.completed_at = utc_now()
        row.validation_result = {
            "status": "succeeded" if summary else "failed",
            "state": "passed" if summary else "failed",
            "issues": [] if summary else [{"code": "summary_rejected", "message": row.error or ""}],
            "provider": {"response_id": None, "response_status": "live"},
        }
        self._session.flush()
        return summary, row.id


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
    """Return the current advisory recommendation of an application."""
    return session.execute(
        select(permit.Recommendation)
        .where(
            permit.Recommendation.application_id == application_id,
            permit.Recommendation.status == "proposed",
        )
        .order_by(permit.Recommendation.created_at.desc())
    ).scalars().first()


def record_reviewer_stance(
    session: Session,
    *,
    recommendation_id: str,
    application_id: str,
    stance: str,
    reason: str,
    actor: ActorContext,
    now: datetime | None = None,
) -> permit.Recommendation:
    """Record whether the reviewer agrees with the advisory recommendation.

    Disagreeing requires a reason.  The stance is evidence beside the
    decision; it never changes the recommendation and never decides.
    """
    from acme_city.auth.permissions import PermissionResolver

    PermissionResolver(session, now=now).authorize(
        actor,
        "permit.decide",
        ResourceContext(domain_id="permits", record_ids=()),
    )
    if stance not in {"agree", "disagree"}:
        raise ValidationError("the reviewer stance is 'agree' or 'disagree'")
    if stance == "disagree" and not reason.strip():
        raise ValidationError("disagreeing with the recommendation requires a reason")
    row = session.get(permit.Recommendation, recommendation_id)
    if row is None or row.application_id != application_id:
        from acme_city.core.errors import NotFoundError

        raise NotFoundError("that recommendation does not exist for this application")
    row.reviewer_stance = stance
    row.reviewer_stance_reason = reason.strip() or None
    row.reviewer_stance_actor_id = actor.actor_id
    row.version += 1
    session.flush()
    AuditService(session, now=now).append(
        action="recommendation.stance",
        actor=actor,
        target_type="application",
        target_id=row.application_id,
        reason=f"reviewer {stance} with the agent recommendation"
        + (f": {reason.strip()}" if reason.strip() else ""),
        references=[row.id],
        metadata={"stance": stance, "recommendation_id": row.id},
    )
    return row


__all__ = [
    "EXTRACTION_AGENT_ID",
    "IDENTITY_AGENT_ID",
    "INTAKE_AGENT_ID",
    "OUTCOME_APPROVE",
    "OUTCOME_CONDITIONS",
    "OUTCOME_DENY",
    "OUTCOME_INFORMATION",
    "OUTCOME_JUDGMENT",
    "RECOMMENDATION_AGENT_ID",
    "RULES_AGENT_ID",
    "STEP_NAMES",
    "TriageService",
    "build_rationale",
    "current_recommendation",
    "list_steps",
    "recommendation_outcome",
    "record_reviewer_stance",
    "service_actor",
]

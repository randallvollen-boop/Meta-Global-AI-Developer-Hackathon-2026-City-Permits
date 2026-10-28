"""The bounded Muse run service.

One run is one recorded fact.  The service records the run before it talks to
the provider, validates the output against the records the actor may see, and
writes a proposal only after the validation passed.  A live run, a replayed
run and a cached run are separate immutable records, and a failed run is never
rewritten.

Three modes exist:

``live``
    One request to the provider.  The call budget is reserved before the
    dispatch, one call is in flight at a time, there is no automatic retry and
    a provider error stops the following live calls.

``replay``
    A recorded output from a versioned fixture.  The replay is explicit: the
    caller names the fixture and the source run it replays, and the recorded
    prompt, schema and fixture versions must still be the current ones.

``cached``
    The output of an earlier run with exactly the same input, prompt, schema
    and model.  The earlier run is left untouched.
"""
# REQUIRES: AI-01, AI-02, AI-03, AI-04
# A model run records its mode, provider, model, prompt and schema versions, its inputs, its
# output, its validation, its usage, its latency and its errors. Live, replay and cached runs
# stay separate, a failed live run is never rewritten, and a proposal is written only after
# the validation passed.

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError, ValidationError
from acme_city.core.ids import new_id
from acme_city.muse.client import (
    MAX_OUTPUT_TOKENS,
    MuseClient,
    MuseRequestError,
    ProviderResponse,
    summarize_request,
)
from acme_city.muse.payloads import (
    VisibleEvidenceBundle,
    assert_no_truth_in_payload,
    build_extraction_payload,
    build_match_payload,
    fixture_root,
    read_document_fixture,
)
from acme_city.muse.schemas import (
    APPLICANT_ASSIST_TASK,
    DEFAULT_MUSE_MODEL,
    EXTRACTION_TASK,
    MATCH_TASK,
    MUSE_PROVIDER,
    PROPOSING_TASKS,
    TASK_CONFIG,
)
from acme_city.muse.validation import (
    ValidationIssue,
    ValidationOutcome,
    parse_output_text,
    validate_extraction_output,
    validate_match_output,
)
from acme_city.persistence.models import model_run, permit, registry

#: The permissions a run of each task needs.  Every one of them must be held.
TASK_PERMISSIONS: Final[dict[str, tuple[str, ...]]] = {
    EXTRACTION_TASK: ("records.document.view",),
    MATCH_TASK: ("records.document.view", "registry.crosswalk.propose"),
}

#: The permissions that mark a staff actor.  An applicant holds none of them,
#: so an applicant never reaches the model boundary even when the applicant may
#: read a document of its own case.
STAFF_PERMISSIONS: Final = frozenset(
    {
        "application.evaluate",
        "change.case.transition",
        "finance.allocation.confirm",
        "finance.assessment.create",
        "governance.dataset.register",
        "permit.decide",
        "permit.issue",
        "registry.crosswalk.decide",
        "registry.crosswalk.propose",
        "registry.provenance.view",
        "rule.version.draft",
        "source.record.update",
        "source.snapshot.stage",
    }
)

#: The label every model proposal score carries.
UNCALIBRATED_SCORE_LABEL: Final = "uncalibrated_heuristic"

#: The registry vocabulary a proposed disposition is recorded in.
DISPOSITION_MAP: Final[dict[str, str]] = {
    "link": "supported",
    "no_link": "no_match",
    "needs_review": "unresolved",
}

#: One live call is in flight at a time.  The lock is process wide.
_LIVE_DISPATCH_LOCK = threading.Lock()


def allowed_model(settings: Settings) -> str:
    """Return the model a run may use.

    The model is the first entry of the configured allowlist that the
    settings accept.  A model outside the Standard allowlist is never used.
    """
    for candidate in settings.muse_model_allowlist:
        if settings.model_is_allowed(candidate):
            return candidate
    return DEFAULT_MUSE_MODEL


def live_budget_error(session: Session, settings: Settings) -> str | None:
    """Return why a live call may not be sent, if it may not be sent.

    The budget and the error-stop policy are shared by every path that may
    reach the provider: the proposing runs of this module and the applicant
    help assistant both read the same cap and stop at the same recorded
    provider error.

    Args:
        session: The open session.
        settings: The application settings, which hold the call cap.

    Returns:
        The reason the call may not be sent, or ``None`` when it may.
    """
    rows = session.execute(
        select(model_run.ModelRun).where(model_run.ModelRun.mode == "live")
    ).scalars().all()
    for row in rows:
        if row.error:
            return (
                "a previous live run recorded a provider error; no further live call "
                "is sent"
            )
    used = sum(1 for row in rows if row.completed_at is not None)
    if used >= settings.muse_live_call_cap:
        return "the live call budget of this build run is exhausted"
    return None


class MuseRunCommand(BaseModel):
    """One request for bounded model work.

    The command never carries authority.  The server resolves the actor, the
    scope and the model, and a caller may only name the records it already
    knows about.
    """

    model_config = ConfigDict(extra="forbid")

    task: Literal["extraction", "match_proposal"]
    mode: Literal["live", "replay", "cached"] = "live"
    application_id: str = Field(min_length=1, max_length=64)
    document_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    prompt_version: str | None = None
    schema_version: str | None = None
    source_snapshot_id: str | None = None
    replay_fixture: str | None = None
    replay_of_run_id: str | None = None


class ModelRunView(BaseModel):
    """One recorded model run."""

    run_id: str
    task: str
    mode: str
    status: str
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    response_id: str | None = None
    response_status: str | None = None
    output: dict[str, Any] | None = None
    validation: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = None
    error: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    actor_id: str | None = None
    fixture_version: str | None = None
    replay_of_run_id: str | None = None
    cache_key: str | None = None
    input_refs: dict[str, Any] = Field(default_factory=dict)
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    score_label: str = UNCALIBRATED_SCORE_LABEL
    score_is_calibrated: bool = False


@dataclass(frozen=True)
class _Dispatch:
    """What a mode produced: the output and how it was obtained."""

    output: dict[str, Any] | None
    error: str | None
    response_id: str | None = None
    response_status: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int | None = None
    provider_error: bool = False
    bindings: dict[str, Any] = field(default_factory=dict)
    source_run_id: str | None = None


def _recommended_candidate(
    candidates: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Return the candidate a proposed link refers to.

    The model signals the candidate it proposes with its ordering score.  The
    server picks the highest score and breaks a tie with the order of the
    output, so the proposal is deterministic and never a second, silent
    interpretation of the model's answer.
    """
    best: Mapping[str, Any] | None = None
    best_score: float | None = None
    for candidate in candidates:
        if not candidate.get("entity_id"):
            continue
        raw = candidate.get("proposal_score")
        score = float(raw) if isinstance(raw, (int, float)) else None
        if best is None or (score is not None and (best_score is None or score > best_score)):
            best = candidate
            best_score = score
    return best


class MuseService:
    """Runs bounded model work and records what happened."""
    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        client: MuseClient | None = None,
        now: datetime | None = None,
        replay_root: Path | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._client = client or MuseClient(settings)
        self._now = now or utc_now()
        self._permissions = PermissionResolver(session, now=self._now)
        self._replay_root = replay_root or (fixture_root() / "replay")
        self._audit = AuditService(session, now=self._now)

    # -------------------------------------------------------------------- run

    def run(self, command: MuseRunCommand, actor: ActorContext) -> ModelRunView:
        """Run one bounded model task and record what happened.

        Args:
            command: The requested task, mode and records.
            actor: The acting actor.  The server resolves the scope.

        Returns:
            The recorded run.  A failed run is returned as a recorded run with
            its error and its validation issues; it is never hidden and never
            retried.
        """
        config = TASK_CONFIG.get(command.task)
        if config is None:
            raise ValidationError(f"unknown Muse task: {command.task!r}")
        if command.task not in PROPOSING_TASKS:
            # The applicant assistant is not a proposing task.  It is
            # dispatched by the applicant-help service, which owns the source
            # bundle, the grant and the privacy of the conversation.
            raise ValidationError(
                "the applicant assistant task is dispatched by its own path and never "
                "by the proposing run service"
            )
        if command.prompt_version and command.prompt_version != config["prompt_version"]:
            raise ValidationError(
                "the requested prompt version is not the current prompt version"
            )
        if command.schema_version and command.schema_version != config["schema_version"]:
            raise ValidationError(
                "the requested schema version is not the current schema version"
            )
        if command.mode == "replay" and not command.replay_fixture:
            raise ValidationError("a replay must name the fixture it replays")
        if command.mode == "replay" and not command.replay_of_run_id:
            raise ValidationError("a replay must name the source run it replays")

        self._authorize(actor, command)

        fixture: dict[str, Any] | None = None
        if command.mode == "replay":
            fixture = self._read_fixture(command.replay_fixture or "")

        bundle = VisibleEvidenceBundle.for_actor(
            command.application_id,
            actor,
            session=self._session,
            document_ids=command.document_ids,
            source_snapshot_id=command.source_snapshot_id,
        )
        payload = self._payload(command, bundle)
        assert_no_truth_in_payload(payload)

        input_refs = self._input_refs(command, bundle, payload)
        cache_key = self._cache_key(command, bundle, input_refs)
        run_row = self._create_run(command, actor, bundle, config, input_refs, cache_key, fixture)

        if command.mode == "live":
            dispatch = self._dispatch_live(command, bundle, payload)
        elif command.mode == "replay":
            dispatch = self._dispatch_replay(command, bundle, fixture or {})
        else:
            dispatch = self._dispatch_cached(command, bundle, cache_key)

        return self._finish(run_row, command, actor, bundle, dispatch)

    # ------------------------------------------------------------------ read

    def list_runs(
        self, actor: ActorContext, *, application_id: str | None = None
    ) -> list[ModelRunView]:
        """Return the recorded runs the actor may read.

        Args:
            actor: The acting actor.  A run is visible when the application it
                was about is visible to the actor.
            application_id: An optional filter for one application.

        Returns:
            The recorded runs, newest first.
        """
        self._authorize_reader(actor)
        rows = self._session.execute(
            select(model_run.ModelRun).order_by(
                model_run.ModelRun.created_at.desc(), model_run.ModelRun.id.desc()
            )
        ).scalars().all()
        views: list[ModelRunView] = []
        for row in rows:
            refs = row.input_refs or {}
            run_application = str(refs.get("application_id") or "")
            run_reference = str(refs.get("source_application_number") or "")
            if str(refs.get("task") or "") == APPLICANT_ASSIST_TASK:
                # A chat run belongs to the applicant who asked.  Staff never
                # read an un-escalated conversation, so the run is not listed
                # here at all.
                continue
            if not self._record_is_visible(actor, run_application, run_reference):
                continue
            if application_id and run_application != application_id:
                continue
            command = MuseRunCommand(
                task=str(refs.get("task") or EXTRACTION_TASK),
                application_id=run_application or "unknown",
            )
            views.append(self._view(row, command, []))
        return views

    def _authorize_reader(self, actor: ActorContext) -> None:
        """Refuse an actor that may not read model runs."""
        resource = ResourceContext(domain_id="permits", record_ids=())
        if not self._permissions.allows(actor, "records.document.view", resource):
            raise PermissionDeniedError(
                f"actor {actor.actor_id} may not read model runs",
                actor_id=actor.actor_id,
                action="records.document.view",
                domain_id="permits",
            )
        held = self._permissions.permissions_for(actor.actor_id)
        if not held & STAFF_PERMISSIONS:
            raise PermissionDeniedError(
                f"actor {actor.actor_id} may not read model runs",
                actor_id=actor.actor_id,
                action="muse.run",
                domain_id="permits",
            )

    def _record_is_visible(
        self, actor: ActorContext, application_id: str, reference: str
    ) -> bool:
        """Return whether a run is inside the record scope of the actor."""
        if not actor.record_scope:
            return True
        return bool({application_id, reference} & actor.record_scope)

    # -------------------------------------------------------------- authorize

    def _authorize(self, actor: ActorContext, command: MuseRunCommand) -> None:
        """Refuse an actor that may not request bounded model work.

        A run needs the explicit grants of its task and at least one staff
        permission.  An applicant holds none of the staff permissions, so the
        model boundary is closed to an applicant even when the applicant may
        read a document of its own case.
        """
        required = TASK_PERMISSIONS.get(command.task, ())
        application = self._session.get(permit.Application, command.application_id)
        resource = ResourceContext(
            domain_id="permits",
            record_ids=(
                command.application_id,
                application.source_application_number if application is not None else "",
            ),
        )
        for action in required:
            if not self._permissions.allows(actor, action, resource):
                raise PermissionDeniedError(
                    f"actor {actor.actor_id} may not request {command.task} model work",
                    actor_id=actor.actor_id,
                    action=action,
                    domain_id="permits",
                )
        held = self._permissions.permissions_for(actor.actor_id)
        if not held & STAFF_PERMISSIONS:
            raise PermissionDeniedError(
                f"actor {actor.actor_id} may not request {command.task} model work",
                actor_id=actor.actor_id,
                action="muse.run",
                domain_id="permits",
            )

    # ----------------------------------------------------------------- payload

    def _payload(
        self, command: MuseRunCommand, bundle: VisibleEvidenceBundle
    ) -> dict[str, Any]:
        """Return the outbound payload of a run."""
        model = self._model()
        if command.task == EXTRACTION_TASK:
            return build_extraction_payload(
                bundle, model=model, max_output_tokens=MAX_OUTPUT_TOKENS
            )
        return build_match_payload(bundle, model=model, max_output_tokens=MAX_OUTPUT_TOKENS)

    def _model(self) -> str:
        """Return the model a run may use."""
        return allowed_model(self._settings)

    # --------------------------------------------------------------- recording

    def _input_refs(
        self,
        command: MuseRunCommand,
        bundle: VisibleEvidenceBundle,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return the references a run was given."""
        refs: dict[str, Any] = {
            "task": command.task,
            "application_id": bundle.application_id,
            "source_application_number": bundle.source_application_number,
            "application_revision": bundle.application_revision,
            "documents": [
                {
                    "document_id": reference.document_id,
                    "version": reference.version,
                    "content_hash": reference.content_hash,
                    "line_count": reference.line_count,
                    "document_type": reference.document_type,
                }
                for reference in bundle.documents
            ],
            "candidate_ids": list(bundle.candidate_ids()),
            "request": summarize_request(payload),
        }
        if bundle.source_record is not None:
            refs["source_record"] = {
                "source_snapshot_id": bundle.source_record.source_snapshot_id,
                "source_system_id": bundle.source_record.source_system_id,
                "source_dataset_id": bundle.source_record.source_dataset_id,
                "source_record_id": bundle.source_record.source_record_id,
                "source_record_version": bundle.source_record.source_record_version,
                "payload_hash": bundle.source_record.payload_hash,
            }
        return refs

    def _cache_key(
        self,
        command: MuseRunCommand,
        bundle: VisibleEvidenceBundle,
        input_refs: Mapping[str, Any],
    ) -> str:
        """Return the hash that identifies an equivalent run."""
        config = TASK_CONFIG[command.task]
        material = {
            "task": command.task,
            "model": self._model(),
            "prompt_version": config["prompt_version"],
            "schema_version": config["schema_version"],
            "application_id": bundle.application_id,
            "application_revision": bundle.application_revision,
            "documents": [
                [item["document_id"], item["version"], item["content_hash"]]
                for item in input_refs.get("documents", [])
            ],
            "source_record": input_refs.get("source_record"),
            "candidate_ids": sorted(bundle.candidate_ids()),
        }
        text = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _create_run(
        self,
        command: MuseRunCommand,
        actor: ActorContext,
        bundle: VisibleEvidenceBundle,
        config: Mapping[str, str],
        input_refs: dict[str, Any],
        cache_key: str,
        fixture: Mapping[str, Any] | None,
    ) -> model_run.ModelRun:
        """Record the run before anything is dispatched."""
        refs = dict(input_refs)
        refs["cache_key"] = cache_key
        row = model_run.ModelRun(
            id=new_id("modelrun"),
            correlation_id=new_id("corr"),
            mode=command.mode,
            provider=MUSE_PROVIDER,
            model=self._model(),
            prompt_version=config["prompt_version"],
            schema_version=config["schema_version"],
            input_refs=refs,
            output=None,
            validation_result=None,
            usage=None,
            latency_ms=None,
            error=None,
            started_at=self._now,
            completed_at=None,
            actor_id=actor.actor_id,
            fixture_version=(
                str(fixture.get("fixture_version")) if fixture and fixture.get("fixture_version") else None
            ),
            replay_of_run_id=command.replay_of_run_id,
            scenario_id=bundle.scenario_id,
        )
        self._session.add(row)
        self._session.flush()
        self._record_inputs(row, bundle)
        return row

    def _record_inputs(
        self, row: model_run.ModelRun, bundle: VisibleEvidenceBundle
    ) -> None:
        """Record the references of a run and the evidence it may quote."""
        self._session.add(
            model_run.ModelInput(
                id=new_id("modelin"),
                run_id=row.id,
                input_type="application_revision",
                input_ref=f"{bundle.application_id}:rev{bundle.application_revision}",
                content_hash=None,
            )
        )
        for reference in bundle.documents:
            self._session.add(
                model_run.ModelInput(
                    id=new_id("modelin"),
                    run_id=row.id,
                    input_type="document_version",
                    input_ref=f"{reference.document_id}:v{reference.version}",
                    content_hash=reference.content_hash,
                )
            )
            document = self._session.get(permit.Document, reference.document_id)
            self._session.add(
                model_run.EvidenceReference(
                    id=new_id("evidence"),
                    run_id=row.id,
                    evidence_kind="document",
                    entity_type="document",
                    entity_id=reference.document_id,
                    path=document.file_ref if document is not None else "",
                    label=f"{reference.document_type} version {reference.version}",
                    content_hash=reference.content_hash,
                    fictional_demo=True,
                )
            )
        if bundle.source_record is not None:
            self._session.add(
                model_run.ModelInput(
                    id=new_id("modelin"),
                    run_id=row.id,
                    input_type="source_snapshot",
                    input_ref=bundle.source_record.source_snapshot_id,
                    content_hash=bundle.source_record.payload_hash,
                )
            )

    # ---------------------------------------------------------------- dispatch

    def _dispatch_live(
        self,
        command: MuseRunCommand,
        bundle: VisibleEvidenceBundle,
        payload: dict[str, Any],
    ) -> _Dispatch:
        """Send one live request, under the call budget."""
        blocked = self._live_budget_error()
        if blocked is not None:
            return _Dispatch(output=None, error=blocked, provider_error=True)
        with _LIVE_DISPATCH_LOCK:
            blocked = self._live_budget_error()
            if blocked is not None:
                return _Dispatch(output=None, error=blocked, provider_error=True)
            try:
                response: ProviderResponse = self._client.create_response(payload)
            except MuseRequestError as exc:
                return _Dispatch(output=None, error=str(exc), provider_error=True)
        if response.error is not None:
            return _Dispatch(
                output=None,
                error=response.error,
                response_id=response.response_id,
                response_status=response.status,
                usage=response.usage,
                latency_ms=response.latency_ms,
                provider_error=True,
            )
        data, issue = parse_output_text(command.task, response.output_text)
        if issue is not None:
            return _Dispatch(
                output=None,
                error=issue.message,
                response_id=response.response_id,
                response_status=response.status,
                usage=response.usage,
                latency_ms=response.latency_ms,
                provider_error=True,
            )
        return _Dispatch(
            output=data,
            error=None,
            response_id=response.response_id,
            response_status=response.status,
            usage=response.usage,
            latency_ms=response.latency_ms,
        )

    def _live_budget_error(self) -> str | None:
        """Return why a live call may not be sent, if it may not be sent."""
        return live_budget_error(self._session, self._settings)

    def _dispatch_replay(
        self, command: MuseRunCommand, bundle: VisibleEvidenceBundle, fixture: Mapping[str, Any]
    ) -> _Dispatch:
        """Return the recorded output of a versioned replay fixture."""
        if fixture.get("task") != command.task:
            return _Dispatch(
                output=None,
                error="the replay fixture belongs to a different task",
                provider_error=True,
            )
        config = TASK_CONFIG[command.task]
        if fixture.get("prompt_version") != config["prompt_version"]:
            return _Dispatch(
                output=None,
                error="the replay fixture was recorded with another prompt version",
                provider_error=True,
            )
        if fixture.get("schema_version") != config["schema_version"]:
            return _Dispatch(
                output=None,
                error="the replay fixture was recorded with another schema version",
                provider_error=True,
            )
        if fixture.get("source_run_id") != command.replay_of_run_id:
            return _Dispatch(
                output=None,
                error="the replay fixture does not belong to the requested source run",
                provider_error=True,
            )
        recorded = fixture.get("output")
        if not isinstance(recorded, dict):
            return _Dispatch(
                output=None,
                error="the replay fixture carries no recorded output",
                provider_error=True,
            )
        bound, bindings = self._bind_replay_output(recorded, bundle)
        return _Dispatch(
            output=bound,
            error=None,
            response_id=fixture.get("source_response_id"),
            response_status="replayed",
            usage=dict(fixture.get("usage") or {}),
            latency_ms=fixture.get("latency_ms"),
            bindings=bindings,
        )

    def _read_fixture(self, name: str) -> dict[str, Any]:
        """Return the recorded fixture with the given name."""
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ValidationError("the replay fixture name is not acceptable")
        path = self._replay_root / name
        if not path.is_file():
            raise ValidationError(f"the replay fixture {name!r} does not exist")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValidationError(f"the replay fixture {name!r} cannot be read") from exc
        if not isinstance(data, dict):
            raise ValidationError(f"the replay fixture {name!r} is not an object")
        return data

    def _bind_replay_output(
        self, recorded: Mapping[str, Any], bundle: VisibleEvidenceBundle
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Bind a recorded output to the records of the current run.

        A recorded output names the application and the document version it
        was produced from.  The identifier of a stored document version is
        generated, so the binding resolves the recorded reference against the
        visible documents by their content hash.
        """
        bound = dict(recorded)
        bindings: dict[str, Any] = {}

        application_ref = str(bound.get("application_id") or "")
        if application_ref and application_ref != bundle.application_id:
            if application_ref == bundle.source_application_number:
                bound["application_id"] = bundle.application_id
                bindings["application_id"] = {
                    "recorded": application_ref,
                    "bound": bundle.application_id,
                }
            else:
                bindings["application_id"] = {"recorded": application_ref, "bound": None}

        document_ref = str(bound.get("document_id") or "")
        visible = {reference.document_id for reference in bundle.documents}
        if document_ref and document_ref not in visible:
            target = self._document_for_reference(bundle, document_ref)
            bindings["document_id"] = {
                "recorded": document_ref,
                "bound": target.document_id if target is not None else None,
            }
            if target is not None:
                bound["document_id"] = target.document_id
        return bound, bindings

    def _document_for_reference(
        self, bundle: VisibleEvidenceBundle, reference: str
    ) -> Any:
        """Return the visible document a recorded reference names."""
        digest: str | None = None
        if len(reference) == 64 and all(char in "0123456789abcdef" for char in reference.lower()):
            digest = reference.lower()
        else:
            try:
                digest = hashlib.sha256(read_document_fixture(reference)).hexdigest()
            except Exception:  # noqa: BLE001 - an unknown reference binds to nothing
                digest = None
        if digest is None:
            return None
        for document in bundle.documents:
            if document.content_hash == digest:
                return document
        return None

    def _dispatch_cached(
        self, command: MuseRunCommand, bundle: VisibleEvidenceBundle, cache_key: str
    ) -> _Dispatch:
        """Return the output of an earlier run with the same input."""
        rows = self._session.execute(
            select(model_run.ModelRun)
            .where(model_run.ModelRun.mode.in_(("live", "replay", "cached")))
            .order_by(model_run.ModelRun.created_at, model_run.ModelRun.id)
        ).scalars().all()
        for row in rows:
            refs = row.input_refs or {}
            if refs.get("cache_key") != cache_key:
                continue
            if row.error or not row.output:
                # A failed run is never reused and never rewritten.
                continue
            validation = row.validation_result or {}
            if validation.get("state") != "passed":
                continue
            return _Dispatch(
                output=dict(row.output),
                error=None,
                response_id=None,
                response_status="cached",
                usage=dict(row.usage or {}),
                latency_ms=row.latency_ms,
                source_run_id=row.id,
            )
        return _Dispatch(
            output=None,
            error="no cached run matches this input, prompt, schema and model",
            provider_error=True,
        )

    # ----------------------------------------------------------------- finish

    def _finish(
        self,
        row: model_run.ModelRun,
        command: MuseRunCommand,
        actor: ActorContext,
        bundle: VisibleEvidenceBundle,
        dispatch: _Dispatch,
    ) -> ModelRunView:
        """Validate the output, write the proposals and close the run."""
        if dispatch.output is None:
            outcome = ValidationOutcome(
                state="not_run",
                issues=(
                    ValidationIssue(
                        code="run_failed",
                        message=dispatch.error or "the run produced no output",
                    ),
                ),
            )
        elif command.task == EXTRACTION_TASK:
            outcome = validate_extraction_output(
                dispatch.output, bundle=bundle, application_id=bundle.application_id
            )
        else:
            outcome = validate_match_output(
                dispatch.output,
                bundle=bundle,
                source_snapshot_id=(
                    bundle.source_record.source_snapshot_id
                    if bundle.source_record is not None
                    else ""
                ),
                allowed_candidate_ids=bundle.candidate_ids(),
            )

        proposals: list[dict[str, Any]] = []
        if outcome.ok and dispatch.output is not None:
            proposals = self._write_proposals(row, command, bundle, dispatch.output)

        validation = outcome.to_dict()
        validation["status"] = "succeeded" if outcome.ok else "failed"
        validation["provider"] = {
            "response_id": dispatch.response_id,
            "response_status": dispatch.response_status,
        }
        if dispatch.bindings:
            validation["bindings"] = dispatch.bindings

        row.output = dispatch.output
        row.validation_result = validation
        row.usage = dict(dispatch.usage or {})
        row.latency_ms = dispatch.latency_ms
        row.error = dispatch.error
        row.completed_at = self._now
        if dispatch.source_run_id:
            row.replay_of_run_id = dispatch.source_run_id
        self._session.flush()

        self._session.add(
            model_run.ModelOutput(
                id=new_id("modelout"),
                run_id=row.id,
                payload=dispatch.output,
                validation_errors=[issue.to_dict() for issue in outcome.issues],
                validation_state=(
                    "validated" if outcome.ok else ("rejected" if outcome.state == "failed" else outcome.state)
                ),
            )
        )
        self._session.flush()

        self._audit.append(
            action="muse.run",
            actor=actor,
            target_type="model_run",
            target_id=row.id,
            reason=f"{command.task} run in {command.mode} mode: {validation['status']}",
            references=[bundle.application_id],
            correlation_id=row.correlation_id,
            outcome="accepted" if outcome.ok else "denied",
            denial_reason=None if outcome.ok else "the model output failed validation",
            metadata={
                "task": command.task,
                "mode": command.mode,
                "model": row.model,
                "prompt_version": row.prompt_version,
                "schema_version": row.schema_version,
                "validation_state": outcome.state,
            },
        )

        return self._view(row, command, proposals)

    def _write_proposals(
        self,
        row: model_run.ModelRun,
        command: MuseRunCommand,
        bundle: VisibleEvidenceBundle,
        output: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Write the proposals of a validated output."""
        if command.task == EXTRACTION_TASK:
            return self._write_extraction(row, bundle, output)
        return self._write_match(row, bundle, output)

    def _write_extraction(
        self,
        row: model_run.ModelRun,
        bundle: VisibleEvidenceBundle,
        output: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Write the extraction observations of a validated output."""
        written: list[dict[str, Any]] = []
        for observation in output.get("observations", []):
            evidence = observation.get("evidence") or {}
            record = permit.ExtractionObservation(
                id=new_id("obs"),
                document_id=str(output.get("document_id")),
                document_version=int(output.get("document_version") or 1),
                field_path=str(observation.get("field")),
                proposed_value=str(observation.get("proposed_value")),
                page_region=f"L{evidence.get('line_start')}-L{evidence.get('line_end')}",
                evidence_excerpt=str(evidence.get("excerpt")),
                model_run_id=row.id,
                validation_state="proposed",
            )
            self._session.add(record)
            written.append(
                {
                    "observation_id": record.id,
                    "document_id": record.document_id,
                    "field_path": record.field_path,
                    "proposed_value": record.proposed_value,
                }
            )
        self._session.flush()
        return written

    def _write_match(
        self,
        row: model_run.ModelRun,
        bundle: VisibleEvidenceBundle,
        output: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Write the match proposal of a validated output."""
        if bundle.source_record is None:
            return []
        disposition = DISPOSITION_MAP.get(
            str(output.get("recommended_disposition")), "unresolved"
        )
        candidates = output.get("candidates") or []
        recommended = None
        if disposition == "supported":
            recommended = _recommended_candidate(candidates)
        entity_id = str(recommended.get("entity_id")) if recommended else None
        score = recommended.get("proposal_score") if recommended else None

        supporting = [
            {
                "field": "model_supporting",
                "source_snapshot_id": bundle.source_record.source_snapshot_id,
                "raw_value": None,
                "normalized_value": None,
                "direction": "supporting",
                "method": "model_proposal",
                "detail": str(text),
            }
            for candidate in candidates
            for text in (candidate.get("supporting") or [])
        ]
        conflicting = [
            {
                "field": "model_conflicting",
                "source_snapshot_id": bundle.source_record.source_snapshot_id,
                "raw_value": None,
                "normalized_value": None,
                "direction": "conflicting",
                "method": "model_proposal",
                "detail": str(text),
            }
            for candidate in candidates
            for text in (candidate.get("conflicting") or [])
        ]

        record = registry.MatchProposal(
            id=new_id("proposal"),
            correlation_id=new_id("corr"),
            source_snapshot_id=bundle.source_record.source_snapshot_id,
            entity_id=entity_id,
            candidate_ids=[str(candidate.get("entity_id")) for candidate in candidates],
            compared_fields=sorted(
                {
                    str(item.get("field"))
                    for candidate in candidates
                    for item in (
                        list(candidate.get("supporting") or [])
                        + list(candidate.get("conflicting") or [])
                    )
                    if isinstance(item, Mapping)
                }
            ),
            supporting_evidence=supporting,
            conflicting_evidence=conflicting,
            method="model_proposal",
            model_run_id=row.id,
            proposal_score=float(score) if isinstance(score, (int, float)) else None,
            score_is_calibrated=False,
            disposition=disposition,
            created_by_actor_id=row.actor_id,
            scenario_id=bundle.scenario_id,
        )
        self._session.add(record)
        self._session.flush()
        return [
            {
                "proposal_id": record.id,
                "entity_id": record.entity_id,
                "disposition": record.disposition,
                "proposal_score": record.proposal_score,
                "score_is_calibrated": False,
                "score_label": UNCALIBRATED_SCORE_LABEL,
            }
        ]

    # ------------------------------------------------------------------- view

    def _view(
        self,
        row: model_run.ModelRun,
        command: MuseRunCommand,
        proposals: Sequence[Mapping[str, Any]],
    ) -> ModelRunView:
        """Return the view of one recorded run."""
        validation = dict(row.validation_result or {})
        status = str(validation.get("status") or ("failed" if row.error else "unknown"))
        refs = dict(row.input_refs or {})
        provider = validation.get("provider") or {}
        return ModelRunView(
            run_id=row.id,
            task=command.task,
            mode=row.mode,
            status=status,
            provider=row.provider,
            model=row.model,
            prompt_version=row.prompt_version,
            schema_version=row.schema_version,
            response_id=provider.get("response_id"),
            response_status=provider.get("response_status"),
            output=row.output,
            validation=validation,
            usage=dict(row.usage or {}),
            latency_ms=row.latency_ms,
            error=row.error,
            started_at=row.started_at,
            completed_at=row.completed_at,
            actor_id=row.actor_id,
            fixture_version=row.fixture_version,
            replay_of_run_id=row.replay_of_run_id,
            cache_key=str(refs.get("cache_key")) if refs.get("cache_key") else None,
            input_refs=refs,
            proposals=[dict(item) for item in proposals],
            score_label=UNCALIBRATED_SCORE_LABEL,
            score_is_calibrated=False,
        )


__all__ = [
    "DISPOSITION_MAP",
    "STAFF_PERMISSIONS",
    "MuseRunCommand",
    "MuseService",
    "ModelRunView",
    "TASK_PERMISSIONS",
    "UNCALIBRATED_SCORE_LABEL",
    "allowed_model",
    "live_budget_error",
]

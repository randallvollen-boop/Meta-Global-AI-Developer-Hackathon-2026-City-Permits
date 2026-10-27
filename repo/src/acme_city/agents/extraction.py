"""Field extraction for the intake agent.

The extractor proposes values from the documents that were actually received.
In replay mode (the default) the proposal is built deterministically from the
lines the document contains and is then passed through the same validation a
live model output passes through.  The validation result is reported as it
was computed: the issues the validator found, and nothing else.  No
percentage is ever invented.
"""
# REQUIRES: AI-03, AI-04, SEC-04
# A proposed value is written only when the validator accepted it, and the
# run records the real validation state.

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.core.ids import new_id
from acme_city.muse.payloads import VisibleEvidenceBundle
from acme_city.muse.schemas import EXTRACTION_TASK, TASK_CONFIG
from acme_city.muse.validation import validate_extraction_output
from acme_city.persistence.models import model_run as model_run_models
from acme_city.persistence.models import permit

#: The document lines the replay extractor reads, and the field each one
#: proposes.  A line is only read when the document really carries it.
EXTRACTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("applicant_legal_name", "Applicant name:"),
    ("unit_address", "Site address:"),
    ("parcel_reference", "Parcel reference:"),
    ("project_description", "Project description:"),
    ("declared_valuation", "Declared valuation:"),
    ("contractor_registration", "Contractor licence:"),
)

#: The model the replay labels its run with.
REPLAY_MODEL = "muse-spark-1.3"


def replay_extraction(
    session: Session,
    application: permit.Application,
    actor: ActorContext,
) -> dict[str, Any]:
    """Run one replay extraction and return what actually happened.

    The returned mapping names the run, its mode, the real validation state,
    the issues the validator reported and the observations that were written.
    """
    bundle = VisibleEvidenceBundle.for_actor(
        application.id, actor, session=session
    )
    if not bundle.documents:
        return {
            "run_id": None,
            "mode": "replay",
            "state": "skipped",
            "issues": [],
            "observations": [],
        }

    observations: list[dict[str, Any]] = []
    source: tuple[str, int] | None = None
    for reference in bundle.documents:
        lines = bundle.lines_of(reference.document_id)
        for field, marker in EXTRACTION_PATTERNS:
            for index, line in enumerate(lines, start=1):
                if marker.lower() not in line.lower():
                    continue
                value = line.split(":", 1)[1].strip() if ":" in line else line.strip()
                if not value:
                    continue
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
            source = (reference.document_id, reference.version)
            break

    if source is None or not observations:
        return {
            "run_id": None,
            "mode": "replay",
            "state": "skipped",
            "issues": [],
            "observations": [],
        }

    document_id, document_version = source
    output = {
        "application_id": application.id,
        "document_id": document_id,
        "document_version": document_version,
        "observations": observations,
    }
    outcome = validate_extraction_output(output, bundle=bundle, application_id=application.id)
    config = TASK_CONFIG[EXTRACTION_TASK]
    row = model_run_models.ModelRun(
        id=new_id("modelrun"),
        correlation_id=new_id("corr"),
        mode="replay",
        provider="meta",
        model=REPLAY_MODEL,
        prompt_version=config["prompt_version"],
        schema_version=config["schema_version"],
        input_refs={
            "task": EXTRACTION_TASK,
            "application_id": application.id,
            "source_application_number": application.source_application_number,
            "documents": [
                {
                    "document_id": reference.document_id,
                    "version": reference.version,
                    "content_hash": reference.content_hash,
                }
                for reference in bundle.documents
            ],
        },
        output=output if outcome.ok else None,
        validation_result={
            **outcome.to_dict(),
            "status": "succeeded" if outcome.ok else "failed",
            "provider": {"response_id": None, "response_status": "replayed"},
            "replay_note": (
                "replayed from the received document text; no provider call was sent"
            ),
        },
        usage={},
        latency_ms=None,
        error=None if outcome.ok else "the replayed extraction failed validation",
        started_at=_now(),
        completed_at=_now(),
        actor_id=actor.actor_id,
        replay_of_run_id="intake-document-replay",
    )
    session.add(row)
    session.flush()

    written: list[dict[str, Any]] = []
    if outcome.ok:
        for observation in observations:
            evidence = observation.get("evidence") or {}
            record = permit.ExtractionObservation(
                id=new_id("obs"),
                document_id=document_id,
                document_version=document_version,
                field_path=str(observation["field"]),
                proposed_value=str(observation["proposed_value"]),
                page_region=f"L{evidence.get('line_start')}-L{evidence.get('line_end')}",
                evidence_excerpt=str(evidence.get("excerpt")),
                model_run_id=row.id,
                validation_state="proposed",
            )
            session.add(record)
            written.append(
                {
                    "observation_id": record.id,
                    "field": record.field_path,
                    "value": record.proposed_value,
                }
            )
        session.flush()

    return {
        "run_id": row.id,
        "mode": "replay",
        "state": "succeeded" if outcome.ok else "failed",
        "issues": [issue.to_dict() for issue in outcome.issues],
        "observations": written,
    }


def _now():
    """Return the current time in timezone-aware UTC."""
    from acme_city.core.clock import utc_now

    return utc_now()


__all__ = ["EXTRACTION_PATTERNS", "REPLAY_MODEL", "replay_extraction"]

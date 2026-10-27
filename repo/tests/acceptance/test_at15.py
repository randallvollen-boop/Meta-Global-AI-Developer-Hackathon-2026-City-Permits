"""AT15: every model run is traceable and every mode stays distinct.

A run records its mode, its provider and model, its prompt and schema
versions, the references it was given, its output, its validation, its usage,
its latency and its errors.  A proposal score is labeled uncalibrated.  A live
run, a replayed run and a cached run are three different records, a failed
live run is preserved, and a replay has to be chosen explicitly.

The provider is mocked at the provider boundary: no live request is sent and
no spend occurs.
"""
# REQUIRES: AT15, AI-03, AI-04
# A model run persists its mode, provider, model, prompt and schema versions, its inputs, its
# output, its validation, its usage, its latency and its errors. Live, replay and cached runs
# stay distinct, a failed live run is preserved, and a replay must be selected explicitly.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.documents.service import DocumentService, StoreDocumentCommand
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.muse.client import MuseClient
from acme_city.muse.payloads import fixture_root, read_document_fixture
from acme_city.muse.router import router as muse_router
from acme_city.muse.service import MuseRunCommand, MuseService
from acme_city.persistence.models import model_run, permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

APPLICATION_ID = "app_synth_001"
EXTRACTION_FIXTURE = "extraction-success.json"


class RecordingTransport(httpx.BaseTransport):
    """A transport that records the request and answers with a fixed body."""

    def __init__(self, body: dict[str, Any]) -> None:
        self.requests: list[httpx.Request] = []
        self._body = body

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=self._body)


def provider_body(text: str = "{}") -> dict[str, Any]:
    """Return a provider response body that carries the given text."""
    return {
        "id": "resp_at15",
        "model": "muse-spark-1.3",
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]}
        ],
        "usage": {
            "input_tokens": 512,
            "output_tokens": 128,
            "total_tokens": 640,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def context_for(session, actor_id: str) -> ActorContext:
    """Return the server-resolved context of a seeded persona."""
    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


@pytest.fixture()
def seeded(tmp_path: Path):
    """Return the settings, the factory and the stored document."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'at15.db'}",
            "ACME_SECRET_KEY": "at15-acceptance-secret-value",
            "META_API_KEY": "test-provider-key-not-a-real-credential",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                DemoEnvironment(
                    id="demo_environment_local",
                    environment_id=ENVIRONMENT_ID,
                    fictional_demo=True,
                    fixture_version=bundle.fixture_version,
                    label="local fictional demonstration",
                )
            )
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            service = DocumentService(session, root=tmp_path / "documents")
            stored = service.store_version(
                StoreDocumentCommand(
                    application_id=APPLICATION_ID,
                    document_type="construction_plans",
                    filename="SYN-APP-001-application-v1.txt",
                    media_type="text/plain",
                    content=read_document_fixture("SYN-APP-001-application-v1.txt"),
                ),
                steward,
            )
            session.commit()
        yield settings, factory, stored, steward
    finally:
        factory.dispose()


def test_a_live_run_records_every_field_of_the_trace(seeded) -> None:
    settings, factory, stored, steward = seeded
    transport = RecordingTransport(provider_body())
    with factory() as session:
        service = MuseService(
            session, settings, client=MuseClient(settings, transport=transport)
        )
        view = service.run(
            MuseRunCommand(
                task="extraction",
                mode="live",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()
        row = session.get(model_run.ModelRun, view.run_id)

    assert row.mode == "live"
    assert row.provider == "meta"
    assert row.model == "muse-spark-1.3"
    assert row.prompt_version
    assert row.schema_version
    assert row.actor_id == "persona_data_steward"
    assert row.started_at is not None
    assert row.completed_at is not None
    assert row.latency_ms is not None
    assert row.usage["input_tokens"] == 512
    assert row.usage["total_tokens"] == 640
    assert row.validation_result["state"] in {"passed", "failed"}
    assert row.input_refs["documents"][0]["document_id"] == stored.document_id
    assert row.input_refs["documents"][0]["content_hash"] == stored.content_hash
    assert row.input_refs["application_revision"] == 1

    inputs = session.execute(
        select(model_run.ModelInput).where(model_run.ModelInput.run_id == row.id)
    ).scalars().all()
    assert {item.input_type for item in inputs} >= {
        "application_revision",
        "document_version",
    }
    outputs = session.execute(
        select(model_run.ModelOutput).where(model_run.ModelOutput.run_id == row.id)
    ).scalars().all()
    assert len(outputs) == 1
    assert outputs[0].validation_state in {"validated", "rejected", "not_run"}


def test_a_proposal_score_is_labeled_uncalibrated(seeded) -> None:
    settings, factory, stored, steward = seeded
    transport = RecordingTransport(provider_body())
    with factory() as session:
        service = MuseService(
            session, settings, client=MuseClient(settings, transport=transport)
        )
        view = service.run(
            MuseRunCommand(
                task="match_proposal",
                mode="live",
                application_id=APPLICATION_ID,
                source_snapshot_id="snap_erp_finance_ERP-BL-00413_v1",
            ),
            steward,
        )
        session.commit()
    assert view.score_is_calibrated is False
    assert view.score_label == "uncalibrated_heuristic"


def test_live_replay_and_cached_runs_are_three_different_records(seeded) -> None:
    settings, factory, stored, steward = seeded
    fixture = json.loads(
        (fixture_root() / "replay" / EXTRACTION_FIXTURE).read_text(encoding="utf-8")
    )
    transport = RecordingTransport(provider_body())
    with factory() as session:
        service = MuseService(
            session, settings, client=MuseClient(settings, transport=transport)
        )
        live = service.run(
            MuseRunCommand(
                task="extraction",
                mode="live",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()
        replay = service.run(
            MuseRunCommand(
                task="extraction",
                mode="replay",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
                replay_fixture=EXTRACTION_FIXTURE,
                replay_of_run_id=fixture["source_run_id"],
            ),
            steward,
        )
        session.commit()
        cached = service.run(
            MuseRunCommand(
                task="extraction",
                mode="cached",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()

        rows = session.execute(select(model_run.ModelRun)).scalars().all()
        modes = sorted(row.mode for row in rows)
        assert modes == ["cached", "live", "replay"]
        assert len({row.id for row in rows}) == 3
        assert replay.replay_of_run_id == fixture["source_run_id"]
        # The live run answered with an output that failed the validation, so it
        # is never reused.  The cache reuses the run that passed.
        assert live.status == "failed"
        assert cached.replay_of_run_id == replay.run_id


def test_a_failed_live_run_is_preserved(seeded) -> None:
    settings, factory, stored, steward = seeded
    transport = RecordingTransport(
        {"id": "resp_at15_error", "status": "failed", "error": {"message": "the provider refused"}}
    )
    with factory() as session:
        service = MuseService(
            session, settings, client=MuseClient(settings, transport=transport)
        )
        view = service.run(
            MuseRunCommand(
                task="extraction",
                mode="live",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()
        row = session.get(model_run.ModelRun, view.run_id)
        assert row.error
        assert row.mode == "live"
        assert row.completed_at is not None
        observations = session.execute(select(permit.ExtractionObservation)).scalars().all()
        assert observations == []


def test_a_replay_has_to_be_selected_explicitly(seeded) -> None:
    settings, factory, stored, steward = seeded
    from acme_city.core.errors import ValidationError

    with factory() as session:
        service = MuseService(session, settings)
        with pytest.raises(ValidationError):
            service.run(
                MuseRunCommand(
                    task="extraction",
                    mode="replay",
                    application_id=APPLICATION_ID,
                    document_ids=[stored.document_id],
                ),
                steward,
            )
        with pytest.raises(ValidationError):
            service.run(
                MuseRunCommand(
                    task="extraction",
                    mode="replay",
                    application_id=APPLICATION_ID,
                    document_ids=[stored.document_id],
                    replay_fixture="extraction-success.json",
                ),
                steward,
            )


def test_the_endpoints_expose_the_recorded_runs(seeded) -> None:
    settings, factory, stored, steward = seeded
    transport = RecordingTransport(provider_body())
    app = create_app(settings)
    app.include_router(muse_router)
    with TestClient(app) as client:
        assert client.get("/api/muse/runs").status_code == 401
        selected = client.post("/api/session/select", json={"actor_id": "persona_data_steward"})
        assert selected.status_code == 200, selected.text

        denied = client.post(
            "/api/muse/run",
            json={"task": "extraction", "mode": "live", "application_id": APPLICATION_ID},
        )
        assert denied.status_code == 200
        assert denied.json()["mode"] == "live"

        listed = client.get("/api/muse/runs")
        assert listed.status_code == 200
        runs = listed.json()["runs"]
        assert len(runs) == 1
        assert runs[0]["mode"] == "live"
        assert runs[0]["model"] == "muse-spark-1.3"
        assert runs[0]["score_label"] == "uncalibrated_heuristic"


def test_an_applicant_never_reaches_the_model_boundary(seeded) -> None:
    settings, factory, stored, _steward = seeded
    app = create_app(settings)
    app.include_router(muse_router)
    with TestClient(app) as client:
        client.post("/api/session/select", json={"actor_id": "persona_applicant"})
        refused = client.post(
            "/api/muse/run",
            json={
                "task": "extraction",
                "mode": "live",
                "application_id": APPLICATION_ID,
                "document_ids": [stored.document_id],
            },
        )
        assert refused.status_code == 403
        assert refused.json()["code"] == "permission_denied"
        listed = client.get("/api/muse/runs")
        assert listed.status_code == 403

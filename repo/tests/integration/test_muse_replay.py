"""A replay is explicit, a cache is exact and a failed run is never rewritten.

The recorded fixtures replay the output of an earlier run.  The replay names
the fixture and the source run it replays, it is labelled as a replay and it
is validated against the current records before anything is written.  A cached
run reuses the output of a run with exactly the same input, prompt, schema
and model, and it never rewrites the run it reuses.
"""
# REQUIRES: AI-03, AI-04
# Live, replay and cached runs stay separate records. A replay is explicit, a cache needs an
# exact input, prompt, schema and model match, and a failed run is never reused or rewritten.

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import ValidationError
from acme_city.documents.service import DocumentService, StoreDocumentCommand
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.muse.client import MuseClient
from acme_city.muse.payloads import fixture_root, read_document_fixture
from acme_city.muse.service import MuseRunCommand, MuseService
from acme_city.persistence.models import model_run, permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

APPLICATION_ID = "app_synth_001"
EXTRACTION_FIXTURE = "extraction-success.json"
MATCH_FIXTURE = "match-proposal-success.json"
MALFORMED_FIXTURE = "malformed-output.json"


class RecordingTransport(httpx.BaseTransport):
    """A transport that records the request and answers with a fixed body."""

    def __init__(self, body: dict) -> None:
        self.requests: list[httpx.Request] = []
        self._body = body

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=self._body)


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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'replay.db'}",
            "ACME_SECRET_KEY": "muse-replay-secret-value",
            "META_API_KEY": "test-provider-key-not-a-real-credential",
            "ACME_MUSE_LIVE_CALLS_ALLOWED": "true",
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


def recorded(name: str) -> dict:
    """Return the recorded replay fixture."""
    return json.loads((fixture_root() / "replay" / name).read_text(encoding="utf-8"))


def test_a_replay_is_explicit_and_names_its_source_run(seeded) -> None:
    settings, factory, stored, steward = seeded
    fixture = recorded(EXTRACTION_FIXTURE)
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
                    replay_fixture=EXTRACTION_FIXTURE,
                ),
                steward,
            )


def test_a_replay_records_the_source_run_it_replays(seeded) -> None:
    settings, factory, stored, steward = seeded
    fixture = recorded(EXTRACTION_FIXTURE)
    with factory() as session:
        service = MuseService(session, settings)
        view = service.run(
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

        assert view.mode == "replay"
        assert view.status == "succeeded"
        assert view.replay_of_run_id == fixture["source_run_id"]
        assert view.fixture_version == fixture["fixture_version"]
        assert view.response_status == "replayed"
        assert view.usage["input_tokens"] == fixture["usage"]["input_tokens"]
        assert view.latency_ms == fixture["latency_ms"]
        assert view.proposals
        assert view.score_is_calibrated is False
        assert view.score_label == "uncalibrated_heuristic"

        observations = session.execute(
            select(permit.ExtractionObservation).where(
                permit.ExtractionObservation.model_run_id == view.run_id
            )
        ).scalars().all()
        assert len(observations) == 8
        assert observations[0].document_id == stored.document_id
        assert observations[0].model_run_id == view.run_id


def test_a_replay_binds_the_recorded_output_to_the_current_document(seeded) -> None:
    settings, factory, stored, steward = seeded
    fixture = recorded(EXTRACTION_FIXTURE)
    with factory() as session:
        service = MuseService(session, settings)
        view = service.run(
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
        bindings = view.validation["bindings"]
        assert bindings["application_id"]["recorded"] == "SYN-APP-001"
        assert bindings["application_id"]["bound"] == APPLICATION_ID
        assert bindings["document_id"]["bound"] == stored.document_id


def test_a_replay_of_another_source_run_is_refused_and_writes_nothing(seeded) -> None:
    settings, factory, stored, steward = seeded
    with factory() as session:
        service = MuseService(session, settings)
        view = service.run(
            MuseRunCommand(
                task="extraction",
                mode="replay",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
                replay_fixture=EXTRACTION_FIXTURE,
                replay_of_run_id="modelrun_some_other_run",
            ),
            steward,
        )
        session.commit()
        assert view.status == "failed"
        assert view.error
        observations = session.execute(select(permit.ExtractionObservation)).scalars().all()
        assert observations == []


def test_a_replay_of_a_malformed_output_is_recorded_as_a_failure(seeded) -> None:
    settings, factory, stored, steward = seeded
    fixture = recorded(MALFORMED_FIXTURE)
    with factory() as session:
        service = MuseService(session, settings)
        view = service.run(
            MuseRunCommand(
                task="extraction",
                mode="replay",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
                replay_fixture=MALFORMED_FIXTURE,
                replay_of_run_id=fixture["source_run_id"],
            ),
            steward,
        )
        session.commit()
        assert view.status == "failed"
        codes = {issue["code"] for issue in view.validation["issues"]}
        assert "unknown_application" in codes
        assert "document_version_mismatch" in codes
        assert "malformed_numeric_value" in codes
        assert "line_out_of_range" in codes
        assert "excerpt_mismatch" in codes
        observations = session.execute(select(permit.ExtractionObservation)).scalars().all()
        assert observations == []


def test_a_match_proposal_replay_is_recorded_as_a_proposal(seeded) -> None:
    settings, factory, _stored, steward = seeded
    fixture = recorded(MATCH_FIXTURE)
    with factory() as session:
        service = MuseService(session, settings)
        view = service.run(
            MuseRunCommand(
                task="match_proposal",
                mode="replay",
                application_id=APPLICATION_ID,
                source_snapshot_id=fixture["output"]["source_snapshot_id"],
                replay_fixture=MATCH_FIXTURE,
                replay_of_run_id=fixture["source_run_id"],
            ),
            steward,
        )
        session.commit()
        assert view.mode == "replay"
        assert view.status == "succeeded"
        assert view.proposals[0]["entity_id"] == "party_false_friend"
        assert view.proposals[0]["disposition"] == "supported"
        assert view.proposals[0]["score_is_calibrated"] is False
        assert view.proposals[0]["score_label"] == "uncalibrated_heuristic"


def test_a_cached_run_reuses_an_exact_match_and_leaves_the_source_run_alone(seeded) -> None:
    settings, factory, stored, steward = seeded
    fixture = recorded(EXTRACTION_FIXTURE)
    transport = RecordingTransport({"id": "resp_never", "status": "failed", "error": "no"})
    with factory() as session:
        service = MuseService(session, settings, client=MuseClient(settings, transport=transport))
        first = service.run(
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
        first_row = session.get(model_run.ModelRun, first.run_id)
        before = (first_row.output, first_row.validation_result, first_row.completed_at)

        second = service.run(
            MuseRunCommand(
                task="extraction",
                mode="cached",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()

        assert second.mode == "cached"
        assert second.status == "succeeded"
        assert second.replay_of_run_id == first.run_id
        assert second.output == first.output

        # The source run is untouched.
        session.expire_all()
        first_row = session.get(model_run.ModelRun, first.run_id)
        assert (first_row.output, first_row.validation_result, first_row.completed_at) == before
        assert first_row.mode == "replay"

        rows = session.execute(select(model_run.ModelRun)).scalars().all()
        assert sorted(row.mode for row in rows) == ["cached", "replay"]


def test_a_failed_live_run_is_never_cached_and_never_rewritten(seeded) -> None:
    settings, factory, stored, steward = seeded
    transport = RecordingTransport({"id": "resp_failed", "status": "failed", "error": "no"})
    with factory() as session:
        service = MuseService(session, settings, client=MuseClient(settings, transport=transport))
        failed = service.run(
            MuseRunCommand(
                task="extraction",
                mode="live",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()
        assert failed.status == "failed"
        assert failed.error

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
        assert cached.status == "failed"
        assert "no cached run" in (cached.error or "")

        row = session.get(model_run.ModelRun, failed.run_id)
        assert row.error
        assert row.output is None
        assert row.completed_at is not None

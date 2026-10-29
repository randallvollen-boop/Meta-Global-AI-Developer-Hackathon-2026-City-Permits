"""The provider boundary is exactly one bounded request.

The request goes to the Responses endpoint, carries a bearer credential that
is injected at dispatch, asks for a strict JSON schema, bounds its output,
enables no tool and no web search, and is sent once: there is no retry.  The
credential never reaches a recorded run.
"""
# REQUIRES: AI-01, AI-02, AI-03, AI-04
# The provider boundary posts one bounded request with a strict JSON schema, a bounded output
# budget, no tools, no web search and no retry. The credential is injected at dispatch and
# never recorded.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.documents.service import DocumentService, StoreDocumentCommand
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.muse.client import (
    MAX_OUTPUT_CEILING,
    MAX_OUTPUT_TOKENS,
    META_RESPONSES_URL,
    MuseClient,
    MuseRequestError,
)
from acme_city.muse.payloads import read_document_fixture
from acme_city.muse.schemas import DEFAULT_MUSE_MODEL, task_schema
from acme_city.muse.service import MuseRunCommand, MuseService
from acme_city.persistence.models import model_run
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

APPLICATION_ID = "app_synth_001"
CREDENTIAL = "test-provider-key-not-a-real-credential"


class RecordingTransport(httpx.BaseTransport):
    """A transport that records the request and answers with a fixed body."""

    def __init__(self, body: dict[str, Any], status_code: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self._body = body
        self._status_code = status_code

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status_code, json=self._body)


def provider_body(text: str = "{}") -> dict[str, Any]:
    """Return a provider response body that carries the given text."""
    return {
        "id": "resp_contract_1",
        "model": DEFAULT_MUSE_MODEL,
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]}
        ],
        "usage": {
            "input_tokens": 640,
            "output_tokens": 180,
            "total_tokens": 820,
            "input_tokens_details": {"cached_tokens": 128},
            "output_tokens_details": {"reasoning_tokens": 12},
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
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'contract.db'}",
            "ACME_SECRET_KEY": "muse-contract-secret-value",
            "META_API_KEY": CREDENTIAL,
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


def test_the_request_goes_to_the_responses_endpoint_with_a_bearer_credential(seeded) -> None:
    settings, factory, stored, steward = seeded
    transport = RecordingTransport(provider_body())
    with factory() as session:
        service = MuseService(
            session, settings, client=MuseClient(settings, transport=transport)
        )
        service.run(
            MuseRunCommand(
                task="extraction",
                mode="live",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()

    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert str(request.url) == META_RESPONSES_URL
    assert request.method == "POST"
    assert request.headers["authorization"] == f"Bearer {CREDENTIAL}"
    assert request.headers["content-type"] == "application/json"


def test_the_request_asks_for_a_strict_json_schema(seeded) -> None:
    settings, factory, stored, steward = seeded
    transport = RecordingTransport(provider_body())
    with factory() as session:
        service = MuseService(
            session, settings, client=MuseClient(settings, transport=transport)
        )
        service.run(
            MuseRunCommand(
                task="extraction",
                mode="live",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()

    payload = json.loads(transport.requests[0].content.decode("utf-8"))
    assert payload["model"] == DEFAULT_MUSE_MODEL
    assert settings.model_is_allowed(payload["model"])
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert payload["text"]["format"]["name"]
    assert payload["text"]["format"]["schema"] == task_schema("extraction")
    assert payload["max_output_tokens"] <= MAX_OUTPUT_TOKENS


def test_the_request_enables_no_tool_and_no_web_search(seeded) -> None:
    settings, factory, stored, steward = seeded
    transport = RecordingTransport(provider_body())
    with factory() as session:
        service = MuseService(
            session, settings, client=MuseClient(settings, transport=transport)
        )
        service.run(
            MuseRunCommand(
                task="extraction",
                mode="live",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()

    payload = json.loads(transport.requests[0].content.decode("utf-8"))
    for key in ("tools", "tool_choice", "response_format", "web_search_options", "functions"):
        assert key not in payload


def test_a_run_sends_exactly_one_request(seeded) -> None:
    settings, factory, stored, steward = seeded
    transport = RecordingTransport(provider_body())
    with factory() as session:
        service = MuseService(
            session, settings, client=MuseClient(settings, transport=transport)
        )
        service.run(
            MuseRunCommand(
                task="extraction",
                mode="live",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()
    assert len(transport.requests) == 1


def test_the_credential_never_reaches_a_recorded_run(seeded) -> None:
    settings, factory, stored, steward = seeded
    transport = RecordingTransport(provider_body())
    with factory() as session:
        service = MuseService(
            session, settings, client=MuseClient(settings, transport=transport)
        )
        service.run(
            MuseRunCommand(
                task="extraction",
                mode="live",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()
        row = session.execute(select(model_run.ModelRun)).scalars().one()
        recorded = json.dumps(
            {
                "output": row.output,
                "validation": row.validation_result,
                "usage": row.usage,
                "error": row.error,
                "input_refs": row.input_refs,
            },
            default=str,
        )
    assert CREDENTIAL not in recorded
    # The request summary carries the body hash, never the body.
    summary = row.input_refs["request"]
    assert summary["body_sha256"]
    assert "headers" not in summary
    assert "authorization" not in json.dumps(summary).lower()


def test_the_provider_response_is_recorded(seeded) -> None:
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

    assert view.response_id == "resp_contract_1"
    assert view.response_status == "completed"
    assert view.usage["input_tokens"] == 640
    assert view.usage["cached_input_tokens"] == 128
    assert view.usage["output_tokens"] == 180
    assert view.usage["reasoning_tokens"] == 12
    assert view.usage["total_tokens"] == 820
    assert view.latency_ms is not None
    assert row.provider_response_id == "resp_contract_1"
    assert row.provider == "meta"
    assert row.model == DEFAULT_MUSE_MODEL


def test_a_model_outside_the_allowlist_is_refused_before_the_dispatch(seeded) -> None:
    settings, factory, _stored, _steward = seeded
    transport = RecordingTransport(provider_body())
    client = MuseClient(settings, transport=transport)
    payload = {
        "model": "muse-spark-1.3-contributor",
        "input": "x",
        "text": {"format": {"type": "json_schema", "name": "n", "schema": {}, "strict": True}},
        "max_output_tokens": 100,
    }
    with pytest.raises(MuseRequestError):
        client.create_response(payload)
    assert transport.requests == []


def test_a_payload_with_a_tool_is_refused_before_the_dispatch(seeded) -> None:
    settings, factory, _stored, _steward = seeded
    transport = RecordingTransport(provider_body())
    client = MuseClient(settings, transport=transport)
    payload = {
        "model": DEFAULT_MUSE_MODEL,
        "input": "x",
        "tools": [{"type": "web_search"}],
        "text": {"format": {"type": "json_schema", "name": "n", "schema": {}, "strict": True}},
        "max_output_tokens": 100,
    }
    with pytest.raises(MuseRequestError):
        client.create_response(payload)
    assert transport.requests == []


def test_an_unbounded_output_budget_is_refused_before_the_dispatch(seeded) -> None:
    settings, factory, _stored, _steward = seeded
    transport = RecordingTransport(provider_body())
    client = MuseClient(settings, transport=transport)
    payload = {
        "model": DEFAULT_MUSE_MODEL,
        "input": "x",
        "text": {"format": {"type": "json_schema", "name": "n", "schema": {}, "strict": True}},
        # Changed deliberately (the policy tasks reserve more output): the
        # refused budget is one above the hard ceiling.
        "max_output_tokens": MAX_OUTPUT_CEILING + 1,
    }
    with pytest.raises(MuseRequestError):
        client.create_response(payload)
    assert transport.requests == []


def test_a_contributor_model_is_never_allowed() -> None:
    settings = Settings.load(
        environ={"ACME_SECRET_KEY": "contributor-check-secret-value"},
        key_file=Path("/nonexistent/ai-keys.env"),
    )
    assert not settings.model_is_allowed("muse-spark-1.3-contributor")
    assert not settings.model_is_allowed("muse-spark-1.3-Contributor")


def test_a_provider_error_is_recorded_and_stops_the_following_live_calls(seeded) -> None:
    settings, factory, stored, steward = seeded
    transport = RecordingTransport(
        {"id": "resp_error", "status": "failed", "error": {"message": "the provider refused"}},
        status_code=200,
    )
    with factory() as session:
        service = MuseService(
            session, settings, client=MuseClient(settings, transport=transport)
        )
        first = service.run(
            MuseRunCommand(
                task="extraction",
                mode="live",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()
        assert first.status == "failed"
        assert "the provider refused" in (first.error or "")

        second = service.run(
            MuseRunCommand(
                task="extraction",
                mode="live",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()
        assert second.status == "failed"
        assert "provider error" in (second.error or "")

    # The second run never reached the provider.
    assert len(transport.requests) == 1


def test_the_live_call_budget_bounds_the_number_of_requests(seeded) -> None:
    settings, factory, stored, steward = seeded
    transport = RecordingTransport(provider_body())
    with factory() as session:
        service = MuseService(
            session, settings, client=MuseClient(settings, transport=transport)
        )
        for _ in range(settings.muse_live_call_cap):
            service.run(
                MuseRunCommand(
                    task="extraction",
                    mode="live",
                    application_id=APPLICATION_ID,
                    document_ids=[stored.document_id],
                ),
                steward,
            )
            session.commit()
        blocked = service.run(
            MuseRunCommand(
                task="extraction",
                mode="live",
                application_id=APPLICATION_ID,
                document_ids=[stored.document_id],
            ),
            steward,
        )
        session.commit()
    assert blocked.status == "failed"
    assert "budget" in (blocked.error or "")
    assert len(transport.requests) == settings.muse_live_call_cap

"""Muse rewrites the reason of one recommendation and nothing else.

The strict schema carries the rewritten text alone, so a model cannot return
an outcome or a certainty.  The call carries the fields of the one record the
task is about.  Every attempt is recorded, and a refused attempt leaves the
deterministic reason of the assistant standing.

The provider is a fake transport: no test here makes an outside call.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from acme_city.agents import steward_explain
from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.muse.budget import MuseBudget
from acme_city.muse.client import MuseClient, ProviderResponse
from acme_city.muse.schemas import (
    STEWARD_EXPLANATION_SCHEMA_VERSION,
    STEWARD_EXPLANATION_TASK,
    task_schema,
)
from acme_city.muse.service import LIVE_DISPATCH_LOCK
from acme_city.persistence.models import model_run
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.registry import steward_assist
from acme_city.registry.schemas import MatchProposalCommand
from acme_city.registry.service import RegistryService

STEWARD = ActorContext(actor_id="persona_data_steward", role_ids=frozenset({"domain_steward"}))

CREDENTIAL = "test-muse-explanation-key-not-a-real-credential"


class FakeTransport(httpx.BaseTransport):
    """A transport that records the request and answers with a fixed body."""

    def __init__(self, body: str, *, status: int = 200) -> None:
        self.body = body
        self.status = status
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            self.status,
            json={"id": "resp_explain", "status": "completed", "output_text": self.body},
        )


def build_settings(tmp_path: Path, **extra: str) -> Settings:
    environ = {
        "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'steward-explain.db'}",
        "ACME_SECRET_KEY": "steward-explain-test-secret",
        "META_API_KEY": CREDENTIAL,
        **extra,
    }
    settings = Settings.load(environ=environ, key_file=tmp_path / "missing.env")
    initialize_database(settings)
    return settings


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = build_settings(tmp_path)
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
    finally:
        factory.dispose()
    return settings


def a_recommendation(settings: Settings) -> StewardRecommendation:
    """Return the recommendation of one record match, recorded."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            view = RegistryService(session).propose(
                MatchProposalCommand(
                    source_system_id="erp_finance",
                    dataset_key="business_licensing_register",
                    source_record_id="ERP-BL-00412",
                ),
                STEWARD,
            )
            proposal = steward_assist.recommend(
                session, steward_assist.Task("link", view.proposal_id), settings=settings
            )
            return steward_assist.store_recommendation(session, proposal)
    finally:
        factory.dispose()


def a_run(settings: Settings) -> model_run.ModelRun:
    """Return the last recorded run of the explanation path."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return session.execute(
                select(model_run.ModelRun)
                .where(
                    model_run.ModelRun.input_refs["task"].as_string()
                    == STEWARD_EXPLANATION_TASK
                )
                .order_by(model_run.ModelRun.created_at.desc())
            ).scalars().first()
    finally:
        factory.dispose()


def explanation_body(text: str) -> str:
    """Return the body a provider answers with."""
    return json.dumps({"explanation": text})


# ------------------------------------------------------------------ the schema


def test_the_schema_carries_the_text_and_nothing_else() -> None:
    """The output model refuses a field the schema does not declare."""
    from acme_city.muse.validation import parse_task_output

    model, issue = parse_task_output(
        STEWARD_EXPLANATION_TASK, {"explanation": "The names agree."}
    )
    assert issue is None
    assert model is not None
    assert model.explanation == "The names agree."

    model, issue = parse_task_output(
        STEWARD_EXPLANATION_TASK,
        {"explanation": "The names agree.", "outcome": "confirm"},
    )
    assert model is None
    assert issue is not None
    assert issue.code == "schema_invalid"


def test_the_schema_of_the_task_is_strict() -> None:
    """The provider is asked for a strict schema of the text alone."""
    schema = task_schema(STEWARD_EXPLANATION_TASK)
    assert schema["additionalProperties"] is False
    assert sorted(schema["properties"]) == ["explanation"]
    assert schema["required"] == ["explanation"]


# ------------------------------------------------------------------- the data


def test_the_call_carries_the_fields_of_the_one_record(seeded: Settings) -> None:
    """The payload holds the record of the task and nothing else."""
    recommendation = a_recommendation(seeded)
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            fields = steward_explain.record_fields(session, recommendation)
    finally:
        factory.dispose()
    assert fields
    assert {item["field"] for item in fields} >= {"holder_name"}
    payload = steward_explain.build_explanation_payload(
        fields=fields,
        reason=recommendation.reason,
        outcome=recommendation.outcome,
        confidence=recommendation.confidence,
        model=seeded.muse_model_allowlist[0],
    )
    text = payload["input"]
    assert "holder_name" in text
    assert recommendation.reason in text
    # The payload names the model, the schema and the strict format.
    assert payload["text"]["format"]["strict"] is True
    assert payload["text"]["format"]["name"] == "acme_city_steward_explanation"
    assert payload["model"] == seeded.muse_model_allowlist[0]


# ---------------------------------------------------------------- the dispatch


def test_a_call_rewrites_the_reason_and_records_the_run(seeded: Settings) -> None:
    """The words come from the model and the run is recorded."""
    recommendation = a_recommendation(seeded)
    transport = FakeTransport(explanation_body("The license holder names the same business."))
    client = MuseClient(seeded, transport=transport)
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, recommendation.id)
            assert row is not None
            result = steward_explain.explain(
                session, seeded, row, actor_id="persona_data_steward", client=client
            )
    finally:
        factory.dispose()

    assert result.explained is True
    assert result.error == ""
    assert result.text == "The license holder names the same business."
    assert len(transport.requests) == 1

    run = a_run(seeded)
    assert run is not None
    assert run.mode == "live"
    assert run.error is None
    assert run.prompt_version and run.schema_version
    assert run.input_refs["recommendation_id"] == recommendation.id
    assert run.input_refs["task"] == STEWARD_EXPLANATION_TASK
    # The run records the names of the fields, never their values.
    assert "holder_name" in run.input_refs["record_fields"]
    assert "record_hash" in run.input_refs


def test_the_outcome_and_the_certainty_never_change(seeded: Settings) -> None:
    """Muse rewrites the words; the decision of the City stands."""
    recommendation = a_recommendation(seeded)
    transport = FakeTransport(explanation_body("The names agree."))
    client = MuseClient(seeded, transport=transport)
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, recommendation.id)
            assert row is not None
            steward_explain.explain(
                session, seeded, row, actor_id="persona_data_steward", client=client
            )
            stored = session.get(StewardRecommendation, recommendation.id)
            assert stored is not None
            assert stored.outcome == recommendation.outcome
            assert stored.confidence == recommendation.confidence
            assert stored.reason == recommendation.reason
    finally:
        factory.dispose()


def test_an_output_that_carries_an_outcome_is_refused(seeded: Settings) -> None:
    """A model that returns a decision has its output refused."""
    recommendation = a_recommendation(seeded)
    body = json.dumps({"explanation": "The names agree.", "outcome": "confirm"})
    transport = FakeTransport(body)
    client = MuseClient(seeded, transport=transport)
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, recommendation.id)
            assert row is not None
            result = steward_explain.explain(
                session, seeded, row, actor_id="persona_data_steward", client=client
            )
    finally:
        factory.dispose()

    assert result.explained is False
    assert result.text == recommendation.reason
    assert "schema" in result.error
    run = a_run(seeded)
    assert run is not None
    assert run.error is not None


def test_a_refused_call_is_recorded_and_the_reason_stands(seeded: Settings) -> None:
    """A provider error is recorded; the deterministic reason stands."""
    recommendation = a_recommendation(seeded)
    transport = FakeTransport("{}", status=500)
    client = MuseClient(seeded, transport=transport)
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, recommendation.id)
            assert row is not None
            result = steward_explain.explain(
                session, seeded, row, actor_id="persona_data_steward", client=client
            )
    finally:
        factory.dispose()

    assert result.explained is False
    assert result.text == recommendation.reason
    assert result.error
    run = a_run(seeded)
    assert run is not None
    assert run.error is not None


def test_a_disabled_provider_is_recorded_and_the_reason_stands(tmp_path: Path) -> None:
    """A deployment without a live provider records the refused attempt."""
    settings = build_settings(tmp_path, ACME_MUSE_PROVIDER_ENABLED="false")
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
    finally:
        factory.dispose()

    recommendation = a_recommendation(settings)
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, recommendation.id)
            assert row is not None
            result = steward_explain.explain(
                session, settings, row, actor_id="persona_data_steward"
            )
    finally:
        factory.dispose()

    assert result.explained is False
    assert result.text == recommendation.reason
    assert "disabled" in result.error
    run = a_run(settings)
    assert run is not None
    assert run.error is not None


def test_the_live_budget_refuses_the_call_and_records_it(seeded: Settings) -> None:
    """The cap of the build run stops the call before the provider."""
    recommendation = a_recommendation(seeded)
    transport = FakeTransport(explanation_body("The names agree."))
    client = MuseClient(seeded, transport=transport)
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            # A live run that recorded a provider error stops the next call.
            session.add(
                model_run.ModelRun(
                    id="modelrun_previous_error",
                    correlation_id="corr_previous_error",
                    mode="live",
                    provider="meta",
                    model=seeded.muse_model_allowlist[0],
                    prompt_version="acme-extraction-prompt-v1",
                    schema_version="acme-extraction-schema-v1",
                    input_refs={},
                    output=None,
                    validation_result={"provider": {"response_status": "failed"}},
                    usage={},
                    latency_ms=1,
                    error="the provider refused the request",
                    started_at=steward_explain.utc_now(),
                    completed_at=steward_explain.utc_now(),
                    actor_id="persona_data_steward",
                )
            )
            session.flush()
            row = session.get(StewardRecommendation, recommendation.id)
            assert row is not None
            result = steward_explain.explain(
                session, seeded, row, actor_id="persona_data_steward", client=client
            )
    finally:
        factory.dispose()

    assert result.explained is False
    assert transport.requests == []
    assert "previous live run" in result.error
    run = a_run(seeded)
    assert run is not None
    assert run.error is not None


def test_the_daily_cap_refuses_the_call_before_the_transport(tmp_path: Path) -> None:
    """The daily allowance of the provider is shared with every other path."""
    settings = build_settings(tmp_path, ACME_MUSE_DAILY_CALL_CAP="0")
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
    finally:
        factory.dispose()

    recommendation = a_recommendation(settings)
    transport = FakeTransport(explanation_body("The names agree."))
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            # The client of the application reserves one call of the daily
            # allowance before it dispatches.
            client = MuseClient(
                settings,
                transport=transport,
                budget=MuseBudget(session, settings=settings),
            )
            row = session.get(StewardRecommendation, recommendation.id)
            assert row is not None
            result = steward_explain.explain(
                session, settings, row, actor_id="persona_data_steward", client=client
            )
    finally:
        factory.dispose()

    assert result.explained is False
    assert transport.requests == []
    assert "allowance" in result.error
    run = a_run(settings)
    assert run is not None
    assert run.error is not None


def test_the_gate_says_why_a_call_may_not_be_sent(seeded: Settings) -> None:
    """The gates name the reason a live call may not be sent."""
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            assert steward_explain.gate_error(session, seeded) is None
            without = seeded.model_copy(update={"meta_api_key": None})
            assert "credential" in (steward_explain.gate_error(session, without) or "")
            disabled = seeded.model_copy(update={"muse_provider_enabled": False})
            assert "disabled" in (steward_explain.gate_error(session, disabled) or "")
    finally:
        factory.dispose()


def test_the_schema_version_is_recorded(seeded: Settings) -> None:
    """The run names the schema version it was made with."""
    assert STEWARD_EXPLANATION_SCHEMA_VERSION == "acme-steward-explanation-schema-v1"
    run_settings: dict[str, Any] = {"muse_model_allowlist": seeded.muse_model_allowlist}
    assert run_settings["muse_model_allowlist"]


# --------------------------------------------------------------- the refusal


class FixedClient:
    """A client that answers with one prepared response."""

    def __init__(self, response: ProviderResponse) -> None:
        self.response = response
        self.calls = 0

    def create_response(self, payload: dict[str, Any]) -> ProviderResponse:
        self.calls += 1
        return self.response


def test_a_refused_answer_is_not_a_rewrite(seeded: Settings) -> None:
    """A provider that refuses to answer leaves the reason of the assistant standing."""
    recommendation = a_recommendation(seeded)
    client = FixedClient(
        ProviderResponse(
            status="completed",
            refusal="I cannot explain this.",
            output_text=explanation_body("Ask the source for verification."),
        )
    )
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, recommendation.id)
            assert row is not None
            result = steward_explain.explain(
                session, seeded, row, actor_id="persona_data_steward", client=client
            )
    finally:
        factory.dispose()

    assert result.explained is False
    assert result.text == recommendation.reason
    assert result.error == steward_explain.REFUSAL_MESSAGE
    # The answer of the provider was never taken for the reason.
    assert client.calls == 1
    run = a_run(seeded)
    assert run is not None
    assert run.error == steward_explain.REFUSAL_MESSAGE
    assert run.output is None
    validation = dict(run.validation_result or {})
    assert validation["state"] == "failed"
    # The words of the refusal stay in the validation of the run.
    assert validation["details"]["refusal"] == "I cannot explain this."


def test_an_unfinished_answer_is_not_a_rewrite(seeded: Settings) -> None:
    """A provider that did not finish leaves the reason of the assistant standing."""
    recommendation = a_recommendation(seeded)
    client = FixedClient(
        ProviderResponse(
            status="incomplete",
            incomplete_details={"reason": "max_output_tokens"},
            output_text=explanation_body("Ask the source for verification."),
        )
    )
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, recommendation.id)
            assert row is not None
            result = steward_explain.explain(
                session, seeded, row, actor_id="persona_data_steward", client=client
            )
    finally:
        factory.dispose()

    assert result.explained is False
    assert result.text == recommendation.reason
    assert result.error == steward_explain.INCOMPLETE_MESSAGE
    assert client.calls == 1
    run = a_run(seeded)
    assert run is not None
    assert run.error == steward_explain.INCOMPLETE_MESSAGE
    assert run.output is None
    validation = dict(run.validation_result or {})
    assert validation["state"] == "failed"
    # The reason the provider gave stays in the validation of the run.
    assert validation["details"]["incomplete_details"] == {"reason": "max_output_tokens"}


# ------------------------------------------------------------- the live cap


def test_the_explanation_waits_for_the_live_dispatch_lock(seeded: Settings) -> None:
    """The dispatch of an explanation takes the lock every live path takes."""
    recommendation = a_recommendation(seeded)
    transport = FakeTransport(explanation_body("The names agree."))
    client = MuseClient(seeded, transport=transport)
    factory = SessionFactory(seeded.database_url)
    started = threading.Event()
    finished = threading.Event()

    def worker() -> None:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, recommendation.id)
            assert row is not None
            started.set()
            steward_explain.explain(
                session, seeded, row, actor_id="persona_data_steward", client=client
            )
        finished.set()

    with LIVE_DISPATCH_LOCK:
        thread = threading.Thread(target=worker)
        thread.start()
        assert started.wait(timeout=5)
        # The lock of the other live paths is held, so the provider is not reached.
        time.sleep(0.2)
        assert transport.requests == []
    thread.join(timeout=10)
    assert finished.is_set()
    assert len(transport.requests) == 1


def test_the_explanation_reads_the_cap_again_under_the_lock(
    seeded: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A call whose slot of the build run was spent while it waited is refused."""
    settings = seeded.model_copy(update={"muse_live_call_cap": 1})
    recommendation = a_recommendation(seeded)
    transport = FakeTransport(explanation_body("The names agree."))
    client = MuseClient(settings, transport=transport)
    original_gate = steward_explain.gate_error

    def gated(session: Any, gate_settings: Any) -> Any:
        result = original_gate(session, gate_settings)
        # Another path of the City spends the last call of the build run.
        moment = steward_explain.utc_now()
        session.add(
            model_run.ModelRun(
                id="modelrun_other_path",
                correlation_id="corr_other_path",
                mode="live",
                provider="meta",
                model=settings.muse_model_allowlist[0],
                prompt_version="acme-extraction-prompt-v1",
                schema_version="acme-extraction-schema-v1",
                input_refs={},
                output=None,
                validation_result={"state": "passed", "status": "succeeded"},
                usage={},
                latency_ms=1,
                error=None,
                started_at=moment,
                completed_at=moment,
                actor_id="persona_data_steward",
            )
        )
        session.flush()
        return result

    monkeypatch.setattr(steward_explain, "gate_error", gated)
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(StewardRecommendation, recommendation.id)
            assert row is not None
            result = steward_explain.explain(
                session, settings, row, actor_id="persona_data_steward", client=client
            )
    finally:
        factory.dispose()

    assert result.explained is False
    assert result.error is not None
    assert "exhausted" in result.error
    # The provider was never reached.
    assert transport.requests == []
    run = a_run(seeded)
    assert run is not None
    assert run.error is not None

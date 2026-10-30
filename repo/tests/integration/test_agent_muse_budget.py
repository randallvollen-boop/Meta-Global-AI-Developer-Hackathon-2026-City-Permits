"""The daily allowance of provider calls.

The allowance is one number for the whole day.  A call is reserved before it
is dispatched, so a day without room sends nothing, a call that fails still
counts and a restart reads the same counter instead of a fresh one.

The hosted dispatch lock sits above the allowance: a hosted deployment
refuses every live call, even when the day still has room.
"""
# REQUIRES: AI-01, AI-03
# The provider boundary reserves one call of the daily allowance before it dispatches.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from acme_city.core.clock import utc_now
from acme_city.core.config import Settings
from acme_city.applicant_help import assist as applicant_assist
from acme_city.applicant_help.sources import SourceBundle
from acme_city.muse.budget import MuseBudget, MuseBudgetExceeded
from acme_city.muse.client import MuseClient, MuseLiveCallBlocked
from acme_city.muse.image_client import MuseImageClient
from acme_city.muse.service import live_budget_error
from acme_city.persistence.models import agent_ops, model_run
from acme_city.policy import muse as policy_muse
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

CREDENTIAL = "test-muse-budget-key-not-a-real-credential"


class RecordingTransport(httpx.BaseTransport):
    """A transport that records the request and answers with a fixed body."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(200, json={"id": "resp_budget", "status": "completed", "output_text": "{}"})


def build_settings(tmp_path: Path, **extra: str) -> Settings:
    environ = {
        "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'muse-budget.db'}",
        "ACME_SECRET_KEY": "muse-budget-secret-value",
        "META_API_KEY": CREDENTIAL,
        "ACME_MUSE_PROVIDER_ENABLED": "true",
        **extra,
    }
    settings = Settings.load(environ=environ, key_file=tmp_path / "missing.env")
    initialize_database(settings)
    return settings


def payload_for(settings: Settings) -> dict:
    return {
        "model": settings.muse_model_allowlist[0],
        "text": {
            "format": {
                "type": "json_schema",
                "strict": True,
                "name": "budget_probe",
                "schema": {"type": "object", "properties": {}},
            }
        },
        "max_output_tokens": 100,
    }


def test_an_exhausted_budget_refuses_the_call_before_the_transport(tmp_path: Path) -> None:
    """A day without room sends nothing."""
    settings = build_settings(tmp_path, ACME_MUSE_DAILY_CALL_CAP="1")
    factory = SessionFactory(settings.database_url)
    stub = RecordingTransport()
    try:
        with transaction(factory) as session:
            budget = MuseBudget(session, settings=settings)
            budget.reserve()
            assert budget.used() == 1
            client = MuseClient(settings, transport=stub, budget=budget)
            with pytest.raises(MuseBudgetExceeded):
                client.create_response(payload_for(settings))
        # The provider was never reached.
        assert stub.calls == []
    finally:
        factory.dispose()


def test_the_hosted_lock_wins_over_the_budget(tmp_path: Path) -> None:
    """A hosted deployment refuses every live call, even with room left."""
    settings = build_settings(
        tmp_path, ACME_PUBLIC_DEMO="true", ACME_MUSE_DAILY_CALL_CAP="10"
    )
    factory = SessionFactory(settings.database_url)
    stub = RecordingTransport()
    try:
        with transaction(factory) as session:
            budget = MuseBudget(session, settings=settings)
            client = MuseClient(settings, transport=stub, budget=budget)
            with pytest.raises(MuseLiveCallBlocked):
                client.create_response(payload_for(settings))
            # The lock refused the call, so the day still has every call.
            assert budget.used() == 0
        assert stub.calls == []
    finally:
        factory.dispose()


def test_a_call_with_room_is_sent_and_costs_one_call(tmp_path: Path) -> None:
    settings = build_settings(tmp_path, ACME_MUSE_DAILY_CALL_CAP="2")
    factory = SessionFactory(settings.database_url)
    stub = RecordingTransport()
    try:
        with transaction(factory) as session:
            budget = MuseBudget(session, settings=settings)
            client = MuseClient(settings, transport=stub, budget=budget)
            response = client.create_response(payload_for(settings))
            assert response.error is None
            assert budget.used() == 1
        assert len(stub.calls) == 1
    finally:
        factory.dispose()


def test_a_failed_call_still_counts_against_the_day(tmp_path: Path) -> None:
    """The call was reserved, so the day spent it even when it failed."""

    class FailingTransport(httpx.BaseTransport):
        def __init__(self) -> None:
            self.calls: list[httpx.Request] = []

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            raise httpx.ConnectError("the provider is not reachable")

    settings = build_settings(tmp_path, ACME_MUSE_DAILY_CALL_CAP="1")
    factory = SessionFactory(settings.database_url)
    stub = FailingTransport()
    try:
        with transaction(factory) as session:
            budget = MuseBudget(session, settings=settings)
            client = MuseClient(settings, transport=stub, budget=budget)
            response = client.create_response(payload_for(settings))
            assert response.error
            assert budget.used() == 1
            # The day has no room left, so the next call is refused.
            with pytest.raises(MuseBudgetExceeded):
                client.create_response(payload_for(settings))
        assert len(stub.calls) == 1
    finally:
        factory.dispose()


def test_a_restart_does_not_reset_the_allowance(tmp_path: Path) -> None:
    """The counter of the day is in the database, so it survives a restart."""
    settings = build_settings(tmp_path, ACME_MUSE_DAILY_CALL_CAP="1")
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            MuseBudget(session, settings=settings).reserve()
        # A new factory is a new process that reads the same database.
        restarted = SessionFactory(settings.database_url)
        try:
            with restarted() as session:
                budget = MuseBudget(session, settings=settings)
                assert budget.used() == 1
        finally:
            restarted.dispose()
    finally:
        factory.dispose()


def test_the_day_rolls_over_at_midnight_utc(tmp_path: Path) -> None:
    """The allowance of one day never reaches the next day."""
    settings = build_settings(tmp_path, ACME_MUSE_DAILY_CALL_CAP="1")
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            today = MuseBudget(session, settings=settings)
            today.reserve()
            assert today.used() == 1
            tomorrow = MuseBudget(
                session, settings=settings, now=utc_now() + timedelta(days=1)
            )
            assert tomorrow.day() != today.day()
            assert tomorrow.used() == 0
            assert tomorrow.cap == 1
    finally:
        factory.dispose()


def test_a_cap_of_zero_sends_no_call_at_all(tmp_path: Path) -> None:
    """A deployment without an allowance never reaches the provider."""
    settings = build_settings(tmp_path, ACME_MUSE_DAILY_CALL_CAP="0")
    factory = SessionFactory(settings.database_url)
    stub = RecordingTransport()
    try:
        with transaction(factory) as session:
            budget = MuseBudget(session, settings=settings)
            client = MuseClient(settings, transport=stub, budget=budget)
            with pytest.raises(MuseBudgetExceeded):
                client.create_response(payload_for(settings))
            image = MuseImageClient(settings, transport=stub, budget=budget)
            result = image.generate("a wooden deck")
            assert result.ok is False
            assert "allowance" in (result.error or "")
        assert stub.calls == []
    finally:
        factory.dispose()


@pytest.mark.parametrize("path", ("applicant_help", "policy"))
def test_each_text_provider_path_obeys_a_zero_daily_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """The application entry points build clients with the shared allowance."""
    settings = build_settings(
        tmp_path,
        ACME_MUSE_DAILY_CALL_CAP="0",
        ACME_APPLICANT_ASSIST_LIVE_ENABLED="true",
        ACME_POLICY_ASSIST_LIVE_ENABLED="true",
    )
    factory = SessionFactory(settings.database_url)
    stub = RecordingTransport()

    def client_with_recording_transport(client_settings, **kwargs):
        return MuseClient(client_settings, transport=stub, **kwargs)

    module = applicant_assist if path == "applicant_help" else policy_muse
    monkeypatch.setattr(module, "MuseClient", client_with_recording_transport)
    try:
        with transaction(factory) as session:
            if path == "applicant_help":
                result = applicant_assist.dispatch_assist(
                    session,
                    settings,
                    bundle=SourceBundle(
                        passages=(),
                        bundle_hash="budget-probe",
                        content_hash="budget-probe",
                        basis_at=utc_now(),
                    ),
                    question="What does this permit need?",
                    context={},
                )
            else:
                result = policy_muse.dispatch(
                    session,
                    settings,
                    task="policy_propose",
                    basis={},
                    payload=payload_for(settings),
                )
            assert result.error is not None
            assert "allowance" in result.error
        assert stub.calls == []
    finally:
        factory.dispose()


def test_the_image_client_uses_the_same_allowance(tmp_path: Path) -> None:
    """The image path spends the same day as the responses path."""
    settings = build_settings(tmp_path, ACME_MUSE_DAILY_CALL_CAP="1")
    factory = SessionFactory(settings.database_url)
    stub = RecordingTransport()
    try:
        with transaction(factory) as session:
            budget = MuseBudget(session, settings=settings)
            client = MuseClient(settings, transport=stub, budget=budget)
            client.create_response(payload_for(settings))
            image = MuseImageClient(settings, transport=stub, budget=budget)
            result = image.generate("a wooden deck")
            assert result.ok is False
            assert "allowance" in (result.error or "")
        assert len(stub.calls) == 1
    finally:
        factory.dispose()


def test_the_counter_of_the_day_is_one_row(tmp_path: Path) -> None:
    """The day is the identity of the allowance."""
    settings = build_settings(tmp_path, ACME_MUSE_DAILY_CALL_CAP="5")
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            budget = MuseBudget(session, settings=settings)
            budget.reserve()
            budget.reserve()
            rows = session.query(agent_ops.MuseDailyBudget).all()
            assert len(rows) == 1
            assert rows[0].day == budget.day()
            assert rows[0].calls_used == 2
    finally:
        factory.dispose()


def test_a_daily_cap_refusal_does_not_stop_the_next_day(tmp_path: Path) -> None:
    """A refusal before dispatch is not a provider error on the next day."""
    settings = build_settings(
        tmp_path,
        ACME_MUSE_DAILY_CALL_CAP="1",
        ACME_MUSE_LIVE_CALL_CAP="10",
    )
    factory = SessionFactory(settings.database_url)
    yesterday = datetime(2026, 10, 29, 23, 59, tzinfo=UTC)
    tomorrow = yesterday + timedelta(minutes=2)
    try:
        with transaction(factory) as session:
            budget = MuseBudget(session, settings=settings, now=yesterday)
            budget.reserve()
            with pytest.raises(MuseBudgetExceeded):
                budget.reserve()
            # This is the row the service records for the refusal.  It has no
            # provider response because no request left the process.
            session.add(
                model_run.ModelRun(
                    id="modelrun_daily_cap_refusal",
                    correlation_id="corr_daily_cap_refusal",
                    mode="live",
                    provider="meta",
                    model="muse-spark-test",
                    prompt_version="test",
                    schema_version="test",
                    started_at=yesterday,
                    completed_at=yesterday,
                    validation_result={"status": "failed", "provider": {}},
                    error="the daily allowance of 1 provider call(s) is used up",
                )
            )
            session.flush()
            assert live_budget_error(session, settings) is None
            renewed = MuseBudget(session, settings=settings, now=tomorrow)
            renewed.reserve()
            assert renewed.used() == 1
    finally:
        factory.dispose()

"""The Muse path of the what-if agent (policy 3): briefing, explanation and proposal.

Covers the demo briefing from the labelled replay fixture, the deliberately
failing fixture and the fallback, the grants on every read and write, CSRF and
the mandatory version, the live switch (off by default, a provider client that
raises, the shared cap), the proposal flow (nothing saved until the
Administrator saves), that no business row is written, that Muse runs are
visible only to the holders of the grants, escaping, and the determinism of the
fixtures.
"""
# REQUIRES: AI-01, AI-02, AI-03, AI-04, PER-04, SEC-01, SEC-03
# The what-if agent replays only labelled fixtures, validates every claim, falls back to the
# deterministic briefing, and is readable only by the holders of its dedicated grants.

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from insight_support import ADMIN, build_environment, open_factory
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.errors import ConflictError, PermissionDeniedError, ValidationError
from acme_city.muse.client import MuseRequestError, ProviderResponse
from acme_city.persistence.base import Base
from acme_city.persistence.models import audit as audit_models
from acme_city.persistence.models import model_run
from acme_city.persistence.models import policy as models
from acme_city.persistence.session import transaction
from acme_city.policy import muse
from acme_city.policy.service import PolicyService
from acme_city.ui.router import router as ui_router

STEWARD = "persona_data_steward"
REVIEWER = "persona_permit_reviewer"
APPLICANT = "persona_applicant"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
REPO = Path(__file__).resolve().parents[2]
REPLAY_LABEL = "Recorded replay (a labelled demonstration fixture, not a live Muse answer)"

#: What a briefing may never say.
FORBIDDEN_WORDS = ("revenue", "staff-day", "staff day", "throughput", "no permit required")

BUSINESS_TABLES = (
    "applications", "application_revisions", "documents", "application_findings",
    "decisions", "permits", "permit_types", "rule_versions", "fee_schedule_versions",
    "assessments", "observations", "match_proposals",
)


@pytest.fixture(scope="module")
def settings(tmp_path_factory):
    return build_environment(tmp_path_factory.mktemp("policy-muse"), synthetic=False, name="muse.db")


@pytest.fixture()
def client(settings):
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> TestClient:
    assert client.post("/api/session/select", json={"actor_id": actor_id}).status_code == 200
    return client


def csrf_of(body: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert match, "the page carries a form token"
    return match.group(1)


def version_in(body: str, form_action: str) -> str:
    block = body[body.index(form_action):]
    match = re.search(r'name="expected_version" value="(\d+)"', block)
    assert match, form_action
    return match.group(1)


def create_scenario(client: TestClient, suggestion: str) -> str:
    page = choose(client, ADMIN).get("/policy/scenarios")
    response = client.post(
        "/policy/scenarios",
        data={"csrf_token": csrf_of(page.text), "expected_version": "0", "suggestion": suggestion, "name": suggestion},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response.headers["location"].split("?")[0]


def run_demo(client: TestClient, suggestion: str = "fence_height_7ft", **fields: str) -> str:
    editor = create_scenario(client, suggestion)
    page = client.get(editor)
    payload = {
        "csrf_token": csrf_of(page.text),
        "expected_version": re.search(r'name="expected_version" value="(\d+)"', page.text).group(1),
        "kind": "synthetic_year", "seed": "20261028", "count": "600",
    }
    payload.update(fields)
    response = client.post(f"{editor}/run", data=payload, follow_redirects=False)
    assert response.status_code == 303, response.text
    return response.headers["location"].split("?")[0]


def ask_muse_brief(client: TestClient, run_path: str):
    page = client.get(f"{run_path}/briefing")
    return client.post(
        f"{run_path}/briefing/muse",
        data={"csrf_token": csrf_of(page.text),
              "expected_version": version_in(page.text, "briefing/muse")},
        follow_redirects=True,
    )


def actor_context(session, actor_id: str) -> ActorContext:
    grants = PermissionResolver(session).grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        domain_scope=frozenset(g.domain_id for g in grants if g.domain_id),
        record_scope=frozenset(r for g in grants for r in g.record_scope),
    )


def business_snapshot(settings) -> dict[str, str]:
    factory = open_factory(settings)
    try:
        with factory() as session:
            digests = {}
            for table in Base.metadata.sorted_tables:
                if table.name not in BUSINESS_TABLES:
                    continue
                rows = [
                    json.dumps({k: str(v) for k, v in row._mapping.items()}, sort_keys=True)
                    for row in session.execute(table.select()).all()
                ]
                digests[table.name] = hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()
            return digests
    finally:
        factory.dispose()


def muse_rows(settings, task: str | None = None) -> list[model_run.ModelRun]:
    factory = open_factory(settings)
    try:
        with factory() as session:
            rows = session.execute(select(model_run.ModelRun)).scalars().all()
            return [
                r for r in rows
                if isinstance(r.input_refs, dict) and r.input_refs.get("task") in ((task,) if task else ("policy_brief", "policy_propose"))
            ]
    finally:
        factory.dispose()


# ----------------------------------------------------------- the demo briefing


def test_the_demo_run_gets_a_muse_briefing_from_the_labelled_replay(client, settings) -> None:
    before = business_snapshot(settings)
    run_path = run_demo(client)
    page = client.get(f"{run_path}/briefing")
    assert 'data-testid="policy-write-with-muse"' in page.text
    assert 'data-testid="policy-writer-deterministic"' in page.text  # before Muse is asked
    after = ask_muse_brief(client, run_path).text
    assert 'data-testid="policy-writer-muse"' in after
    assert 'data-testid="muse-source"' in after and 'data-mode="replay"' in after
    assert REPLAY_LABEL in after
    assert " in · " in after and " out" in after  # usage is shown with the source
    assert "synthetic data: 600 generated cases" in after
    assert "28 of the 600 cases would get a different result" in after
    assert "from 6 ft to 7 ft (ACME Code §14-306)" in after
    assert "which is 28 fewer" in after
    assert 'data-testid="policy-section-cites"' in after  # each section names its typed facts
    assert "outcome.deny.change" in after
    assert 'data-testid="synthetic-badge"' in after
    lowered = after.lower()
    assert not any(word in lowered for word in FORBIDDEN_WORDS)
    # Asking only recorded a model run and an audit event; no business row changed.
    assert business_snapshot(settings) == before


def test_the_muse_briefing_downloads_escaped_with_its_source(client) -> None:
    run_path = run_demo(client)
    ask_muse_brief(client, run_path)
    body = client.get(f"{run_path}/briefing/download?format=html")
    assert body.status_code == 200
    assert REPLAY_LABEL in body.text
    assert "<script" not in body.text.lower()
    md = client.get(f"{run_path}/briefing/download?format=md")
    assert md.status_code == 200 and "Recorded replay" in md.text


def test_the_failing_fixture_falls_back_to_the_deterministic_briefing_with_a_label(client) -> None:
    run_path = run_demo(client, "shed_condition_300")
    page = ask_muse_brief(client, run_path).text
    assert 'data-testid="policy-writer-fallback"' in page
    assert "The Muse briefing was not used." in page
    assert "Deterministic briefing built from the typed facts of this run." in page
    assert "rejected" in page
    for code in ("wrong_direction", "uncited_figure", "rule_source_mismatch"):
        assert code in page
    # Nothing of the rejected text reaches the reader.
    assert "fewer cases would be recommended" not in page
    assert "About 40 cases would benefit" not in page
    assert "250 sq ft" not in page
    assert 'data-testid="policy-writer-muse"' not in page


def test_a_run_with_no_fixture_says_so_and_shows_the_deterministic_briefing(client) -> None:
    run_path = run_demo(client, seed="7", count="60")
    page = ask_muse_brief(client, run_path).text
    assert 'data-testid="policy-writer-fallback"' in page
    assert "no recorded demonstration answer matches this request" in page
    assert "Deterministic briefing built from the typed facts of this run." in page


def test_the_explanation_panel_shows_a_validated_explanation(client) -> None:
    run_path = run_demo(client)
    page = client.get(run_path).text
    assert 'data-testid="policy-explain-submit"' in page
    explained = client.post(
        f"{run_path}/explain",
        data={"csrf_token": csrf_of(page), "expected_version": version_in(page, "/explain")},
        follow_redirects=True,
    ).text
    assert 'data-testid="policy-explanation"' in explained
    assert REPLAY_LABEL in explained
    assert "Cites:" in explained
    assert "28 of the 600 cases would get a different result" in explained


def test_the_explanation_of_a_run_with_no_fixture_shows_the_fallback(client) -> None:
    run_path = run_demo(client, "shed_condition_300")  # only the failing briefing fixture exists
    page = client.get(run_path).text
    explained = client.post(
        f"{run_path}/explain",
        data={"csrf_token": csrf_of(page), "expected_version": version_in(page, "/explain")},
        follow_redirects=True,
    ).text
    assert 'data-testid="policy-explain-fallback"' in explained
    assert 'data-testid="policy-explanation"' not in explained


# --------------------------------------------------------------------- grants


@pytest.mark.parametrize("actor", [APPLICANT, STEWARD, REVIEWER])
def test_the_muse_routes_refuse_the_other_personas_including_direct_ids(client, actor, settings) -> None:
    run_path = run_demo(client)
    ask_muse_brief(client, run_path)
    client.post("/policy/propose", data={
        "csrf_token": csrf_of(client.get("/policy/scenarios").text), "expected_version": "0",
        "question": "What if the side and rear yard fence limit were 7 ft?"})
    proposal_id = muse_rows(settings, "policy_propose")[0].id
    choose(client, actor)
    assert client.get(f"/policy/proposals/{proposal_id}").status_code == 403
    for path in (f"{run_path}/briefing/muse", f"{run_path}/explain", "/policy/propose"):
        response = client.post(path, data={"csrf_token": "x", "expected_version": "0", "question": "x"})
        assert response.status_code == 403, (actor, path)
    # The recorded Muse runs are not readable through the general run lists or the detail view.
    for run in muse_rows(settings):
        assert client.get(f"/detail/muse-run/{run.id}").status_code in (403, 404)
    listed = client.get("/api/muse/runs")
    if listed.status_code == 200:
        assert all(r.get("task") not in ("policy_brief", "policy_propose") for r in listed.json()["runs"])


def test_no_general_run_list_shows_a_policy_muse_run(client, settings) -> None:
    run_path = run_demo(client)
    ask_muse_brief(client, run_path)
    ids = [r.id for r in muse_rows(settings)]
    assert ids
    for persona in (ADMIN, STEWARD, REVIEWER, APPLICANT):
        choose(client, persona)
        listed = client.get("/api/muse/runs")
        if listed.status_code == 200:
            assert not any(i in listed.text for i in ids), persona
        for path in (f"{run_path}", f"{run_path}/briefing", "/policy/scenarios"):
            body = client.get(path)
            if body.status_code == 200:
                # The model-run panel of the evidence section never lists a policy Muse run.
                assert 'data-testid="model-runs"' not in body.text or not any(i in body.text for i in ids)
        for run_id in ids:
            assert client.get(f"/detail/muse-run/{run_id}").status_code in (403, 404)


def test_only_the_city_administrator_holds_the_policy_muse_grants(settings) -> None:
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            resolver = PermissionResolver(session)
            wanted = {"policy.muse.brief", "policy.muse.propose"}
            assert wanted <= resolver.permissions_for(ADMIN)
            for actor in (APPLICANT, STEWARD, REVIEWER):
                assert not (wanted & resolver.permissions_for(actor)), actor
    finally:
        factory.dispose()


def test_the_service_checks_the_grant_on_every_method(settings) -> None:
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            admin = actor_context(session, ADMIN)
            policy = PolicyService(session, now=NOW)
            scenario = policy.create_scenario(admin, name="Muse guard", changes=[
                {"kind": "rule_threshold", "rule_id": "DF-2", "limit_value": "7"}], expected_version=0)
            run = policy.run_scenario(admin, scenario.id, expected_version=scenario.version,
                                      spec={"kind": "synthetic_year", "count": "50"})
            service = muse.PolicyMuseService(session, settings, now=NOW)
            for actor_id in (APPLICANT, STEWARD, REVIEWER):
                other = actor_context(session, actor_id)
                calls = (
                    lambda: service.request_brief(other, run, purpose="brief", expected_version=0),
                    lambda: service.request_proposal(other, question="What if the fence limit were 7 ft?", expected_version=0),
                    lambda: service.latest_brief(other, run, "brief"),
                    lambda: service.brief_version(other, run, "brief"),
                    lambda: service.briefing_for(other, run),
                    lambda: service.proposal(other, "modelrun_none"),
                    lambda: service.changes_for_save(other, "modelrun_none"),
                    lambda: service.recent_proposals(other),
                )
                for call in calls:
                    with pytest.raises(PermissionDeniedError):
                        call()
    finally:
        factory.dispose()


# ----------------------------------------------------- csrf and mandatory version


def test_every_muse_write_needs_csrf_and_a_version(client, settings) -> None:
    run_path = run_demo(client)
    page = client.get(f"{run_path}/briefing")
    token = csrf_of(page.text)
    before = len(muse_rows(settings))
    for path, extra in (
        (f"{run_path}/briefing/muse", {}),
        (f"{run_path}/explain", {}),
        ("/policy/propose", {"question": "What if the side and rear yard fence limit were 7 ft?"}),
    ):
        bad_token = client.post(path, data={"csrf_token": "wrong", "expected_version": "0", **extra})
        assert bad_token.status_code in (400, 403), path
        no_version = client.post(path, data={"csrf_token": token, **extra})
        assert no_version.status_code == 422 or no_version.status_code == 400, (path, no_version.status_code)
        assert "expected version is required" in no_version.text, path
    stale = client.post(f"{run_path}/briefing/muse", data={"csrf_token": token, "expected_version": "5"})
    assert stale.status_code == 409
    assert len(muse_rows(settings)) == before  # a refused request records no run


def test_a_second_request_with_the_old_version_is_a_conflict(client) -> None:
    run_path = run_demo(client)
    page = client.get(f"{run_path}/briefing")
    data = {"csrf_token": csrf_of(page.text), "expected_version": "0"}
    assert client.post(f"{run_path}/briefing/muse", data=data, follow_redirects=False).status_code == 303
    assert client.post(f"{run_path}/briefing/muse", data=data, follow_redirects=False).status_code == 409


# ------------------------------------------------------------------ proposals


QUESTION = "What if the side and rear yard fence limit were 7 ft?"
NO_PERMIT = "What if no permit were required for a shed?"


def propose(client: TestClient, question: str):
    page = client.get("/policy/scenarios")
    return client.post(
        "/policy/propose",
        data={"csrf_token": csrf_of(page.text), "expected_version": "0", "question": question},
        follow_redirects=True,
    )


def test_a_proposal_is_shown_validated_and_nothing_is_saved_until_the_administrator_saves(client, settings) -> None:
    choose(client, ADMIN)
    scenarios_before = len(client.get("/policy/scenarios").text.split('data-testid="policy-row"')) - 1
    business = business_snapshot(settings)
    page = propose(client, QUESTION).text
    assert 'data-testid="policy-proposal-changes"' in page
    assert "Change ACME Code §14-306" in page
    assert "limit 6 to 7" in page
    assert REPLAY_LABEL in page
    assert 'data-testid="policy-proposal-save"' in page
    listing = client.get("/policy/scenarios").text
    assert len(listing.split('data-testid="policy-row"')) - 1 == scenarios_before  # nothing saved yet
    assert business_snapshot(settings) == business
    saved = client.post(
        "/policy/scenarios",
        data={"csrf_token": csrf_of(page), "expected_version": "0",
              "proposal": re.search(r'name="proposal" value="([^"]+)"', page).group(1),
              "name": "Muse proposed fence what-if"},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    editor = client.get(saved.headers["location"]).text
    assert "Change ACME Code §14-306" in editor and "limit 6 to 7" in editor
    # It is saved, not run: no run exists for it yet.
    assert "Muse proposed fence what-if" in editor
    assert business_snapshot(settings) == business


def test_saving_a_proposal_needs_csrf_and_the_version_zero(client) -> None:
    choose(client, ADMIN)
    page = propose(client, QUESTION).text
    proposal = re.search(r'name="proposal" value="([^"]+)"', page).group(1)
    token = csrf_of(page)
    assert client.post("/policy/scenarios", data={"csrf_token": "bad", "expected_version": "0",
                                                  "proposal": proposal, "name": "x"}).status_code in (400, 403)
    assert client.post("/policy/scenarios", data={"csrf_token": token, "proposal": proposal,
                                                  "name": "x"}).status_code in (400, 422)
    assert client.post("/policy/scenarios", data={"csrf_token": token, "expected_version": "3",
                                                  "proposal": proposal, "name": "x"}).status_code == 409


def test_an_unsupported_proposal_is_rejected_whole_and_names_the_reason(client) -> None:
    choose(client, ADMIN)
    page = propose(client, NO_PERMIT).text
    assert 'data-testid="policy-proposal-rejected"' in page
    assert 'data-testid="policy-proposal-save"' not in page
    assert "not supported in this release" in page.lower()
    assert 'data-testid="policy-proposal-save-form"' not in page


def test_an_unknown_question_has_no_proposal_and_no_provider_call(client, settings, monkeypatch) -> None:
    def refuse(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("the replay path must not call a provider")

    monkeypatch.setattr("acme_city.muse.client.MuseClient.create_response", refuse)
    choose(client, ADMIN)
    page = propose(client, "What if every fee were free on Tuesdays?").text
    assert 'data-testid="policy-proposal-rejected"' in page
    assert "no recorded demonstration answer matches this request" in page


def test_a_hostile_question_is_escaped(client) -> None:
    choose(client, ADMIN)
    page = propose(client, "<script>alert(1)</script> what if the fence limit were 9 ft?").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


# ---------------------------------------------------------- live is off by default


def test_live_is_off_by_default_and_never_enabled_by_a_credential(tmp_path) -> None:
    plain = Settings.load(environ={"ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'a.db'}",
                                   "ACME_SECRET_KEY": "policy-live-default-secret"},
                          key_file=tmp_path / "missing.env")
    assert plain.policy_assist_live_enabled is False
    assert plain.safe_summary()["policy_assist_live_enabled"] is False
    with_key = Settings.load(environ={"ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'a.db'}",
                                      "ACME_SECRET_KEY": "policy-live-default-secret",
                                      "META_API_KEY": "credential-present"},
                             key_file=tmp_path / "missing.env")
    assert with_key.policy_assist_live_enabled is False
    on = Settings.load(environ={"ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'a.db'}",
                                "ACME_SECRET_KEY": "policy-live-default-secret",
                                "ACME_POLICY_ASSIST_LIVE_ENABLED": "true"},
                       key_file=tmp_path / "missing.env")
    assert on.policy_assist_live_enabled is True


class _Raises:
    """A provider client that raises; the replay path must never touch it."""

    calls = 0

    def create_response(self, payload):
        type(self).calls += 1
        raise MuseRequestError("the provider is unreachable")


class _Explodes:
    calls = 0

    def create_response(self, payload):
        type(self).calls += 1
        raise RuntimeError("boom")


@pytest.fixture()
def fresh(tmp_path):
    """A database of its own: the live cap and the error-stop are counted over all recorded runs."""
    return build_environment(tmp_path, synthetic=False, name="live.db")


def _live_settings(settings) -> Settings:
    return Settings.load(
        environ={"ACME_DATABASE_URL": settings.database_url, "ACME_SECRET_KEY": "policy-live-secret-value",
                 "ACME_POLICY_ASSIST_LIVE_ENABLED": "true", "ACME_MUSE_LIVE_CALL_CAP": "3"},
        key_file=Path("/nonexistent/missing.env"),
    )


def _run_for_service(session, count: str = "50"):
    admin = actor_context(session, ADMIN)
    policy = PolicyService(session, now=NOW)
    scenario = policy.create_scenario(admin, name="Live test", changes=[
        {"kind": "rule_threshold", "rule_id": "DF-2", "limit_value": "7"}], expected_version=0)
    run = policy.run_scenario(admin, scenario.id, expected_version=scenario.version,
                              spec={"kind": "synthetic_year", "count": count})
    return admin, run


def test_the_replay_path_never_calls_the_client_even_when_one_is_given(settings) -> None:
    _Raises.calls = 0
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            admin, run = _run_for_service(session)
            service = muse.PolicyMuseService(session, settings, now=NOW, client=_Raises())
            result = service.request_brief(admin, run, purpose="brief", expected_version=0)
            assert result.mode == "replay" and result.accepted is False
            proposal = service.request_proposal(admin, question="no such question", expected_version=0)
            assert proposal.mode == "replay" and not proposal.accepted
    finally:
        factory.dispose()
    assert _Raises.calls == 0


@pytest.mark.parametrize("client_class", [_Raises, _Explodes])
def test_a_provider_client_that_raises_is_a_recorded_error_and_the_fallback_shows(fresh, client_class) -> None:
    client_class.calls = 0
    live = _live_settings(fresh)
    factory = open_factory(fresh)
    try:
        with transaction(factory) as session:
            admin, run = _run_for_service(session)
            service = muse.PolicyMuseService(session, live, now=NOW, client=client_class())
            result = service.request_brief(admin, run, purpose="brief", expected_version=0)
            assert result.mode == "live"
            assert result.accepted is False and result.output is None
            assert "No Muse briefing was written" in result.notice
            shown, latest = service.briefing_for(admin, run)
            assert shown.writer == "deterministic" and latest is not None
            # The error is recorded, and it stops every further live call (the shared error-stop).
            second = service.request_brief(admin, run, purpose="brief", expected_version=1)
            assert second.accepted is False
            assert "a previous live run recorded a provider error" in second.notice
        assert client_class.calls == 1
    finally:
        factory.dispose()


def test_a_live_answer_is_validated_like_a_replay_and_labelled_live(fresh) -> None:
    fixture = json.loads((REPO / "fixtures/replay/policy-assist/fence-7ft-brief.json").read_text())

    class Answers:
        def create_response(self, payload):
            assert payload["text"]["format"]["strict"] is True
            assert payload["text"]["format"]["name"] == "acme_city_policy_brief"
            assert "BEGIN TYPED FACTS" in payload["input"]
            return ProviderResponse(response_id="resp_1", status="completed", usage={"input_tokens": 9, "output_tokens": 4},
                                    output_text=json.dumps(fixture["output"]), latency_ms=12)

    live = _live_settings(fresh)
    factory = open_factory(fresh)
    try:
        with transaction(factory) as session:
            admin = actor_context(session, ADMIN)
            policy = PolicyService(session, now=NOW)
            scenario = policy.create_scenario(admin, name="Live ok", suggestion_key="fence_height_7ft", expected_version=0)
            run = policy.run_scenario(admin, scenario.id, expected_version=scenario.version,
                                      spec={"kind": "synthetic_year"})
            service = muse.PolicyMuseService(session, live, now=NOW, client=Answers())
            result = service.request_brief(admin, run, purpose="brief", expected_version=0)
            assert result.mode == "live" and result.accepted
            assert result.source["source_label"] == "Muse Spark (live)"
            assert result.source["latency_ms"] == 12 and result.source["usage"]["input_tokens"] == 9
    finally:
        factory.dispose()


def test_a_live_answer_that_fails_validation_is_rejected_whole(fresh) -> None:
    fixture = json.loads((REPO / "fixtures/replay/policy-assist/fence-7ft-brief.json").read_text())
    bad = json.loads(json.dumps(fixture["output"]))
    bad["sections"][1]["sentences"][1]["text"] = "Recommendations to approve would fall from 306 to 334 cases."

    class Answers:
        def create_response(self, payload):
            return ProviderResponse(response_id="resp_2", status="completed", output_text=json.dumps(bad))

    live = _live_settings(fresh)
    factory = open_factory(fresh)
    try:
        with transaction(factory) as session:
            admin = actor_context(session, ADMIN)
            policy = PolicyService(session, now=NOW)
            scenario = policy.create_scenario(admin, name="Live bad", suggestion_key="fence_height_7ft", expected_version=0)
            run = policy.run_scenario(admin, scenario.id, expected_version=scenario.version,
                                      spec={"kind": "synthetic_year"})
            service = muse.PolicyMuseService(session, live, now=NOW, client=Answers())
            result = service.request_brief(admin, run, purpose="brief", expected_version=0)
            assert result.accepted is False and result.output is None
            assert any(i["code"] == "wrong_direction" for i in result.issues)
            assert service.briefing_for(admin, run)[0].writer == "deterministic"
    finally:
        factory.dispose()


# -------------------------------------------------------- audit and the fixtures


def test_every_muse_action_is_audited_without_free_text(client, settings) -> None:
    run_path = run_demo(client)
    ask_muse_brief(client, run_path)
    propose(client, QUESTION)
    factory = open_factory(settings)
    try:
        with factory() as session:
            events = session.execute(select(audit_models.AuditEvent).where(
                audit_models.AuditEvent.action.in_(("policy.muse.brief", "policy.muse.propose")))).scalars().all()
            assert {e.action for e in events} == {"policy.muse.brief", "policy.muse.propose"}
            for event in events:
                text = json.dumps(event.metadata_json or {})
                assert QUESTION not in text and "fence" not in text.lower()
    finally:
        factory.dispose()


def _builder():
    spec = importlib.util.spec_from_file_location("build_policy_assist_fixtures", REPO / "scripts/build_policy_assist_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_fixtures_are_exactly_what_the_builder_writes() -> None:
    documents = _builder().build_documents()
    directory = REPO / "fixtures/replay/policy-assist"
    assert sorted(documents) == sorted(p.name for p in directory.glob("*.json"))
    for name, data in documents.items():
        text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        assert (directory / name).read_text(encoding="utf-8") == text, name


def test_the_fixtures_are_labelled_demonstrations_keyed_by_the_run_content() -> None:
    for path in sorted((REPO / "fixtures/replay/policy-assist").glob("*.json")):
        data = json.loads(path.read_text())
        assert data["fixture_kind"] == "policy_assist_replay"
        assert "not a recording of a Muse answer" in data["note"]
        assert data["replay_key"] == muse.replay_key(data["task"], data["basis"])
        if data["task"] == "policy_brief":
            basis = data["basis"]
            assert {"population_hash", "baseline_config_hash", "scenario_config_hash", "changes_hash",
                    "facts_hash"} <= set(basis)
        else:
            assert "baseline_config_hash" in data["basis"] and "question_key" in data["basis"]


def test_a_fixture_with_an_edited_key_does_not_load(tmp_path) -> None:
    source = REPO / "fixtures/replay/policy-assist/fence-7ft-brief.json"
    data = json.loads(source.read_text())
    data["replay_key"] = "0" * 64
    (tmp_path / "x.json").write_text(json.dumps(data))
    with pytest.raises(ValidationError):
        muse.load_replay_fixtures(tmp_path)
    data = json.loads(source.read_text())
    data["prompt_version"] = "other"
    (tmp_path / "x.json").write_text(json.dumps(data))
    with pytest.raises(ValidationError):
        muse.load_replay_fixtures(tmp_path)
    data = json.loads(source.read_text())
    data["fixture_kind"] = "recording"
    (tmp_path / "x.json").write_text(json.dumps(data))
    with pytest.raises(ValidationError):
        muse.load_replay_fixtures(tmp_path)


def test_a_run_of_another_configuration_does_not_replay(settings) -> None:
    """The same question of a run over another population has no fixture: the key covers the content."""
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            admin, run = _run_for_service(session, count="55")
            service = muse.PolicyMuseService(session, settings, now=NOW)
            result = service.request_brief(admin, run, purpose="brief", expected_version=0)
            assert result.accepted is False and "no recorded demonstration answer" in result.notice
    finally:
        factory.dispose()


def test_a_stale_scenario_row_count_does_not_change_the_replay_key(settings) -> None:
    """Two runs of the same scenario at different moments share one replay key."""
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            admin = actor_context(session, ADMIN)
            keys = []
            hashes = []
            for hour in (12, 17):
                moment = datetime(2026, 10, 28, hour, 0, tzinfo=UTC)
                policy = PolicyService(session, now=moment)
                scenario = policy.create_scenario(admin, name=f"Moment {hour}", suggestion_key="fence_height_7ft", expected_version=0)
                run = policy.run_scenario(admin, scenario.id, expected_version=scenario.version, spec={"kind": "synthetic_year", "count": "80"})
                facts = muse.muse_facts(run)
                keys.append(muse.replay_key("policy_brief", muse.brief_basis(run, "brief", facts)))
                hashes.append(run.content_hash)
            assert hashes[0] != hashes[1]  # the run content hash includes the wall-clock moment
            assert keys[0] == keys[1]  # the replay key does not
    finally:
        factory.dispose()

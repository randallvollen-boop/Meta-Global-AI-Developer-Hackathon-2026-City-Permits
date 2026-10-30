"""The two agent screens, the administration screen and the new scenarios.

The screens are persona-scoped: a persona sees a screen only when it holds a
grant for it, and the browser never decides who may act.  Every change is a
governed, audited action.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.portal_intake.scenarios import PERMIT_TYPE_KEYS, build_scenario
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import agent_ops, audit, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def environment(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'agents.db'}",
            "ACME_SECRET_KEY": "agents-test-secret-value",
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
    finally:
        factory.dispose()
    return settings


@pytest.fixture()
def client(environment) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def csrf(client: TestClient, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def act(client: TestClient, action_id: str, fields: dict, next_path: str) -> dict:
    response = client.post(
        f"/ui/actions/{action_id}",
        data={
            "csrf_token": csrf(client, next_path),
            "action_id": action_id,
            "next": next_path,
            **fields,
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_seventeen_permit_types_carry_their_configuration(environment) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            rows = session.execute(select(permit.PermitType)).scalars().all()
            assert len(rows) == 17
            by_key = {row.key: row for row in rows}
            assert set(by_key) == set(PERMIT_TYPE_KEYS)
            for row in rows:
                assert row.review_area, row.key
                assert row.process_category in (
                    "simple",
                    "with_plans",
                    "formal_review",
                ), row.key
                assert row.discretionary is not None, row.key
                assert row.fee_schedule_key, row.key
            assert by_key["shed"].review_area == "Building"
            assert by_key["shed"].process_category == "simple"
            assert by_key["shed"].discretionary is False
            assert by_key["pod"].review_area == "Engineering"
            assert by_key["fire_alarm"].review_area == "Fire"
            assert by_key["fire_alarm"].process_category == "with_plans"
            assert by_key["change_occupancy"].process_category == "formal_review"
            assert by_key["site_plan_review"].review_area == "Planning & Zoning"
            assert by_key["zoning_variance"].review_area == "Board / Administrative"
            assert by_key["certificate_appropriateness"].discretionary is True
            assert by_key["rezoning"].discretionary is True
    finally:
        factory.dispose()


def test_the_agent_screens_are_persona_scoped(client: TestClient) -> None:
    # Changed deliberately (the Agent Operator): the wake and run grants moved
    # to the Agent Operator, so the agent screens are opened by that persona.
    choose(client, "persona_agent_operator")
    assert client.get("/agent/intake").status_code == 200
    assert client.get("/agent/adjudication").status_code == 200
    assert client.get("/admin").status_code == 403

    choose(client, "persona_data_steward")
    assert client.get("/agent/intake").status_code == 403
    assert client.get("/agent/adjudication").status_code == 403
    assert client.get("/admin").status_code == 403

    choose(client, "persona_permit_reviewer")
    assert client.get("/agent/adjudication").status_code == 403
    assert client.get("/agent/intake").status_code == 403
    assert client.get("/admin").status_code == 403

    choose(client, "persona_city_administrator")
    assert client.get("/agent/intake").status_code == 403
    assert client.get("/agent/adjudication").status_code == 403
    assert client.get("/admin").status_code == 200

    choose(client, "persona_applicant")
    assert client.get("/agent/intake").status_code == 403
    assert client.get("/agent/adjudication").status_code == 403
    assert client.get("/admin").status_code == 403


def test_only_the_operator_sees_the_wake_button(client: TestClient) -> None:
    # Changed deliberately (the Agent Operator): the wake grant moved to the
    # Agent Operator.  A persona without it is refused the agent screen, so no
    # locked toggle is rendered for it any more.
    choose(client, "persona_agent_operator")
    body = client.get("/agent/intake").text
    assert 'data-testid="agent-toggle"' in body
    assert 'data-testid="agent-toggle-locked"' not in body

    choose(client, "persona_data_steward")
    assert client.get("/agent/intake").status_code == 403


def test_the_agent_screen_shows_its_kpis_and_graph(client: TestClient) -> None:
    choose(client, "persona_agent_operator")
    body = client.get("/agent/intake").text
    for testid in ("kpi-waiting", "kpi-processed", "kpi-needs-human", "kpi-errors"):
        assert f'data-testid="{testid}"' in body
    assert 'data-testid="agent-graph"' in body
    for node in (
        "classifier",
        "field_extractor",
        "document_qc",
        "duplicate_finder",
        "completeness",
        "router",
    ):
        assert f'data-node-id="{node}"' in body
    assert "Each group waits for the group before it." in body
    # The screen no longer claims that the steps run in parallel.
    assert "run in parallel" not in body

    choose(client, "persona_agent_operator")
    body = client.get("/agent/adjudication").text
    for testid in (
        "kpi-in-review",
        "kpi-recommended",
        "kpi-awaiting-confirmation",
        "kpi-held",
    ):
        assert f'data-testid="{testid}"' in body
    for node in (
        "rule_loader",
        "rule_evaluator",
        "condition_builder",
        "precedent_check",
        "disposition",
    ):
        assert f'data-node-id="{node}"' in body


def test_the_sidebar_status_line_is_shown_to_staff_only(client: TestClient) -> None:
    # Changed deliberately (the Agent Operator): the status line follows the
    # run grants, so the Agent Operator is the staff member who sees it.
    choose(client, "persona_agent_operator")
    body = client.get("/agent/intake").text
    assert 'data-testid="agent-status"' in body
    assert "Intake agent is asleep" in body

    choose(client, "persona_applicant")
    body = client.get("/queue").text
    assert 'data-testid="agent-status"' not in body


def test_the_administration_screen_lists_the_configuration(client: TestClient) -> None:
    choose(client, "persona_city_administrator")
    body = client.get("/admin?tab=permit-types").text
    assert body.count('data-testid="admin-permit-type-row"') == 17
    assert "Administration" in body
    assert 'data-testid="admin-add-permit-type"' in body
    assert 'data-testid="admin-document-toggle"' in body

    body = client.get("/admin?tab=users").text
    assert 'data-testid="admin-people"' in body
    assert 'data-testid="admin-service-identities"' in body
    assert "service_agent_intake" in body
    assert "service_agent_adjudication" in body
    assert 'data-testid="admin-add-user"' in body

    body = client.get("/admin?tab=reason-codes").text
    assert body.count('data-testid="admin-reason-code-row"') == 12
    assert "DOES_NOT_MEET_CODE" in body

    body = client.get("/admin?tab=log").text
    assert 'data-testid="admin-configuration-log"' in body


def test_a_permit_type_change_is_governed_and_audited(
    client: TestClient, environment
) -> None:
    choose(client, "persona_city_administrator")
    result = act(
        client,
        "config.permit_type.document",
        {
            "permit_type_id": "permit_type_shed",
            "document_type": "construction_plans",
            "required": "yes",
            "expected_version": "1",
        },
        "/admin?tab=permit-types",
    )
    assert result["status"] == "accepted", result
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.get(permit.PermitType, "permit_type_shed")
            assert "construction_plans" in (row.required_documents or [])
            events = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "config.permit_type.document"
                )
            ).scalars().all()
            assert len(events) == 1
            assert events[0].actor_id == "persona_city_administrator"
    finally:
        factory.dispose()


def test_a_data_steward_may_not_change_the_configuration(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    response = client.post(
        "/ui/actions/config.permit_type.document",
        data={
            "csrf_token": csrf(client, "/queue/intake"),
            "action_id": "config.permit_type.document",
            "next": "/queue/intake",
            "permit_type_id": "permit_type_shed",
            "document_type": "construction_plans",
            "required": "yes",
        },
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 403, response.text


def test_a_new_permit_type_has_no_rule_and_is_held(
    client: TestClient, environment
) -> None:
    choose(client, "persona_city_administrator")
    result = act(
        client,
        "config.permit_type.create",
        {
            "key": "greenhouse",
            "label": "Greenhouse",
            "description": "A small residential greenhouse.",
            "review_area": "Building",
            "process_category": "simple",
            "discretionary": "no",
            "required_fields": "parcel_number project_description",
            "required_documents": "site_plan",
            "fee_schedule_key": "fee_commercial_demo",
        },
        "/admin?tab=permit-types",
    )
    assert result["status"] == "accepted", result
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.execute(
                select(permit.PermitType).where(permit.PermitType.key == "greenhouse")
            ).scalar_one()
            assert row.process_category == "simple"
            assert row.review_area == "Building"
            rules = session.execute(
                select(permit.Recommendation)
            ).scalars().all()
            assert rules == []
    finally:
        factory.dispose()


def test_an_added_user_does_not_appear_in_the_persona_switcher(
    client: TestClient, environment
) -> None:
    choose(client, "persona_city_administrator")
    result = act(
        client,
        "config.user.add",
        {
            "name": "Marlow Quint",
            "department": "Building Safety",
            "persona_role": "Permit Reviewer",
        },
        "/admin?tab=users",
    )
    assert result["status"] == "accepted", result
    body = client.get("/select").text
    assert "Marlow Quint" not in body
    body = client.get("/admin?tab=users").text
    assert "Marlow Quint" in body
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            grants = session.execute(
                select(audit.AuditEvent).where(
                    audit.AuditEvent.action == "config.user.add"
                )
            ).scalars().all()
            assert len(grants) == 1
    finally:
        factory.dispose()


def test_a_reason_code_can_be_added_and_retired(client: TestClient, environment) -> None:
    choose(client, "persona_city_administrator")
    result = act(
        client,
        "config.reason_code.add",
        {
            "code": "INCOMPLETE_DRAWING",
            "label": "Incomplete drawing",
            "description": "The drawing set is incomplete.",
            # A reason code names the use it may serve.
            "code_type": "return",
        },
        "/admin?tab=reason-codes",
    )
    assert result["status"] == "accepted", result
    body = client.get("/admin?tab=reason-codes").text
    assert "INCOMPLETE_DRAWING" in body
    result = act(
        client,
        "config.reason_code.retire",
        {"code": "INCOMPLETE_DRAWING"},
        "/admin?tab=reason-codes",
    )
    assert result["status"] == "accepted", result
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.execute(
                select(permit.ReasonCode).where(
                    permit.ReasonCode.code == "INCOMPLETE_DRAWING"
                )
            ).scalar_one()
            assert row.active is False
    finally:
        factory.dispose()


def test_a_requirement_change_does_not_reach_an_already_received_case(
    client: TestClient, environment
) -> None:
    """A configuration change takes effect for new intake only."""
    choose(client, "persona_data_steward")
    response = client.post(
        "/api/intake/simulate", json={"scenario": "fence-conforming-rear"}
    )
    assert response.status_code == 200, response.text
    (received,) = response.json()["results"]
    received_id = received["application_id"]

    choose(client, "persona_city_administrator")
    result = act(
        client,
        "config.permit_type.document",
        {
            "permit_type_id": "permit_type_deck_fence",
            "document_type": "construction_plans",
            "required": "yes",
            "expected_version": "1",
        },
        "/admin?tab=permit-types",
    )
    assert result["status"] == "accepted", result

    # The case that was already received keeps the requirements it was
    # measured against.
    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.toggle",
        {"agent_key": "intake", "mode": "awake"},
        "/agent/intake",
    )
    act(
        client,
        "agent.run.intake",
        {"application_id": received_id},
        "/agent/intake",
    )
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.get(permit.Application, received_id)
            assert row.status == "ready_for_review"
    finally:
        factory.dispose()

    # A case that arrives after the change carries the new requirement.
    choose(client, "persona_data_steward")
    record = build_scenario("fence-conforming-rear")[0]
    payload = record.model_dump(mode="json")
    payload["portal_reference"] = "PORTAL-2026-FENCE-REAR-002"
    response = client.post("/api/intake/records", json=payload)
    assert response.status_code == 200, response.text
    arrived_id = response.json()["application_id"]
    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.run.intake",
        {"application_id": arrived_id},
        "/agent/intake",
    )
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.get(permit.Application, arrived_id)
            assert row.status == "needs_information"
            findings = session.execute(
                select(permit.ApplicationFinding).where(
                    permit.ApplicationFinding.application_id == arrived_id
                )
            ).scalars().all()
            assert any(finding.finding_type == "missing_document" for finding in findings)
    finally:
        factory.dispose()


def test_the_new_scenarios_build_their_records() -> None:
    assert len(build_scenario("shed-large")) == 1
    assert len(build_scenario("variance-request")) == 1
    assert len(build_scenario("hvac-no-contractor")) == 1
    assert len(build_scenario("fax-unreadable")) == 1
    duplicate = build_scenario("duplicate-fence")
    assert len(duplicate) == 2
    assert duplicate[0].applicant.name == duplicate[1].applicant.name
    assert duplicate[0].site_address == duplicate[1].site_address
    assert duplicate[0].permit_type_key == duplicate[1].permit_type_key
    assert duplicate[0].portal_reference != duplicate[1].portal_reference

    random_records = build_scenario("random", count=17)
    assert len(random_records) == 17
    assert {record.permit_type_key for record in random_records} == set(PERMIT_TYPE_KEYS)
    assert {record.channel for record in random_records} <= {
        "portal",
        "counter_scan",
        "email",
        "mail",
        "fax",
    }
    assert build_scenario("random", count=17) == random_records


def test_the_fax_scenario_carries_an_unreadable_page() -> None:
    (record,) = build_scenario("fax-unreadable")
    assert record.channel == "fax"
    flags = [flag for document in record.documents for flag in document.quality]
    assert "unreadable" in flags


def test_the_run_buttons_of_a_sleeping_agent_say_why(client: TestClient) -> None:
    # Changed deliberately (the Agent Operator): the wake grant moved to the
    # Agent Operator, so it is the only persona that opens the agent screen.
    # It sees why the run buttons are locked, and it may wake the agent.
    choose(client, "persona_agent_operator")
    body = client.get("/agent/intake").text
    flat = body.replace("\n", " ")
    assert re.search(r'data-testid="agent-run-all"\s+disabled aria-describedby="agent-sleep-notice"', flat)
    assert 'id="agent-sleep-notice"' in body
    assert "Use Wake agent above to turn them on." in body
    choose(client, "persona_data_steward")
    assert client.get("/agent/intake").status_code == 403


def test_the_operator_run_is_recorded_in_the_work_queue(
    client: TestClient, environment
) -> None:
    """A manual run is an attempt of the queue, and the run names it."""
    choose(client, "persona_city_administrator")
    response = client.post(
        "/api/intake/simulate", json={"scenario": "fence-conforming-rear"}
    )
    assert response.status_code == 200, response.text
    (received,) = response.json()["results"]
    received_id = received["application_id"]

    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.toggle",
        {"agent_key": "intake", "mode": "awake"},
        "/agent/intake",
    )
    result = act(
        client,
        "agent.run.intake",
        {"application_id": received_id},
        "/agent/intake",
    )
    assert result["status"] == "accepted", result

    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            rows = session.execute(select(agent_ops.AgentWorkQueue)).scalars().all()
            assert len(rows) == 1
            work = rows[0]
            assert work.application_id == received_id
            assert work.agent_key == "intake"
            assert work.status == agent_ops.WORK_COMPLETED
            assert work.attempts == 1
            run = session.execute(
                select(agent_models.AgentRun).where(
                    agent_models.AgentRun.application_id == received_id
                )
            ).scalars().one()
            assert dict(run.inputs or {})["work_id"] == work.id
    finally:
        factory.dispose()


def test_the_batch_action_runs_the_cases_the_policy_allows(
    client: TestClient, environment
) -> None:
    """The batch action stays inside the batch size of the stored policy."""
    choose(client, "persona_city_administrator")
    for scenario in ("fence-conforming-rear", "fence-front-too-tall"):
        response = client.post("/api/intake/simulate", json={"scenario": scenario})
        assert response.status_code == 200, response.text
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            policy = session.execute(
                select(agent_ops.AgentProcessingPolicy)
            ).scalars().one()
            policy.max_batch_size = 1
            session.flush()
    finally:
        factory.dispose()

    choose(client, "persona_agent_operator")
    act(
        client,
        "agent.toggle",
        {"agent_key": "intake", "mode": "awake"},
        "/agent/intake",
    )
    result = act(client, "agent.run.intake", {}, "/agent/intake")
    assert result["status"] == "accepted", result
    assert result["message"] == "The intake agent ran on 1 waiting case(s)."

    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            works = session.execute(select(agent_ops.AgentWorkQueue)).scalars().all()
            assert len(works) == 1
            assert works[0].status == agent_ops.WORK_COMPLETED
    finally:
        factory.dispose()

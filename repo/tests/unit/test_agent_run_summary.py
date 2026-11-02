"""The waiting count, the batch button and the last run on an agent screen.

The count is the waiting list the inbox already uses.  The button names that
count.  An empty queue is refused and records no run.  After a press, the
screen lists the cases that press handled, in the words the recorded steps
stored.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import audit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.agent_views import batch_button_label, plain_outcome
from acme_city.ui.router import router as ui_router

_ITEM = re.compile(
    r'<li data-testid="agent-last-run-item">\s*'
    r'<a href="([^"]*)" data-testid="agent-last-run-link">([^<]*)</a>\s*'
    r'<span data-testid="agent-last-run-outcome">([^<]*)</span>',
    re.S,
)


def test_the_batch_button_names_the_waiting_count() -> None:
    """The label is the count when it fits, and the next slice when it does not."""
    assert batch_button_label(0, 20) == "Process cases"
    assert batch_button_label(1, 20) == "Process 1 case"
    assert batch_button_label(8, 20) == "Process 8 cases"
    assert batch_button_label(20, 20) == "Process 20 cases"
    assert batch_button_label(34, 20) == "Process the next 20 of 34"
    assert batch_button_label(0, 20, noun="task") == "Process tasks"
    assert batch_button_label(1, 20, noun="task") == "Process 1 task"
    assert batch_button_label(21, 20, noun="task") == "Process the next 20 of 21"


def test_plain_outcome_reads_the_recorded_step_notes() -> None:
    """The words on the screen are the notes the run stored, rewritten plainly."""
    def intake(*notes: tuple[str, str]) -> str:
        return plain_outcome("intake", [{"node_id": key, "note": note} for key, note in notes])

    early = (
        "router",
        "Route to early resolution: 1 blocking finding(s) must be cleared first.",
    )
    ready = ("router", "Ready for review in the Building area.")
    judging = (
        "router",
        "Verify before review: 2 finding(s) need a person's judgement.",
    )
    one_link = ("duplicate_finder", "Proposed 1 identity link(s) for a person to approve.")
    no_link = ("duplicate_finder", "Proposed 0 identity link(s) for a person to approve.")
    parcel = ("address_locator", "Proposed a parcel link for ACME-P-1001.")

    assert intake(early, one_link) == "Routed to early resolution: 1 blocking finding"
    assert intake(
        ("router", "Route to early resolution: 3 blocking finding(s) must be cleared first.")
    ) == "Routed to early resolution: 3 blocking findings"
    assert intake(judging) == "Needs a person's judgement: 2 findings"
    assert intake(
        ("router", "Verify before review: 1 finding(s) need a person's judgement.")
    ) == "Needs a person's judgement: 1 finding"
    assert intake(ready, one_link) == "Ready for review. Identity link proposed"
    assert intake(ready, no_link, parcel) == "Ready for review"
    assert intake(one_link) == "Identity link proposed"

    pending = "Every applicable rule passes, so the agent recommends approval."
    assert plain_outcome(
        "adjudication",
        [{"node_id": "disposition", "note": f"{pending} The recommendation is pending."}],
    ) == pending


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'agent-run-summary.db'}",
            "ACME_SECRET_KEY": "agent-run-summary-test-secret",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(DemoEnvironment(
                id="demo_environment_local", environment_id=ENVIRONMENT_ID,
                fictional_demo=True, fixture_version=bundle.fixture_version,
                label="local fictional demonstration",
            ))
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    finally:
        factory.dispose()
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        assert test_client.post(
            "/api/session/select", json={"actor_id": "persona_agent_operator"}
        ).status_code == 200
        yield test_client, settings


def _button(page: str) -> str:
    match = re.search(r'<button[^>]*data-testid="agent-run-all"[^>]*>', page, re.S)
    assert match, page
    return match.group(0)


def _post(client: TestClient, path: str, action_id: str, fields: dict[str, str]):
    token = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert token
    return client.post(
        f"/ui/actions/{action_id}",
        data={"csrf_token": token.group(1), "action_id": action_id, "next": path, **fields},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


def _runs(settings: Settings, agent_key: str) -> int:
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return int(session.execute(
                select(func.count()).select_from(agent_models.AgentRun).where(
                    agent_models.AgentRun.agent_key == agent_key
                )
            ).scalar_one())
    finally:
        factory.dispose()


def _accepted(settings: Settings, action: str) -> int:
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(audit.AuditEvent).where(audit.AuditEvent.action == action)
            ).scalars().all()
            return sum(1 for row in rows if row.outcome == "accepted")
    finally:
        factory.dispose()


def test_an_empty_queue_shows_the_count_and_refuses_a_run(client) -> None:
    """Nothing waiting is visible, and a press records no skipped run."""
    test_client, settings = client
    page = test_client.get("/agent/intake").text
    assert "Waiting work (0)" in page
    assert re.search(r'data-testid="agent-run-all"[^>]*>\s*Process cases\s*<', page)
    assert 'data-testid="agent-nothing-waiting"' in page
    assert "Nothing is waiting" in page
    asleep = _button(page)
    assert "disabled" in asleep
    assert 'aria-describedby="agent-sleep-notice"' in asleep
    assert "agent-nothing-waiting" not in asleep

    woken = _post(
        test_client, "/agent/intake", "agent.toggle",
        {"agent_key": "intake", "mode": "awake"},
    )
    assert woken.status_code == 200, woken.text
    awake = test_client.get("/agent/intake").text
    button = _button(awake)
    assert "disabled" in button
    assert 'aria-describedby="agent-nothing-waiting"' in button
    assert "Waiting work (0)" in awake

    refused = _post(test_client, "/agent/intake", "agent.run.intake", {})
    assert refused.status_code == 422, refused.text
    body = refused.json()
    assert body["status"] == "denied"
    assert body["message"] == "Nothing is waiting"
    assert _runs(settings, "intake") == 0
    assert _accepted(settings, "ui.agent.run.intake") == 0


def _latest_batch(settings: Settings, agent_key: str) -> list[dict[str, str]]:
    """Return the plain result of the latest press, oldest case first."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            runs = list(session.execute(
                select(agent_models.AgentRun)
                .where(agent_models.AgentRun.agent_key == agent_key)
                .order_by(
                    agent_models.AgentRun.started_at.desc(),
                    agent_models.AgentRun.id.desc(),
                )
            ).scalars())
            assert runs
            batch_id = str((runs[0].inputs or {}).get("batch_id") or "")
            assert batch_id
            members = [
                run for run in runs
                if str((run.inputs or {}).get("batch_id") or "") == batch_id
            ]
            members.sort(key=lambda run: (run.started_at, run.id))
            items: list[dict[str, str]] = []
            for run in members:
                nodes = session.execute(
                    select(agent_models.AgentRunNode)
                    .where(agent_models.AgentRunNode.agent_run_id == run.id)
                    .order_by(agent_models.AgentRunNode.position)
                ).scalars().all()
                from acme_city.persistence.models import permit

                application = session.get(permit.Application, run.application_id)
                assert application is not None
                items.append({
                    "reference": application.source_application_number,
                    "outcome": plain_outcome(
                        agent_key,
                        [{"node_id": node.node_id, "note": node.note or ""} for node in nodes],
                        outcome=run.outcome,
                        detail=run.outcome_detail or "",
                    ),
                    "href": f"/agents/cases/{run.application_id}?from=/agent/{agent_key}",
                })
            return items
    finally:
        factory.dispose()


def _shown(page: str) -> list[tuple[str, str, str]]:
    return [
        (href, html.unescape(reference), html.unescape(outcome))
        for href, reference, outcome in _ITEM.findall(page)
    ]


def test_the_last_run_lists_each_intake_case_the_press_handled(client) -> None:
    """Two arrivals are counted, run, and listed from the recorded steps."""
    test_client, settings = client
    for scenario in ("deck-high", "address-unknown"):
        assert test_client.post(
            "/api/intake/simulate", json={"scenario": scenario}
        ).status_code == 200
    before = test_client.get("/agent/intake").text
    assert "Waiting work (2)" in before
    assert re.search(r'data-testid="agent-run-all"[^>]*>\s*Process 2 cases\s*<', before)
    assert before.count('data-testid="agent-waiting-row"') == 2

    assert _post(
        test_client, "/agent/intake", "agent.toggle",
        {"agent_key": "intake", "mode": "awake"},
    ).status_code == 200
    ran = _post(test_client, "/agent/intake", "agent.run.intake", {})
    assert ran.status_code == 200, ran.text
    assert ran.json()["message"] == "The intake agent ran on 2 waiting case(s)."

    page = test_client.get("/agent/intake").text
    expected = _latest_batch(settings, "intake")
    shown = _shown(page)
    assert len(shown) == len(expected) == 2
    assert "by Agent Operator, 2 cases" in page
    phrases = {item["outcome"] for item in expected}
    assert any("Ready for review" in phrase for phrase in phrases)
    assert any(phrase.startswith("Routed to early resolution:") for phrase in phrases)
    for (href, reference, outcome), item in zip(shown, expected, strict=True):
        assert reference == item["reference"]
        assert reference.startswith("SYN-APP-")
        assert not reference.startswith("app_")
        assert outcome == item["outcome"]
        assert "finding(s)" not in outcome
        assert item["href"] in href
    assert "Waiting work (0)" in page
    button = _button(page)
    assert "disabled" in button
    assert 'aria-describedby="agent-nothing-waiting"' in button
    assert "Nothing is waiting" in page

    again = _post(test_client, "/agent/intake", "agent.run.intake", {})
    assert again.status_code == 422, again.text
    assert again.json()["message"] == "Nothing is waiting"
    assert _runs(settings, "intake") == 2
    assert _accepted(settings, "ui.agent.run.intake") == 1


def test_the_adjudication_screen_lists_the_case_the_press_handled(client) -> None:
    """The adjudication press lists the case and then has nothing left to run."""
    test_client, settings = client
    assert test_client.post(
        "/api/intake/simulate", json={"scenario": "deck-high"}
    ).status_code == 200
    assert _post(
        test_client, "/agent/intake", "agent.toggle",
        {"agent_key": "intake", "mode": "awake"},
    ).status_code == 200
    assert _post(test_client, "/agent/intake", "agent.run.intake", {}).status_code == 200

    waiting = test_client.get("/agent/adjudication").text
    assert "Waiting work (1)" in waiting
    assert re.search(r'data-testid="agent-run-all"[^>]*>\s*Process 1 case\s*<', waiting)
    assert _post(
        test_client, "/agent/adjudication", "agent.toggle",
        {"agent_key": "adjudication", "mode": "awake"},
    ).status_code == 200
    ran = _post(test_client, "/agent/adjudication", "agent.run.adjudication", {})
    assert ran.status_code == 200, ran.text
    assert ran.json()["message"] == "The adjudication agent ran on 1 case(s)."

    page = test_client.get("/agent/adjudication").text
    expected = _latest_batch(settings, "adjudication")
    shown = _shown(page)
    assert len(shown) == len(expected) == 1
    assert "by Agent Operator, 1 case" in page
    href, reference, outcome = shown[0]
    assert reference == expected[0]["reference"]
    assert reference.startswith("SYN-APP-")
    assert outcome == expected[0]["outcome"]
    assert "The recommendation is pending" not in outcome
    assert outcome
    assert expected[0]["href"] in href
    assert "Waiting work (0)" in page
    button = _button(page)
    assert "disabled" in button
    assert 'aria-describedby="agent-nothing-waiting"' in button
    assert "Nothing is waiting" in page

    case_page = test_client.get(expected[0]["href"]).text
    assert 'data-testid="agent-case-back"' in case_page
    assert "Back to the agent" in case_page
    assert 'href="/agent/adjudication"' in case_page

    again = _post(test_client, "/agent/adjudication", "agent.run.adjudication", {})
    assert again.status_code == 422, again.text
    assert again.json()["message"] == "Nothing is waiting"
    assert _runs(settings, "adjudication") == 1


def test_the_steward_screen_counts_unprepared_tasks_and_lists_the_press(client) -> None:
    """A prepared task leaves the count, and the press lists what it handled.

    The operator can open the screen and cannot press the batch button.  The
    Data Steward, who holds the run grant, posts the same action.  An empty
    queue is refused and records no run.
    """
    test_client, settings = client
    fresh = test_client.get("/agent/steward_assist")
    assert fresh.status_code == 200
    assert re.search(r"Waiting work \(\d+\)", fresh.text)
    assert 'data-testid="agent-run-all"' not in fresh.text

    assert test_client.post(
        "/api/intake/simulate", json={"scenario": "address-typo"}
    ).status_code == 200
    assert _post(
        test_client, "/agent/intake", "agent.toggle",
        {"agent_key": "intake", "mode": "awake"},
    ).status_code == 200
    assert _post(test_client, "/agent/intake", "agent.run.intake", {}).status_code == 200

    page = test_client.get("/agent/steward_assist").text
    count = re.search(r"Waiting work \((\d+)\)", page)
    assert count
    waiting = int(count.group(1))
    assert waiting > 0
    assert f'id="agent-waiting-heading">Waiting work ({waiting})' in page
    before = _runs(settings, "steward_assist")
    assert _post(
        test_client, "/agent/steward_assist", "agent.toggle",
        {"agent_key": "steward_assist", "mode": "awake"},
    ).status_code == 200
    assert test_client.post(
        "/api/session/select", json={"actor_id": "persona_data_steward"}
    ).status_code == 200
    first = _post(test_client, "/steward", "agent.run.steward_assist", {})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "accepted"
    assert "waiting task" in first.json()["message"]
    assert _runs(settings, "steward_assist") == before + 1

    assert test_client.post(
        "/api/session/select", json={"actor_id": "persona_agent_operator"}
    ).status_code == 200
    after = test_client.get("/agent/steward_assist").text
    shown = _shown(after)
    assert shown
    assert "by " in after
    assert 'data-testid="agent-last-run-summary"' in after
    summary = re.search(r'data-testid="agent-last-run-summary">(.*?)</p>', after, re.S)
    assert summary
    assert "task" in summary.group(1)
    for href, reference, outcome in shown:
        assert reference
        assert not reference.startswith("app_")
        assert outcome
        assert "from=/agent/steward_assist" in href
    remaining = re.search(r"Waiting work \((\d+)\)", after)
    assert remaining
    assert int(remaining.group(1)) < waiting

    if int(remaining.group(1)) == 0:
        assert test_client.post(
            "/api/session/select", json={"actor_id": "persona_data_steward"}
        ).status_code == 200
        second = _post(test_client, "/steward", "agent.run.steward_assist", {})
        assert second.status_code == 422, second.text
        assert second.json()["message"] == "Nothing is waiting"
        assert _runs(settings, "steward_assist") == before + 1
        assert _accepted(settings, "ui.agent.run.steward_assist") == 1

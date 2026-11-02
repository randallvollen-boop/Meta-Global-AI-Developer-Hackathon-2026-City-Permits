"""The slimmed agent pages: banners gone, controls still work and explain themselves."""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "acme_city" / "templates"

REMOVED_COPY = {
    "agents.html": ["Live Muse calls are off in this demo", "Process selected cases", "No run history filter"],
    "agent_screen.html": [
        "The agent proposes; a person decides",
        "A woken agent stays awake",
        "It never runs on a timer",
        "Each group waits for the group before it",
    ],
    "agent_runs.html": ["Every recorded attempt of the agents"],
    "agent_run_detail.html": [
        "Recorded attempt evidence",
        "Only a failed attempt can be retried",
    ],
    "agent_case.html": ["The operational picture of the case"],
}


def test_the_banners_and_explainers_are_gone() -> None:
    for name, phrases in REMOVED_COPY.items():
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        for phrase in phrases:
            assert phrase not in text, (name, phrase)


def test_the_sleep_notice_is_kept_verbatim() -> None:
    text = (TEMPLATES / "agent_screen.html").read_text(encoding="utf-8")
    assert "The agent is asleep, so the run buttons are off." in text
    assert re.search(r"disabled aria-describedby=\"agent-sleep-notice\"", text)


def test_the_extra_detail_sits_behind_more_details() -> None:
    screen = (TEMPLATES / "agent_screen.html").read_text(encoding="utf-8")
    more = screen.index('data-testid="agent-more-details"')
    for marker in ('data-testid="agent-kpis"', 'data-testid="agent-history"', 'data-testid="agent-graph"'):
        assert screen.index(marker) > more, marker
    detail = (TEMPLATES / "agent_run_detail.html").read_text(encoding="utf-8")
    assert detail.index('data-testid="agent-run-detail-provenance"') > detail.index("agent-run-detail-more")
    runs = (TEMPLATES / "agent_runs.html").read_text(encoding="utf-8")
    assert "run-more-filters" in runs and 'data-testid="agent-run-dot"' in runs


class _Forms(HTMLParser):
    """Collect every form: its action, hidden fields and the buttons inside it."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = dict(attrs)
        if tag == "form":
            self.forms.append({"action": a.get("action"), "fields": {}, "buttons": []})
        elif self.forms and tag == "input" and a.get("type") == "hidden":
            self.forms[-1]["fields"][a["name"]] = a.get("value", "")
        elif self.forms and tag == "button":
            self.forms[-1]["buttons"].append(a)


def _forms(client: TestClient, path: str, testid: str) -> list[dict]:
    parser = _Forms()
    parser.feed(client.get(path).text)
    return [
        f for f in parser.forms
        if any(b.get("data-testid") == testid for b in f["buttons"])
    ]


def _click(client: TestClient, path: str, testid: str, index: int = 0) -> dict:
    """Submit the form that holds the button, the way a click does."""
    form = _forms(client, path, testid)[index]
    button = next(b for b in form["buttons"] if b.get("data-testid") == testid)
    assert "disabled" not in button, testid
    response = client.post(
        form["action"], data=form["fields"],
        headers={"Accept": "application/json"}, follow_redirects=False,
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'agent-pages.db'}",
            "ACME_SECRET_KEY": "agent-pages-test-secret",
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
        yield test_client


def _simulate(client: TestClient, scenario: str = "deck-high") -> None:
    assert client.post("/api/intake/simulate", json={"scenario": scenario}).status_code == 200


def test_wake_and_sleep_buttons_work_and_the_notice_follows(client: TestClient) -> None:
    page = client.get("/agent/intake").text
    assert 'data-testid="agent-sleep-notice"' in page
    assert "The agent is asleep, so the run buttons are off." in page
    assert _click(client, "/agent/intake", "agent-toggle")["status"] == "accepted"
    awake = client.get("/agent/intake").text
    assert 'data-testid="agent-sleep-notice"' not in awake
    assert "Put agent to sleep" in awake
    assert _click(client, "/agent/intake", "agent-toggle")["status"] == "accepted"
    assert 'data-testid="agent-sleep-notice"' in client.get("/agent/intake").text


def test_run_buttons_are_disabled_while_asleep_and_point_at_the_notice(client: TestClient) -> None:
    _simulate(client)
    page = client.get("/agent/intake").text
    for testid in ("agent-run-all", "agent-run-one"):
        tag = re.search(rf'<button[^>]*data-testid="{testid}"[^>]*>', page)
        assert tag and "disabled" in tag.group(0)
        assert 'aria-describedby="agent-sleep-notice"' in tag.group(0)


def test_process_next_and_process_one_run_the_agent(client: TestClient) -> None:
    _simulate(client)
    _click(client, "/agent/intake", "agent-toggle")
    one = _click(client, "/agent/intake", "agent-run-one")
    assert one["status"] == "accepted"
    assert 'data-testid="agent-history-row"' in client.get("/agent/intake").text
    # A repeated deck-high reference is the case that was just processed.
    # A different arrival is what the batch button then runs.
    _simulate(client, "address-unknown")
    assert _click(client, "/agent/intake", "agent-run-all")["status"] == "accepted"


def test_the_run_history_marks_each_row_with_a_state_dot(client: TestClient) -> None:
    _simulate(client)
    _click(client, "/agent/intake", "agent-toggle")
    _click(client, "/agent/intake", "agent-run-one")
    page = client.get("/agents/runs").text
    assert page.count('data-testid="agent-run-row"') == page.count('data-testid="agent-run-dot"') >= 1
    assert 'data-testid="agent-run-detail-link"' in page


def test_a_completed_run_shows_the_router_line_and_no_retry(client: TestClient) -> None:
    _simulate(client)
    _click(client, "/agent/intake", "agent-toggle")
    _click(client, "/agent/intake", "agent-run-one")
    link = re.search(r'href="(/agents/runs/[^"]+)" data-testid="agent-run-detail-link"', client.get("/agents/runs").text)
    assert link
    detail = client.get(link.group(1)).text
    assert "Processing steps" in detail
    assert "Ready for review in the Building area" in detail
    assert "agent-run-detail-retry" not in detail

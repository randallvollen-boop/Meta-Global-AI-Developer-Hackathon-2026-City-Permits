"""The focused case of the Data Steward.

The case shows what a person needs to decide: the problem, why it matters,
what is compared, what the action does and what happened.  The evidence of
the decision, the tables and the forms of Muse sit behind a disclosure, and
the case ends with one line that says what it does not decide.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02, PER-04

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.fixtures.steward_demo import seed_cedarline  # noqa: E402
from acme_city.persistence.models import registry  # noqa: E402
from acme_city.persistence.session import SessionFactory, transaction  # noqa: E402
from acme_city.ui.router import router as ui_router  # noqa: E402

#: The personas of the test.
STEWARD = "persona_data_steward"
OPERATOR = "persona_agent_operator"
ADMIN = "persona_city_administrator"

#: The source record the demonstration compares with the master records.
RECORD = "PER-AP-0003"


def _client(settings) -> TestClient:
    app = create_app(settings)
    app.include_router(ui_router)
    return TestClient(app)


@pytest.fixture()
def client(tmp_path) -> TestClient:
    """A demonstration database whose queue holds the Cedarline work."""
    settings = build_environment(tmp_path, synthetic=False, name="steward-case.db")
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            seed_cedarline(session)
    finally:
        factory.dispose()
    with _client(settings) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def csrf(client: TestClient, path: str) -> str:
    """Return the CSRF token of the session from a rendered page."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def post(client: TestClient, action: str, fields: dict[str, str], next_path: str):
    """Post one action of the interface and return the answer of the server."""
    return client.post(
        f"/ui/actions/{action}",
        data={"csrf_token": csrf(client, next_path), "next": next_path, **fields},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


def wake_the_assistant(client: TestClient) -> None:
    """Wake the steward assistant, the way the Agent Operator does."""
    choose(client, OPERATOR)
    response = post(
        client,
        "agent.toggle",
        {"agent_key": "steward_assist", "mode": "awake"},
        "/agent/steward_assist",
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted", response.text
    choose(client, STEWARD)


def prepare(client: TestClient) -> None:
    """Ask the assistant to prepare the work of the queue."""
    response = post(client, "steward.assist.prepare", {}, "/steward")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted", response.text


def case_path(client: TestClient, record: str = RECORD) -> str:
    """Return the address of the focused case of one source record."""
    queue = client.get("/steward?filter=needs_review").text
    for href in re.findall(r'href="(/steward/issues/link/[^"]+)"', queue):
        if record in client.get(href).text.split("<h1", 1)[1][:400]:
            return href
    raise AssertionError(f"no task for {record}")


def parcel_case_path(client: TestClient) -> str:
    """Return the address of a parcel case, the way the demonstration makes one."""
    choose(client, ADMIN)
    simulated = client.post("/api/intake/simulate", json={"scenario": "address-typo"})
    assert simulated.status_code == 200, simulated.text
    application_id = simulated.json()["results"][0]["application_id"]
    choose(client, OPERATOR)
    post(
        client,
        "agent.toggle",
        {"agent_key": "intake", "mode": "awake"},
        "/agent/intake",
    )
    post(client, "agent.run.intake", {}, "/agent/intake")
    choose(client, STEWARD)
    return f"/steward/issues/parcel/{application_id}"


def disclosure(body: str, testid: str) -> str:
    """Return the markup of one disclosure of a rendered page.

    The disclosure is read with its own nesting, so a disclosure inside it
    does not end the search.
    """
    marker = f'data-testid="{testid}"'
    start = body.find(marker)
    assert start != -1, testid
    opening = body.rfind("<details", 0, start)
    assert opening != -1, testid
    depth = 0
    position = opening
    pattern = re.compile(r"<(/?)details\b[^>]*>")
    while True:
        match = pattern.search(body, position)
        assert match is not None, testid
        depth += -1 if match.group(1) else 1
        position = match.end()
        if depth == 0:
            return body[opening : match.end()]


# ------------------------------------------------------------ the assistant


def test_the_case_shows_the_pill_the_reason_and_the_accept_button(
    client: TestClient,
) -> None:
    """The panel of the assistant leads with what the steward decides on."""
    choose(client, STEWARD)
    wake_the_assistant(client)
    prepare(client)
    body = client.get(case_path(client)).text
    panel = re.search(r'data-testid="assistant-panel">(.*?)</section>', body, re.S)
    assert panel is not None
    assert 'data-testid="assistant-pill"' in panel.group(1)
    assert 'data-testid="assistant-reason"' in panel.group(1)
    assert 'data-testid="assistant-accept"' in panel.group(1)
    assert 'data-testid="assistant-reason-field"' in panel.group(1)
    # The evidence and the forms of Muse sit behind the disclosure.
    more = disclosure(body, "assistant-more")
    assert 'data-testid="assistant-evidence"' in more
    assert 'data-testid="assistant-explain"' in more
    assert 'data-testid="assistant-clear"' in more
    assert 'data-testid="assistant-evidence"' not in panel.group(1).split(
        'data-testid="assistant-more"'
    )[0]


def test_the_recommendation_is_accepted_with_one_action(client: TestClient) -> None:
    """The steward accepts the recommendation, and the link is approved."""
    choose(client, STEWARD)
    wake_the_assistant(client)
    prepare(client)
    path = case_path(client)
    body = client.get(path).text
    identifier = re.search(r'name="recommendation_id" value="([^"]+)"', body)
    assert identifier is not None, body[:400]
    response = post(
        client,
        "steward.assist.accept",
        {"recommendation_id": identifier.group(1), "next": path},
        path,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "accepted", payload
    assert "accepted" in str(payload.get("message", "")).lower()


# -------------------------------------------------------------- the evidence


def test_the_evidence_of_a_link_case_is_reachable_behind_the_disclosure(
    client: TestClient,
) -> None:
    """The agreements and the conflicts of a link case are still on the page."""
    choose(client, STEWARD)
    # The business identity of Cedarline Coffee Works has both: it agrees on
    # the name and it conflicts on the licence number and the unit.
    body = client.get(case_path(client, "ERP-BL-00413")).text
    details = disclosure(body, "case-q4-details")
    assert 'data-testid="agreement"' in details
    assert 'data-testid="conflict"' in details
    assert 'data-testid="evidence-block"' in details
    assert 'data-testid="provenance"' in details
    # The disclosure is closed until the steward asks for it.
    assert " open" not in details.split(">")[0]


def test_the_parcel_map_is_present_for_a_parcel_case(client: TestClient) -> None:
    """The parcel case still carries the map of the parcel."""
    choose(client, STEWARD)
    path = parcel_case_path(client)
    body = client.get(path).text
    assert body.count('data-question="') == 6
    details = disclosure(body, "case-q4-details")
    assert 'class="prop-map"' in details
    assert "Approve parcel link" in body


def test_the_chooser_shows_the_record_that_was_chosen(client: TestClient) -> None:
    """The button of the chooser shows the record the steward picked."""
    choose(client, STEWARD)
    path = case_path(client, "ERP-BL-00413")
    body = client.get(path).text
    chooser = body.split('data-testid="candidate-chooser"')[1].split("</form>")[0]
    options = re.findall(r'<option value="([^"]+)"', chooser)
    assert options, chooser
    chosen = options[-1]
    url = f"{path}&candidate={chosen}" if "?" in path else f"{path}?candidate={chosen}"
    page = client.get(url).text
    assert f'data-entity="{chosen}" data-selected="true"' in page


def test_the_case_ends_with_one_line(client: TestClient) -> None:
    """Every case ends with the same one line about the permit."""
    choose(client, STEWARD)
    body = client.get(case_path(client)).text
    note = re.search(r'data-testid="separate-note">(.*?)</p>', body, re.S)
    assert note is not None, body[:400]
    assert note.group(1).strip() == "Does not decide the permit."


def test_the_case_carries_no_disclaimer(client: TestClient) -> None:
    """The page states no disclaimer about the locator, the owner or the policy."""
    choose(client, STEWARD)
    body = client.get(case_path(client)).text
    assert "The Address locator is a deterministic simulation" not in body
    assert "(synthetic)" not in body
    assert "The policy of the Data Steward authorized it" not in body
    assert "Choosing a record only changes what the page shows" not in body

"""The Data issues queue of the Data Steward and the batch it may accept.

The queue shows what a person needs to decide: the task, the record and the
one action of the row.  The other facts of a task, the search and the work
from a source record sit behind a disclosure.  The agreement figure is one
line, the batch says what it does in one line, and the steward reads the list
of a batch before anything is accepted.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02, PER-04

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.fixtures.steward_demo import seed_cedarline  # noqa: E402
from acme_city.persistence.session import SessionFactory, transaction  # noqa: E402
from acme_city.ui.router import router as ui_router  # noqa: E402

#: The personas of the test.
STEWARD = "persona_data_steward"
OPERATOR = "persona_agent_operator"


def _client(settings) -> TestClient:
    app = create_app(settings)
    app.include_router(ui_router)
    return TestClient(app)


@pytest.fixture()
def client(tmp_path) -> TestClient:
    """A demonstration database whose queue holds the Cedarline work."""
    settings = build_environment(tmp_path, synthetic=False, name="steward-review.db")
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


def post_many(
    client: TestClient, action: str, names: list[str], next_path: str, digest: str
):
    """Post one field several times, the way the preview form does."""
    return client.post(
        f"/ui/actions/{action}",
        data={
            "csrf_token": csrf(client, next_path),
            "next": next_path,
            "preview_item": list(names),
            "preview_digest": digest,
        },
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


def head_texts(body: str, table: str) -> list[str]:
    """Return the column heads of one table of a rendered page."""
    part = body.split(f'data-testid="{table}"')[1].split("</thead>")[0]
    return [
        re.sub(r"<[^>]+>", "", head).strip()
        for head in re.findall(r'<th scope="col">(.*?)</th>', part, re.S)
    ]


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


# --------------------------------------------------------------- the queue


def test_the_queue_shows_the_task_the_record_and_the_action(client: TestClient) -> None:
    """The table of the queue holds three columns, and the rest is disclosed."""
    choose(client, STEWARD)
    body = client.get("/steward").text
    assert head_texts(body, "issue-table") == ["Task", "Record", "Action"]
    assert head_texts(body, "issue-details-table")[:4] == [
        "Task",
        "Affected application",
        "Source",
        "Status",
    ]
    # The other facts of a task sit behind the disclosure, closed.
    details = disclosure(body, "queue-details")
    assert details.startswith("<details")
    assert " open" not in details.split(">")[0]
    assert 'data-testid="issue-status"' in details


def test_the_search_and_the_source_record_work_sit_behind_a_disclosure(
    client: TestClient,
) -> None:
    """The search and the work from a source record are not in the default view."""
    choose(client, STEWARD)
    body = client.get("/steward").text
    filters = disclosure(body, "queue-filters")
    assert 'data-testid="queue-search"' in filters
    assert " open" not in filters.split(">")[0]
    source = disclosure(body, "work-by-source-record")
    assert " open" not in source.split(">")[0]
    assert 'data-testid="action"' in source


def test_the_agreement_figure_is_one_line(client: TestClient) -> None:
    """The figure of the agreement is a single line, with the counts behind it."""
    choose(client, STEWARD)
    body = client.get("/steward").text
    panel = re.search(r'data-testid="agreement-panel">(.*?)</section>', body, re.S)
    assert panel is not None
    assert panel.group(1).count("<p") == 1, panel.group(1)
    assert 'data-testid="agreement-empty"' in panel.group(1)

    wake_the_assistant(client)
    prepare(client)
    body = client.get("/steward").text
    panel = re.search(r'data-testid="agreement-panel">(.*?)</section>', body, re.S)
    assert panel is not None
    assert panel.group(1).count("<p") == 1, panel.group(1)
    assert 'data-testid="agreement-figure"' in panel.group(1)
    assert 'data-testid="agreement-share"' in panel.group(1)
    counts = re.search(r'data-testid="agreement-counts">\s*([^<]+)<', panel.group(1))
    assert counts is not None, panel.group(1)
    assert "accepted unchanged of" in counts.group(1)


def test_the_queue_carries_no_explainer_of_the_batch(client: TestClient) -> None:
    """The button of the batch names the count; no paragraph explains it again."""
    choose(client, STEWARD)
    wake_the_assistant(client)
    prepare(client)
    body = client.get("/steward").text
    assert "Accept all high-confidence (3)" in body
    assert "the assistant is sure of" not in body
    assert "You confirm the list before anything is accepted" not in body


def test_the_disabled_accept_all_button_says_why(client: TestClient) -> None:
    """A batch with nothing in it is a disabled button and a reason beside it."""
    choose(client, STEWARD)
    body = client.get("/steward").text
    button = re.search(
        r'<(?:button|a)[^>]*data-testid="assistant-batch-preview"[^>]*>', body
    )
    assert button is not None, body[:400]
    assert "disabled" in button.group(0)
    assert 'aria-describedby="assistant-batch-note"' in button.group(0)
    note = re.search(r'data-testid="assistant-batch-note">(.*?)</p>', body, re.S)
    assert note is not None, body[:400]
    assert "sure enough" in note.group(1)


# --------------------------------------------------------------- the batch


def test_the_walkthrough_accepts_the_batch_with_the_list_first(
    client: TestClient,
) -> None:
    """Step 5 of the walkthrough: prepare, read the list, confirm the list."""
    choose(client, STEWARD)
    wake_the_assistant(client)
    prepare(client)
    body = client.get("/steward").text
    assert "Accept all high-confidence (3)" in body
    button = re.search(
        r'<a[^>]*data-testid="assistant-batch-preview"[^>]*>', body
    )
    assert button is not None, body[:400]
    assert 'href="/steward/batch"' in button.group(0)

    preview = client.get("/steward/batch").text
    assert preview.count('data-testid="batch-item"') == 3
    assert 'data-testid="assistant-batch-confirm"' in preview

    items = re.findall(r'name="preview_item" value="([^"]+)"', preview)
    digest = re.search(r'name="preview_digest" value="([^"]+)"', preview)
    assert digest is not None, preview[:400]
    response = post_many(
        client, "steward.assist.batch_accept", items, "/steward/batch", digest.group(1)
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "accepted", payload
    assert "Accepted 3 of 3" in payload["message"]


def test_the_preview_keeps_the_fields_that_skip_a_changed_item(
    client: TestClient,
) -> None:
    """The list carries the version of every item and the proof of the list."""
    choose(client, STEWARD)
    wake_the_assistant(client)
    prepare(client)
    preview = client.get("/steward/batch").text
    items = re.findall(r'name="preview_item" value="([^"]+)"', preview)
    assert len(items) == 3
    assert all(":" in item for item in items)
    assert all(item.rsplit(":", 1)[1].isdigit() for item in items)
    digest = re.search(r'name="preview_digest" value="([^"]+)"', preview)
    assert digest is not None, preview[:400]
    assert digest.group(1)


def test_the_batch_page_states_the_rule_in_one_line(client: TestClient) -> None:
    """The page of the batch says what it does in one line, and nothing more."""
    choose(client, STEWARD)
    wake_the_assistant(client)
    prepare(client)
    preview = client.get("/steward/batch").text
    note = re.search(r'data-testid="batch-note">(.*?)</p>', preview, re.S)
    assert note is not None, preview[:400]
    assert note.group(1).strip() == "Changed items are skipped and named."
    assert "Nothing is accepted until you confirm this list." in preview
    # The long paragraph of the batch is gone.
    assert "the assistant is sure of every one of them" not in preview
    assert "An item that changed since this list was made is" not in preview

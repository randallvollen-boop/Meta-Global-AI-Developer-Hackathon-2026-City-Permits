"""The what-if screens with the live model off: what they say and what they offer.

Live Muse calls are off on the hosted demonstration, so the recorded answers
are the only answers there are.  The screen has to say so, and it has to offer
the recorded questions as they are instead of asking for a question it cannot
answer.  A recorded answer that was refused stays refused, and the page never
calls a provider.
"""
# REQUIRES: UX-01, UX-03, PER-04

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.ui.router import router as ui_router

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import build_settings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN = "persona_city_administrator"

#: The recorded questions of the demonstration set, exactly as they are stored.
RECORDED_QUESTIONS = (
    "What if the side and rear yard fence limit were 7 ft?",
    "What if no permit were required for a shed?",
)


@pytest.fixture()
def client(tmp_path: Path):
    """Return a client with its own seeded database."""
    settings = build_settings(tmp_path, "policy-offline.db")
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        test_client.post("/api/session/select", json={"actor_id": ADMIN})
        yield test_client


def _list(client: TestClient) -> str:
    response = client.get("/policy/scenarios")
    assert response.status_code == 200
    return response.text


# --------------------------------------------------------------- the list


def test_the_list_says_that_the_live_calls_are_off(client: TestClient) -> None:
    body = _list(client)
    assert "Live Muse calls are off" in body
    assert "recorded demonstration fixtures only" in body


def test_the_recorded_questions_are_offered_as_choices(client: TestClient) -> None:
    body = _list(client)
    select = re.search(r'<select[^>]*data-testid="policy-question-choice".*?</select>', body, re.S)
    assert select, "the recorded questions are offered as a choice"
    options = re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', select.group(0))
    values = [value for value, _label in options]
    assert values == list(RECORDED_QUESTIONS), values
    labels = [label for _value, label in options]
    assert labels[0] == RECORDED_QUESTIONS[0], "the recorded question is offered as it is"
    assert labels[1] == "Example of an unsupported request"


def test_the_page_does_not_promise_an_answer_to_any_question(client: TestClient) -> None:
    """A free question is refused, and the screen says so before it is asked."""
    body = _list(client)
    assert "Only the recorded example above can be answered locally" in body
    assert "Another question is refused" in body


def test_the_saved_work_comes_first_and_the_creation_comes_first_when_there_is_none(
    client: TestClient,
) -> None:
    empty = _list(client)
    assert empty.index('data-testid="policy-new"') < empty.index('data-testid="policy-list"')

    token = re.search(r'name="csrf_token" value="([^"]+)"', empty).group(1)
    response = client.post(
        "/policy/scenarios",
        data={"csrf_token": token, "expected_version": "0",
              "suggestion": "fence_height_7ft", "name": "A saved what-if"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    saved = _list(client)
    assert saved.index('data-testid="policy-list"') < saved.index('data-testid="policy-new"')
    assert "A saved what-if" in saved


def test_the_created_moment_is_named_and_shown_as_a_date(client: TestClient) -> None:
    body = _list(client)
    assert "<th scope=\"col\">Created</th>" in body
    assert "Saved</th>" not in body
    # The moment is a date, not a technical timestamp.
    assert not re.search(r"data-testid=\"policy-row\".*?\d{4}-\d{2}-\d{2}T", body, re.S)


def test_no_provider_is_called_for_the_list(client: TestClient, monkeypatch) -> None:
    def refuse(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("the list must not call a provider")

    monkeypatch.setattr("acme_city.muse.client.MuseClient.create_response", refuse)
    assert _list(client)

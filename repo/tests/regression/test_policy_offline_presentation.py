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


# -------------------------------------------------------- the proposal review


def _propose(client: TestClient, question: str) -> str:
    """Ask for a proposal and return the page that shows it."""
    page = client.get("/policy/scenarios")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    response = client.post(
        "/policy/propose",
        data={"csrf_token": token, "expected_version": "0", "question": question},
        follow_redirects=True,
    )
    assert response.status_code == 200
    return response.text


def test_a_checked_proposal_says_that_nothing_is_saved_yet(client: TestClient) -> None:
    body = _propose(client, RECORDED_QUESTIONS[0])
    assert "Checked proposal. No what-if has been saved." in body
    assert "This saves a what-if. It does not run it, and it changes no published rule." in body
    assert 'data-testid="policy-proposal-save"' in body


def test_a_checked_proposal_names_the_change_the_rule_and_its_source(client: TestClient) -> None:
    body = _propose(client, RECORDED_QUESTIONS[0])
    assert "Change ACME Code §14-306" in body
    assert "limit 6 to 7" in body
    assert "Rule limit" in body
    assert "Why the recorded answer says so" in body
    assert "Recorded replay" in body


def test_a_refused_proposal_offers_a_way_out_and_no_save(client: TestClient) -> None:
    body = _propose(client, RECORDED_QUESTIONS[1])
    assert "These changes could not be used" in body
    assert "Choose an example" in body
    assert "Build a what-if" in body
    assert 'data-testid="policy-proposal-save"' not in body
    assert "not supported in this release" in body.lower()


def test_a_refused_proposal_keeps_the_question_it_was_given(client: TestClient) -> None:
    """A refused question is never answered with a different proposal."""
    question = "What if every fee were free on Tuesdays?"
    body = _propose(client, question)
    assert question in body
    assert "no recorded demonstration answer matches this request" in body
    assert "Nothing was saved." in body


# ------------------------------------------------------------- the editor


def _editor(client: TestClient) -> str:
    """Save a what-if from the first example and return its editor page."""
    page = client.get("/policy/scenarios")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    response = client.post(
        "/policy/scenarios",
        data={"csrf_token": token, "expected_version": "0",
              "suggestion": "fence_height_7ft", "name": "An editor probe"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    editor = client.get(response.headers["location"].split("?")[0])
    assert editor.status_code == 200
    return editor.text


def test_the_editor_leads_with_the_changes_and_the_run_settings(client: TestClient) -> None:
    body = _editor(client)
    assert body.index('id="changes-heading"') < body.index('id="run-comparison"')
    assert body.index('id="run-comparison"') < body.index('id="add-a-change"')
    assert "Your changes" in body
    assert "Run comparison" in body
    assert 'href="#run-comparison"' in body
    assert 'data-testid="policy-run-anchor"' in body
    assert 'data-testid="policy-add-anchor"' in body


def test_the_editor_keeps_the_seven_change_forms(client: TestClient) -> None:
    body = _editor(client)
    for kind in ("threshold", "retirement", "requirement", "category",
                 "discretionary", "target", "fee"):
        assert f'data-testid="policy-add-{kind}"' in body, kind
        assert f'data-testid="policy-add-{kind}-submit"' in body, kind
    assert 'data-testid="policy-unsupported-kinds"' in body


def test_the_technical_values_are_explained_without_changing_them(client: TestClient) -> None:
    body = _editor(client)
    assert "Fence height, side and rear yard (ACME Code §14-306)" in body
    assert "at most 6" in body
    assert '<option value="max">At most</option>' in body
    assert "Review with plans" in body


def test_the_revisions_table_names_the_change_type(client: TestClient) -> None:
    body = _editor(client)
    assert "Change type" in body
    assert "Made by" not in body


def test_the_deletion_sits_in_its_own_disclosure(client: TestClient) -> None:
    body = _editor(client)
    assert 'id="delete-whatif"' in body
    assert "<summary>Delete this what-if</summary>" in body


def test_the_fee_change_keeps_cents_as_cents(client: TestClient) -> None:
    body = _editor(client)
    assert "New fixed charge in cents" in body
    assert "100 cents equals 1 dollar" in body
    assert 'name="fixed_review_charge_cents"' in body

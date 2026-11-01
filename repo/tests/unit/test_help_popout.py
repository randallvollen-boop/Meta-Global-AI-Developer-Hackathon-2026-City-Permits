"""The assistant panel of the applicant.

The assistant opens in a panel over the page: the page stays where it is,
the fields and the files the applicant typed stay exactly as they were, and
the panel holds the same assistant as the page of its own - the same
endpoints, the same conversation, the same citations.

Without a script the launcher is an ordinary link and the panel opens on a
page of its own.  Nothing opens a window of its own any more.
"""
# REQUIRES: UX-02, UX-03, PER-04, PER-05, SEC-03

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

from acme_city.applicant_help import views as help_views  # noqa: E402
from acme_city.app import create_app  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402
from acme_city.persistence.models import help as help_models  # noqa: E402
from acme_city.persistence.session import SessionFactory  # noqa: E402

#: The panel page, with the fragment the page slides up over.
PANEL_PATH = "/apply/help/panel"
FRAGMENT_PATH = "/apply/help/panel?fragment=1"

#: The pages of the applicant that carry the launcher.
APPLICANT_PAGES = ("/apply", "/apply/track", "/apply/deck_fence")

#: The question the applicant asks in the panel.
QUESTION = "Do I need a permit for a 6 ft fence?"

#: The script of the panel.
HELP_SCRIPT = ROOT / "src" / "acme_city" / "static" / "help.js"


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    """A demonstration database with the City website seeded."""
    return build_environment(
        tmp_path_factory.mktemp("help-panel"), synthetic=False, name="panel.db"
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    """The City website as it runs locally."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def token(client: TestClient, path: str = PANEL_PATH) -> str:
    """Return the CSRF token of a page of the applicant."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def ask(client: TestClient, question: str, **extra) -> str:
    """Ask a question and return the location the answer is served from."""
    data = {
        "csrf_token": token(client),
        "question": question,
        "conversation_version": extra.pop("conversation_version", "0"),
        "conversation_id": extra.pop("conversation_id", ""),
        "placement": extra.pop("placement", "form"),
        **extra,
    }
    response = client.post("/apply/help", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    return response.headers["location"]


# ------------------------------------------------------------- the launcher


@pytest.mark.parametrize("path", APPLICANT_PAGES)
def test_every_applicant_page_carries_the_launcher_of_the_panel(
    client: TestClient, path: str
) -> None:
    """Every applicant page opens the assistant over the page."""
    choose(client, "persona_applicant")
    body = client.get(path).text
    launcher = re.search(
        r'<a class="city-help-link" href="([^"]+)"[^>]*data-testid="help-ask"',
        body,
    )
    assert launcher is not None, path
    assert launcher.group(1).startswith(PANEL_PATH), path
    # The launcher is a plain link, so it works without a script.
    assert "target=" not in launcher.group(0), path
    assert "data-help-panel-open" in launcher.group(0), path
    # The chat button at the corner of the page opens the same panel.
    button = re.search(
        r'<a class="help-chat-launcher" href="([^"]+)"[^>]*data-testid="help-chat-launcher"',
        body,
    )
    assert button is not None, path
    assert button.group(1).startswith(PANEL_PATH), path
    # The panel of the page is there, and it is closed.
    assert 'id="help-panel-host"' in body, path
    assert 'data-testid="help-panel-sheet"' in body, path
    assert re.search(r'id="help-panel-host"[^>]*hidden', body) is not None, path


def test_a_visitor_of_the_city_website_is_offered_no_launcher(
    client: TestClient,
) -> None:
    """The panel is the applicant's, not the visitor's."""
    body = client.get("/city/").text
    assert 'data-testid="help-chat-launcher"' not in body
    assert 'data-testid="help-ask"' not in body
    assert 'href="/help" data-testid="help-link"' in body


def test_a_staff_persona_is_offered_no_launcher(client: TestClient) -> None:
    """The staff screens keep their own frame."""
    choose(client, "persona_data_steward")
    body = client.get("/queue").text
    assert 'data-testid="help-chat-launcher"' not in body
    assert 'data-testid="help-ask"' not in body


def test_the_applicant_is_offered_the_panel_on_the_city_pages(
    client: TestClient,
) -> None:
    """The City website carries the panel for the applicant too."""
    choose(client, "persona_applicant")
    body = client.get("/city/").text
    assert 'data-testid="help-chat-launcher"' in body
    assert 'data-testid="help-panel-sheet"' in body


def test_nothing_opens_a_window_of_its_own(client: TestClient) -> None:
    """The assistant does not open a second window."""
    choose(client, "persona_applicant")
    body = client.get("/apply").text
    assert "window.open" not in body
    script = HELP_SCRIPT.read_text(encoding="utf-8")
    assert "window.open" not in script
    assert "acme-permit-help" not in script


def test_the_popout_placement_is_gone() -> None:
    """The window had a placement of its own; the panel does not."""
    assert "popout" not in help_views.PLACEMENTS
    assert "popout" not in help_views.PANEL_PLACEMENTS
    assert "popout" not in help_models.HELP_PLACEMENTS


# ---------------------------------------------------------------- the panel


def test_the_panel_page_carries_the_panel_and_nothing_else(
    client: TestClient,
) -> None:
    """The page of the panel is the panel: no page heading, no back buttons."""
    choose(client, "persona_applicant")
    body = client.get(PANEL_PATH).text
    assert 'data-testid="help-panel"' in body
    assert 'data-placement="form"' in body
    assert "Help with your permit</h1>" not in body
    assert "Back to the permit list" not in body
    assert "Back to your application form" not in body
    # The application form is never part of the panel.
    assert 'data-testid="application-form"' not in body
    assert 'name="height_ft"' not in body
    assert 'data-testid="help-escalate-form"' not in body


def test_the_fragment_is_the_panel_without_the_frame_around_it(
    client: TestClient,
) -> None:
    """The panel that slides up over the page is the same panel."""
    choose(client, "persona_applicant")
    response = client.get(FRAGMENT_PATH)
    assert response.status_code == 200, response.text
    body = response.text
    assert 'data-testid="help-panel"' in body
    # The frame of the page is not in the fragment.
    assert "<html" not in body
    assert "city-header" not in body
    assert "city-footer" not in body
    # The panel of the page answers in place; the target is the fallback
    # that keeps the page of the applicant intact when the script is not
    # there.
    form = re.search(r'<form[^>]*data-testid="help-form".*?>', body, re.S)
    assert form is not None
    assert 'target="_blank"' in form.group(0)


def test_the_fragment_carries_the_placement_of_the_page(
    client: TestClient,
) -> None:
    """The panel of the tracker knows where it was opened from."""
    choose(client, "persona_applicant")
    body = client.get(f"{PANEL_PATH}?fragment=1&placement=track").text
    assert 'data-placement="track"' in body


def test_the_panel_shows_at_most_three_questions(client: TestClient) -> None:
    """Three questions are offered; the rest sit behind a disclosure."""
    choose(client, "persona_applicant")
    body = client.get(PANEL_PATH).text
    shown = re.search(
        r'<ul class="help-suggestions"[^>]*data-testid="help-suggestions">(.*?)</ul>',
        body,
        re.S,
    )
    assert shown is not None
    assert shown.group(0).count('data-testid="help-suggestion"') == 3
    rest = re.search(
        r'<details class="detail-more" data-testid="help-more-questions".*?</details>',
        body,
        re.S,
    )
    assert rest is not None
    assert rest.group(0).count('data-testid="help-suggestion"') >= 1


def test_a_question_answers_in_the_panel(client: TestClient) -> None:
    """The turn of a question asked in the panel stays in the panel."""
    choose(client, "persona_applicant")
    location = ask(client, QUESTION)
    assert location.startswith(PANEL_PATH), location
    body = client.get(location).text
    assert 'data-testid="help-turn"' in body
    assert "ACME Code §14-306" in body


def test_the_conversation_carries_over_into_the_panel(
    client: TestClient,
) -> None:
    """The panel of the page shows the conversation the applicant already had."""
    choose(client, "persona_applicant")
    location = ask(client, QUESTION)
    conversation = re.search(r"conversation=([^&]+)", location).group(1)
    body = client.get(f"{PANEL_PATH}?fragment=1&conversation={conversation}").text
    assert 'data-testid="help-turn"' in body
    assert QUESTION in body


def test_the_conversation_of_another_applicant_is_not_found(
    client: TestClient,
) -> None:
    """The panel shows the conversation of its own applicant only."""
    choose(client, "persona_applicant")
    location = ask(client, QUESTION)
    conversation = re.search(r"conversation=([^&]+)", location).group(1)
    choose(client, "persona_data_steward")
    assert client.get(f"{PANEL_PATH}?conversation={conversation}").status_code in {
        403,
        404,
    }
    assert (
        client.get(f"{PANEL_PATH}?fragment=1&conversation={conversation}").status_code
        in {403, 404}
    )


def test_a_request_from_the_panel_reaches_the_case_it_is_about(
    client: TestClient, settings: Settings
) -> None:
    """The contact page continues the conversation of the panel."""
    choose(client, "persona_applicant")
    location = ask(client, QUESTION, application_id="app_d05")
    conversation = re.search(r"conversation=([^&]+)", location).group(1)

    contact = client.get(f"/city/contact?conversation={conversation}").text
    assert f'name="conversation_id" value="{conversation}"' in contact
    # The question of the panel is the one the box starts with.
    assert QUESTION in contact

    response = client.post(
        "/apply/help/escalate",
        data={
            "csrf_token": token(client, "/city/contact"),
            "placement": "contact",
            "conversation_id": conversation,
            "conversation_version": "1",
            "question": QUESTION,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/city/contact#ask"

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            request = session.execute(
                select(help_models.HelpRequest)
            ).scalars().one()
            assert request.conversation_id == conversation
            # The request is about the case the panel was about.
            assert request.application_id == "app_d05"
    finally:
        factory.dispose()


def test_the_rate_limit_of_the_panel_is_the_one_of_the_page(
    client: TestClient,
) -> None:
    """The panel asks no more questions than the page did."""
    choose(client, "persona_applicant")
    for number in range(12):
        response = client.post(
            "/apply/help",
            data={
                "csrf_token": token(client),
                "question": f"question number {number}",
                "conversation_version": "0",
                "conversation_id": "",
                "placement": "form",
            },
            follow_redirects=False,
        )
        if response.status_code != 303:
            assert response.status_code == 422, response.text
            assert "asked enough questions" in response.text
            return
    pytest.fail("the rate limit of the panel was never reached")

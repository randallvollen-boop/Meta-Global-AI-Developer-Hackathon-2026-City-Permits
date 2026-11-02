"""The staff frame: the footer line, the banner and the panel of the last action.

Every staff screen shares one frame.  It shows what a person needs to decide
and nothing else: the navigation, the acting persona and, after an action,
one sentence about what changed.  The internal build label is gone, the
demonstration disclosure is one line in the footer, and the result of the last
action sits in a panel that opens from the bell in the header.  The detail
list of that result sits behind a disclosure, and a hidden region announces
every result to a screen reader.
"""
# REQUIRES: UX-01, UX-02

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
from acme_city.ui.router import router as ui_router  # noqa: E402

REVIEWER = "persona_permit_reviewer"
ADMIN = "persona_city_administrator"

#: The staff screens that used to carry the empty "Last action" box.
STAFF_ROUTES: tuple[tuple[str, str], ...] = (
    (REVIEWER, "/queue"),
    (REVIEWER, "/queue/review"),
    (REVIEWER, "/permits/app_synth_001"),
    (ADMIN, "/map"),
    (ADMIN, "/overview"),
    (ADMIN, "/lifecycle"),
    (ADMIN, "/reconciliation"),
)

#: The one line the footer carries.
FOOTER_LINE = "Fictional City of Acme demonstration. Synthetic records only."


def _client(settings) -> TestClient:
    app = create_app(settings)
    app.include_router(ui_router)
    return TestClient(app)


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    """A demonstration database nobody has acted in yet."""
    settings = build_environment(
        tmp_path_factory.mktemp("chrome"), synthetic=False, name="chrome.db"
    )
    with _client(settings) as test_client:
        yield test_client


@pytest.fixture()
def acted_client(tmp_path) -> TestClient:
    """A database of its own, so the action of a test leaves no trace."""
    settings = build_environment(tmp_path, synthetic=False, name="acted.db")
    with _client(settings) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def region_of(body: str) -> str:
    """Return the panel of the last action of a rendered page."""
    match = re.search(r'<aside id="ui-feedback-panel".*?</aside>', body, re.S)
    assert match is not None, "no panel of the last action"
    return match.group(0)


def live_region_of(body: str) -> str:
    """Return the hidden region that announces the result to a screen reader."""
    match = re.search(r'<div id="ui-feedback-region".*?</div>', body, re.S)
    assert match is not None, "no live region"
    return match.group(0)


def csrf_of(body: str) -> str:
    """Return the CSRF token of the session from a rendered page."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert match is not None, "no CSRF token"
    return match.group(1)


@pytest.mark.parametrize("actor_id,path", STAFF_ROUTES)
def test_no_staff_screen_shows_the_empty_last_action(
    client: TestClient, actor_id: str, path: str
) -> None:
    """Before an action the frame shows no result and the panel stays shut."""
    choose(client, actor_id)
    response = client.get(path)
    assert response.status_code == 200, (path, response.text[:200])
    body = response.text
    assert "No action has been performed" not in body, path
    region = region_of(body)
    assert 'data-outcome="none"' in region, path
    # The panel is shut until the person asks for it, so nothing stands at
    # the top of the screen.
    assert "hidden" in region.split(">")[0], path
    # The panel holds no message before an action.
    assert re.search(r'data-testid="feedback-message"[^>]*></p>', region), region
    # The live region stays for announcements, but it shows nothing.
    live = live_region_of(body)
    assert 'aria-live="polite"' in live, path
    assert "visually-hidden" in live, path


def test_the_frame_opens_the_last_action_from_the_header(
    client: TestClient,
) -> None:
    """The bell in the header opens the panel; no result stands at the top."""
    choose(client, REVIEWER)
    body = client.get("/queue").text
    assert 'data-testid="last-action-toggle"' in body
    assert 'aria-controls="ui-feedback-panel"' in body
    assert 'data-testid="feedback-panel-title"' in body
    # The panel stands at the end of the frame, not at the top of the screen.
    assert body.index('id="ui-feedback-panel"') > body.index("<main")


@pytest.mark.parametrize("actor_id,path", STAFF_ROUTES)
def test_no_staff_screen_carries_the_banner_or_the_build_label(
    client: TestClient, actor_id: str, path: str
) -> None:
    """The demo banner and the side foot are gone from every staff screen."""
    choose(client, actor_id)
    response = client.get(path)
    assert response.status_code == 200, (path, response.text[:200])
    body = response.text
    assert 'data-testid="demo-banner"' not in body, path
    assert "About this demo" not in body, path
    assert "schema 0004" not in body, path
    assert "Local candidate" not in body, path
    assert "Fictional data" not in body, path


@pytest.mark.parametrize("actor_id,path", STAFF_ROUTES)
def test_the_footer_is_one_line(client: TestClient, actor_id: str, path: str) -> None:
    """The footer carries the demonstration disclosure in one line."""
    choose(client, actor_id)
    body = client.get(path).text
    match = re.search(r'<footer class="app-footer">(.*?)</footer>', body, re.S)
    assert match is not None, path
    footer = match.group(1)
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", footer, re.S)
    assert len(paragraphs) == 1, (path, footer)
    text = re.sub(r"\s+", " ", paragraphs[0]).strip()
    assert text == FOOTER_LINE, (path, text)
    # One line of text: no line break inside it.
    assert "\n" not in paragraphs[0].strip(), path


def test_the_last_action_shows_one_sentence_and_hides_the_detail_list(
    acted_client: TestClient,
) -> None:
    """After a real action the sentence shows and the detail list is behind a disclosure."""
    choose(acted_client, REVIEWER)
    page = acted_client.get("/permits/app_synth_001")
    response = acted_client.post(
        "/ui/actions/permit.evaluate",
        data={
            "application_id": "app_synth_001",
            "csrf_token": csrf_of(page.text),
            "next": "/permits/app_synth_001",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200, response.text[:200]
    region = region_of(response.text)
    assert 'data-outcome="accepted"' in region, region[:200]

    message = re.search(r'data-testid="feedback-message"[^>]*>(.*?)</p>', region, re.S)
    assert message is not None, region
    sentence = re.sub(r"\s+", " ", message.group(1)).strip()
    assert sentence, region
    assert sentence.endswith("."), sentence

    disclosure = re.search(
        r'<details class="feedback-more"[^>]*data-testid="feedback-more"[^>]*>(.*?)</details>',
        region,
        re.S,
    )
    assert disclosure is not None, region
    assert "<summary>More details</summary>" in disclosure.group(1), region
    assert '<dl class="feedback-detail">' in disclosure.group(1), region
    # The detail list is collapsed until the person asks for it.
    assert "open" not in disclosure.group(0).split(">")[0], region
    # The values are still there for anyone who opens the disclosure.
    for name in (
        "feedback-destination",
        "feedback-state",
        "feedback-pending",
        "feedback-version",
        "feedback-affected",
    ):
        assert f'data-testid="{name}"' in disclosure.group(1), name
    for term in ("Destination", "State", "Pending", "Version", "Affected", "Recorded"):
        assert f"<dt>{term}</dt>" in disclosure.group(1), term


def test_the_feedback_survives_a_refresh_and_stays_behind_the_disclosure(
    acted_client: TestClient,
) -> None:
    """The disclosure is still there when the page is read again."""
    choose(acted_client, REVIEWER)
    page = acted_client.get("/permits/app_synth_001")
    acted_client.post(
        "/ui/actions/permit.evaluate",
        data={
            "application_id": "app_synth_001",
            "csrf_token": csrf_of(page.text),
            "next": "/permits/app_synth_001",
        },
        follow_redirects=True,
    )
    region = region_of(acted_client.get("/permits/app_synth_001").text)
    assert "feedback-more" in region
    assert '<dl class="feedback-detail">' in region

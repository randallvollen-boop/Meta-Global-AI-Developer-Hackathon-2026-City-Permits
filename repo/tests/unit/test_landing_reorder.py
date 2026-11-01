"""The landing: the personas come first, the video comes after them.

The landing is the first thing a visitor sees.  It offers the five personas
in one row, says in one line who they are, and keeps the video and the guide
links below them.  The card of a persona names the persona; the sentences that
say who the person is, what the job is and where to start are the hover text
and the accessible description of the card.
"""
# REQUIRES: UX-01, PER-04

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import client, settings  # noqa: E402,F401

from acme_city.ui.view_models import PERSONA_ORDER, PERSONA_PROFILES  # noqa: E402

#: The five selectable personas and the screen each one lands on.
PERSONAS: tuple[tuple[str, str, str], ...] = (
    ("persona_applicant", "Applicant", "/apply"),
    ("persona_agent_operator", "Agent Operator", "/agents"),
    ("persona_data_steward", "Data Steward", "/steward"),
    ("persona_permit_reviewer", "Permit Reviewer", "/queue"),
    ("persona_city_administrator", "City Administrator", "/overview"),
)


@pytest.fixture()
def landing(client: TestClient) -> str:
    """The rendered landing page."""
    response = client.get("/select")
    assert response.status_code == 200, response.text[:300]
    return response.text


def test_the_heading_comes_first_and_one_line_explains_the_page(landing: str) -> None:
    assert '<h1 id="select-heading">Choose a persona</h1>' in landing
    assert 'data-testid="select-line"' in landing
    # The persona menu in the top right is where the switch lives.
    assert "persona menu in the top right" in landing


def test_the_intro_paragraph_is_gone(landing: str) -> None:
    assert "Each persona is a fictional person who plays one job" not in landing
    assert "the browser never sends a role" not in landing


def test_the_landing_carries_no_last_action_box(landing: str) -> None:
    assert "Last action" not in landing
    assert 'id="ui-feedback-region"' not in landing


def test_the_five_personas_come_first_in_story_order(landing: str) -> None:
    cards = re.findall(r'data-testid="persona-card"', landing)
    assert len(cards) == 5
    positions = [landing.index(f'data-persona="{actor_id}"') for actor_id, _, _ in PERSONAS]
    assert positions == sorted(positions), "the cards are not in the order of the story"
    labels = re.findall(r'<h2 class="persona-name">([^<]+)</h2>', landing)
    assert labels == list(PERSONA_ORDER)


def test_every_card_carries_its_hover_text_and_its_description(landing: str) -> None:
    cards = re.findall(
        r'<li class="persona-card" data-testid="persona-card" title="([^"]*)">(.*?)</li>',
        landing,
        re.S,
    )
    assert len(cards) == 5, cards
    for (hover, body), (actor_id, label, _) in zip(cards, PERSONAS):
        profile = PERSONA_PROFILES[label]
        hover = html.unescape(hover)
        assert profile["who"] in hover, actor_id
        assert profile["does"] in hover, actor_id
        assert profile["start"] in hover, actor_id
        # The button names the three sentences for anyone who cannot hover.
        described = re.search(rf'data-persona="{actor_id}"[^>]*aria-describedby="([^"]*)"', body)
        assert described is not None, actor_id
        parts = described.group(1).split()
        assert len(parts) == 3, actor_id
        for part in parts:
            sentence = re.search(
                rf'<p class="persona-\w+ visually-hidden" id="{part}">([^<]*)</p>', body
            )
            assert sentence is not None, part
            assert sentence.group(1).strip(), part
        assert profile["who"] in html.unescape(body), actor_id
        assert profile["does"] in html.unescape(body), actor_id
        assert profile["start"] in html.unescape(body), actor_id


def test_the_card_names_the_persona_and_the_button_says_it(landing: str) -> None:
    for actor_id, label, _ in PERSONAS:
        assert f'<h2 class="persona-name">{label}</h2>' in landing, label
        assert f">Continue as {label}</button>" in landing, label


def test_every_persona_posts_its_own_start_screen(landing: str) -> None:
    for actor_id, _, target in PERSONAS:
        form = re.search(
            rf'<input type="hidden" name="actor_id" value="{actor_id}">\s*'
            rf'<input type="hidden" name="next" value="([^"]+)">',
            landing,
        )
        assert form is not None, actor_id
        assert form.group(1) == target, actor_id


def test_the_video_comes_after_the_cards_behind_a_title_card(landing: str) -> None:
    cards_at = landing.index('data-testid="persona-list"')
    video_at = landing.index('data-testid="demo-video"')
    links_at = landing.index('data-testid="guide-links"')
    assert cards_at < video_at < links_at
    assert "Watch the 3-minute tour" in landing
    # The player sits inside the disclosure: it is not on the page until the
    # title card is opened.
    assert '<details class="video-title"' in landing
    player = landing.index('data-testid="demo-video-player"')
    assert player > landing.index('data-testid="demo-video-title"')


def test_the_guide_links_are_on_one_line(landing: str) -> None:
    links = re.search(r'<p class="landing-links" data-testid="guide-links">(.*?)</p>', landing, re.S)
    assert links is not None
    body = links.group(1)
    assert body.count("<a ") == 2, body
    assert "/walkthrough" in body and "/lifecycle" in body
    assert "\n" not in body.strip(), "the guide links are one line"


def test_the_public_notice_is_one_line(landing: str) -> None:
    notice = re.search(r'data-testid="public-demo-notice">(.*?)</p>', landing, re.S)
    if notice is None:
        return
    assert notice.group(1).strip() == "Fictional data. Resets nightly."

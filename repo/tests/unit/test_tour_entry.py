"""The tour has an entry point: the landing and the menu of the persona chip.

The button says "Take the tour" and it carries the marker the engine listens
for.  The staff frame and the City frame both load the engine, so the tour
opens from any screen of the application.  A signed-in reader opens it from the
menu of the chip in the top right; a signed-out reader opens it from the
landing.
"""
# REQUIRES: UX-04, UX-01

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import choose, client, settings  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[2]

BASE = ROOT / "src" / "acme_city" / "templates" / "base.html"
CITY = ROOT / "src" / "acme_city" / "templates" / "city" / "layout.html"
OVERLAY = ROOT / "src" / "acme_city" / "templates" / "components" / "tour_overlay.html"


def test_the_landing_offers_the_tour(client: TestClient) -> None:
    body = client.get("/select").text
    assert 'data-tour-start' in body
    assert ">Take the tour</button>" in body
    # The button of the landing sits in the line that offers the guides.
    line = re.search(r'<p class="landing-links"[^>]*>(.*?)</p>', body, re.S)
    assert line is not None
    assert "data-tour-start" in line.group(1)
    assert "/walkthrough" in line.group(1)


def test_the_staff_frame_offers_the_tour(client: TestClient) -> None:
    """The staff frame opens the tour from the menu of the persona chip."""
    choose(client, "persona_data_steward")
    body = client.get("/queue").text
    assert 'data-testid="tour-start-menu"' in body
    assert ">Take the tour</button>" in body
    # The separate button of the header is gone.
    assert 'data-testid="tour-start-header"' not in body


def test_the_city_frame_offers_the_tour(client: TestClient) -> None:
    """The City frame opens the tour from the menu of the same chip."""
    choose(client, "persona_applicant")
    body = client.get("/city/").text
    assert 'data-testid="tour-start-menu"' in body
    assert ">Take the tour</button>" in body
    # The item of the footer is gone.
    assert 'data-testid="tour-start-footer"' not in body


def test_both_frames_load_the_engine() -> None:
    for path in (BASE, CITY):
        text = path.read_text(encoding="utf-8")
        assert '{% include "components/tour_overlay.html" %}' in text, path
    overlay = OVERLAY.read_text(encoding="utf-8")
    assert '/ui/static/tour.js' in overlay
    assert '/ui/static/tour.css' in overlay


def test_the_engine_is_served() -> None:
    assert (ROOT / "src" / "acme_city" / "static" / "tour.js").is_file()
    assert (ROOT / "src" / "acme_city" / "static" / "tour.css").is_file()


@pytest.mark.parametrize(
    "path",
    ("/select", "/city/", "/city/community", "/queue", "/apply"),
)
def test_every_frame_carries_the_engine(client: TestClient, path: str) -> None:
    body = client.get(path).text
    assert '/ui/static/tour.js' in body, path
    assert '/ui/static/tour.css' in body, path

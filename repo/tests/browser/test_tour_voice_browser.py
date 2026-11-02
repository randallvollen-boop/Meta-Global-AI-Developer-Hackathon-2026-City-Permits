"""Browser coverage for the optional narrated guided tour."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from conftest import BrowserServer, start_server


REPO_ROOT = Path(__file__).resolve().parents[2]
SILENT_MP3 = REPO_ROOT / "tests" / "fixtures" / "tour-audio" / "silent.mp3.b64"


def start_resident_tour(page, server: BrowserServer) -> None:
    """Open the resident intro and wait for a completed manifest request."""
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.wait_for_function(
        "() => performance.getEntriesByType('resource').some((entry) => "
        "entry.name.endsWith('/tour-audio/manifest.json'))"
    )
    page.evaluate("() => window.acmeTour.start('resident')")
    page.wait_for_url(f"{server.base_url}/apply")
    page.wait_for_function(
        "() => performance.getEntriesByType('resource').some((entry) => "
        "entry.name.endsWith('/tour-audio/manifest.json'))"
    )
    page.wait_for_selector('[data-testid="tour-overlay"]:not([hidden])')
    page.wait_for_function(
        "() => document.querySelector('[data-testid=\"tour-title\"]')"
        ".textContent.trim() === 'A fence for the back yard'"
    )


@pytest.fixture()
def voice_server(tmp_path: Path) -> BrowserServer:
    """Serve one test-only silent clip without changing checked-in static files."""
    audio_dir = tmp_path / "tour-audio"
    audio_dir.mkdir()
    (audio_dir / "resident-intro.mp3").write_bytes(
        base64.b64decode(SILENT_MP3.read_text(encoding="ascii").strip())
    )
    (audio_dir / "manifest.json").write_text(
        json.dumps({"resident-intro": "resident-intro.mp3"}), encoding="utf-8"
    )
    yield from start_server(tmp_path, tour_audio_dir=audio_dir)


def test_no_voice_button_appears_when_the_manifest_is_empty(page, server: BrowserServer) -> None:
    start_resident_tour(page, server)
    assert page.locator('[data-testid="tour-voice"]').is_hidden()
    assert page.recorded_errors == []


def test_voice_button_toggles_and_remembers_the_visitor_choice(
    page, voice_server: BrowserServer
) -> None:
    start_resident_tour(page, voice_server)
    voice = page.locator('[data-testid="tour-voice"]')
    assert voice.is_visible()
    assert voice.inner_text().strip() == "Play voice"
    assert voice.get_attribute("aria-pressed") == "false"
    voice.click()
    assert voice.inner_text().strip() == "Mute voice"
    assert voice.get_attribute("aria-pressed") == "true"
    assert page.evaluate("() => sessionStorage.getItem('acme-tour-voice')") == "on"
    assert page.recorded_errors == []

"""Browser coverage for the on-demand voice of the guided tour.

The voice is spoken on demand: the visitor presses the button and the clip of
this step is heard.  Nothing else starts a clip.  The auto-play never speaks,
the tour keeps no choice about the voice, and a step that the tour leaves
behind is silent.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from conftest import BrowserServer, start_server
from playwright.sync_api import expect


REPO_ROOT = Path(__file__).resolve().parents[2]
SILENT_MP3 = REPO_ROOT / "tests" / "fixtures" / "tour-audio" / "silent.mp3.b64"

#: The length of one step of the auto-play in the tests.  The ordinary tour
#: waits nine seconds; the hook shortens it, and the hook travels with the
#: state of the tour, so it holds across the change of the screen.
AUTO_PLAY_MS = 2000

#: The spy on the media element.  It counts every call of play() and of
#: pause() in the session storage, so the count survives the change of the
#: screen.  It runs on every page of the browser, because the tour opens the
#: next screen with a change of the page.
MEDIA_SPY = """
try {
  const count = (name) => {
    try { return Number(sessionStorage.getItem(name) || '0'); } catch (error) { return 0; }
  };
  const remember = (name) => {
    try { sessionStorage.setItem(name, String(count(name) + 1)); } catch (error) {}
  };
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    remember('acme-test-play-calls');
    return play.apply(this, arguments);
  };
  const pause = HTMLMediaElement.prototype.pause;
  HTMLMediaElement.prototype.pause = function () {
    remember('acme-test-pause-calls');
    return pause.apply(this, arguments);
  };
} catch (error) {}
"""


def steps_of(page, server: BrowserServer, path: str = "resident") -> list[dict]:
    """Return the steps the server serves for one path of the tour."""
    return page.request.get(f"{server.base_url}/tour/steps?path={path}").json()["steps"]


def wait_for_title(page, title: str, timeout: int = 30_000) -> None:
    """Wait until the panel of the tour shows the given step."""
    page.wait_for_function(
        "(title) => { const element = document.querySelector('[data-testid=\"tour-title\"]');"
        " return element !== null && element.textContent.trim() === title; }",
        arg=title,
        timeout=timeout,
    )


def wait_for_playing(page) -> None:
    """Wait until the clip of the tour is playing."""
    page.wait_for_function(
        "() => { const audio = document.querySelector('[data-testid=\"tour-audio\"]');"
        " return audio !== null && !audio.paused; }"
    )


def is_playing(page) -> bool:
    """Say whether the clip of the tour is playing."""
    return not bool(
        page.evaluate(
            "() => { const audio = document.querySelector('[data-testid=\"tour-audio\"]');"
            " return audio === null || audio.paused; }"
        )
    )


def calls_of(page, name: str) -> int:
    """Return the number of calls the spy has counted."""
    return int(page.evaluate(f"() => Number(sessionStorage.getItem('{name}') || '0')"))


def open_landing(page, server: BrowserServer) -> None:
    """Open the landing page and wait for a completed manifest request."""
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    page.wait_for_function(
        "() => performance.getEntriesByType('resource').some((entry) => "
        "entry.name.endsWith('/tour-audio/manifest.json'))"
    )


def start_resident_tour(page, server: BrowserServer) -> None:
    """Open the resident intro and wait for a completed manifest request."""
    open_landing(page, server)
    page.evaluate("() => window.acmeTour.start('resident')")
    page.wait_for_url(f"{server.base_url}/apply")
    page.wait_for_function(
        "() => performance.getEntriesByType('resource').some((entry) => "
        "entry.name.endsWith('/tour-audio/manifest.json'))"
    )
    page.wait_for_selector('[data-testid="tour-overlay"]:not([hidden])')
    wait_for_title(page, "A fence for the back yard")


@pytest.fixture()
def voice_server(tmp_path: Path) -> BrowserServer:
    """Serve one test-only silent clip without changing checked-in static files."""
    audio_dir = tmp_path / "tour-audio"
    audio_dir.mkdir()
    (audio_dir / "resident-intro.mp3").write_bytes(
        base64.b64decode(SILENT_MP3.read_text(encoding="ascii").strip())
    )
    (audio_dir / "manifest.json").write_text(
        json.dumps(
            {
                "resident-intro": "resident-intro.mp3",
                "resident-ask": "resident-intro.mp3",
            }
        ),
        encoding="utf-8",
    )
    yield from start_server(tmp_path, tour_audio_dir=audio_dir)


@pytest.fixture()
def empty_voice_server(tmp_path: Path) -> BrowserServer:
    """Serve a narration folder whose manifest names no clip."""
    audio_dir = tmp_path / "tour-audio"
    audio_dir.mkdir()
    (audio_dir / "manifest.json").write_text("{}", encoding="utf-8")
    yield from start_server(tmp_path, tour_audio_dir=audio_dir)


def test_no_voice_button_appears_when_the_manifest_is_empty(
    page, empty_voice_server: BrowserServer
) -> None:
    start_resident_tour(page, empty_voice_server)
    assert page.locator('[data-testid="tour-voice"]').is_hidden()
    assert page.recorded_errors == []


def test_the_shipped_manifest_offers_the_voice_of_the_resident_intro(
    page, server: BrowserServer
) -> None:
    start_resident_tour(page, server)
    voice = page.locator('[data-testid="tour-voice"]')
    expect(voice).to_be_visible()
    assert voice.inner_text().strip() == "Play voice"
    assert voice.get_attribute("aria-pressed") == "false"
    assert page.recorded_errors == []


def test_a_tap_plays_the_clip_of_this_step(page, server: BrowserServer) -> None:
    """The button plays the clip of this step, and says that it plays."""
    page.add_init_script(MEDIA_SPY)
    start_resident_tour(page, server)
    voice = page.locator('[data-testid="tour-voice"]')
    expect(voice).to_be_visible()
    assert voice.inner_text().strip() == "Play voice"
    assert voice.get_attribute("aria-pressed") == "false"
    voice.click()
    assert voice.inner_text().strip() == "Stop voice"
    assert voice.get_attribute("aria-pressed") == "true"
    # The clip is heard: the element of the tour is not paused.
    wait_for_playing(page)
    assert is_playing(page)
    # The tap is the one thing that started a clip.
    assert calls_of(page, "acme-test-play-calls") == 1
    assert page.recorded_errors == []


def test_a_second_tap_stops_the_clip(page, server: BrowserServer) -> None:
    """The button stops the clip that is playing."""
    start_resident_tour(page, server)
    voice = page.locator('[data-testid="tour-voice"]')
    voice.click()
    wait_for_playing(page)
    assert voice.inner_text().strip() == "Stop voice"
    assert voice.get_attribute("aria-pressed") == "true"
    voice.click()
    assert voice.inner_text().strip() == "Play voice"
    assert voice.get_attribute("aria-pressed") == "false"
    assert not is_playing(page)
    assert page.recorded_errors == []


def test_the_button_is_at_rest_when_the_clip_ends(
    page, voice_server: BrowserServer
) -> None:
    """A clip that ends on its own leaves the button at rest."""
    start_resident_tour(page, voice_server)
    voice = page.locator('[data-testid="tour-voice"]')
    voice.click()
    # The clip of the test is a moment long, so it ends on its own.
    page.wait_for_function(
        "() => { const audio = document.querySelector('[data-testid=\"tour-audio\"]');"
        " const button = document.querySelector('[data-testid=\"tour-voice\"]');"
        " return audio !== null && audio.ended && button !== null"
        " && button.textContent.trim() === 'Play voice'; }"
    )
    assert voice.inner_text().strip() == "Play voice"
    assert voice.get_attribute("aria-pressed") == "false"
    assert not is_playing(page)
    assert page.recorded_errors == []


def test_the_next_step_stops_the_clip(page, server: BrowserServer) -> None:
    """The clip of a step stops when the tour moves on, and does not carry on."""
    page.add_init_script(MEDIA_SPY)
    steps = steps_of(page, server)
    start_resident_tour(page, server)
    voice = page.locator('[data-testid="tour-voice"]')
    voice.click()
    wait_for_playing(page)
    page.locator('[data-testid="tour-next"]').click()
    # The clip was stopped before the tour left the step.
    page.wait_for_function(
        "() => Number(sessionStorage.getItem('acme-test-pause-calls') || '0') > 0"
    )
    wait_for_title(page, steps[1]["title"])
    # The voice of the next step is at rest: nothing plays without a tap.
    voice = page.locator('[data-testid="tour-voice"]')
    expect(voice).to_be_visible()
    assert voice.inner_text().strip() == "Play voice"
    assert voice.get_attribute("aria-pressed") == "false"
    assert not is_playing(page)
    assert calls_of(page, "acme-test-play-calls") == 1
    assert page.recorded_errors == []


def test_the_auto_play_never_starts_a_clip(page, voice_server: BrowserServer) -> None:
    """The tour walks on by itself over two steps, and it never speaks."""
    page.add_init_script(MEDIA_SPY)
    steps = steps_of(page, voice_server)
    open_landing(page, voice_server)
    page.evaluate("(ms) => window.acmeTour.setInterval(ms)", AUTO_PLAY_MS)
    page.evaluate("() => window.acmeTour.start('resident')")
    page.wait_for_url(f"{voice_server.base_url}/apply")
    wait_for_title(page, steps[0]["title"])
    page.locator('[data-testid="tour-play"]').click()
    assert page.locator('[data-testid="tour-play"]').inner_text().strip() == "Pause"
    # The tour walks on by itself, over two steps.
    wait_for_title(page, steps[1]["title"])
    wait_for_title(page, steps[2]["title"])
    # No clip was ever started: the auto-play never speaks.
    assert calls_of(page, "acme-test-play-calls") == 0
    assert not is_playing(page)
    assert page.recorded_errors == []


def test_the_auto_play_does_not_carry_the_voice_on(
    page, server: BrowserServer
) -> None:
    """A clip that was asked for does not follow the tour into the next step."""
    page.add_init_script(MEDIA_SPY)
    steps = steps_of(page, server)
    open_landing(page, server)
    page.evaluate("(ms) => window.acmeTour.setInterval(ms)", AUTO_PLAY_MS)
    page.evaluate("() => window.acmeTour.start('resident')")
    page.wait_for_url(f"{server.base_url}/apply")
    wait_for_title(page, steps[0]["title"])
    voice = page.locator('[data-testid="tour-voice"]')
    voice.click()
    wait_for_playing(page)
    assert calls_of(page, "acme-test-play-calls") == 1
    # The auto-play walks on by itself, and it starts no clip of its own.
    page.locator('[data-testid="tour-play"]').click()
    assert page.locator('[data-testid="tour-play"]').inner_text().strip() == "Pause"
    wait_for_title(page, steps[1]["title"])
    wait_for_title(page, steps[2]["title"])
    assert calls_of(page, "acme-test-play-calls") == 1
    # The voice of the step the tour came to is at rest.
    voice = page.locator('[data-testid="tour-voice"]')
    expect(voice).to_be_visible()
    assert voice.inner_text().strip() == "Play voice"
    assert voice.get_attribute("aria-pressed") == "false"
    assert not is_playing(page)
    assert page.recorded_errors == []


def test_the_tour_keeps_no_choice_about_the_voice(page, server: BrowserServer) -> None:
    """The voice of a step is not remembered, and no storage holds a key."""
    steps = steps_of(page, server)
    start_resident_tour(page, server)
    voice = page.locator('[data-testid="tour-voice"]')
    voice.click()
    wait_for_playing(page)
    assert page.evaluate("() => localStorage.getItem('acme-tour-voice')") is None
    assert page.evaluate("() => sessionStorage.getItem('acme-tour-voice')") is None
    # The next step is silent: the wish to hear the voice was not kept.
    page.locator('[data-testid="tour-next"]').click()
    wait_for_title(page, steps[1]["title"])
    voice = page.locator('[data-testid="tour-voice"]')
    assert voice.inner_text().strip() == "Play voice"
    assert voice.get_attribute("aria-pressed") == "false"
    assert not is_playing(page)
    assert page.evaluate("() => localStorage.getItem('acme-tour-voice')") is None
    assert page.evaluate("() => sessionStorage.getItem('acme-tour-voice')") is None
    assert page.recorded_errors == []


def test_the_old_voice_key_is_cleared(page, voice_server: BrowserServer) -> None:
    """A visitor who comes back is not left with a voice that speaks by itself."""
    page.add_init_script(
        "try { localStorage.setItem('acme-tour-voice', 'on'); } catch (error) {}\n"
        "try { sessionStorage.setItem('acme-tour-voice', 'on'); } catch (error) {}\n"
    )
    start_resident_tour(page, voice_server)
    assert page.evaluate("() => localStorage.getItem('acme-tour-voice')") is None
    assert page.evaluate("() => sessionStorage.getItem('acme-tour-voice')") is None
    voice = page.locator('[data-testid="tour-voice"]')
    expect(voice).to_be_visible()
    assert voice.inner_text().strip() == "Play voice"
    assert voice.get_attribute("aria-pressed") == "false"
    assert not is_playing(page)
    assert page.recorded_errors == []


def test_a_refused_voice_says_why(page, voice_server: BrowserServer) -> None:
    """The browser refuses the clip: the panel says so beside the button."""
    start_resident_tour(page, voice_server)
    page.evaluate(
        "() => { HTMLMediaElement.prototype.play = function () {"
        " return Promise.reject(new Error('the browser refused the clip')); }; }"
    )
    voice = page.locator('[data-testid="tour-voice"]')
    voice.click()
    note = page.locator('[data-testid="tour-voice-note"]')
    expect(note).to_be_visible()
    assert note.inner_text().strip() == "The voice could not start. Tap again to try."
    # The button is at rest again: the visitor may try once more.
    assert voice.inner_text().strip() == "Play voice"
    assert voice.get_attribute("aria-pressed") == "false"
    assert page.recorded_errors == []

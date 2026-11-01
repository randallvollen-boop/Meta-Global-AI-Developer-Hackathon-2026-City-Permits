"""The theme: light everywhere, dark only where the reader asks for it.

Light is the default on every page, whatever the device says.  The staff
frame offers a dark mode in the menu of the persona chip; the choice is kept
and survives a reload.  The City frame and the landing of a signed-out reader
stay light.
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

from conftest import BrowserServer

#: The screens the walk covers, in both frames.
SCREENS = (
    "/select",
    "/city/",
    "/city/permits",
    "/apply",
    "/help",
    "/queue",
    "/steward",
    "/permits/app_d05",
)


def _background(page) -> str:
    """Return the colour the page is painted in."""
    return page.evaluate("getComputedStyle(document.body).backgroundColor")


def _theme(page) -> str:
    """Return the theme the page is drawn in."""
    return page.evaluate("document.documentElement.getAttribute('data-theme')")


def _state(page) -> str:
    """Return the state the dark mode control reports."""
    return (page.locator('[data-testid="theme-state"]').text_content() or "").strip()


def _sign_in(page, server: BrowserServer, actor_id: str) -> None:
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator(f'button[data-persona="{actor_id}"]').click()
    page.wait_for_load_state("domcontentloaded")


def test_every_frame_opens_light_on_a_dark_device(browser, server: BrowserServer) -> None:
    """The setting of the device is never followed: every frame opens light."""
    light_context = browser.new_context(
        viewport={"width": 1280, "height": 900}, color_scheme="light"
    )
    dark_context = browser.new_context(
        viewport={"width": 1280, "height": 900}, color_scheme="dark"
    )
    try:
        light_page = light_context.new_page()
        dark_page = dark_context.new_page()
        for path in SCREENS:
            light_page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
            dark_page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
            assert _theme(dark_page) == "light", path
            # The dark device paints the page exactly like the light one.
            assert _background(dark_page) == _background(light_page), path
        # And the reader who signs in on a dark device still gets the light
        # interface.
        _sign_in(dark_page, server, "persona_data_steward")
        _sign_in(light_page, server, "persona_data_steward")
        for path in SCREENS:
            dark_page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
            assert _theme(dark_page) == "light", path
            light_page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
            assert _background(dark_page) == _background(light_page), path
    finally:
        light_context.close()
        dark_context.close()


def test_the_dark_mode_switches_the_staff_frame_and_persists(
    browser, server: BrowserServer
) -> None:
    """The dark mode of the staff frame switches both ways and is remembered."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    try:
        _sign_in(page, server, "persona_data_steward")
        page.goto(f"{server.base_url}/queue", wait_until="domcontentloaded")
        light = _background(page)
        # The control sits in the menu of the chip in the top right.
        page.locator('[data-testid="persona-trigger"]').click()
        toggle = page.locator('[data-testid="theme-toggle"]')
        assert toggle.is_visible()
        assert toggle.inner_text().strip().startswith("Dark mode")
        assert _state(page) == "Off"
        toggle.click()
        assert _theme(page) == "dark"
        dark = _background(page)
        assert dark != light
        assert _state(page) == "On"
        assert page.evaluate("localStorage.getItem('acme-theme')") == "dark"
        # The choice survives a reload.
        page.reload(wait_until="domcontentloaded")
        assert _theme(page) == "dark"
        assert _background(page) == dark
        assert _state(page) == "On"
        # And back to light.
        page.locator('[data-testid="persona-trigger"]').click()
        page.locator('[data-testid="theme-toggle"]').click()
        assert _theme(page) == "light"
        assert _background(page) == light
        assert page.evaluate("localStorage.getItem('acme-theme')") == "light"
    finally:
        context.close()


def test_the_city_frame_stays_light_even_with_a_dark_choice(
    browser, server: BrowserServer
) -> None:
    """The dark mode of the staff frame never reaches the City website."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    try:
        _sign_in(page, server, "persona_data_steward")
        page.goto(f"{server.base_url}/queue", wait_until="domcontentloaded")
        page.locator('[data-testid="persona-trigger"]').click()
        page.locator('[data-testid="theme-toggle"]').click()
        assert _theme(page) == "dark"
        # The City website stays light, and offers no dead control.
        for path in ("/city/", "/city/permits", "/city/community"):
            page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
            assert _theme(page) == "light", path
            assert page.locator('[data-testid="theme-toggle"]').count() == 0, path
        # The landing of a signed-out reader is light too.
        page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
        assert _theme(page) == "light"
    finally:
        context.close()

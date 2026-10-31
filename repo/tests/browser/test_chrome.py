"""The staff chrome: the theme toggle, the account bar and the demo control corner.

Root cause of the theme bug these tests guard: the deferred ``app.js`` ran
``initTheme`` at load and again on DOMContentLoaded, bound two click listeners,
and every click toggled twice (so the theme never changed).
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

from conftest import BrowserServer

BG = "() => getComputedStyle(document.body).backgroundColor"


def test_the_theme_toggle_switches_both_ways_and_persists(page, server: BrowserServer, login) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue", wait_until="networkidle")
    start = page.evaluate(BG)
    page.locator("#theme-toggle").click()
    dark = page.evaluate(BG)
    assert dark != start
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"
    assert page.evaluate("localStorage.getItem('acme-theme')") == "dark"
    page.reload(wait_until="networkidle")
    assert page.evaluate(BG) == dark  # persisted
    page.locator("#theme-toggle").click()
    assert page.evaluate(BG) == start
    assert page.evaluate("localStorage.getItem('acme-theme')") == "light"
    assert page.recorded_errors == []


def test_the_city_website_has_no_dead_theme_toggle(page, server: BrowserServer, login) -> None:
    login("persona_applicant")
    page.goto(f"{server.base_url}/city/", wait_until="networkidle")
    assert page.locator("#theme-toggle").count() == 0
    assert page.locator('[data-testid="theme-toggle"]').count() == 0


def test_the_top_bar_shows_the_account_and_the_persona_menu(
    page, server: BrowserServer, login
) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue", wait_until="networkidle")
    assert page.locator(".seg-btn").count() == 0
    header = page.locator("header.top")
    assert "Data Steward" in header.locator('[data-testid="acting-persona"]').inner_text()
    # Changed deliberately (persona switcher, S4): the top bar carries the
    # switcher now, so its menu holds the five personas.
    assert header.locator("[data-demo-persona]").count() == 5
    header.locator(".account-trigger").click()
    header.locator('[data-testid="sign-out"]').click()
    page.wait_for_url(f"{server.base_url}/select")


def _rect(page, selector: str) -> dict:
    return page.evaluate(
        "(s) => { const r = document.querySelector(s).getBoundingClientRect();"
        " return {l: r.left, t: r.top, r: r.right, b: r.bottom}; }",
        selector,
    )


def _overlap(a: dict, b: dict) -> bool:
    return not (a["r"] <= b["l"] or b["r"] <= a["l"] or a["b"] <= b["t"] or b["b"] <= a["t"])


def test_toast_and_the_persona_menu_never_share_a_corner(browser, server: BrowserServer) -> None:
    for width, height in ((1280, 900), (390, 844)):
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        try:
            page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
            page.locator('button[data-persona="persona_data_steward"]').click()
            # The Data Steward lands on its own work queue (STW-2).
            page.wait_for_url(f"{server.base_url}/steward")
            page.evaluate(
                "() => { const t = document.getElementById('toast');"
                " t.textContent = 'Saved. A message that is long enough to wrap on a narrow screen.';"
                " t.classList.add('on'); }"
            )
            page.wait_for_timeout(300)
            toast = _rect(page, "#toast")
            chip = _rect(page, '[data-testid="persona-trigger"]')
            # Changed deliberately (persona switcher, S4): the switcher is the
            # chip in the top bar now, and it never sits under the toast.
            assert not _overlap(toast, chip), (width, toast, chip)
            assert toast["t"] < height / 2 and chip["t"] < height / 2
            assert toast["r"] <= width and chip["r"] <= width
            page.locator('[data-testid="persona-trigger"]').click()
            panel = _rect(page, '[data-testid="demo-switch"]')
            assert panel["l"] >= 0 and panel["r"] <= width and panel["b"] <= height
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        finally:
            context.close()

"""The persona menu on a phone and a tablet.

The chip stays in the right half of the header. The open menu stays on the
screen, above the help chat and a detail drawer, and every persona in it
lands on that persona's own home.
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

import re

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow

#: The five personas, the home of each one, and one other screen each may open.
PERSONAS = (
    ("persona_applicant", "/city/", "/city/permits"),
    ("persona_agent_operator", "/agents", "/agents/runs"),
    ("persona_data_steward", "/steward", "/masters"),
    ("persona_permit_reviewer", "/queue", "/queue/review"),
    ("persona_city_administrator", "/overview", "/admin"),
)

#: Where the menu sends each persona: the same target the landing cards use.
HOMES = {actor_id: home for actor_id, home, _other in PERSONAS}

#: A staff record that opens the detail drawer.
DRAWER_PATH = "/masters?detail=record:party_cedarline"

#: The centre of a control is inside the viewport, and that control is the
#: topmost element there. A child of the control, such as the line under a
#: persona name, counts as the control.
_TOP_PROBE = """(element) => {
  const rect = element.getBoundingClientRect();
  const hit = document.elementFromPoint(
    rect.left + rect.width / 2, rect.top + rect.height / 2
  );
  return {
    inside: rect.width > 0 && rect.height > 0
      && rect.top >= -0.5 && rect.left >= -0.5
      && rect.bottom <= window.innerHeight + 0.5
      && rect.right <= window.innerWidth + 0.5,
    topmost: !!hit && (hit === element || element.contains(hit)),
    hit: hit ? (hit.getAttribute("data-testid") || hit.className || hit.tagName) : "",
    width: rect.width,
    height: rect.height,
  };
}"""


def _sign_in(page, server: BrowserServer, actor_id: str, home: str) -> None:
    """Sign in as one persona and wait until its home is showing."""
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator(f'button[data-persona="{actor_id}"]').click()
    page.wait_for_url(re.compile(re.escape(home) + r"/?$"))


def _header(page) -> str:
    """Return the header the page is drawn in."""
    if page.locator("header.city-header").count():
        return "header.city-header"
    return "header.top"


def _open_menu(page) -> None:
    """Open the persona menu."""
    page.locator('[data-testid="persona-trigger"]').click()
    page.locator('[data-testid="demo-switch"]').wait_for(state="visible")


def _close_menu(page) -> None:
    """Close the persona menu without activating one of its controls."""
    page.locator("details.account-menu").evaluate("menu => { menu.open = false; }")


def _assert_chip_and_menu(page, path: str) -> None:
    """The chip is in the right half, and the open menu is on the screen."""
    chip = page.locator('[data-testid="persona-trigger"]')
    assert chip.count() == 1, path
    chip_box = chip.bounding_box()
    header_box = page.locator(_header(page)).bounding_box()
    assert chip_box is not None and header_box is not None, path
    centre = chip_box["x"] + chip_box["width"] / 2
    midpoint = header_box["x"] + header_box["width"] / 2
    assert centre >= midpoint, (path, chip_box, header_box)
    assert chip_box["width"] >= 40 and chip_box["height"] >= 40, (path, chip_box)
    _open_menu(page)
    buttons = page.locator("[data-demo-persona]")
    assert buttons.count() == 5, path
    controls = [buttons.nth(index) for index in range(5)]
    controls.append(page.locator('[data-testid="sign-out"]'))
    for control in controls:
        handle = control.element_handle()
        assert handle is not None, path
        report = page.evaluate(_TOP_PROBE, handle)
        assert report["inside"], (path, report)
        assert report["topmost"], (path, report)
    for index in range(5):
        box = buttons.nth(index).bounding_box()
        assert box is not None, path
        assert box["width"] >= 40 and box["height"] >= 40, (path, box)
        actor_id = buttons.nth(index).get_attribute("data-demo-persona")
        posted = buttons.nth(index).locator("xpath=ancestor::form[1]").locator(
            'input[name="next"]'
        )
        assert posted.input_value() == HOMES[actor_id], (path, actor_id)
    assert_no_horizontal_overflow(page)
    _close_menu(page)


def _assert_menu_is_topmost(page, path: str) -> None:
    """With another layer open, the menu controls are still the topmost."""
    _open_menu(page)
    controls = [page.locator("[data-demo-persona]").nth(index) for index in range(5)]
    controls.append(page.locator('[data-testid="sign-out"]'))
    for control in controls:
        handle = control.element_handle()
        assert handle is not None, path
        report = page.evaluate(_TOP_PROBE, handle)
        assert report["inside"], (path, report)
        assert report["topmost"], (path, report)
    _close_menu(page)


@pytest.mark.parametrize(
    ("width", "height"), ((390, 844), (820, 1180)), ids=("phone", "tablet")
)
def test_the_persona_menu_fits_and_switches_home(
    browser, server: BrowserServer, width: int, height: int
) -> None:
    """Every persona can open the menu, and a switch lands on that home."""
    context = browser.new_context(
        viewport={"width": width, "height": height},
        has_touch=True,
        is_mobile=True,
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    page.on(
        "console",
        lambda message: errors.append(f"console: {message.text}")
        if message.type == "error"
        else None,
    )
    try:
        for actor_id, home, other in PERSONAS:
            _sign_in(page, server, actor_id, home)
            for path in (home, other):
                page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
                assert page.url.split("?")[0].rstrip("/").endswith(path.rstrip("/")), (
                    path,
                    page.url,
                )
                _assert_chip_and_menu(page, path)

        _sign_in(page, server, "persona_applicant", "/city/")
        page.goto(f"{server.base_url}/city/", wait_until="domcontentloaded")
        page.locator('[data-testid="help-chat-launcher"]').click()
        page.locator('[data-testid="help-panel-sheet"]').wait_for(state="visible")
        _assert_menu_is_topmost(page, "chat")

        _sign_in(page, server, "persona_data_steward", "/steward")
        page.goto(f"{server.base_url}{DRAWER_PATH}", wait_until="domcontentloaded")
        page.locator("#ui-drawer").wait_for(state="visible")
        _assert_menu_is_topmost(page, DRAWER_PATH)

        _sign_in(page, server, "persona_permit_reviewer", "/queue")
        page.goto(f"{server.base_url}/queue", wait_until="domcontentloaded")
        _open_menu(page)
        page.locator('[data-demo-persona="persona_agent_operator"]').click()
        page.wait_for_url(re.compile(r"/agents/?$"))
        assert "moved_from" not in page.url
        assert page.locator('[data-testid="moved-notice"]').count() == 0
        assert "can't open" not in page.locator("main").inner_text()
        assert (
            page.locator('[data-testid="acting-persona"]').inner_text().strip()
            == "Agent Operator"
        )
        assert errors == []
    finally:
        context.close()

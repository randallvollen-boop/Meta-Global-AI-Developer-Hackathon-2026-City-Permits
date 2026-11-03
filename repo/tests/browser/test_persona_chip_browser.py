"""The persona chip sits in the same corner of every frame, for every persona.

The chip is the one way into the demo controls: it names the persona that
acts and its menu lists the five personas and the guided tour.  This module
walks every persona over a fixed list of screens in both frames, on a desktop
and on a phone, and checks that the chip is there, in the top right, with the
same menu.
"""
# REQUIRES: UX-01, UX-02, UX-04

from __future__ import annotations

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow

#: The five personas, the role the chip names and the home of each one.
PERSONAS = (
    ("persona_applicant", "Applicant", "/city/"),
    ("persona_agent_operator", "Agent Operator", "/agents"),
    ("persona_data_steward", "Data Steward", "/steward"),
    ("persona_permit_reviewer", "Permit Reviewer", "/queue"),
    ("persona_city_administrator", "City Administrator", "/overview"),
)

#: The screens every persona walks: the City website, the portal, the help
#: hub, the permit workspace, the public record of a permit and the home of
#: the persona.
SCREENS = (
    "/city/",
    "/city/permits",
    "/apply",
    "/help",
    "/permits/app_d05",
    "/city/community/permit/ACME-2026-000731",
)


def _rect(page, selector: str) -> dict | None:
    """Return the box of the first element that matches, or None."""
    return page.evaluate(
        "(s) => { const node = document.querySelector(s);"
        " if (!node) return null;"
        " const r = node.getBoundingClientRect();"
        " return {l: r.left, t: r.top, r: r.right, b: r.bottom}; }",
        selector,
    )


def _dot_and_label_centres(page) -> tuple[float, float]:
    """Return the vertical centre of the dot of the chip and of its label."""
    return page.evaluate(
        "() => {"
        " const dot = document.querySelector('[data-testid=\"persona-trigger\"] .dot');"
        " const label = document.querySelector('[data-testid=\"acting-persona\"]');"
        " if (!dot || !label) return null;"
        " const d = dot.getBoundingClientRect();"
        " const l = label.getBoundingClientRect();"
        " return [(d.top + d.bottom) / 2, (l.top + l.bottom) / 2]; }"
    )


def _frame(page) -> str:
    """Return the frame the page is drawn in."""
    if page.locator("body[data-city-site]").count():
        return "city"
    return "staff"


def _header_of(frame: str) -> str:
    """Return the selector of the header of the frame."""
    return "header.city-header" if frame == "city" else "header.top"


def _assert_the_chip(page, role: str, path: str) -> None:
    """Assert the chip of the page: present, in the top right, naming the role."""
    frame = _frame(page)
    chip = page.locator('[data-testid="persona-trigger"]')
    assert chip.count() == 1, (path, frame)
    assert chip.is_visible(), (path, frame)
    # The chip names the role that acts, not the name of the person.
    assert chip.locator('[data-testid="acting-persona"]').inner_text().strip() == role, (
        path,
        frame,
    )
    box = _rect(page, '[data-testid="persona-trigger"]')
    header = _rect(page, _header_of(frame))
    assert box is not None and header is not None, (path, frame)
    # The chip sits in the right third of the header.
    centre = (box["l"] + box["r"]) / 2
    assert centre >= header["l"] + (header["r"] - header["l"]) * 2 / 3, (path, frame, box, header)
    # And it stays inside the header.
    assert header["l"] <= box["l"] and box["r"] <= header["r"] + 1, (path, frame, box, header)


def _assert_the_menu(page, path: str) -> None:
    """Assert the menu of the chip: the five personas, the tour and the sign out."""
    page.locator('[data-testid="persona-trigger"]').click()
    menu = page.locator('[data-testid="demo-switch"]')
    assert menu.is_visible(), path
    assert menu.locator("[data-demo-persona]").count() == 5, path
    assert page.locator('[data-testid="tour-start-menu"]').is_visible(), path
    assert page.locator('[data-testid="tour-start-menu"]').inner_text().strip() == (
        "Take the tour"
    ), path
    # The tour sits under the demo controls.
    label = page.locator(".account-switch-label")
    assert label.count() == 1, path
    tour = page.locator('[data-testid="tour-start-menu"]').bounding_box()
    head = label.bounding_box()
    assert tour is not None and head is not None, path
    assert tour["y"] > head["y"], path
    assert page.locator('[data-testid="sign-out"]').is_visible(), path
    # Close the menu again, so the next screen starts from the same state.
    page.locator('[data-testid="persona-trigger"]').click()


def _walk(page, server: BrowserServer, actor_id: str, role: str, home: str) -> None:
    """Sign in as one persona and walk the screens of both frames."""
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator(f'button[data-persona="{actor_id}"]').click()
    page.wait_for_url(f"{server.base_url}{home}*")
    for path in SCREENS + (home,):
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        _assert_the_chip(page, role, path)
        _assert_the_menu(page, path)
        assert_no_horizontal_overflow(page)


@pytest.mark.parametrize("width,height", ((1280, 900), (390, 844)), ids=["1280", "390"])
def test_the_chip_is_in_the_top_right_of_every_frame_for_every_persona(
    page, server: BrowserServer, width: int, height: int
) -> None:
    """Every persona finds the same chip in the top right of every screen."""
    page.set_viewport_size({"width": width, "height": height})
    for actor_id, role, home in PERSONAS:
        _walk(page, server, actor_id, role, home)
    # A screen a persona may not open answers with a refusal, and the browser
    # reports that status as a console message.  Nothing else may fail.
    unexpected = [
        error
        for error in page.recorded_errors
        if not error.startswith("console: Failed to load resource")
    ]
    assert unexpected == []


def test_the_chip_of_the_city_frame_carries_the_name_of_the_applicant(
    page, server: BrowserServer
) -> None:
    """The City chip is one line; the name of the person opens with the menu."""
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator('button[data-persona="persona_applicant"]').click()
    page.wait_for_url(f"{server.base_url}/city/*")
    page.goto(f"{server.base_url}/city/", wait_until="domcontentloaded")
    chip = page.locator('.city-header [data-testid="persona-trigger"]')
    assert chip.locator('[data-testid="acting-persona"]').inner_text().strip() == "Applicant"
    # The chip is one line: the role, and nothing else.
    assert chip.locator(".account-sub").count() == 0
    assert chip.locator('[data-testid="applicant-name"]').count() == 0
    assert chip.inner_text().strip() == "Applicant"
    # The name of the person is the tooltip of the chip.
    assert chip.get_attribute("title") == "Demo Applicant"
    # And it is the first line of the menu the chip opens, above its items.
    chip.click()
    panel = page.locator(".city-header .account-panel")
    name = panel.locator('[data-testid="applicant-name"]')
    assert name.inner_text().strip() == "Demo Applicant"
    name_box = name.bounding_box()
    items_box = panel.locator('[data-testid="demo-switch"]').bounding_box()
    assert name_box is not None and items_box is not None
    assert name_box["y"] < items_box["y"], (name_box, items_box)
    # The wrapper of the City chip keeps the test id the walkthroughs use.
    assert page.locator('.city-header [data-testid="applicant-account"]').count() == 1


def test_the_dot_of_the_chip_stands_on_the_line_of_the_role(
    page, server: BrowserServer
) -> None:
    """The dot and the role of the chip share one line, in both frames.

    The chip used to hold two lines, so the dot was centred between them and
    the role read as top aligned.  The chip is one line now: the dot and the
    role are centred together.
    """
    page.set_viewport_size({"width": 1280, "height": 900})
    for actor_id, home, path in (
        ("persona_applicant", "/city/", "/city/"),
        ("persona_permit_reviewer", "/queue", "/queue"),
    ):
        page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
        page.locator(f'button[data-persona="{actor_id}"]').click()
        page.wait_for_url(f"{server.base_url}{home}*")
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        centres = _dot_and_label_centres(page)
        assert centres is not None, (actor_id, path)
        dot, label = centres
        assert abs(dot - label) <= 2, (actor_id, path, dot, label)


def test_a_signed_out_reader_sees_no_chip(page, server: BrowserServer) -> None:
    """Without a session there is no chip, in either frame."""
    for path in ("/select", "/city/"):
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert page.locator('[data-testid="persona-trigger"]').count() == 0, path
        assert page.locator('[data-testid="demo-switch"]').count() == 0, path

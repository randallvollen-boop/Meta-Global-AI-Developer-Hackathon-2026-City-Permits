"""The browser navigation tests of the admin-a lane.

The admin-a lane adds its navigation browser tests here; ``test_navigation.py``
is frozen.  These checks cover the shared frame at 390 by 844 and the
grouping of the City Administrator navigation.
"""
# REQUIRES: UX-01

from __future__ import annotations

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

#: The five personas and the screen each one lands on.
PERSONA_HOMES: tuple[tuple[str, str], ...] = (
    ("persona_applicant", "/city/"),
    ("persona_data_steward", "/steward"),
    ("persona_permit_reviewer", "/queue"),
    ("persona_city_administrator", "/overview"),
    ("persona_agent_operator", "/agents"),
)

#: The screens the Administrator opens every day.
BAR_SCREENS: tuple[str, ...] = (
    "overview",
    "queue",
    "masters",
    "permit",
    "steward",
    "source_records",
    "activity",
    "rules",
    "reconciliation",
    "governance",
    "admin",
    "intake_queue",
)

#: The screens under More tools.
MORE_SCREENS: tuple[str, ...] = (
    "insight_city",
    "policy_scenarios",
    "ops_dashboard",
    "ops_audit",
    "ops_support",
    "ops_checks",
)


def _rect(page, selector: str) -> dict:
    return page.evaluate(
        "(s) => { const r = document.querySelector(s).getBoundingClientRect();"
        " return {l: r.left, t: r.top, r: r.right, b: r.bottom}; }",
        selector,
    )


def _overlap(a: dict, b: dict) -> bool:
    return not (a["r"] <= b["l"] or b["r"] <= a["l"] or a["b"] <= b["t"] or b["b"] <= a["t"])


@pytest.fixture(autouse=True)
def _admin_navigation_is_registered() -> None:
    """Register the Administrator navigation before every check of this module.

    Another browser test replaces the profile with a dummy one and removes it
    again, so the grouping of the lane is put back here.
    """
    from acme_city.ui import admin_nav

    admin_nav.register()


@pytest.mark.parametrize("actor_id,home", PERSONA_HOMES)
def test_the_demo_notice_is_visible_on_every_persona_home(
    viewport_390, server: BrowserServer, login, actor_id: str, home: str
) -> None:
    page = viewport_390
    login(actor_id)
    landed = page.url.split("?")[0].rstrip("/")
    assert landed.endswith(home.rstrip("/")), page.url
    if actor_id == "persona_applicant":
        # Changed deliberately (city frame, S2): the City website carries no
        # banner; the disclosure is one line in the footer.
        assert page.locator('[data-testid="city-demo-banner"]').count() == 0
        footer = page.locator('[data-testid="city-footer-note"]')
        assert footer.count() == 1
        assert footer.is_visible()
        text = " ".join(footer.inner_text().split())
        assert text.startswith("Fictional City of Acme website"), text
    else:
        # Changed deliberately (staff frame, S1): the staff screens carry no
        # banner; the disclosure is one line in the footer.
        assert page.locator('[data-testid="demo-banner"]').count() == 0
        footer = page.locator('[data-testid="app-footer"]')
        assert footer.count() == 1
        assert footer.is_visible()
        text = " ".join(footer.inner_text().split())
        assert text == "Fictional ACME City demonstration. Synthetic records only.", text
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


@pytest.mark.parametrize("path", ["/city/", "/city/community"])
def test_the_city_website_shows_its_notice_without_overflow(
    viewport_390, server: BrowserServer, login, path: str
) -> None:
    page = viewport_390
    login("persona_applicant")
    page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
    # Changed deliberately (city frame, S2): the banner is gone; the
    # disclosure is one line in the footer.
    assert page.locator('[data-testid="city-demo-banner"]').count() == 0
    notice = page.locator('[data-testid="city-footer-note"]')
    assert notice.count() == 1
    assert notice.is_visible()
    assert "Fictional" in notice.inner_text()
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


@pytest.mark.parametrize("actor_id,_home", PERSONA_HOMES)
def test_the_mobile_bar_and_the_persona_menu_do_not_meet_on_every_persona_home(
    viewport_390, server: BrowserServer, login, actor_id: str, _home: str
) -> None:
    page = viewport_390
    login(actor_id)
    bar = page.locator(".mobile-nav")
    chip = page.locator('[data-testid="persona-trigger"]')
    # Changed deliberately (persona switcher, S4): both frames carry the
    # switcher in the top bar; only the staff frame has the mobile bar.
    if chip.count():
        if bar.count():
            assert not _overlap(_rect(page, ".mobile-nav"), _rect(page, '[data-testid="persona-trigger"]'))
        assert_not_covered(page, chip)
    else:
        assert page.locator(".demo-switch").count() == 0
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


def test_the_administrator_navigation_keeps_its_screens_and_groups_them(
    viewport_390, server: BrowserServer, login
) -> None:
    page = viewport_390
    login("persona_city_administrator")
    keys = page.locator(".side .app-nav a[data-screen-key]")
    listed = [keys.nth(index).get_attribute("data-screen-key") for index in range(keys.count())]
    assert listed == list(BAR_SCREENS) + list(MORE_SCREENS), listed
    # The screens that read across the whole program sit under More tools.
    more = page.locator('.side [data-testid="nav-more"]')
    assert more.count() == 1
    more_keys = more.locator("a[data-screen-key]")
    grouped = [
        more_keys.nth(index).get_attribute("data-screen-key")
        for index in range(more_keys.count())
    ]
    assert grouped == list(MORE_SCREENS), grouped
    # Every screen is still reachable from the bar and from More tools.
    for key in MORE_SCREENS:
        assert page.locator(f'.side .app-nav a[data-screen-key="{key}"]').count() == 1, key
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


def test_the_persona_cards_still_render_the_profiles(page, server: BrowserServer) -> None:
    from acme_city.ui.view_models import PERSONA_PROFILES

    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    cards = page.locator('[data-testid="persona-card"]')
    assert cards.count() == len(PERSONA_PROFILES)
    for label, profile in PERSONA_PROFILES.items():
        # Match the card by its title: another card's text may mention this persona.
        card = cards.filter(
            has=page.get_by_role("heading", name=label, exact=True)
        )
        assert card.count() == 1, label
        text = card.inner_text()
        assert profile["who"] in text, label
        assert profile["does"] in text, label
        assert profile["start"] in text, label

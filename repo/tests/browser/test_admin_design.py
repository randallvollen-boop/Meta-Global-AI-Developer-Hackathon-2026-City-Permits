"""The admin-b screens in the browser: the phone fit of every screen.

The harness of the lane is shared by its slices.  It opens a screen as the
City Administrator at 390 by 844 pixels, checks that the page does not scroll
sideways, that the mobile navigation and the demo switcher do not cover the
controls of the screen and that the browser reports no error.

The first slice of the lane adds the harness and the guard that keeps the new
stylesheet away from the screens of the other lanes.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04

from __future__ import annotations

import pytest

from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

#: The screens of the other lanes, with the address that opens each of them.
OTHER_SCREENS = (
    ("persona_applicant", "/city/"),
    ("persona_data_steward", "/queue"),
    ("persona_permit_reviewer", "/queue"),
    ("persona_city_administrator", "/queue"),
)

#: The staff screens, which carry the shared "Last action" region.
STAFF_SCREENS = (
    ("persona_data_steward", "/queue"),
    ("persona_permit_reviewer", "/queue"),
    ("persona_city_administrator", "/queue"),
)


@pytest.fixture(autouse=True)
def patient_browser(page):
    """Give the page time to answer when the whole suite runs on one machine.

    The checks of this lane are about the layout of a screen, not about how
    fast a server answers.  A loaded machine must not turn a layout check into
    a timeout.
    """
    page.set_default_timeout(60_000)
    return page


def open_screen(page, server: BrowserServer, path: str) -> None:
    """Open one screen of the demonstration server."""
    page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")


def fits_a_phone(page) -> None:
    """Check that the page fits a phone and that its heading is reachable."""
    assert_no_horizontal_overflow(page)
    heading = page.locator("main h1").first
    if heading.count():
        assert_not_covered(page, heading)


def test_the_admin_b_stylesheet_does_not_reach_the_other_screens(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """The scoped stylesheet may not change a screen the lane does not own."""
    for actor_id, path in OTHER_SCREENS:
        login(actor_id)
        open_screen(page, server, path)
        assert_no_horizontal_overflow(page)
        assert page.locator(".admin-b").count() == 0, path
    assert page.recorded_errors == []


def test_the_other_screens_keep_their_feedback_region(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """The shared "Last action" region survives the new stylesheet."""
    for actor_id, path in STAFF_SCREENS:
        login(actor_id)
        open_screen(page, server, path)
        assert page.locator('[data-testid="feedback"]').count() == 1, path
        assert page.locator('[data-testid="feedback-message"]').count() == 1, path
    assert page.recorded_errors == []


def test_a_saved_what_if_stacks_on_a_phone(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """The saved list is one table that stacks, with a name for every field."""
    login("persona_city_administrator")
    open_screen(page, server, "/policy/scenarios")
    page.locator('[data-testid="policy-suggestion"]').first.click()
    page.wait_for_url("**/policy/scenarios/polscen_*")
    open_screen(page, server, "/policy/scenarios")
    row = page.locator('[data-testid="policy-row"]').first
    assert row.count() == 1
    cell = row.locator('td[data-label="Revision"]')
    assert cell.count() == 1
    shown = cell.evaluate("element => getComputedStyle(element, '::before').content")
    assert "Revision" in shown, shown
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


# ------------------------------------------------------- the proposal review


def test_the_proposal_review_fits_a_phone(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """The checked proposal fits a phone and its save control stays reachable."""
    login("persona_city_administrator")
    open_screen(page, server, "/policy/scenarios")
    page.locator('[data-testid="policy-question"]').fill(
        "What if the side and rear yard fence limit were 7 ft?"
    )
    page.locator('[data-testid="policy-propose-submit"]').click()
    page.wait_for_selector('[data-testid="policy-proposal-changes"]')
    assert_no_horizontal_overflow(page)
    save = page.locator('[data-testid="policy-proposal-save"]')
    assert save.is_visible()
    assert_not_covered(page, save)
    assert page.recorded_errors == []


def test_a_refused_proposal_offers_the_way_back(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """A refused proposal offers the two ways forward and no save."""
    login("persona_city_administrator")
    open_screen(page, server, "/policy/scenarios")
    page.locator('[data-testid="policy-question"]').fill(
        "What if no permit were required for a shed?"
    )
    page.locator('[data-testid="policy-propose-submit"]').click()
    page.wait_for_selector('[data-testid="policy-proposal-rejected"]')
    assert page.locator('[data-testid="policy-proposal-save"]').count() == 0
    assert page.locator('a[href="/policy/scenarios#examples"]').count() == 1
    assert page.locator('a[href="/policy/scenarios#build-whatif"]').count() == 1
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


# ------------------------------------------------------------- the editor


def test_the_editor_fits_a_phone_and_keeps_its_forms(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """The editor fits a phone: the changes, the run settings and the forms."""
    login("persona_city_administrator")
    open_screen(page, server, "/policy/scenarios")
    page.locator('[data-testid="policy-suggestion"]').first.click()
    page.wait_for_url("**/policy/scenarios/polscen_*")
    editor = page.url.split("?")[0]
    page.goto(editor, wait_until="domcontentloaded")
    assert_no_horizontal_overflow(page)
    anchor = page.locator('[data-testid="policy-run-anchor"]')
    assert anchor.is_visible()
    assert_not_covered(page, anchor)
    assert page.locator('[data-testid="policy-run-submit"]').is_visible()
    # The change catalogue is a disclosure, so it is opened before it is used.
    page.locator('details:has([data-testid="policy-add-fee"]) > summary').click()
    assert page.locator('[data-testid="policy-add-fee"]').is_visible()
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


def test_the_editor_saves_a_change_from_a_phone(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """A change can still be added on a phone, and the run button stays honest."""
    login("persona_city_administrator")
    open_screen(page, server, "/policy/scenarios")
    page.locator('[data-testid="policy-suggestion"]').first.click()
    page.wait_for_url("**/policy/scenarios/polscen_*")
    editor = page.url.split("?")[0]
    page.goto(editor, wait_until="domcontentloaded")
    page.locator('details:has([data-testid="policy-add-requirement"]) > summary').click()
    form = page.locator('[data-testid="policy-add-requirement"]')
    form.locator('select[name="permit_type_key"]').select_option("shed")
    form.locator('select[name="item_kind"]').select_option("document")
    form.locator('select[name="action"]').select_option("add")
    form.locator('input[name="item"]').fill("site_plan")
    form.locator('button[type="submit"]').click()
    page.wait_for_load_state("domcontentloaded")
    assert page.locator('[data-testid="policy-change"]').count() == 2
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


# ------------------------------------------------------- the scenarios list


def test_the_scenarios_list_fits_a_phone(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """The list of what-ifs fits a phone and its first action stays reachable."""
    login("persona_city_administrator")
    open_screen(page, server, "/policy/scenarios")
    assert_no_horizontal_overflow(page)
    assert page.locator(".admin-b").count() == 1
    suggestion = page.locator('[data-testid="policy-suggestion"]').first
    assert suggestion.is_visible()
    assert_not_covered(page, suggestion)
    assert page.recorded_errors == []


def test_the_scenarios_list_offers_the_recorded_examples(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """The recorded questions are choices, and the empty form opens when asked."""
    login("persona_city_administrator")
    open_screen(page, server, "/policy/scenarios")
    choice = page.locator('[data-testid="policy-question-choice"]')
    assert choice.count() == 1
    text = choice.inner_text()
    assert "What if the side and rear yard fence limit were 7 ft?" in text
    assert "Example of an unsupported request" in text
    # The disclosure is opened before its control is used.
    page.locator('details:has([data-testid="policy-create-form"]) > summary').click()
    assert page.locator('[data-testid="policy-name"]').is_visible()
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


# ------------------------------------------------ governance and source overview


def test_governance_source_overview_fits_a_phone(
    page, server: BrowserServer, login, viewport_390
) -> None:
    """Source attention and cards fit 390px and remain reachable."""
    login("persona_city_administrator")
    open_screen(page, server, "/governance?tab=sources")
    assert page.locator("h1").inner_text() == "Data sources and ownership"
    assert page.locator('[data-testid="governance-attention"]').count() == 1
    assert page.locator('[data-testid="source-card"]').count() == 3
    fits_a_phone(page)
    assert_not_covered(page, page.locator('[data-testid="source-card"]').last)
    assert page.recorded_errors == []

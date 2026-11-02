"""The browser walkthrough of the screens.

The walkthrough visits every screen, checks that nothing overflows at 390
pixels, that the keyboard reaches the controls and that no page reports an
error.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04, GOV-04, SEC-01
# The screens render, stay inside a 390 pixel viewport, keep their labels and
# their status region, and reach the keyboard controls.

from __future__ import annotations

import sys
from pathlib import Path

from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.nav_expectations import EXPECTED_NAVIGATION  # noqa: E402

#: The screens of the demonstration and the path of their detail.
#:
#: Parity phase 3b added three screens.  They are not in this list: the
#: sweep runs as the City Administrator, and the Administrator holds no
#: grant for them.  Each one is swept as its own persona in
#: ``PERSONA_SCREENS``.
SCREENS = (
    ("/queue", "Work queue"),
    # Changed deliberately (steward restyle): the screens carry their new names.
    ("/applicants", "People and organizations"),
    ("/masters", "Master records"),
    ("/permits/app_synth_001", "Permit workspace"),
    ("/steward", "Data issues"),
    ("/source-records", "Source records"),
    ("/activity", "Activity"),
    ("/rules", "Rules and fees"),
    ("/reconciliation", "Reconciliation"),
    ("/governance", "Governance and sources"),
    # Changed deliberately (the Agent Operator): the two agent screens are
    # opened by the wake and run grants, which the City Administrator no longer
    # holds.  They are swept as their own persona in PERSONA_SCREENS.
    ("/admin", "Administration"),
    ("/insight/city", "City view"),
    ("/policy/scenarios", "What-if"),
    # The planning overview is the City Administrator's home and carries its
    # own grant, so it is swept with the Administrator.
    ("/overview", "Planning overview"),
    # P3c: the four operations screens of the City Administrator.
    ("/ops/dashboard", "Operations"),
    ("/ops/audit", "Audit log"),
    ("/ops/support", "Support"),
    ("/ops/checks", "Checks"),
)

#: The screens that are swept as the persona that owns them.
PERSONA_SCREENS: tuple[tuple[str, str, str], ...] = (
    ("persona_data_steward", "/queue/intake", "Intake queue"),
    ("persona_data_steward", "/queue/early-resolution", "Early resolution"),
    ("persona_permit_reviewer", "/queue/review", "Review queue"),
    # Changed deliberately (the Agent Operator): the two agent screens are
    # opened by the wake and run grants, which the Agent Operator holds.
    ("persona_agent_operator", "/agent/intake", "Intake agent"),
    ("persona_agent_operator", "/agent/adjudication", "Adjudication agent"),
)

#: The screens each persona may open, primary group first, then More tools.
#: Aggregated in tests/support/nav_expectations, one module per persona, so
#: a lane changes its persona's list there and this file stays frozen.
NAVIGATION_BY_PERSONA = EXPECTED_NAVIGATION

#: The screens a persona may not open; each one answers 403.
HIDDEN_SCREENS = {
    "persona_applicant": ["/steward", "/source-records", "/activity", "/masters", "/rules", "/rules-fees", "/reconciliation", "/governance",
                           "/agent/intake", "/agent/adjudication", "/admin",
                           "/queue/intake", "/queue/early-resolution", "/queue/review"],
    # Changed deliberately (the Agent Operator): the wake and run grants moved
    # to the Agent Operator, so the agent screens are closed to the other
    # personas as well.
    "persona_data_steward": ["/reconciliation", "/governance", "/agent/intake", "/agent/adjudication", "/admin",
                              "/queue/review"],
    "persona_permit_reviewer": ["/steward", "/source-records", "/activity", "/masters", "/rules", "/rules-fees", "/reconciliation", "/governance",
                                "/agent/intake", "/agent/adjudication", "/admin",
                                "/queue/early-resolution"],
    "persona_city_administrator": ["/agent/intake", "/agent/adjudication",
                                   "/queue/early-resolution", "/queue/review"],
}
#: P3insight: the City view is held by the City Administrator only.
for _persona in ("persona_applicant", "persona_data_steward", "persona_permit_reviewer"):
    HIDDEN_SCREENS[_persona].append("/insight/city")
#: Policy 2: the What-if screen is held by the City Administrator only.
for _persona in ("persona_applicant", "persona_data_steward", "persona_permit_reviewer"):
    HIDDEN_SCREENS[_persona].append("/policy/scenarios")
#: The planning overview is the City Administrator's own home and carries its
#: own grant, so no other persona may open it.
for _persona in ("persona_applicant", "persona_data_steward", "persona_permit_reviewer"):
    HIDDEN_SCREENS[_persona].append("/overview")
#: P3c: the four operations screens are held by the City Administrator only.
for _persona in ("persona_applicant", "persona_data_steward", "persona_permit_reviewer"):
    HIDDEN_SCREENS[_persona].extend(
        ["/ops/dashboard", "/ops/audit", "/ops/support", "/ops/checks"]
    )


def test_the_screens_render_without_a_page_error(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    for path, title in SCREENS:
        response = page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert response is not None
        assert response.status == 200, path
        assert page.title().startswith(title.split(":")[0]), path
    assert page.recorded_errors == []


def test_the_navigation_holds_the_screens_of_the_persona(
    page, server: BrowserServer, login
) -> None:
    for actor_id, expected in NAVIGATION_BY_PERSONA.items():
        login(actor_id)
        page.goto(f"{server.base_url}/queue", wait_until="domcontentloaded")
        if actor_id == "persona_applicant":
            # Changed deliberately: the Applicant has no staff-layout landing any more; /queue
            # redirects to the City website, which carries no staff navigation.
            assert page.url.rstrip("/").endswith("/city"), page.url
            assert page.locator(".side .app-nav a").count() == 0
            continue
        items = page.locator(".side .app-nav a")
        assert items.count() == len(expected), actor_id
        keys = [items.nth(index).get_attribute("data-screen-key") for index in range(len(expected))]
        assert keys == expected, actor_id


def test_each_new_queue_is_swept_as_its_own_persona(
    page, server: BrowserServer, login
) -> None:
    """The three phase 3b screens are opened by the persona that owns them."""
    for actor_id, path, title in PERSONA_SCREENS:
        login(actor_id)
        response = page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert response is not None
        assert response.status == 200, (actor_id, path)
        assert page.title().startswith(title.split(":")[0]), (actor_id, path)
        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 1, (actor_id, path, overflow)
    assert page.recorded_errors == []


def test_a_hidden_screen_answers_403(page, server: BrowserServer, login) -> None:
    for actor_id, paths in HIDDEN_SCREENS.items():
        login(actor_id)
        for path in paths:
            response = page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
            assert response is not None
            assert response.status == 403, (actor_id, path)


def test_no_screen_overflows_at_390_pixels(page, server: BrowserServer, login) -> None:
    login("persona_city_administrator")
    page.set_viewport_size({"width": 390, "height": 844})
    for path, _title in SCREENS:
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 1, (path, overflow)


def test_no_screen_overflows_on_a_desktop_viewport(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    page.set_viewport_size({"width": 1280, "height": 900})
    for path, _title in SCREENS:
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 1, (path, overflow)


def test_the_keyboard_reaches_the_skip_link_and_the_controls(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/queue", wait_until="domcontentloaded")
    page.keyboard.press("Tab")
    focused = page.evaluate("() => document.activeElement.className")
    assert "skip-link" in focused
    outline = page.evaluate(
        "() => { const style = window.getComputedStyle(document.activeElement);"
        " return style.outlineStyle + ' ' + style.outlineWidth; }"
    )
    assert "none" not in outline
    for _ in range(12):
        page.keyboard.press("Tab")
    tag = page.evaluate("() => document.activeElement.tagName")
    assert tag in {"A", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "SUMMARY"}


def test_every_control_of_a_screen_is_labelled(page, server: BrowserServer, login) -> None:
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/queue", wait_until="domcontentloaded")
    unlabelled = page.evaluate(
        """() => {
            const controls = Array.from(
                document.querySelectorAll('input, select, textarea')
            ).filter((element) => element.type !== 'hidden');
            return controls
                .filter((element) => {
                    if (element.getAttribute('aria-label')) { return false; }
                    if (element.id && document.querySelector(`label[for="${element.id}"]`)) {
                        return false;
                    }
                    return !element.closest('label');
                })
                .map((element) => element.outerHTML.slice(0, 80));
        }"""
    )
    assert unlabelled == []


def test_the_live_region_announces_the_outcome(
    page, server: BrowserServer, login
) -> None:
    """The hidden region speaks the result, the panel holds it."""
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    region = page.locator('[data-testid="feedback-live"]')
    assert region.count() == 1
    assert region.get_attribute("role") == "status"
    assert region.get_attribute("aria-live") == "polite"
    assert region.get_attribute("aria-atomic") == "true"
    # The region is hidden from the eye, not from the screen reader.
    box = region.bounding_box()
    assert box is not None
    assert box["width"] <= 1 and box["height"] <= 1, box
    # The panel of the last action holds the result and opens from the bell.
    panel = page.locator('[data-testid="feedback"]')
    assert panel.count() == 1
    assert panel.get_attribute("role") == "dialog"
    assert panel.get_attribute("hidden") is not None
    bell = page.locator('[data-testid="last-action-toggle"]')
    assert bell.count() == 1
    assert bell.get_attribute("aria-controls") == "ui-feedback-panel"
    assert bell.get_attribute("aria-expanded") == "false"


def test_the_evidence_and_history_panels_stay_present(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    # Changed deliberately (steward restyle): the steward's collection screens
    # (Master records, Data issues, Source records, Activity) no longer end with a
    # collection-wide "No evidence is recorded" panel.  Evidence lives in the
    # selected record or case, so those screens are swept as a record's Sources
    # view and as a focused case instead (below).
    # Changed deliberately (demo polish, AD1): the administration screen carries
    # its history in its Configuration log tab, so it has no panels of its own.
    collection_screens = {
        "/applicants",
        "/masters",
        "/steward",
        "/source-records",
        "/activity",
        "/admin",
    }
    # Changed deliberately (demo polish, AD2): the what-if list drops the
    # evidence panel. The decision is the saved what-if and the run.
    # Changed deliberately (demo polish, AD3): insight, rules and the
    # operations screens drop the panel too.
    no_evidence = {
        "/policy/scenarios",
        "/insight/city",
        "/rules",
        "/ops/dashboard",
        "/ops/audit",
        "/ops/support",
        "/ops/checks",
    }
    for path, _title in SCREENS:
        if path in collection_screens:
            continue
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        if path in no_evidence:
            assert page.locator('[data-testid="evidence-panel"]').count() == 0, path
            continue
        assert page.locator('[data-testid="evidence-panel"]').count() == 1, path
    page.goto(
        f"{server.base_url}/masters/party_cedarline?view=sources", wait_until="domcontentloaded"
    )
    assert page.locator('[data-testid="evidence-panel"]').count() == 1
    page.goto(f"{server.base_url}/masters", wait_until="domcontentloaded")
    assert page.locator('[data-testid="evidence-panel"]').count() == 0


def test_the_history_panel_stays_present_on_the_record_screens(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    # Changed deliberately (steward restyle): a record's history is its History
    # view, and the Data issues queue itself carries no history (a focused case
    # lists what happened).
    for path in ("/permits/app_synth_001", "/applicants/party_cedarline?view=history"):
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert page.locator('[data-testid="history-panel"]').count() == 1, path


def test_the_footer_states_that_the_data_is_fictional(
    page, server: BrowserServer, login
) -> None:
    # Changed deliberately (staff frame, S1): the banner is gone and the
    # disclosure is one line in the footer.
    login("persona_city_administrator")
    page.goto(f"{server.base_url}/queue", wait_until="domcontentloaded")
    assert page.locator('[data-testid="demo-banner"]').count() == 0
    footer = page.locator('[data-testid="app-footer"]').inner_text()
    assert "Fictional City of Acme demonstration" in footer
    assert "Westerville" not in footer


def test_the_queue_fits_a_phone_and_no_fixed_layer_covers_it(
    viewport_390, server: BrowserServer, login
) -> None:
    """Smoke test of the shared 390 pixel helpers on the work queue."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue", wait_until="load")
    assert page.viewport_size == {"width": 390, "height": 844}
    assert_no_horizontal_overflow(page)
    assert page.locator(".mobile-nav").is_visible()
    # Changed deliberately (persona switcher, S4): the switcher is the chip in
    # the top bar, not a floating control in the corner.
    assert page.locator('[data-testid="persona-trigger"]').is_visible()
    assert_not_covered(page, page.locator("main h1").first)
    # Changed deliberately (steward restyle, STW-2): the Data Steward groups
    # its secondary tools under More tools, so the bar entry that is checked is
    # its own work queue and not the permit queue.
    assert_not_covered(page, page.locator('.mobile-nav a[href="/steward"]'))
    assert page.recorded_errors == []

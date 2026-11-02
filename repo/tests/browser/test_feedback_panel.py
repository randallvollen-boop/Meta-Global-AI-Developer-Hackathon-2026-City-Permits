"""The panel of the last action: the bell, the toast and the screen reader.

The result of an action does not stand at the top of the screen any more.
A bell in the header carries it, a dot marks a result that has not been
opened yet, a toast shows the one line of the result for a moment, and a
hidden region announces every result to a screen reader.  A refusal is shown
without a click, and the panel is a full-width sheet on a phone.
"""
# REQUIRES: UX-01, UX-02, UX-04

from __future__ import annotations

from conftest import BrowserServer, assert_no_horizontal_overflow


def overlaps(a: dict, b: dict) -> bool:
    """Say whether two boxes share any ground."""
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


def toast_is_on(page) -> bool:
    """Say whether the toast stands on the screen."""
    classes = page.locator("#toast").get_attribute("class") or ""
    return "on" in classes.split()


def bell_expanded(page) -> str:
    """Return the state of the bell of the last action."""
    return page.locator('[data-testid="last-action-toggle"]').get_attribute("aria-expanded")


def test_an_action_marks_the_bell_and_shows_a_toast(
    page, server: BrowserServer, login, submit_action
) -> None:
    """The bell carries a dot and the toast shows the one line of the result."""
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    bell = page.locator('[data-testid="last-action-toggle"]')
    dot = page.locator('[data-testid="last-action-dot"]')
    assert bell.count() == 1
    # Nothing has happened yet, so the bell carries no dot.
    assert not dot.is_visible()

    message = submit_action("permit.evaluate", {"application_id": "app_synth_001"})
    assert message.strip()
    # The dot marks the result that has not been opened yet.
    assert dot.is_visible()
    # The toast shows the one line of the result.
    assert toast_is_on(page)
    assert message.strip() in page.locator("#toast").inner_text()


def test_the_toast_of_an_action_hides_itself_again(
    page, server: BrowserServer, login, submit_action
) -> None:
    """The toast is brief: it goes away on its own."""
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    submit_action("permit.evaluate", {"application_id": "app_synth_001"})
    # The toast goes away on its own, without a click.
    page.wait_for_function(
        "() => !document.getElementById('toast').classList.contains('on')",
        timeout=15_000,
    )
    assert not toast_is_on(page)


def test_the_panel_shows_the_message_and_the_more_details(
    page, server: BrowserServer, login, submit_action
) -> None:
    """The bell opens the panel, and the panel holds the result and its detail."""
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    message = submit_action("permit.evaluate", {"application_id": "app_synth_001"})

    panel = page.locator('[data-testid="feedback"]')
    assert not panel.is_visible()
    page.locator('[data-testid="last-action-toggle"]').click()
    panel.wait_for(state="visible")
    assert bell_expanded(page) == "true"
    assert message.strip() in panel.locator('[data-testid="feedback-message"]').inner_text()

    # The detail list sits behind one disclosure in the panel.
    more = panel.locator('[data-testid="feedback-more"]')
    assert more.count() == 1
    assert "More details" in more.inner_text()
    for name in (
        "feedback-destination",
        "feedback-state",
        "feedback-pending",
        "feedback-version",
        "feedback-affected",
    ):
        assert more.locator(f'[data-testid="{name}"]').count() == 1, name
    more.locator("summary").click()
    assert more.locator('[data-testid="feedback-destination"]').inner_text().strip()

    # The result has been seen, so the dot is gone.
    assert not page.locator('[data-testid="last-action-dot"]').is_visible()


def test_a_refused_action_is_shown_without_a_click(
    page, server: BrowserServer, login, submit_action
) -> None:
    """A refusal opens the panel on the spot and its toast stays."""
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    # The record moves on elsewhere, so the write of the screen is stale and
    # the server refuses it.
    evaluated = page.request.post(
        f"{server.base_url}/api/permits/applications/app_synth_001/evaluate"
    )
    assert evaluated.ok, evaluated.text()
    message = submit_action(
        "permit.decide",
        {
            "application_id": "app_synth_001",
            "outcome": "approved",
            "reason": "a decision against a version that has moved on",
        },
    )
    assert "changed since it was read" in message

    # The panel is open without a click and it carries the refusal.
    panel = page.locator('[data-testid="feedback"]')
    assert panel.is_visible()
    assert panel.get_attribute("data-outcome") == "denied"
    assert message.strip() in panel.locator('[data-testid="feedback-message"]').inner_text()
    assert bell_expanded(page) == "true"

    # The toast of a refusal stays until it is dismissed.
    assert toast_is_on(page)
    assert message.strip() in page.locator("#toast").inner_text()
    page.locator('[data-testid="toast-dismiss"]').click()
    assert not toast_is_on(page)


def test_the_screen_reader_region_hears_every_result(
    page, server: BrowserServer, login, submit_action
) -> None:
    """The hidden region carries the result of the action."""
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    live = page.locator('[data-testid="feedback-live"]')
    assert live.count() == 1
    assert live.get_attribute("role") == "status"
    assert live.get_attribute("aria-live") == "polite"
    assert live.get_attribute("aria-atomic") == "true"
    # The region is hidden from the eye, not from the screen reader.
    box = live.bounding_box()
    assert box is not None
    assert box["width"] <= 1 and box["height"] <= 1, box

    message = submit_action("permit.evaluate", {"application_id": "app_synth_001"})
    assert live.text_content().strip() == message.strip()


def test_the_panel_is_operable_with_the_keyboard(
    page, server: BrowserServer, login
) -> None:
    """The bell opens the panel, Escape closes it and the focus comes back."""
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    bell = page.locator('[data-testid="last-action-toggle"]')
    panel = page.locator('[data-testid="feedback"]')
    bell.focus()
    page.keyboard.press("Enter")
    panel.wait_for(state="visible")
    assert bell_expanded(page) == "true"
    # The focus is inside the panel, so a screen reader reads the result.
    assert (
        page.evaluate("() => document.activeElement.getAttribute('data-testid')")
        == "feedback-panel-title"
    )

    page.keyboard.press("Escape")
    panel.wait_for(state="hidden")
    assert bell_expanded(page) == "false"
    # The focus is back on the bell that opened the panel.
    assert (
        page.evaluate("() => document.activeElement.getAttribute('data-testid')")
        == "last-action-toggle"
    )


def test_the_panel_is_a_full_width_sheet_on_a_phone(
    viewport_390, server: BrowserServer, login, submit_action
) -> None:
    """On a phone the panel is a sheet of the full width above the bar."""
    page = viewport_390
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    # The action is performed on a wide screen; the panel is measured on the
    # phone.
    page.set_viewport_size({"width": 1280, "height": 900})
    submit_action("permit.evaluate", {"application_id": "app_synth_001"})
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator('[data-testid="last-action-toggle"]').click()
    panel = page.locator('[data-testid="feedback"]')
    panel.wait_for(state="visible")
    box = panel.bounding_box()
    assert box is not None
    assert box["x"] <= 1
    assert box["width"] >= 389
    # The bar of the screens at the bottom stays free.
    bar = page.locator(".mobile-nav").bounding_box()
    assert bar is not None
    assert box["y"] + box["height"] <= bar["y"] + 1, (box, bar)
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


def test_the_toast_does_not_cover_the_persona_controls(
    page, server: BrowserServer, login
) -> None:
    """The toast stands beside the header, and the menu of the chip is above it."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue", wait_until="domcontentloaded")
    page.evaluate(
        "() => { const t = document.getElementById('toast');"
        " t.textContent = 'Saved. A message that is long enough to wrap on a narrow screen.';"
        " t.classList.add('on'); }"
    )
    page.wait_for_timeout(300)
    toast = page.locator("#toast").bounding_box()
    assert toast is not None
    for selector in (
        '[data-testid="persona-trigger"]',
        '[data-testid="last-action-toggle"]',
    ):
        box = page.locator(selector).bounding_box()
        assert box is not None, selector
        assert not overlaps(toast, box), (selector, toast, box)
    # The menu of the chip paints above the toast, so it keeps its clicks.
    layers = page.evaluate(
        "() => ({ toast: parseInt(getComputedStyle(document.getElementById('toast')).zIndex, 10),"
        " menu: parseInt(getComputedStyle(document.querySelector('.account-panel')).zIndex, 10) })"
    )
    assert layers["menu"] > layers["toast"], layers


def test_the_panel_paints_above_the_other_overlays(
    page, server: BrowserServer, login
) -> None:
    """The panel stands on the layer of the scale, above the other overlays."""
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    page.locator('[data-testid="last-action-toggle"]').click()
    page.locator('[data-testid="feedback"]').wait_for(state="visible")
    layers = page.evaluate(
        """() => {
            const root = getComputedStyle(document.documentElement);
            const names = ["--z-toast", "--z-scrim", "--z-help-sheet", "--z-drawer",
                           "--z-popover", "--z-tour", "--z-persona-menu"];
            const out = {};
            for (const name of names) {
                out[name] = parseInt(root.getPropertyValue(name), 10);
            }
            out.panel = parseInt(
                getComputedStyle(document.querySelector('[data-testid="feedback"]')).zIndex, 10
            );
            return out;
        }"""
    )
    # Above the toast, the scrim, the help sheet and the detail drawer.
    assert layers["panel"] > layers["--z-toast"], layers
    assert layers["panel"] > layers["--z-scrim"], layers
    assert layers["panel"] > layers["--z-help-sheet"], layers
    assert layers["panel"] > layers["--z-drawer"], layers
    # Below the popover, the guided tour and the open persona menu.
    assert layers["panel"] < layers["--z-popover"], layers
    assert layers["panel"] < layers["--z-tour"], layers
    assert layers["panel"] < layers["--z-persona-menu"], layers

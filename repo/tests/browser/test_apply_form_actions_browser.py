"""The actions of the application form: one tidy row that works.

The applicant ends the form with four controls: the check of the
application, the submit, the draft and the way back to the chooser.  The
submit is the primary action; the draft and the change of project are the
quiet ones.  They share one row on a desktop, they wrap cleanly on a phone,
and each one does what its name says.
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

from conftest import BrowserServer, assert_no_horizontal_overflow

#: The four controls of the action row of the application form.
CONTROLS = (
    '[data-testid="check-application"]',
    '[data-testid="submit-application"]',
    '[data-testid="save-draft"]',
    '[data-testid="change-project"]',
)


def _boxes(page) -> list[dict]:
    """Return the box of every control of the action row."""
    boxes = []
    for selector in CONTROLS:
        box = page.locator(selector).bounding_box()
        assert box is not None, selector
        boxes.append(box)
    return boxes


def test_the_actions_of_the_form_share_one_row_at_1280(page, server: BrowserServer, login) -> None:
    """On a desktop the four controls stand in one row of one height."""
    login("persona_applicant")
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    boxes = _boxes(page)
    tops = {round(box["y"]) for box in boxes}
    assert len(tops) == 1, boxes
    heights = {round(box["height"]) for box in boxes}
    assert len(heights) == 1, boxes
    # The controls do not sit on top of one another.
    for index in range(len(boxes) - 1):
        first, second = boxes[index], boxes[index + 1]
        assert first["x"] + first["width"] <= second["x"] + 1, boxes
    assert page.recorded_errors == []


def test_the_actions_of_the_form_wrap_cleanly_at_390(page, server: BrowserServer, login) -> None:
    """On a phone the row wraps and nothing leaves the screen."""
    login("persona_applicant")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    assert_no_horizontal_overflow(page)
    boxes = _boxes(page)
    for box in boxes:
        assert box["x"] >= 0, box
        assert box["x"] + box["width"] <= 390, box
    # Every row of the wrapped action row holds controls of one height.
    rows: dict[int, list[dict]] = {}
    for box in boxes:
        rows.setdefault(round(box["y"]), []).append(box)
    for top, row in rows.items():
        heights = {round(item["height"]) for item in row}
        assert len(heights) == 1, (top, row)
    assert page.recorded_errors == []


def test_the_draft_and_the_change_are_quiet_and_the_submit_is_primary(
    page, server: BrowserServer, login
) -> None:
    """The submit keeps the fill of the primary button; the other two are quiet."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    submit = page.locator('[data-testid="submit-application"]')
    save = page.locator('[data-testid="save-draft"]')
    change = page.locator('[data-testid="change-project"]')
    assert "primary" in (submit.get_attribute("class") or "")
    assert "button-quiet" in (save.get_attribute("class") or "")
    assert "button-quiet" in (change.get_attribute("class") or "")
    # The change of project is a link that looks like the quiet button.
    assert change.evaluate("element => element.tagName") == "A"
    assert save.evaluate("element => element.tagName") == "BUTTON"
    fills = {}
    for name, locator in (("submit", submit), ("save", save), ("change", change)):
        fills[name] = locator.evaluate(
            "element => { const style = getComputedStyle(element);"
            " return [style.backgroundColor, style.color, style.borderTopColor,"
            " element.getBoundingClientRect().height].join('|'); }"
        )
    assert fills["save"] == fills["change"], fills
    assert fills["save"] != fills["submit"], fills


def test_saving_the_draft_saves_it(page, server: BrowserServer, login) -> None:
    """The draft is saved and the applicant is told where it went."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    page.fill("#f-applicant_name", "Dana Rivers")
    page.fill("#f-applicant_email", "dana.rivers@example.invalid")
    page.locator('[data-testid="save-draft"]').click()
    page.wait_for_url(lambda url: "/apply/track" in url and "saved=" in url)
    toast = page.locator('[data-testid="draft-saved"]')
    assert toast.count() == 1
    assert "was saved" in toast.inner_text()
    assert page.recorded_errors == []


def test_the_change_of_project_returns_to_the_chooser(page, server: BrowserServer, login) -> None:
    """The quiet control that changes the project lands on the chooser."""
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    page.locator('[data-testid="change-project"]').click()
    page.wait_for_url(f"{server.base_url}/apply")
    assert page.locator('[data-testid="chooser-title"]').count() == 1
    assert page.recorded_errors == []

"""The persona selector explains each persona and fits a phone."""

from __future__ import annotations

from conftest import BrowserServer, assert_no_horizontal_overflow

#: The five personas of the landing, in the order of the story, with the one
#: line each card shows about the job.
PERSONAS = (
    ("Applicant", "A resident who applies for a permit and tracks it."),
    ("Agent Operator", "Runs the agents that read and route new applications."),
    ("Data Steward", "Links people and properties so every record matches."),
    ("Permit Reviewer", "Checks each case and records the decision."),
    ("City Administrator", "Sets the rules and fees and watches the whole system."),
)


def test_each_persona_card_says_who_and_what_and_fits_390px(page, server: BrowserServer) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    cards = page.locator('[data-testid="persona-card"]')
    assert cards.count() == 5
    tops = []
    for index in range(cards.count()):
        card = cards.nth(index)
        assert card.locator(".persona-who").count() == 1
        assert card.locator(".persona-does").count() == 1
        assert card.locator("button[data-persona]").count() == 1
        box = card.bounding_box()
        line = card.locator('[data-testid="persona-line"]').bounding_box()
        assert box is not None and line is not None
        assert box["x"] >= -1
        assert box["x"] + box["width"] <= 391
        assert line["x"] + line["width"] <= box["x"] + box["width"] + 1
        tops.append(box["y"])
    # One column: each card sits under the one above it.
    assert tops == sorted(tops)
    assert len({round(top) for top in tops}) == 5, tops
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert_no_horizontal_overflow(page)
    assert page.recorded_errors == []


def test_each_persona_card_shows_its_role_icon(page, server: BrowserServer) -> None:
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    icons = page.locator('[data-testid="persona-card"] img.persona-icon')
    assert icons.count() == 5
    for index in range(icons.count()):
        assert icons.nth(index).evaluate("img => img.complete && img.naturalWidth > 0")


def test_each_card_shows_one_line_about_the_persona(page, server: BrowserServer) -> None:
    """Every card says in one sentence who the person is and what they do here."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    cards = page.locator('[data-testid="persona-card"]')
    assert cards.count() == len(PERSONAS)
    for index, (label, expected) in enumerate(PERSONAS):
        card = cards.nth(index)
        lines = card.locator('[data-testid="persona-line"]')
        assert lines.count() == 1, label
        line = lines.first
        assert line.is_visible(), label
        # The copy is one paragraph of one sentence, not three.
        assert line.evaluate("element => element.tagName") == "P", label
        assert line.evaluate(
            "element => element.childNodes.length === 1"
            " && element.childNodes[0].nodeType === Node.TEXT_NODE"
        ), label
        source = line.evaluate("element => element.textContent")
        assert source == expected, label
        assert "\n" not in source, (label, source)
        visible = " ".join(line.inner_text().split())
        assert visible == expected, label
        assert visible.endswith("."), (label, visible)


def test_the_card_keeps_its_hover_text_and_its_description(page, server: BrowserServer) -> None:
    """The line on the card does not take the hover text or the description."""
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    cards = page.locator('[data-testid="persona-card"]')
    for index, (label, _expected) in enumerate(PERSONAS):
        card = cards.nth(index)
        assert card.get_attribute("title"), label
        button = card.locator("button[data-persona]")
        described = button.get_attribute("aria-describedby")
        assert described, label
        parts = described.split()
        assert len(parts) == 3, label
        for part in parts:
            assert card.locator(f"#{part}").count() == 1, (label, part)


def test_the_five_cards_stay_in_one_row_at_1280(page, server: BrowserServer) -> None:
    """The line of a persona does not push the cards out of one row."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    cards = page.locator('[data-testid="persona-card"]')
    tops = []
    for index in range(cards.count()):
        box = cards.nth(index).bounding_box()
        assert box is not None
        tops.append(round(box["y"]))
    assert len(set(tops)) == 1, tops
    # The five lines of the row fit beside the five cards, not below them.
    lines = page.locator('[data-testid="persona-line"]')
    for index in range(lines.count()):
        box = lines.nth(index).bounding_box()
        card = cards.nth(index).bounding_box()
        assert box is not None and card is not None
        assert box["x"] + box["width"] <= card["x"] + card["width"] + 1
    assert page.recorded_errors == []

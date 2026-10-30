"""Help assertions of the admin_b lane (the shared test_help_docs.py is frozen).

The lane renamed three labels of the what-if screens: the examples are now
"Start from an example", the empty form is "Build a what-if" and the run is
"Run comparison".  The help text quotes the labels of the screens, so it has
to follow them.  The words live in the overlay of the lane, because the shared
help file is frozen.

The results page was reorganised next: the screen is called "Scenario
results", the briefing is opened with "Read briefing", the outcome table is
"Recommended outcomes", the changed cases are "Cases that change" and the
draft handoff is "Draft handoff".  The help text quotes those labels too.
"""
# REQUIRES: UX-01

from __future__ import annotations

from acme_city.help_docs import content


def _administrator_steps() -> str:
    sections = content.tutorial()["sections"]
    section = next(s for s in sections if s["persona_id"] == "persona_city_administrator")
    return " ".join(f"{step['do']} {step['see']}" for step in section["steps"])


def test_the_tutorial_names_the_labels_the_screens_show() -> None:
    steps = _administrator_steps()
    assert "Run comparison" in steps
    assert "Start from an example" in steps
    assert "Run what-if" not in steps
    assert "Read briefing" in steps
    assert "Try recorded Muse briefing" in steps
    assert "Write the briefing with Muse" not in steps
    assert 'label "Recorded Muse briefing"' in steps
    assert "Legislator briefing" not in steps


def test_the_what_if_guide_names_the_labels_the_screens_show() -> None:
    guide = content.guide("run-a-what-if-and-write-the-briefing")
    assert guide is not None
    steps = " ".join(guide["steps"])
    assert "Run comparison" in steps
    assert "Build a what-if" in steps
    assert "Run what-if" not in steps
    assert "Or start empty" not in steps
    assert "Read briefing" in steps
    assert "Try recorded Muse briefing" in steps
    assert "Write the briefing with Muse" not in steps
    assert "Download HTML" in steps
    assert "Download Markdown" in steps
    assert "Download (HTML)" not in steps
    assert "Download (Markdown)" not in steps
    assert "Legislator briefing" not in steps
    assert "Recommended outcomes" in steps
    assert "Recommendation by outcome, baseline and scenario" not in steps


def test_the_approve_guide_names_the_draft_handoff_the_results_page_shows() -> None:
    guide = content.guide("propose-and-approve-a-rule-change")
    assert guide is not None
    steps = " ".join(guide["steps"])
    assert "Draft handoff" in steps
    assert "Path to a real change" not in steps

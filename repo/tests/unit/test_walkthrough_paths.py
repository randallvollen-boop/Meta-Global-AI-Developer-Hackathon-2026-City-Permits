"""The paths of the walkthrough: their words, their labels and their codes.

Each path is one journey.  Each step of a path says in one sentence what to
do and in one sentence what to notice.  The words of a step name the labels
of the application as they are on the screen, and they never name an
internal code.
"""
# REQUIRES: UX-04
# The written steps are short, plain and exact.

from __future__ import annotations

import re
from pathlib import Path

from acme_city.ui import guide_views

#: The repository root of the application.
ROOT = Path(__file__).resolve().parents[2]

#: The files that hold the words of the interface.  The walkthrough itself is
#: left out: it is the text under test, not the text under test's subject.
SOURCES = (
    ROOT / "src" / "acme_city" / "templates",
    ROOT / "src" / "acme_city" / "ui",
    ROOT / "src" / "acme_city" / "registry",
    ROOT / "src" / "acme_city" / "agents",
    ROOT / "src" / "acme_city" / "permits",
    ROOT / "config",
)

#: The file of the walkthrough, which is not a source of a label.
EXCLUDED = (
    "guide_views.py",
    "tour_steps.json",
)

#: The labels the steps name.  Every one of them is on a screen of the
#: application, spelled the way the screen spells it.
#:
#: The labels of the pre-submit check are named by the resident path and they
#: are built by the lane of the pre-submit check.  This lane does not assert
#: them: the other lane proves that they are on the screen.
#:
#: The button that accepts every recommendation the assistant is sure of
#: carries the count of them, so the steps name it with the same (N) the
#: guides of the City use.
LABELS = (
    "Data issues",
    "Prepare recommendations",
    "Accept recommendation",
    "High",
    "Wake agent",
    "Process one",
    "Run checks again",
    "Use a sample address",
    "Stage",
    "Next action",
    "Checks (3 of 6)",
    "Ready to decide",
    "Ready to issue",
    "Waiting on Data Steward",
    "Needs checks",
    "Fee not settled",
    "In early resolution",
    "Submitted with known issues",
    "Data follow-up",
    "Messages from the City",
    "Recommend deny",
    "Exception reason",
    "Needs information",
    "Steward assistant",
    "Put to sleep",
    "Ask Muse to propose",
    "Create a what-if",
    "Rules and fees",
    "Search for my permit",
    "Run application checks",
    "Record review decision",
    "Confirm parcel",
    "Approve",
    "Issue permit",
    "Assess application",
    "Confirm allocation",
    "Reconcile assessment",
    "Reconciliation",
    "Ready for review",
    "Building",
    "Passed",
    "Recorded permit decision",
    "Apply filters",
    "View details",
    "What-if",
    "Residential deck or fence",
    "Submit application",
    "Track application",
    "Early resolution",
    "Start",
)

#: The shapes of an internal code.  The written steps never name one.
CODE_PATTERNS = (
    re.compile(r"\b[a-z]+\.[a-z][a-z_.]*\b"),
    re.compile(r"\b[a-z]+_[a-z_]+\b"),
    re.compile(r"\b(?:PER|ERP|CAFE|SYN)-[A-Z0-9-]+\b"),
)


def application_words() -> str:
    """Return every word the application shows."""
    parts: list[str] = []
    for source in SOURCES:
        for path in source.rglob("*"):
            if not path.is_file() or path.suffix not in {".html", ".py", ".json", ".js"}:
                continue
            if path.name in EXCLUDED:
                continue
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def every_step() -> list[tuple[str, guide_views.Step]]:
    """Return every step of every path, with the key of its path."""
    return [
        (path.key, step) for path in guide_views.PATHS for step in path.steps
    ]


def test_the_paths_hold_a_key_a_title_a_line_and_a_length() -> None:
    keys = [path.key for path in guide_views.PATHS]
    assert keys, "the walkthrough holds no path"
    assert len(keys) == len(set(keys))
    for path in guide_views.PATHS:
        assert re.fullmatch(r"[a-z]+", path.key), path.key
        assert path.title.strip(), path.key
        assert path.one_line.strip(), path.key
        assert path.minutes > 0, path.key
        assert path.steps, path.key


def test_every_step_says_one_sentence_to_do_and_one_to_notice() -> None:
    """A step is short: one sentence to do, one sentence to notice."""
    for key, step in every_step():
        for field, text in (("do", step.do), ("look_for", step.look_for), ("why", step.why)):
            assert text.strip(), (key, step.title, field)
            assert text.endswith("."), (key, step.title, field)
            assert ". " not in text, (key, step.title, field)
            assert "?" not in text, (key, step.title, field)
            assert "!" not in text, (key, step.title, field)


def test_no_step_uses_a_dash_as_punctuation() -> None:
    """The words of a step are plain: no dash stands in for a pause."""
    for key, step in every_step():
        for field, text in (("do", step.do), ("look_for", step.look_for), ("why", step.why)):
            assert "—" not in text, (key, step.title, field)
            assert "–" not in text, (key, step.title, field)
            assert " - " not in text, (key, step.title, field)


def test_no_step_names_an_internal_code() -> None:
    """A judge reads the steps, so they never name a code of the City."""
    for key, step in every_step():
        for field, text in (("do", step.do), ("look_for", step.look_for), ("why", step.why)):
            for pattern in CODE_PATTERNS:
                assert not pattern.search(text), (key, step.title, field, text)


def test_the_steps_name_the_labels_of_the_application() -> None:
    """Every label the steps name is on a screen, spelled the same way."""
    words = application_words()
    for label in LABELS:
        assert label in words, label


def test_the_paths_use_the_personas_of_the_city() -> None:
    """Every step names a persona of the City, or nobody at all."""
    personas = {
        "Applicant",
        "Agent Operator",
        "Data Steward",
        "Permit Reviewer",
        "City Administrator",
    }
    for key, step in every_step():
        if step.persona:
            assert step.persona in personas, (key, step.title, step.persona)
        assert step.path.startswith("/"), (key, step.title, step.path)


def test_the_café_path_walks_the_whole_journey() -> None:
    """The café path holds the six steps of the journey of one permit."""
    path = guide_views.path_by_key("cafe")
    assert path is not None
    assert len(path.steps) == 6
    assert [step.persona for step in path.steps] == [
        "Data Steward",
        "Agent Operator",
        "Permit Reviewer",
        "City Administrator",
        "Permit Reviewer",
        "",
    ]


def test_each_track_names_where_its_story_starts() -> None:
    """Each of the three tracks says who the person is and why the case starts."""
    for key in ("resident", "cafe", "city"):
        path = guide_views.path_by_key(key)
        assert path is not None
        assert path.story.strip(), key
        assert path.story.endswith("."), key
        assert "—" not in path.story and "–" not in path.story and " - " not in path.story
        for pattern in CODE_PATTERNS:
            assert not pattern.search(path.story), (key, path.story)
    resident = guide_views.path_by_key("resident")
    assert resident is not None
    assert "fence" in resident.story
    assert "back yard" in resident.story
    before = guide_views.path_by_key("before")
    assert before is not None
    assert before.story == ""


def test_the_paths_are_the_four_the_plan_names() -> None:
    assert [path.key for path in guide_views.PATHS] == [
        "resident",
        "cafe",
        "city",
        "before",
    ]

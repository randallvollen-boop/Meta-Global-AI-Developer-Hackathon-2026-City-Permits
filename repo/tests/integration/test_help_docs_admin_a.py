"""Help assertions of the admin_a lane (the shared test_help_docs.py is frozen).

The lane writes its help text in ``config/help_content.d/admin_a.json`` and
checks it here, so a label that moves on a screen and a help text that names
it cannot drift apart.
"""
# REQUIRES: UX-01

from __future__ import annotations

from acme_city.help_docs import content


def test_the_operations_guide_names_the_labels_the_dashboard_shows() -> None:
    guide = content.guide("read-the-operations-dashboard-and-audit-log")
    assert guide is not None
    steps = " ".join(guide["steps"])
    # The guide names the switch of the scope statement, in the words the
    # dashboard shows.
    assert '"Include the sample history"' in steps
    assert '"Leave the sample history out"' in steps
    # The guide names the parts of the dashboard a reader is sent to, in the
    # words the screen shows.
    assert '"Current workload"' in steps
    assert '"Recorded processing"' in steps
    assert '"Decisions recorded, by outcome"' in steps
    assert '"View details"' in steps
    assert '"Support"' in steps
    assert '"Send reply"' in steps


def test_the_operations_guide_says_each_thing_once() -> None:
    guide = content.guide("read-the-operations-dashboard-and-audit-log")
    assert guide is not None
    steps = guide["steps"]
    # Every step says something the reader does not read in another step.
    assert len(steps) == len(set(steps))
    # The filters are named once, and the event details once.
    assert sum("Apply filters" in step for step in steps) == 1
    assert sum("View details" in step for step in steps) == 1


def test_the_operations_guide_covers_the_support_screen_it_names() -> None:
    guide = content.guide("read-the-operations-dashboard-and-audit-log")
    assert guide is not None
    assert "support" in guide["title"].lower()

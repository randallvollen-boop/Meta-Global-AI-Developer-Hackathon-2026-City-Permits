"""The judge walkthrough document says what the /walkthrough page says."""
# REQUIRES: UX-04
# The submission copy of the walkthrough cannot drift from the in-app steps.

from __future__ import annotations

from pathlib import Path

from acme_city.ui.guide_views import WALKTHROUGH

DOC = Path(__file__).resolve().parents[3] / "docs" / "submission" / "JUDGE_WALKTHROUGH.md"


def test_the_document_lists_every_step_in_order_with_its_words() -> None:
    text = DOC.read_text(encoding="utf-8")
    position = 0
    for number, step in enumerate(WALKTHROUGH, start=1):
        heading = f"## {number}. {step.title}"
        assert heading in text, heading
        assert text.index(heading) > position, heading
        position = text.index(heading)
        for phrase in (step.path, step.do, step.look_for):
            assert phrase in text, f"{heading}: {phrase}"
    assert text.count("\n## ") == len(WALKTHROUGH)

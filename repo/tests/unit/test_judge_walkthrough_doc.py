"""The judge walkthrough document says what the /walkthrough page says."""
# REQUIRES: UX-04
# The submission copy of the walkthrough cannot drift from the in-app steps.

from __future__ import annotations

import re
from pathlib import Path

from acme_city.ui.guide_views import WALKTHROUGH

DOC = Path(__file__).resolve().parents[3] / "docs" / "submission" / "JUDGE_WALKTHROUGH.md"


def test_the_document_lists_every_step_in_order_with_its_words() -> None:
    text = DOC.read_text(encoding="utf-8")
    headings = list(re.finditer(r"^## .*$", text, flags=re.M))
    numbered = [match for match in headings if re.match(r"## \d+\. ", match.group(0))]
    assert len(numbered) == len(WALKTHROUGH)
    for number, (step, match) in enumerate(zip(WALKTHROUGH, numbered), start=1):
        assert match.group(0) == f"## {number}. {step.title}"
        following = [other.start() for other in headings if other.start() > match.start()]
        body = text[match.end() : following[0] if following else len(text)]
        for phrase in (step.path, step.do, step.look_for):
            assert phrase in body, f"step {number}: {phrase}"
        if step.persona:
            assert f"As **{step.persona}**" in body, f"step {number}: persona"

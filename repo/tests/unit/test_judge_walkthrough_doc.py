"""The judge walkthrough document says what the /walkthrough page says.

The document of the submission is generated from the paths of the page, so
the two cannot drift apart: this test fails when the file on disk differs
from the words the page holds.
"""
# REQUIRES: UX-04
# The submission copy of the walkthrough cannot drift from the in-app steps.

from __future__ import annotations

import re
from pathlib import Path

from acme_city.ui.guide_views import PATHS, walkthrough_markdown

DOC = Path(__file__).resolve().parents[3] / "docs" / "submission" / "JUDGE_WALKTHROUGH.md"


def test_the_document_is_exactly_the_words_of_the_page() -> None:
    """The document is the page, word for word."""
    assert DOC.read_text(encoding="utf-8") == walkthrough_markdown()


def test_the_document_holds_every_path_with_its_steps() -> None:
    text = DOC.read_text(encoding="utf-8")
    headings = [match.group(0) for match in re.finditer(r"^## .*$", text, flags=re.M)]
    paths = [heading for heading in headings if heading[3:] in {path.title for path in PATHS}]
    assert len(paths) == len(PATHS)
    assert paths == [f"## {path.title}" for path in PATHS]
    for path in PATHS:
        assert f"## {path.title}" in text
        assert path.one_line in text
        if path.story:
            assert path.story in text
        for number, step in enumerate(path.steps, start=1):
            assert f"### {number}. {step.title}" in text
            assert step.do in text
            assert step.look_for in text
            assert step.why in text
            if step.persona:
                assert f"As **{step.persona}**" in text


def test_the_document_names_no_step_of_a_path_that_does_not_exist() -> None:
    """Every numbered heading of the document belongs to a path of the page."""
    text = DOC.read_text(encoding="utf-8")
    written = {
        f"{number}. {step.title}"
        for path in PATHS
        for number, step in enumerate(path.steps, start=1)
    }
    numbered = [
        match.group(0)[4:]
        for match in re.finditer(r"^### \d+\. .*$", text, flags=re.M)
    ]
    assert numbered
    assert set(numbered) <= written
    assert len(numbered) == len(written)

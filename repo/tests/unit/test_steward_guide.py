"""The deterministic guide of the Data Steward.

The guide answers from saved words and recorded state.  It never reaches a
model, never names an action the screen did not hold, and never explains a
gap in the evidence with a plausible sentence.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from acme_city.ui import steward_guide

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src" / "acme_city" / "ui" / "steward_guide.py"

#: The screens the guide has saved words for.
SCREENS = (
    "activity",
    "automation_settings",
    "automatic_link",
    "early_resolution",
    "incoming",
    "master_collection",
    "match_case",
    "no_candidate",
    "parcel_case",
    "queue",
    "record_profile",
    "reconciliation",
    "source_correction",
    "source_record",
)

#: The prompts the guide offers.
PROMPTS = (
    "explain_screen",
    "next_step",
    "what_changes",
    "why_match",
    "why_review",
)


@pytest.fixture()
def context() -> steward_guide.GuideContext:
    """Return a context of a match case, with one allowed and one refused action."""
    return steward_guide.GuideContext(
        screen="match_case",
        task="Check the business identity",
        state="Needs review",
        candidate="Cedarline Coffee Works LLC",
        evidence=("the source names the record", "the licence number agrees"),
        conflicts=("the unit does not agree",),
        missing=("the contact email is not recorded",),
        actions=(
            steward_guide.GuideAction(
                label="Confirm link to Cedarline Coffee Works LLC",
                href="#q5",
                category="eligible_proposal",
            ),
            steward_guide.GuideAction(
                label="Remove link",
                href="#q5",
                category="completed_work",
            ),
            steward_guide.GuideAction(
                label="Request source correction",
                href="#q5",
                category="blocking_identity",
                allowed=False,
                reason="Your role cannot do this.",
            ),
        ),
        dependencies="2 applications depend on this identity",
        source_state="the source last changed on 14 Sep 2026",
    )


def test_every_screen_has_saved_words() -> None:
    """The guide knows every screen the steward works in."""
    known = tuple(key for key, _ in steward_guide.screens())
    assert set(known) == set(SCREENS)
    assert len(known) == len(SCREENS)
    for key, label in steward_guide.screens():
        assert label
        assert steward_guide.guidance(key)


def test_every_prompt_has_a_label() -> None:
    """The guide offers its prompts with the words a person reads."""
    known = tuple(key for key, _ in steward_guide.prompts())
    assert set(known) == set(PROMPTS)
    assert len(known) == len(PROMPTS)
    for key, label in steward_guide.prompts():
        assert label


def test_the_saved_words_are_short_plain_and_without_dashes() -> None:
    """The copy reads as plain sentences in sentence case."""
    content = json.loads(steward_guide.GUIDE_PATH.read_text(encoding="utf-8"))
    texts = [str(content["no_evidence"]), str(content["no_guidance"])]
    for entry in content["screens"].values():
        texts.append(str(entry["guidance"]))
        texts.extend(str(item) for item in entry.get("prompts", {}).values())
        texts.extend(str(item["label"]) for item in entry.get("links", []))
    for text in texts:
        assert text
        assert not any(mark in text for mark in ("-", "–", "—")), text
        assert text[0].isupper(), text


def test_the_answer_names_the_screen_the_state_and_the_evidence(
    context: steward_guide.GuideContext,
) -> None:
    """The answer holds an explanation, the recorded state and the evidence."""
    response = steward_guide.build(context, "why_match")
    assert response.explanation
    assert response.state == "Needs review"
    assert response.candidate == "Cedarline Coffee Works LLC"
    assert "the source names the record" in response.evidence
    assert "the unit does not agree" in response.conflicts
    assert "the contact email is not recorded" in response.missing
    assert response.dependencies
    assert response.source_state


def test_the_answer_is_the_saved_guidance_and_never_a_model_answer(
    context: steward_guide.GuideContext,
) -> None:
    """The label says plainly that the answer is saved and that Muse is off."""
    response = steward_guide.build(context)
    assert response.mode == "saved_guidance"
    assert response.mode_label == "Saved guidance. Live Muse is off."
    assert response.prompt_label == "Explain this screen"


def test_a_gap_in_the_evidence_is_named_and_not_filled() -> None:
    """With no evidence the guide says so; it does not invent a reason."""
    response = steward_guide.build(steward_guide.GuideContext(screen="match_case"))
    assert response.evidence == ("No evidence recorded.",)


def test_the_guide_holds_an_evidence_line_only_when_it_was_given_one() -> None:
    """A screen with no recorded evidence shows no evidence line."""
    without = steward_guide.build(steward_guide.GuideContext(screen="queue"))
    assert without.evidence_recorded is False
    with_evidence = steward_guide.build(
        steward_guide.GuideContext(screen="match_case", evidence=("The name matches",))
    )
    assert with_evidence.evidence_recorded is True
    assert with_evidence.evidence == ("The name matches",)


def test_the_next_actions_follow_the_ordering_rule(
    context: steward_guide.GuideContext,
) -> None:
    """The guide offers an eligible proposal before the completed work."""
    response = steward_guide.build(context)
    assert [item.label for item in response.next_actions] == [
        "Confirm link to Cedarline Coffee Works LLC",
        "Remove link",
    ]


def test_stale_evidence_comes_before_the_other_next_actions() -> None:
    """Stale evidence, then a blocking identity question, then a proposal."""
    context = steward_guide.GuideContext(
        screen="match_case",
        actions=(
            steward_guide.GuideAction(label="Read the record again", category="completed_work"),
            steward_guide.GuideAction(label="Refresh the snapshot", category="stale_evidence"),
            steward_guide.GuideAction(label="Answer the identity question", category="blocking_identity"),
            steward_guide.GuideAction(label="Confirm the link", category="eligible_proposal"),
        ),
    )
    response = steward_guide.build(context)
    assert [item.label for item in response.next_actions] == [
        "Refresh the snapshot",
        "Answer the identity question",
        "Confirm the link",
        "Read the record again",
    ]


def test_the_guide_names_no_action_the_screen_did_not_hold() -> None:
    """Only the actions of the context appear in the answer."""
    context = steward_guide.GuideContext(
        screen="match_case",
        actions=(steward_guide.GuideAction(label="Defer"),),
    )
    response = steward_guide.build(context)
    names = {item.label for item in response.next_actions} | {
        item.label for item in response.refusals
    }
    assert names == {"Defer"}


def test_a_refused_action_keeps_its_reason(
    context: steward_guide.GuideContext,
) -> None:
    """A refusal shows why the persona may not act."""
    response = steward_guide.build(context)
    refusals = {item.label: item.detail for item in response.refusals}
    assert refusals["Request source correction"] == "Your role cannot do this."


def test_the_links_point_at_the_section_of_the_screen(
    context: steward_guide.GuideContext,
) -> None:
    """The answer links to the section or the action it talks about."""
    response = steward_guide.build(context)
    assert ("See the comparison", "#q3") in [
        (item.label, item.href) for item in response.links
    ]


def test_an_unknown_screen_or_prompt_falls_back_without_inventing() -> None:
    """An unknown screen says that it has no saved guidance."""
    response = steward_guide.build(steward_guide.GuideContext(screen="nowhere"))
    assert response.explanation == "This screen has no saved guidance yet."
    assert response.prompt == "explain_screen"
    unknown_prompt = steward_guide.build(
        steward_guide.GuideContext(screen="queue"), "not_a_prompt"
    )
    assert unknown_prompt.prompt == "explain_screen"
    assert unknown_prompt.explanation == steward_guide.guidance("queue")


def test_the_guide_never_calls_a_model(
    context: steward_guide.GuideContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Muse stub that raises is never reached by the guide."""

    class RaisingMuse(types.ModuleType):
        def __getattr__(self, name: str):
            raise AssertionError(f"the guide must not reach the model: {name}")

    for name in ("acme_city.muse", "acme_city.muse.client", "acme_city.muse.service"):
        monkeypatch.setitem(sys.modules, name, RaisingMuse(name))
    response = steward_guide.build(context, "what_changes")
    assert response.explanation
    assert response.mode_label == "Saved guidance. Live Muse is off."


def test_the_module_never_imports_the_model_package() -> None:
    """The import graph of the guide holds no Muse package."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(name.startswith("acme_city.muse") for name in imported), imported


def test_importing_the_guide_leaves_the_model_package_unloaded() -> None:
    """Importing the guide in a fresh interpreter loads no Muse package."""
    environment = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, acme_city.ui.steward_guide as g; "
            "print('acme_city.muse' in sys.modules, g.version())",
        ],
        cwd=str(ROOT),
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    loaded, version = result.stdout.split()
    assert loaded == "False"
    assert version.strip("'\"")


def test_the_content_is_versioned() -> None:
    """The saved guidance carries its version."""
    assert steward_guide.version()
    content = json.loads(steward_guide.GUIDE_PATH.read_text(encoding="utf-8"))
    assert content["version"] == steward_guide.version()

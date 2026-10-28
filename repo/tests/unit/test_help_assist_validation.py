"""The adversarial validation of an answer of the applicant help assistant.

Every case builds a small source bundle by hand and feeds the validator one
output.  The whole answer is refused when any paragraph fails, and the
negative phrases live here, under ``tests/``.
"""
# REQUIRES: AI-02, AI-04, PER-04, SEC-03

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from acme_city.applicant_help.assist_validation import validate_assistant_output
from acme_city.applicant_help.sources import Source, SourceBundle

REASONS = ("no_published_text", "outside_acme_rules", "not_about_a_permit", "needs_a_person")

RULE_TEXT = (
    "ACME Code §14-305 — Fence height, front yard\n"
    "Applies when: location = front; structure_kind = fence.\n"
    "Checks: Fence height (ft).\nOperator: must not be more than.\nThreshold: 4."
)
STEPS_TEXT = "Before you apply: choose the project and have the address ready."
TARGET_TEXT = "The service target for this permit type is 5 days."


def _source(source_id: str, kind: str, text: str, *, fact: bool, citation: str = "") -> Source:
    return Source(
        source_id=source_id,
        kind=kind,
        title=source_id,
        version="v1",
        text=text,
        sha256="0" * 64,
        citation=citation,
        facts=MappingProxyType({}),
        server_fact=fact,
    )


@pytest.fixture()
def bundle() -> SourceBundle:
    return SourceBundle(
        passages=(
            _source("rule.DF-1", "rule", RULE_TEXT, fact=True, citation="ACME Code §14-305"),
            _source("steps.before", "steps", STEPS_TEXT, fact=False),
            _source("target.fence", "service_target", TARGET_TEXT, fact=True),
        ),
        bundle_hash="b" * 64,
        basis_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
    )


def output(*paragraphs: dict, cannot: bool = False, reason: str = "") -> dict:
    return {
        "answer": list(paragraphs),
        "next_steps": ["ignored"],
        "cannot_answer": cannot,
        "reason": reason,
    }


def paragraph(text: str, source_id: str = "rule.DF-1", quote: str = "Threshold: 4.") -> dict:
    return {"text": text, "citations": [{"source_id": source_id, "quote": quote}]}


def codes(outcome) -> set[str]:
    return {issue.code for issue in outcome.issues}


def check(bundle, data, **kwargs):
    return validate_assistant_output(data, bundle=bundle, refusal_reasons=REASONS, **kwargs)


def test_a_cited_verbatim_answer_passes(bundle) -> None:
    outcome = check(
        bundle, output(paragraph("The published limit for the front yard is 4 ft."))
    )
    assert outcome.ok, outcome.issues


def test_a_source_that_is_not_in_the_bundle_is_refused(bundle) -> None:
    outcome = check(bundle, output(paragraph("Limit 4 ft.", source_id="rule.INVENTED")))
    assert not outcome.ok
    assert "unknown_source" in codes(outcome)


def test_a_quote_that_is_not_verbatim_is_refused(bundle) -> None:
    outcome = check(bundle, output(paragraph("Limit 4 ft.", quote="Threshold: 4 feet, always.")))
    assert not outcome.ok
    assert "quote_not_verbatim" in codes(outcome)


def test_an_uncited_paragraph_refuses_the_whole_answer(bundle) -> None:
    good = paragraph("The published limit for the front yard is 4 ft.")
    uncited = {"text": "Something with no citation.", "citations": []}
    outcome = check(bundle, output(good, uncited))
    assert not outcome.ok
    assert "uncited_paragraph" in codes(outcome)


def test_one_bad_paragraph_among_good_ones_refuses_the_whole_answer(bundle) -> None:
    good = paragraph("The published limit for the front yard is 4 ft.")
    bad = paragraph("The limit is 9 ft.")
    outcome = check(bundle, output(good, bad))
    assert not outcome.ok
    assert [issue.path for issue in outcome.issues] == ["answer.1"]


def test_an_invented_figure_is_refused(bundle) -> None:
    outcome = check(bundle, output(paragraph("The limit is 7 ft.")))
    assert not outcome.ok
    assert "figure_not_in_source" in codes(outcome)


@pytest.mark.parametrize(
    "claim",
    [
        "Your permit will be approved.",
        "Approval is guaranteed.",
        "No permit is needed for a fence under 6 ft.",
        "You do not need a permit.",
        "A fence this size is exempt from review.",
        "This is legal advice you can rely on.",
    ],
)
def test_outcome_exemption_and_legal_claims_are_refused(bundle, claim) -> None:
    outcome = check(bundle, output(paragraph(claim)))
    assert not outcome.ok
    assert "banned_claim" in codes(outcome)


def test_a_figure_about_time_needs_a_server_fact(bundle) -> None:
    # The steps passage is fixed prose, so it is no computed fact.
    data = output(
        paragraph(
            "It takes 5 days.",
            source_id="steps.before",
            quote="Before you apply: choose the project",
        )
    )
    outcome = check(bundle, data, server_figures=("5",))
    assert not outcome.ok
    assert "high_risk_claim_without_fact" in codes(outcome)


def test_a_figure_about_time_passes_when_it_cites_the_configured_target(bundle) -> None:
    data = output(
        paragraph(
            "The service target is 5 days.",
            source_id="target.fence",
            quote="The service target for this permit type is 5 days.",
        )
    )
    assert check(bundle, data, server_figures=("5",)).ok


def test_a_dimension_needs_a_server_fact(bundle) -> None:
    prose = _source("note.fence", "steps", "A fence is a structure. Limit 4.", fact=False)
    plain = SourceBundle(
        passages=bundle.passages + (prose,),
        bundle_hash=bundle.bundle_hash,
        basis_at=bundle.basis_at,
    )
    data = output(paragraph("The fence height limit is 4 ft.", "note.fence", "Limit 4."))
    outcome = check(plain, data)
    assert not outcome.ok
    assert "high_risk_claim_without_fact" in codes(outcome)


def test_a_refusal_needs_a_reason_of_the_fixed_list(bundle) -> None:
    assert check(bundle, output(cannot=True, reason="needs_a_person")).ok
    outcome = check(bundle, output(cannot=True, reason="because I said so"))
    assert not outcome.ok
    assert "invalid_refusal_reason" in codes(outcome)


def test_a_refusal_cannot_carry_paragraphs(bundle) -> None:
    outcome = check(
        bundle,
        output(paragraph("Limit 4 ft."), cannot=True, reason="needs_a_person"),
    )
    assert "answer_with_refusal" in codes(outcome)


def test_an_output_that_breaks_the_schema_is_refused(bundle) -> None:
    outcome = check(bundle, {"answer": "not a list"})
    assert not outcome.ok
    assert "schema_invalid" in codes(outcome)

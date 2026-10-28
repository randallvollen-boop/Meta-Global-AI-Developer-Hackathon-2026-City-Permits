"""The adversarial validation of an answer of the applicant help assistant.

The assistant may write prose, but the prose may not run ahead of the City's
own text.  The validation stands between a model output and the applicant who
reads it, and it refuses the **whole** answer when any part of it fails: a
paragraph is never dropped to make an answer acceptable.

The rules are:

* the output must match the strict applicant-assist schema;
* every paragraph must cite at least one passage of the bundle the run was
  given, and every quoted passage must be one the run was given;
* every quote must appear verbatim in the text of the passage it cites;
* every figure of a paragraph — a day count, a fee, a height, a count — must
  be supported by a quote, by the citation of a cited passage or by the
  server's own estimate.  A figure the City never computed is refused;
* a figure about a fee or a duration may only be stated when the paragraph
  cites a **server-computed fact**: an evaluated rule result, the configured
  service target or a fee calculation.  The published rule text alone never
  carries a figure about the applicant's own case;
* an answer may not state that a permit is or is not needed, may not promise
  an outcome and may not give legal advice.  A limit is never an exemption;
* the refusal of the assistant must carry one of the reasons of the fixed
  list, and the model's proposed next steps are ignored: the server derives
  the next steps of an applicant from the grants it holds for them.

A failed validation writes nothing.  The applicant receives the deterministic
fallback instead.
"""
# REQUIRES: AI-02, AI-04, PER-04, SEC-03
# An answer of the applicant assistant is validated against the exact source bundle it
# was given before the applicant sees it; a figure, a quote, a source or a claim that the
# City's own text does not carry refuses the whole answer.

from __future__ import annotations

import re
from typing import Any, Final, Mapping, Sequence

from pydantic import ValidationError as PydanticValidationError

from acme_city.applicant_help.matching import numbers_of
from acme_city.applicant_help.sources import SourceBundle
from acme_city.muse.schemas import AssistantOutput
from acme_city.muse.validation import ValidationIssue, ValidationOutcome

#: The phrases that state that a permit is needed, or that it is not.
#:
#: A limit is a limit.  It never states that a project is exempt, and the
#: assistant never states that a project needs a permit either: that is a
#: decision a person makes against the published rules.
EXEMPTION_CLAIM_PATTERNS: Final = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bno permit (?:is|are) (?:needed|required)\b",
        r"\bno permit required\b",
        r"\bpermit is not required\b",
        r"\bwithout (?:a|any) permit\b",
        r"\b(?:you|your project|your application|it)\s+(?:do(?:es)? not|don't|doesn't)\s+"
        r"need a permit\b",
        r"\b(?:you|your project|your application)\s+need a permit\b",
        r"\b(?:is|are) exempt\b",
        r"\bexempt from\b",
        r"\bexemption\b",
    )
)

#: The phrases that promise the outcome of the review.
OUTCOME_CLAIM_PATTERNS: Final = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bwill be (?:approved|denied|issued|granted|rejected|refused)\b",
        r"\b(?:is|are) (?:automatically )?approved\b",
        r"\bguarantee(?:d|s)?\b",
        r"\bwill succeed\b",
        r"\bwill pass\b",
        r"\byour (?:permit|application) will\b",
    )
)

#: The phrases that claim legal advice.
LEGAL_ADVICE_PATTERNS: Final = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\blegal advice\b",
        r"\b(?:attorney|lawyer)\b",
        r"\blegal right\b",
        r"\blegally (?:entitled|required|liable)\b",
        r"\bliable\b",
        r"\bliability\b",
        r"\bin my (?:professional )?(?:opinion|view)\b",
        r"\bi advise\b",
        r"\bi recommend\b",
    )
)

#: The topics whose figures may only come from a server-computed fact.
FIGURE_TOPIC_PATTERNS: Final = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:fee|fees|cost|costs|price|charge|charges|payment|pay|paid)\b",
        r"\b(?:usd|dollars?)\b",
        r"\b(?:day|days|week|weeks|month|months)\b",
    )
)

#: The tolerance of the comparison of two figures.
FIGURE_TOLERANCE: Final = 0.005


def _normalize(text: str) -> str:
    """Return the text with its whitespace collapsed."""
    return " ".join(str(text or "").split())


def _figures(text: str) -> tuple[float, ...]:
    """Return the figures a text names."""
    return numbers_of(text)


def _supported(
    value: float, supported: Sequence[float]
) -> bool:
    """Return whether a figure is one of the supported figures."""
    return any(abs(candidate - value) <= FIGURE_TOLERANCE for candidate in supported)


def _banned_claim(text: str) -> str | None:
    """Return the kind of claim a text carries, if it carries one."""
    for pattern in EXEMPTION_CLAIM_PATTERNS:
        if pattern.search(text) is not None:
            return "exemption"
    for pattern in OUTCOME_CLAIM_PATTERNS:
        if pattern.search(text) is not None:
            return "outcome"
    for pattern in LEGAL_ADVICE_PATTERNS:
        if pattern.search(text) is not None:
            return "legal_advice"
    return None


def _mentions_figure_topic(text: str) -> bool:
    """Return whether a text talks about a fee or a duration."""
    return any(pattern.search(text) is not None for pattern in FIGURE_TOPIC_PATTERNS)


def validate_assistant_output(
    data: Mapping[str, Any],
    *,
    bundle: SourceBundle,
    server_figures: Sequence[str] = (),
    refusal_reasons: Sequence[str] = (),
) -> ValidationOutcome:
    """Return the validation outcome of one answer of the applicant assistant.

    Args:
        data: The parsed output of the run.
        bundle: The source bundle the run was given.  A citation of a passage
            that is not in this bundle is an invented citation.
        server_figures: The figures the server computed itself, for example
            the configured service target.  A figure of the answer may be one
            of them.
        refusal_reasons: The fixed list of reasons the assistant may give
            when it cannot answer.

    Returns:
        The outcome.  A failed outcome carries every issue that was found,
        and the whole answer is refused: a paragraph is never dropped.
    """
    try:
        model = AssistantOutput.model_validate(dict(data))
    except PydanticValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ()))
        return ValidationOutcome(
            state="failed",
            issues=(
                ValidationIssue(
                    code="schema_invalid",
                    message=(
                        "the output does not match the applicant-assist schema: "
                        f"{first.get('msg', 'invalid')}"
                    ),
                    path=location,
                ),
            ),
        )

    checked = [
        "schema",
        "citations",
        "quotes",
        "figures",
        "claims",
        "refusal",
    ]
    issues: list[ValidationIssue] = []

    if model.cannot_answer:
        if model.answer:
            issues.append(
                ValidationIssue(
                    code="answer_with_refusal",
                    message=(
                        "the output refuses to answer and carries paragraphs at the same "
                        "time"
                    ),
                    path="answer",
                )
            )
        if model.reason not in set(refusal_reasons):
            issues.append(
                ValidationIssue(
                    code="invalid_refusal_reason",
                    message=(
                        "the refusal reason is not one of the reasons the City allows"
                    ),
                    path="reason",
                )
            )
    elif model.reason:
        issues.append(
            ValidationIssue(
                code="unexpected_refusal_reason",
                message="the output carries a refusal reason but does not refuse",
                path="reason",
            )
        )

    server_values = [value for text in server_figures for value in _figures(text)]

    for index, paragraph in enumerate(model.answer):
        path = f"answer.{index}"
        if not paragraph.citations:
            issues.append(
                ValidationIssue(
                    code="uncited_paragraph",
                    message="the paragraph cites no passage of the bundle",
                    path=path,
                )
            )
            continue

        quoted: list[str] = []
        citations: list[str] = []
        facts = False
        for position, citation in enumerate(paragraph.citations):
            source = bundle.source(citation.source_id)
            if source is None:
                issues.append(
                    ValidationIssue(
                        code="unknown_source",
                        message=(
                            "the paragraph cites a passage that was not in the bundle the "
                            "run was given"
                        ),
                        path=f"{path}.citations.{position}.source_id",
                    )
                )
                continue
            haystack = _normalize(source.text)
            needle = _normalize(citation.quote)
            if not needle or needle not in haystack:
                issues.append(
                    ValidationIssue(
                        code="quote_not_verbatim",
                        message=(
                            "the quote does not appear verbatim in the passage it cites"
                        ),
                        path=f"{path}.citations.{position}.quote",
                    )
                )
                continue
            quoted.append(citation.quote)
            citations.append(source.citation)
            facts = facts or source.server_fact

        if not quoted:
            # Every citation of this paragraph was refused, so the paragraph
            # has no evidence at all.
            continue

        supported = [value for text in quoted for value in _figures(text)]
        supported.extend(value for text in citations if text for value in _figures(text))
        supported.extend(server_values)
        for value in _figures(paragraph.text):
            if not _supported(value, supported):
                issues.append(
                    ValidationIssue(
                        code="figure_not_in_source",
                        message=(
                            "the paragraph states a figure that no cited passage and no "
                            "server estimate carries"
                        ),
                        path=path,
                    )
                )
                break

        claim = _banned_claim(paragraph.text)
        if claim is not None:
            issues.append(
                ValidationIssue(
                    code="banned_claim",
                    message=(
                        "the paragraph carries a claim the applicant assistant may not "
                        "make"
                    ),
                    path=path,
                )
            )

        if _mentions_figure_topic(paragraph.text) and _figures(paragraph.text):
            if not facts:
                issues.append(
                    ValidationIssue(
                        code="high_risk_claim_without_fact",
                        message=(
                            "the paragraph states a figure about a fee or a duration without "
                            "citing a computed fact of the City"
                        ),
                        path=path,
                    )
                )

    if issues:
        return ValidationOutcome(state="failed", issues=tuple(issues), checked=tuple(checked))
    return ValidationOutcome(state="passed", checked=tuple(checked))


__all__ = [
    "EXEMPTION_CLAIM_PATTERNS",
    "LEGAL_ADVICE_PATTERNS",
    "OUTCOME_CLAIM_PATTERNS",
    "validate_assistant_output",
]

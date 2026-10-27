"""Validation of a model output before anything is written.

A model proposes; it never decides.  Every output is checked against the
records the actor may see before a single observation or match proposal is
written:

* the application, the document version and the source record must be ones the
  actor may see;
* the evidence lines must exist in the exact stored document version and the
  excerpt must be quoted from them;
* the proposed value must be supported by the excerpt it cites;
* a numeric value must be a finite number;
* a candidate must be one the registry offered, and a disposition must be one
  of the proposed values;
* no output may carry an instruction that tries to approve, issue, re-schema
  or re-permission the run.

A failed validation writes nothing.  The failure itself is recorded.
"""
# REQUIRES: AI-02, AI-03, AI-05
# A model output is validated against the exact stored document version and the
# actor-visible records before any observation or proposal is written. Unknown identifiers,
# invented evidence, malformed values and unauthorized instructions fail the validation.

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

from pydantic import ValidationError as PydanticValidationError

from acme_city.muse.payloads import VisibleEvidenceBundle
from acme_city.muse.schemas import EXTRACTABLE_FIELDS, TASK_OUTPUT_MODELS, MuseOutputModel

#: The extracted fields whose value must be a finite number.
NUMERIC_FIELDS: Final = frozenset({"declared_valuation", "occupant_load"})

#: The extracted fields whose value must be a whole number.
INTEGER_FIELDS: Final = frozenset({"occupant_load"})

#: The dispositions a match proposal may recommend.  Each one is a proposal.
MATCH_DISPOSITIONS: Final = ("link", "no_link", "needs_review")

#: The longest excerpt a proposal may cite.
MAX_EXCERPT_LENGTH: Final = 400

#: The longest proposed value a proposal may carry.
MAX_VALUE_LENGTH: Final = 320

#: The field-name fragments that name a workflow decision.
WORKFLOW_FIELD_MARKERS: Final = (
    "decision",
    "approv",
    "deni",
    "disposition",
    "outcome",
    "issu",
    "permit_",
    "fee",
    "price",
    "payment",
    "allocation",
    "status",
    "verdict",
    "instruction",
    "permission",
    "tool",
)

#: The patterns that mark an instruction the model must not carry out.
UNSAFE_INSTRUCTION_PATTERNS: Final = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|earlier|above)\s+instructions",
        r"disregard\s+(?:the\s+)?(?:system|previous|prior|earlier)\b",
        r"(?:mark|set|record)\s+(?:this|the)\s+(?:permit|application|license)\s+as\s+approved",
        r"(?:approve|issue|authorize|deny|grant)\s+this\s+(?:permit|application|license)\b",
        r"this\s+(?:permit|application)\s+is\s+approved\b",
        r"(?:change|modify|replace|extend)\s+the\s+(?:output\s+|response\s+)?schema\b",
        r"(?:call|invoke|use)\s+the\s+\w+\s+tool\b",
        r"grant\s+(?:the\s+)?(?:applicant|actor|user|model|reader)\b[^.\n]*"
        r"(?:permission|access|role)\b",
        r"bypass\s+(?:the\s+)?(?:review|approval|validation|check|guard|control)\b",
        r"reveal\s+(?:your\s+)?(?:system\s+)?prompt\b",
        r"you\s+are\s+now\b",
        r"system\s+prompt\s*:",
    )
)

#: The number of every number-like token in a text.
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

#: The unit words a numeric proposed value may carry.
_UNIT_WORDS: Final = ("usd", "$", "persons", "person", "occupants", "occupant", "people")


@dataclass(frozen=True)
class ValidationIssue:
    """One reason an output was refused."""

    code: str
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return the dictionary form of the issue."""
        return {"code": self.code, "message": self.message, "path": self.path}


@dataclass(frozen=True)
class ValidationOutcome:
    """The result of validating one model output."""

    state: str
    issues: tuple[ValidationIssue, ...] = ()
    checked: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Return whether the output may be written."""
        return self.state == "passed"

    def to_dict(self) -> dict[str, Any]:
        """Return the dictionary form of the outcome."""
        return {
            "state": self.state,
            "issues": [issue.to_dict() for issue in self.issues],
            "checked": list(self.checked),
        }


def _normalize(text: str) -> str:
    """Return the text with its whitespace collapsed."""
    return " ".join(str(text).split())


def _parse_number(value: str) -> float | None:
    """Return the finite number a value carries, or ``None``."""
    text = _normalize(value).lower()
    for unit in _UNIT_WORDS:
        text = text.replace(unit, " ")
    text = text.replace(",", " ").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def _numbers_in(text: str) -> list[float]:
    """Return every number-like token of a text."""
    found: list[float] = []
    for match in _NUMBER.finditer(text):
        try:
            number = float(match.group(0))
        except ValueError:  # pragma: no cover - the pattern only matches numbers
            continue
        if math.isfinite(number):
            found.append(number)
    return found


def _value_supported(value: str, excerpt: str) -> bool:
    """Return whether the excerpt supports the proposed value."""
    needle = _normalize(value).lower()
    haystack = _normalize(excerpt).lower()
    if not needle:
        return False
    if needle in haystack:
        return True
    number = _parse_number(value)
    if number is None:
        return False
    return any(abs(candidate - number) <= 0.005 for candidate in _numbers_in(haystack))


def excerpt_matches(lines: Sequence[str], line_start: int, line_end: int, excerpt: str) -> bool:
    """Return whether the excerpt is quoted from the cited lines.

    The cited lines must exist in the document, and the excerpt must appear in
    them.  The comparison collapses whitespace, so a quotation that differs
    only in spacing is still a quotation.
    """
    if line_start < 1 or line_end < line_start or line_end > len(lines):
        return False
    joined = _normalize(" ".join(lines[line_start - 1 : line_end]))
    needle = _normalize(excerpt)
    if not needle:
        return False
    return needle in joined


def find_unsafe_instruction(text: str) -> str | None:
    """Return the instruction pattern a text carries, if it carries one."""
    for pattern in UNSAFE_INSTRUCTION_PATTERNS:
        match = pattern.search(text or "")
        if match is not None:
            return match.group(0)
    return None


def parse_output_text(task: str, text: str | None) -> tuple[dict[str, Any] | None, ValidationIssue | None]:
    """Return the parsed output of a run, or the issue that stopped it.

    A run that returns no text, text that is not JSON, or JSON that is not an
    object is a malformed output, and a malformed output is never written.
    """
    if text is None or not str(text).strip():
        return None, ValidationIssue(
            code="malformed_output",
            message="the run returned no output text",
        )
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None, ValidationIssue(
            code="malformed_json",
            message="the run returned output that is not valid JSON",
        )
    if not isinstance(data, dict):
        return None, ValidationIssue(
            code="malformed_output",
            message="the run returned output that is not a JSON object",
        )
    return data, None


def _schema_error(task: str, data: Mapping[str, Any], exc: PydanticValidationError) -> ValidationIssue:
    """Return the issue that describes a schema violation."""
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", ()))
    return ValidationIssue(
        code="schema_invalid",
        message=f"the output does not match the {task} schema: {first.get('msg', 'invalid')}",
        path=location,
    )


def _parse_model(task: str, data: Mapping[str, Any]) -> tuple[MuseOutputModel | None, ValidationIssue | None]:
    """Return the parsed output model, or the issue that stopped it."""
    model = TASK_OUTPUT_MODELS.get(task)
    if model is None:
        return None, ValidationIssue(
            code="unknown_task",
            message=f"unknown Muse task: {task!r}",
        )
    try:
        return model.model_validate(dict(data)), None
    except PydanticValidationError as exc:
        return None, _schema_error(task, data, exc)


def validate_extraction_output(
    data: Mapping[str, Any],
    *,
    bundle: VisibleEvidenceBundle,
    application_id: str,
) -> ValidationOutcome:
    """Return the validation outcome of one extraction output.

    Args:
        data: The parsed output of the run.
        bundle: The evidence the run was given.
        application_id: The application the run was about.

    Returns:
        The outcome.  A failed outcome carries every issue that was found, and
        nothing is written when the outcome is not ``passed``.
    """
    issues: list[ValidationIssue] = []
    model, issue = _parse_model("extraction", data)
    if model is None:
        return ValidationOutcome(state="failed", issues=(issue,) if issue else ())

    checked: list[str] = ["schema", "application_scope", "document_scope", "evidence", "values"]

    if model.application_id != application_id:
        issues.append(
            ValidationIssue(
                code="unknown_application",
                message=(
                    "the output names an application that was not the one the run was "
                    "given"
                ),
                path="application_id",
            )
        )
    if model.application_id != bundle.application_id:
        issues.append(
            ValidationIssue(
                code="out_of_scope_application",
                message="the output names an application outside the actor's scope",
                path="application_id",
            )
        )

    reference = bundle.document(model.document_id)
    if reference is None:
        issues.append(
            ValidationIssue(
                code="unknown_document",
                message=(
                    "the output names a document version that was not visible to the actor"
                ),
                path="document_id",
            )
        )
    elif reference.version != model.document_version:
        issues.append(
            ValidationIssue(
                code="document_version_mismatch",
                message=(
                    "the output names a version of the document that is not the stored "
                    "version"
                ),
                path="document_version",
            )
        )

    lines = bundle.lines_of(model.document_id) if reference is not None else ()
    for index, observation in enumerate(model.observations):
        path = f"observations.{index}"
        if observation.field not in EXTRACTABLE_FIELDS:
            code = (
                "unauthorized_field"
                if any(marker in observation.field.lower() for marker in WORKFLOW_FIELD_MARKERS)
                else "unknown_field"
            )
            issues.append(
                ValidationIssue(
                    code=code,
                    message=f"the field {observation.field!r} is not an extractable field",
                    path=f"{path}.field",
                )
            )
        value = observation.proposed_value
        if len(value) > MAX_VALUE_LENGTH:
            issues.append(
                ValidationIssue(
                    code="malformed_value",
                    message="the proposed value is longer than the demonstration accepts",
                    path=f"{path}.proposed_value",
                )
            )
        if observation.field in NUMERIC_FIELDS:
            number = _parse_number(value)
            if number is None:
                issues.append(
                    ValidationIssue(
                        code="malformed_numeric_value",
                        message=(
                            f"the proposed value for {observation.field!r} is not a finite number"
                        ),
                        path=f"{path}.proposed_value",
                    )
                )
            elif observation.field in INTEGER_FIELDS and not float(number).is_integer():
                issues.append(
                    ValidationIssue(
                        code="malformed_numeric_value",
                        message=(
                            f"the proposed value for {observation.field!r} is not a whole number"
                        ),
                        path=f"{path}.proposed_value",
                    )
                )
        if find_unsafe_instruction(value) is not None:
            issues.append(
                ValidationIssue(
                    code="unauthorized_instruction",
                    message=(
                        "the proposed value carries an instruction the demonstration does "
                        "not carry out"
                    ),
                    path=f"{path}.proposed_value",
                )
            )

        evidence = observation.evidence
        if not lines:
            issues.append(
                ValidationIssue(
                    code="unknown_document",
                    message="the cited evidence does not belong to a visible document",
                    path=f"{path}.evidence",
                )
            )
            continue
        if evidence.line_end < evidence.line_start or evidence.line_end > len(lines):
            issues.append(
                ValidationIssue(
                    code="line_out_of_range",
                    message=(
                        "the cited lines do not exist in the stored version of the document"
                    ),
                    path=f"{path}.evidence",
                )
            )
            continue
        if len(evidence.excerpt) > MAX_EXCERPT_LENGTH:
            issues.append(
                ValidationIssue(
                    code="excerpt_too_long",
                    message="the quoted excerpt is longer than the demonstration accepts",
                    path=f"{path}.evidence.excerpt",
                )
            )
            continue
        if not excerpt_matches(lines, evidence.line_start, evidence.line_end, evidence.excerpt):
            issues.append(
                ValidationIssue(
                    code="excerpt_mismatch",
                    message=(
                        "the quoted excerpt does not appear in the cited lines of the stored "
                        "document version"
                    ),
                    path=f"{path}.evidence.excerpt",
                )
            )
            continue
        if observation.field in EXTRACTABLE_FIELDS and not _value_supported(
            value, evidence.excerpt
        ):
            issues.append(
                ValidationIssue(
                    code="value_not_in_evidence",
                    message=(
                        "the proposed value is not supported by the excerpt it cites"
                    ),
                    path=f"{path}.proposed_value",
                )
            )

    if issues:
        return ValidationOutcome(state="failed", issues=tuple(issues), checked=tuple(checked))
    return ValidationOutcome(state="passed", checked=tuple(checked))


def validate_match_output(
    data: Mapping[str, Any],
    *,
    bundle: VisibleEvidenceBundle,
    source_snapshot_id: str,
    allowed_candidate_ids: Sequence[str],
) -> ValidationOutcome:
    """Return the validation outcome of one match-proposal output.

    Args:
        data: The parsed output of the run.
        bundle: The evidence the run was given.
        source_snapshot_id: The source record the run was about.
        allowed_candidate_ids: The candidates the actor may weigh.  A candidate
            outside this set is an invented citation.

    Returns:
        The outcome.
    """
    issues: list[ValidationIssue] = []
    model, issue = _parse_model("match_proposal", data)
    if model is None:
        return ValidationOutcome(state="failed", issues=(issue,) if issue else ())

    checked: list[str] = ["schema", "source_scope", "candidates", "disposition", "instructions"]

    if model.source_snapshot_id != source_snapshot_id:
        issues.append(
            ValidationIssue(
                code="unknown_source_record",
                message=(
                    "the output names a source record that was not the one the run was given"
                ),
                path="source_snapshot_id",
            )
        )

    allowed = set(allowed_candidate_ids)
    seen: set[str] = set()
    for index, candidate in enumerate(model.candidates):
        path = f"candidates.{index}"
        if candidate.entity_id not in allowed:
            issues.append(
                ValidationIssue(
                    code="unsupported_citation",
                    message=(
                        f"the output names the candidate {candidate.entity_id!r}, which was "
                        "not visible to the actor"
                    ),
                    path=f"{path}.entity_id",
                )
            )
        if candidate.entity_id in seen:
            issues.append(
                ValidationIssue(
                    code="duplicate_candidate",
                    message="the output names the same candidate twice",
                    path=f"{path}.entity_id",
                )
            )
        seen.add(candidate.entity_id)
        score = candidate.proposal_score
        if score is not None:
            if not math.isfinite(score) or score < 0.0 or score > 1.0:
                issues.append(
                    ValidationIssue(
                        code="malformed_value",
                        message=(
                            "the proposed score is not a finite value between zero and one"
                        ),
                        path=f"{path}.proposal_score",
                    )
                )
        for text in (*candidate.supporting, *candidate.conflicting):
            if find_unsafe_instruction(text) is not None:
                issues.append(
                    ValidationIssue(
                        code="unauthorized_instruction",
                        message=(
                            "the candidate evidence carries an instruction the demonstration "
                            "does not carry out"
                        ),
                        path=path,
                    )
                )
                break

    if model.recommended_disposition not in MATCH_DISPOSITIONS:
        issues.append(
            ValidationIssue(
                code="unknown_disposition",
                message=(
                    f"the recommended disposition {model.recommended_disposition!r} is not one "
                    f"of {', '.join(MATCH_DISPOSITIONS)}"
                ),
                path="recommended_disposition",
            )
        )
    if find_unsafe_instruction(model.explanation) is not None:
        issues.append(
            ValidationIssue(
                code="unauthorized_instruction",
                message=(
                    "the explanation carries an instruction the demonstration does not carry out"
                ),
                path="explanation",
            )
        )

    if issues:
        return ValidationOutcome(state="failed", issues=tuple(issues), checked=tuple(checked))
    return ValidationOutcome(state="passed", checked=tuple(checked))


__all__ = [
    "EXTRACTABLE_FIELDS",
    "INTEGER_FIELDS",
    "MATCH_DISPOSITIONS",
    "MAX_EXCERPT_LENGTH",
    "MAX_VALUE_LENGTH",
    "NUMERIC_FIELDS",
    "UNSAFE_INSTRUCTION_PATTERNS",
    "WORKFLOW_FIELD_MARKERS",
    "ValidationIssue",
    "ValidationOutcome",
    "excerpt_matches",
    "find_unsafe_instruction",
    "parse_output_text",
    "validate_extraction_output",
    "validate_match_output",
]

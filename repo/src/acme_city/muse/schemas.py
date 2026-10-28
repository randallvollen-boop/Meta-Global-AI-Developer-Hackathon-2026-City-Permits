"""Strict output schemas for the bounded Muse tasks.

A model run returns exactly one of three shapes: an extraction of declared
fields from one stored document version, a match proposal over the
candidates an actor may already see, or the answer of the applicant help
assistant.  All three schemas are strict.  Every object forbids unknown
fields, every field is required, and a value that may be absent is declared
as nullable instead of optional, so a provider never has to guess which keys
it may omit.

The generated JSON Schema deliberately carries only the keywords a strict
structured-output provider accepts.  Numeric bounds and length limits are
enforced by :mod:`acme_city.muse.validation` instead, where a violation is
reported as a readable validation issue rather than a provider error.
"""
# REQUIRES: AI-02, AI-03
# The Muse output schemas are strict, every field is required, unknown fields are
# refused, and the generated JSON Schema stays inside the keyword set a strict
# structured-output provider accepts.

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

#: The version of the extraction output schema.
EXTRACTION_SCHEMA_VERSION: Final = "acme-extraction-schema-v1"

#: The version of the match-proposal output schema.
MATCH_SCHEMA_VERSION: Final = "acme-match-schema-v1"

#: The version of the applicant-assist output schema.
APPLICANT_ASSIST_SCHEMA_VERSION: Final = "acme-assist-schema-v1"

#: The version of the extraction prompt.
EXTRACTION_PROMPT_VERSION: Final = "acme-extraction-prompt-v1"

#: The version of the match-proposal prompt.
MATCH_PROMPT_VERSION: Final = "acme-match-prompt-v1"

#: The version of the applicant-assist prompt.
APPLICANT_ASSIST_PROMPT_VERSION: Final = "acme-assist-prompt-v1"

#: The provider that serves the Standard Muse models.
MUSE_PROVIDER: Final = "meta"

#: The only model a live run may select.
DEFAULT_MUSE_MODEL: Final = "muse-spark-1.3"

#: The schema name the provider is asked to enforce.
EXTRACTION_SCHEMA_NAME: Final = "acme_city_extraction"

#: The schema name the provider is asked to enforce.
MATCH_SCHEMA_NAME: Final = "acme_city_match_proposal"

#: The schema name the provider is asked to enforce for the applicant assistant.
APPLICANT_ASSIST_SCHEMA_NAME: Final = "acme_city_applicant_assist"

#: The JSON Schema keywords that are removed from the generated schema.
#:
#: They are bounds and formatting hints.  A strict structured-output provider
#: rejects them, and the same rules are enforced by the validation layer
#: where the failure is reported against the offending observation.
_DROPPED_SCHEMA_KEYWORDS: Final = frozenset(
    {
        "title",
        "default",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "format",
    }
)


class MuseOutputModel(BaseModel):
    """The base of every strict Muse output model.

    ``extra="forbid"`` is the point of the base class: an output that carries
    a field the schema does not declare is refused rather than ignored.
    """

    model_config = ConfigDict(extra="forbid")


class EvidenceSpan(MuseOutputModel):
    """The lines of one document version that support one proposed value."""

    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    excerpt: str = Field(min_length=1, max_length=2000)


#: The fields an extraction may propose.  Nothing outside this set is accepted.
EXTRACTABLE_FIELDS: Final = frozenset(
    {
        "applicant_legal_name",
        "applicant_alias",
        "business_licence_reference",
        "unit_address",
        "parcel_reference",
        "contractor_registration",
        "contractor_name",
        "project_description",
        "declared_valuation",
        "occupant_load",
    }
)


class ExtractionObservation(MuseOutputModel):
    """One proposed value and the document lines that support it."""

    # The enum tells the provider the only names it may use; validation still
    # rejects anything else, so a replay or a malformed output is caught too.
    field: str = Field(
        min_length=1, max_length=160, json_schema_extra={"enum": sorted(EXTRACTABLE_FIELDS)}
    )
    proposed_value: str = Field(min_length=1, max_length=320)
    evidence: EvidenceSpan


class ExtractionOutput(MuseOutputModel):
    """The extraction of declared fields from one stored document version."""

    application_id: str = Field(min_length=1, max_length=64)
    document_id: str = Field(min_length=1, max_length=64)
    document_version: int = Field(ge=1)
    observations: list[ExtractionObservation]


class MatchCandidate(MuseOutputModel):
    """One canonical entity the model weighed, with its evidence."""

    entity_id: str = Field(min_length=1, max_length=64)
    supporting: list[str] = Field(default_factory=list)
    conflicting: list[str] = Field(default_factory=list)
    proposal_score: float | None = None


class MatchOutput(MuseOutputModel):
    """A proposed link.  The disposition is a proposal, never a decision."""

    source_snapshot_id: str = Field(min_length=1, max_length=64)
    candidates: list[MatchCandidate]
    recommended_disposition: str = Field(min_length=1, max_length=32)
    explanation: str = Field(min_length=1, max_length=2000)


#: The task name of the extraction task.
EXTRACTION_TASK: Final = "extraction"

#: The task name of the match-proposal task.
MATCH_TASK: Final = "match_proposal"

#: The task name of the applicant-assist task.
#:
#: The applicant assistant is a separate, non-proposing path: it writes no
#: observation and no match proposal.  It answers an applicant from a source
#: bundle the server built, and it is dispatched by the applicant-help service
#: rather than by :class:`~acme_city.muse.service.MuseService`.
APPLICANT_ASSIST_TASK: Final = "applicant_assist"

#: The tasks whose output is a proposal the City may act on.
PROPOSING_TASKS: Final = (EXTRACTION_TASK, MATCH_TASK)


class AssistantCitation(MuseOutputModel):
    """One passage the answer quotes, and the passage it came from."""

    source_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=2000)


class AssistantParagraph(MuseOutputModel):
    """One paragraph of the answer and the passages that support it."""

    text: str = Field(min_length=1, max_length=4000)
    citations: list[AssistantCitation]


class AssistantOutput(MuseOutputModel):
    """The answer of the applicant help assistant.

    The answer explains and cites.  It never decides: it carries no decision,
    no disposition and no outcome of a permit.  The ``next_steps`` the model
    proposes are ignored by the server — the next steps of an applicant come
    from the grants the server holds for them — but the field is declared so
    that the provider fills the whole schema.
    """

    answer: list[AssistantParagraph]
    next_steps: list[str]
    cannot_answer: bool
    reason: str = Field(max_length=200)


#: The output model, prompt version and schema version of every task.
TASK_CONFIG: Final[dict[str, dict[str, str]]] = {
    EXTRACTION_TASK: {
        "output_model": "ExtractionOutput",
        "prompt_version": EXTRACTION_PROMPT_VERSION,
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "schema_name": EXTRACTION_SCHEMA_NAME,
    },
    MATCH_TASK: {
        "output_model": "MatchOutput",
        "prompt_version": MATCH_PROMPT_VERSION,
        "schema_version": MATCH_SCHEMA_VERSION,
        "schema_name": MATCH_SCHEMA_NAME,
    },
    APPLICANT_ASSIST_TASK: {
        "output_model": "AssistantOutput",
        "prompt_version": APPLICANT_ASSIST_PROMPT_VERSION,
        "schema_version": APPLICANT_ASSIST_SCHEMA_VERSION,
        "schema_name": APPLICANT_ASSIST_SCHEMA_NAME,
    },
}

#: The strict output model of every task.
TASK_OUTPUT_MODELS: Final[dict[str, type[MuseOutputModel]]] = {
    EXTRACTION_TASK: ExtractionOutput,
    MATCH_TASK: MatchOutput,
    APPLICANT_ASSIST_TASK: AssistantOutput,
}


def _strictify(node: Any) -> Any:
    """Return the strict form of one JSON Schema node.

    Every object forbids unknown fields and lists all of its properties as
    required.  The bounds and formatting keywords are dropped because a strict
    structured-output provider does not accept them.
    """
    if isinstance(node, dict):
        strict: dict[str, Any] = {}
        for key, value in node.items():
            if key in _DROPPED_SCHEMA_KEYWORDS:
                continue
            strict[key] = _strictify(value)
        if strict.get("type") == "object" or "properties" in strict:
            strict["additionalProperties"] = False
            properties = strict.get("properties")
            if isinstance(properties, dict):
                strict["required"] = sorted(properties)
        return strict
    if isinstance(node, list):
        return [_strictify(item) for item in node]
    return node


def strict_json_schema(model: type[MuseOutputModel]) -> dict[str, Any]:
    """Return the strict JSON Schema of one output model.

    Args:
        model: The Pydantic model that describes the output.

    Returns:
        A JSON Schema in which every object forbids unknown fields and lists
        all of its properties as required.
    """
    return _strictify(model.model_json_schema())


def task_schema(task: str) -> dict[str, Any]:
    """Return the strict JSON Schema of one task."""
    model = TASK_OUTPUT_MODELS.get(task)
    if model is None:
        raise KeyError(f"unknown Muse task: {task!r}")
    return strict_json_schema(model)


__all__ = [
    "APPLICANT_ASSIST_PROMPT_VERSION",
    "APPLICANT_ASSIST_SCHEMA_NAME",
    "APPLICANT_ASSIST_SCHEMA_VERSION",
    "APPLICANT_ASSIST_TASK",
    "DEFAULT_MUSE_MODEL",
    "EXTRACTION_PROMPT_VERSION",
    "EXTRACTION_SCHEMA_NAME",
    "EXTRACTION_SCHEMA_VERSION",
    "EXTRACTION_TASK",
    "PROPOSING_TASKS",
    "AssistantCitation",
    "AssistantOutput",
    "AssistantParagraph",
    "EvidenceSpan",
    "ExtractionObservation",
    "ExtractionOutput",
    "MATCH_PROMPT_VERSION",
    "MATCH_SCHEMA_NAME",
    "MATCH_SCHEMA_VERSION",
    "MATCH_TASK",
    "MUSE_PROVIDER",
    "MatchCandidate",
    "MatchOutput",
    "MuseOutputModel",
    "TASK_CONFIG",
    "TASK_OUTPUT_MODELS",
    "strict_json_schema",
    "task_schema",
]

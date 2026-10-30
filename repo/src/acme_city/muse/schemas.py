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

#: The versions of the what-if policy tasks (policy 3).
POLICY_BRIEF_SCHEMA_VERSION: Final = "acme-policy-brief-schema-v1"
POLICY_PROPOSE_SCHEMA_VERSION: Final = "acme-policy-propose-schema-v1"

#: The version of the extraction prompt.
EXTRACTION_PROMPT_VERSION: Final = "acme-extraction-prompt-v1"

#: The version of the match-proposal prompt.
MATCH_PROMPT_VERSION: Final = "acme-match-prompt-v1"

#: The version of the applicant-assist prompt.
APPLICANT_ASSIST_PROMPT_VERSION: Final = "acme-assist-prompt-v1"

#: The versions of the what-if policy prompts (policy 3).
POLICY_BRIEF_PROMPT_VERSION: Final = "acme-policy-brief-prompt-v4"
POLICY_PROPOSE_PROMPT_VERSION: Final = "acme-policy-propose-prompt-v1"

#: The version of the steward-explanation output schema.
STEWARD_EXPLANATION_SCHEMA_VERSION: Final = "acme-steward-explanation-schema-v1"

#: The version of the steward-explanation prompt.
STEWARD_EXPLANATION_PROMPT_VERSION: Final = "acme-steward-explanation-prompt-v1"

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

#: The schema names the provider is asked to enforce for the what-if policy tasks.
POLICY_BRIEF_SCHEMA_NAME: Final = "acme_city_policy_brief"
POLICY_PROPOSE_SCHEMA_NAME: Final = "acme_city_policy_propose"

#: The schema name the provider is asked to enforce for the steward explanation.
STEWARD_EXPLANATION_SCHEMA_NAME: Final = "acme_city_steward_explanation"

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

#: The task names of the what-if policy agent (policy 3).
#:
#: Both are dispatched by their own application-independent path
#: (:mod:`acme_city.policy.muse`) under dedicated grants.  They write no
#: observation, no match proposal and no business row, and their runs are
#: readable only by the holders of those grants.
POLICY_BRIEF_TASK: Final = "policy_brief"
POLICY_PROPOSE_TASK: Final = "policy_propose"

#: The task name of the steward explanation.
#:
#: The steward explanation is a separate, non-proposing path: it writes no
#: observation, no match proposal and no business row.  It rewrites the words
#: of one recommendation and nothing else, so it is dispatched by the steward
#: assistant rather than by :class:`~acme_city.muse.service.MuseService`.
STEWARD_EXPLANATION_TASK: Final = "steward_explanation"

#: The tasks whose runs belong to the what-if screens, never to a general run list.
POLICY_TASKS: Final = (POLICY_BRIEF_TASK, POLICY_PROPOSE_TASK)

#: The tasks whose runs no general run list may show.
PRIVATE_TASKS: Final = (APPLICANT_ASSIST_TASK, STEWARD_EXPLANATION_TASK, *POLICY_TASKS)

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


class PolicyClaim(MuseOutputModel):
    """One figure of a sentence, bound to one typed fact of the run.

    The claim repeats the typed fact it rests on: the value, the unit, the
    direction, the population and the identities of the baseline and the
    scenario it compares.  The server compares every field with the fact it
    holds; a claim that differs in any field refuses the whole response.
    """

    fact_id: str = Field(max_length=120)
    value: str = Field(max_length=40)
    unit: str = Field(max_length=20)
    direction: str = Field(max_length=20)
    population: str = Field(max_length=200)
    baseline_id: str = Field(max_length=80)
    scenario_id: str = Field(max_length=80)


class PolicyRuleRef(MuseOutputModel):
    """One rule source a sentence names.

    A rule threshold or an ACME Code section may only be named through a
    versioned rule source of the run: the rule id, its version label, the
    citation, the limit and the unit, in the baseline or in the scenario.
    """

    rule_id: str = Field(max_length=40)
    version: str = Field(max_length=40)
    citation: str = Field(max_length=80)
    limit_value: str = Field(max_length=40)
    unit: str = Field(max_length=20)
    configuration: str = Field(max_length=20)


class PolicySentence(MuseOutputModel):
    """One sentence and the facts and rule sources it rests on."""

    text: str = Field(max_length=1200)
    claims: list[PolicyClaim]
    rule_refs: list[PolicyRuleRef]


class PolicySection(MuseOutputModel):
    """One section of the briefing: a heading key and its sentences."""

    section: str = Field(max_length=40)
    question: str = Field(max_length=300)
    sentences: list[PolicySentence]


class PolicyBriefOutput(MuseOutputModel):
    """The legislator briefing or explanation of one what-if run.

    The briefing explains figures the engine counted.  It computes nothing
    and recommends nothing.
    """

    title: str = Field(max_length=200)
    sections: list[PolicySection]
    cannot_brief: bool
    reason: str = Field(max_length=200)


class PolicyProposedChange(MuseOutputModel):
    """One proposed change, in a flat strict form.

    An unused text field is empty, an unused number is -1.  The server turns
    the record into a change request of the supported kinds and validates it
    on its own; a kind the release does not support is refused by name.
    """

    kind: str = Field(max_length=60)
    rule_id: str = Field(max_length=40)
    limit_value: str = Field(max_length=40)
    operator: str = Field(max_length=20)
    condition: str = Field(max_length=200)
    permit_type_key: str = Field(max_length=64)
    item_kind: str = Field(max_length=20)
    item: str = Field(max_length=64)
    action: str = Field(max_length=20)
    process_category: str = Field(max_length=40)
    discretionary: str = Field(max_length=10)
    service_target_days: int
    fee_schedule_id: str = Field(max_length=64)
    fixed_review_charge_cents: int
    valuation_multiplier: str = Field(max_length=40)
    rationale: str = Field(max_length=500)


class PolicyProposeOutput(MuseOutputModel):
    """The what-if the agent proposes for an administrator to review and save."""

    name: str = Field(max_length=200)
    proposals: list[PolicyProposedChange]
    cannot_propose: bool
    reason: str = Field(max_length=200)


class StewardExplanationOutput(MuseOutputModel):
    """The plain words of one recommendation of the steward assistant.

    The schema carries the rewritten text and nothing else.  The outcome, the
    confidence and the evidence of a recommendation are decided by the City
    and never travel back from a model, so a model cannot return them: an
    output that carries an outcome or a confidence is refused by the strict
    schema, not ignored.
    """

    explanation: str = Field(min_length=1, max_length=2000)


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
    POLICY_BRIEF_TASK: {
        "output_model": "PolicyBriefOutput",
        "prompt_version": POLICY_BRIEF_PROMPT_VERSION,
        "schema_version": POLICY_BRIEF_SCHEMA_VERSION,
        "schema_name": POLICY_BRIEF_SCHEMA_NAME,
    },
    POLICY_PROPOSE_TASK: {
        "output_model": "PolicyProposeOutput",
        "prompt_version": POLICY_PROPOSE_PROMPT_VERSION,
        "schema_version": POLICY_PROPOSE_SCHEMA_VERSION,
        "schema_name": POLICY_PROPOSE_SCHEMA_NAME,
    },
    STEWARD_EXPLANATION_TASK: {
        "output_model": "StewardExplanationOutput",
        "prompt_version": STEWARD_EXPLANATION_PROMPT_VERSION,
        "schema_version": STEWARD_EXPLANATION_SCHEMA_VERSION,
        "schema_name": STEWARD_EXPLANATION_SCHEMA_NAME,
    },
}

#: The strict output model of every task.
TASK_OUTPUT_MODELS: Final[dict[str, type[MuseOutputModel]]] = {
    EXTRACTION_TASK: ExtractionOutput,
    MATCH_TASK: MatchOutput,
    APPLICANT_ASSIST_TASK: AssistantOutput,
    POLICY_BRIEF_TASK: PolicyBriefOutput,
    POLICY_PROPOSE_TASK: PolicyProposeOutput,
    STEWARD_EXPLANATION_TASK: StewardExplanationOutput,
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
            if key in ("properties", "$defs") and isinstance(value, dict):
                # These map field and definition names, never keywords: a
                # field called "title" is kept.
                strict[key] = {name: _strictify(item) for name, item in value.items()}
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
    "STEWARD_EXPLANATION_PROMPT_VERSION",
    "STEWARD_EXPLANATION_SCHEMA_NAME",
    "STEWARD_EXPLANATION_SCHEMA_VERSION",
    "STEWARD_EXPLANATION_TASK",
    "EXTRACTION_PROMPT_VERSION",
    "EXTRACTION_SCHEMA_NAME",
    "EXTRACTION_SCHEMA_VERSION",
    "EXTRACTION_TASK",
    "POLICY_BRIEF_PROMPT_VERSION",
    "POLICY_BRIEF_SCHEMA_NAME",
    "POLICY_BRIEF_SCHEMA_VERSION",
    "POLICY_BRIEF_TASK",
    "POLICY_PROPOSE_PROMPT_VERSION",
    "POLICY_PROPOSE_SCHEMA_NAME",
    "POLICY_PROPOSE_SCHEMA_VERSION",
    "POLICY_PROPOSE_TASK",
    "POLICY_TASKS",
    "PRIVATE_TASKS",
    "PROPOSING_TASKS",
    "PolicyBriefOutput",
    "PolicyClaim",
    "PolicyProposeOutput",
    "PolicyProposedChange",
    "PolicyRuleRef",
    "PolicySection",
    "PolicySentence",
    "StewardExplanationOutput",
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

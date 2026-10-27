"""A deterministic summary of a case, for the reviewer.

The summary explains; it never decides.  In replay mode (the default) the
summary is built locally from the deterministic rationale, so the demo never
needs a provider call.  Live mode sends the same prompt through Muse Spark
with a strict JSON schema; the parsed summary is validated to name no outcome
different from the deterministic recommendation, and any mismatch, failure or
refusal falls back to the deterministic text.
"""
# REQUIRES: AI-02, AI-04, PER-04
# The Muse summary may only explain.  A summary that names a different
# outcome than the deterministic recommendation is rejected and the
# deterministic text is shown instead.

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from acme_city.muse.client import MuseClient, MuseRequestError, summarize_request

#: The strict schema name of the summary task.
SUMMARY_SCHEMA_NAME = "acme_case_summary"

#: Words that name a decision outcome.  A summary may explain the recorded
#: recommendation but may not introduce a different one.
_OUTCOME_WORDS = {
    "approve": "approve",
    "approved": "approve",
    "approval": "approve",
    "deny": "deny",
    "denied": "deny",
    "denial": "deny",
    "approve_with_conditions": "approve_with_conditions",
    "request_information": "request_information",
    "needs_reviewer_judgment": "needs_reviewer_judgment",
}


class CaseSummaryOutput(BaseModel):
    """The strict output of the summary task: explanation only."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=1200)


def summary_json_schema() -> dict[str, Any]:
    """Return the strict JSON Schema of the summary output."""
    schema = CaseSummaryOutput.model_json_schema()
    properties = schema.get("properties") or {}
    return {
        "type": "object",
        "properties": properties,
        "required": sorted(properties),
        "additionalProperties": False,
    }


def build_summary_payload(
    *, model: str, outcome: str, rationale: str, application_ref: str
) -> dict[str, Any]:
    """Return the outbound payload of one summary request."""
    instructions = (
        "You explain a fictional ACME City permit case to a human reviewer.\n"
        "The recommendation outcome and the rule rationale below are already\n"
        "decided by deterministic rules. Explain them in plain language for\n"
        "the reviewer. Never recommend a different outcome, never approve,\n"
        "deny, price or issue anything, and never add facts that are not in\n"
        "the rationale. Answer with one JSON object matching the schema."
    )
    return {
        "model": model,
        "instructions": instructions,
        "input": (
            f"Application: {application_ref}\n"
            f"Deterministic recommendation outcome: {outcome}\n"
            f"Rule rationale:\n{rationale}"
        ),
        "text": {
            "format": {
                "type": "json_schema",
                "name": SUMMARY_SCHEMA_NAME,
                "schema": summary_json_schema(),
                "strict": True,
            }
        },
        "reasoning": {"effort": "low"},
        "max_output_tokens": 800,
    }


def validate_summary(text: str | None, *, expected_outcome: str) -> str | None:
    """Return the summary when it only explains, else ``None``.

    The text must parse against the strict schema and must not name an
    outcome different from the deterministic recommendation.
    """
    if not text or not text.strip():
        return None
    try:
        data = json.loads(text)
        parsed = CaseSummaryOutput.model_validate(data)
    except Exception:  # noqa: BLE001 - any parse failure means no summary
        return None
    summary = parsed.summary.strip()
    if not summary:
        return None
    for token in re.findall(r"[a-z_]+", summary.lower()):
        named = _OUTCOME_WORDS.get(token)
        if named is not None and named != expected_outcome:
            return None
    return summary


def deterministic_summary(outcome: str, rationale: str) -> str:
    """Return the replay-mode summary: the deterministic explanation itself."""
    return f"Deterministic recommendation: {outcome}. {rationale}"


__all__ = [
    "SUMMARY_SCHEMA_NAME",
    "CaseSummaryOutput",
    "build_summary_payload",
    "deterministic_summary",
    "summary_json_schema",
    "summarize_request",
    "validate_summary",
]

"""The Muse output schemas are strict and the recorded fixtures fit them.

A strict schema refuses an unknown field, requires every field it declares
and stays inside the keyword set a structured-output provider accepts.  The
recorded replay fixtures are outputs of the same schemas.
"""
# REQUIRES: AI-02, AI-03
# The generated JSON Schema forbids unknown fields, lists every property as
# required and carries no keyword a strict provider rejects.

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from acme_city.muse.payloads import fixture_root
from acme_city.muse.schemas import (
    EXTRACTION_SCHEMA_VERSION,
    APPLICANT_ASSIST_SCHEMA_VERSION,
    POLICY_BRIEF_SCHEMA_VERSION,
    POLICY_PROPOSE_SCHEMA_VERSION,
    MATCH_SCHEMA_VERSION,
    STEWARD_EXPLANATION_SCHEMA_VERSION,
    TASK_CONFIG,
    TASK_OUTPUT_MODELS,
    ExtractionOutput,
    MatchOutput,
    strict_json_schema,
    task_schema,
)

#: The keywords a strict structured-output provider does not accept.
UNSUPPORTED_KEYWORDS = {
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


def walk(node: Any):
    """Yield every mapping of a nested structure."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


@pytest.mark.parametrize("task", sorted(TASK_OUTPUT_MODELS))
def test_every_object_forbids_unknown_fields(task: str) -> None:
    schema = task_schema(task)
    objects = [node for node in walk(schema) if node.get("type") == "object"]
    assert objects, "the schema declares no object"
    for node in objects:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])


@pytest.mark.parametrize("task", sorted(TASK_OUTPUT_MODELS))
def test_the_schema_carries_no_unsupported_keyword(task: str) -> None:
    schema = task_schema(task)
    for node in walk(schema):
        for key in node:
            assert key not in UNSUPPORTED_KEYWORDS, f"{key!r} is not a strict keyword"


@pytest.mark.parametrize("task", sorted(TASK_OUTPUT_MODELS))
def test_the_schema_names_its_version(task: str) -> None:
    config = TASK_CONFIG[task]
    assert config["schema_version"] in {
        EXTRACTION_SCHEMA_VERSION,
        MATCH_SCHEMA_VERSION,
        APPLICANT_ASSIST_SCHEMA_VERSION,  # chat 2 added the third task
        POLICY_BRIEF_SCHEMA_VERSION,  # policy 3 added the fourth and fifth tasks
        POLICY_PROPOSE_SCHEMA_VERSION,
        STEWARD_EXPLANATION_SCHEMA_VERSION,  # the steward assistant added the sixth
    }
    assert config["prompt_version"]
    assert config["schema_name"]


def test_the_generated_schema_is_stable() -> None:
    assert strict_json_schema(ExtractionOutput) == strict_json_schema(ExtractionOutput)
    assert task_schema("extraction")["required"] == [
        "application_id",
        "document_id",
        "document_version",
        "observations",
    ]


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(PydanticValidationError):
        ExtractionOutput.model_validate(
            {
                "application_id": "app_synth_001",
                "document_id": "doc_1",
                "document_version": 1,
                "observations": [],
                "decision": "approved",
            }
        )


def test_a_nullable_field_is_required_but_may_be_null() -> None:
    parsed = MatchOutput.model_validate(
        {
            "source_snapshot_id": "snap_1",
            "candidates": [
                {
                    "entity_id": "party_cedarline",
                    "supporting": [],
                    "conflicting": [],
                    "proposal_score": None,
                }
            ],
            "recommended_disposition": "needs_review",
            "explanation": "a proposal",
        }
    )
    assert parsed.candidates[0].proposal_score is None
    schema = task_schema("match_proposal")
    candidate = schema["$defs"]["MatchCandidate"]
    assert "proposal_score" in candidate["required"]
    assert candidate["properties"]["proposal_score"]["anyOf"] == [
        {"type": "number"},
        {"type": "null"},
    ]


def test_the_recorded_fixtures_fit_the_same_schemas() -> None:
    replay = fixture_root() / "replay"
    for name, task in [
        ("extraction-success.json", "extraction"),
        ("match-proposal-success.json", "match_proposal"),
        ("malformed-output.json", "extraction"),
    ]:
        recorded = json.loads((replay / name).read_text(encoding="utf-8"))
        assert recorded["task"] == task
        assert recorded["prompt_version"] == TASK_CONFIG[task]["prompt_version"]
        assert recorded["schema_version"] == TASK_CONFIG[task]["schema_version"]
        # The recorded output parses against the strict model of its task.
        model = TASK_OUTPUT_MODELS[task]
        parsed = model.model_validate(recorded["output"])
        assert parsed is not None


def test_every_replay_fixture_names_its_source_run() -> None:
    replay = fixture_root() / "replay"
    names = sorted(path.name for path in replay.glob("*.json"))
    assert names == [
        "extraction-success.json",
        "malformed-output.json",
        "match-proposal-success.json",
    ]
    for name in names:
        recorded = json.loads((replay / name).read_text(encoding="utf-8"))
        assert recorded["source_run_id"]
        assert recorded["fixture_version"]
        assert recorded["provider"] == "meta"
        assert recorded["model"] == "muse-spark-1.3"
        assert "usage" in recorded
        assert "latency_ms" in recorded


def test_the_replay_fixtures_are_fictional() -> None:
    replay = fixture_root() / "replay"
    for path in replay.glob("*.json"):
        recorded = json.loads(path.read_text(encoding="utf-8"))
        text = json.dumps(recorded).lower()
        assert "westerville" not in text
        assert "city of westerville" not in text

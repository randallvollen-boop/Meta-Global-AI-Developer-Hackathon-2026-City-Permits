"""The bounded Muse integration.

Muse proposes; it never decides.  The package holds the strict output
schemas, the provider client, the actor-scoped evidence bundle, the
validation that stands between a model output and a stored proposal, and the
service that records every run.

A model output only becomes an observation or a match proposal after the
validation passed against the exact stored document version and the records
the acting actor may see.  The evaluator truth file is never read here.
"""
# REQUIRES: AI-01, AI-02, AI-03, AI-04, AI-05
# Strict output schemas, a non-retrying provider client, actor-scoped payloads, model-boundary
# validation and traceable live, replay and cached runs are implemented in this package.

from acme_city.muse.client import (
    MAX_OUTPUT_TOKENS,
    META_RESPONSES_URL,
    MuseClient,
    MuseRequestError,
    ProviderResponse,
)
from acme_city.muse.payloads import (
    CandidateRef,
    DocumentRef,
    SourceRecordRef,
    VisibleEvidenceBundle,
    assert_no_truth_in_payload,
)
from acme_city.muse.schemas import (
    EXTRACTION_SCHEMA_VERSION,
    EXTRACTION_TASK,
    MATCH_SCHEMA_VERSION,
    MATCH_TASK,
    ExtractionOutput,
    MatchOutput,
    strict_json_schema,
    task_schema,
)
from acme_city.muse.service import MuseRunCommand, MuseService, ModelRunView
from acme_city.muse.validation import (
    ValidationIssue,
    ValidationOutcome,
    validate_extraction_output,
    validate_match_output,
)

__all__ = [
    "EXTRACTION_SCHEMA_VERSION",
    "EXTRACTION_TASK",
    "MAX_OUTPUT_TOKENS",
    "MATCH_SCHEMA_VERSION",
    "MATCH_TASK",
    "META_RESPONSES_URL",
    "CandidateRef",
    "DocumentRef",
    "ExtractionOutput",
    "MatchOutput",
    "MuseClient",
    "MuseRequestError",
    "MuseRunCommand",
    "MuseService",
    "ModelRunView",
    "ProviderResponse",
    "SourceRecordRef",
    "ValidationIssue",
    "ValidationOutcome",
    "VisibleEvidenceBundle",
    "assert_no_truth_in_payload",
    "strict_json_schema",
    "task_schema",
    "validate_extraction_output",
    "validate_match_output",
]

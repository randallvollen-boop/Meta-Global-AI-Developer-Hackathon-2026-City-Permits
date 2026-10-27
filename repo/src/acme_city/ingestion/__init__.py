"""Registered source intake.

The package owns the intake of a source record: the raw payload is preserved
first, then validated against the registered contract, then normalized.  It
never publishes a trusted fact on its own and it never establishes an identity
link.
"""
# REQUIRES: ING-01, ING-02, ING-03, ING-04, ING-05
# Raw payload preservation, contract-driven validation, idempotent ingestion keys,
# separate source/effective/receipt times and accurate denominators are implemented
# here. Normalization preserves raw values and never establishes authority or identity.

from acme_city.ingestion.normalization import (
    NormalizedAddress,
    NormalizedName,
    normalize_address,
    normalize_email,
    normalize_identifier,
    normalize_name,
    normalize_phone,
    normalize_text,
)
from acme_city.ingestion.schemas import (
    FieldErrorView,
    IngestCommand,
    IngestResult,
    RecordOutcomeView,
    SourceRecordCommand,
)
from acme_city.ingestion.service import IngestionService
from acme_city.ingestion.validation import (
    DatasetIntakeRules,
    FieldError,
    PayloadValidator,
)

__all__ = [
    "DatasetIntakeRules",
    "FieldError",
    "FieldErrorView",
    "IngestCommand",
    "IngestResult",
    "IngestionService",
    "NormalizedAddress",
    "NormalizedName",
    "PayloadValidator",
    "RecordOutcomeView",
    "SourceRecordCommand",
    "normalize_address",
    "normalize_email",
    "normalize_identifier",
    "normalize_name",
    "normalize_phone",
    "normalize_text",
]

"""Contract-driven payload validation.

The registered source contract supplies the business key, the declared field
types and the allowed values.  The dataset intake rules supply the numeric
fields, the conditional requirements and the reference targets for the
fictional demonstration sources.

Two boundaries are deliberate:

* The intake rules check the *shape* of a source record.  They never apply a
  business threshold: a submitted application that exceeds a review limit is
  valid source data, and the rule catalog decides what to do with it.
* A reference is resolved inside the same source system.  A cross-source
  reference, for example a parcel number quoted by an applicant, is not an
  intake failure: it is a site-resolution question that the registry answers.
"""
# REQUIRES: ING-02
# Type, finite-number, range, enum, conditional, reference and source-version
# validation are implemented here, and every failure carries a field path.

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

#: The reserved fixture-control key.  It never reaches a stored payload and it
#: never carries a business meaning.
CONTROL_FIELD_NAME = "_demo_control"

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class FieldError:
    """One field-level validation failure."""

    field_path: str
    error_code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """Return the stable dictionary form of the error."""
        return {
            "field_path": self.field_path,
            "error_code": self.error_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class NumericFieldRule:
    """A declared numeric field and the range it must stay inside."""

    field: str
    minimum: float | None = None
    maximum: float | None = None
    require_integer: bool = False


@dataclass(frozen=True)
class ReferenceFieldRule:
    """A field that must resolve to a known record of the same source system."""

    field: str
    target_dataset_key: str
    target_record_field: str = "source_record_id"


@dataclass(frozen=True)
class ConditionalRule:
    """A requirement that only applies when another field has a value."""

    when_field: str
    equals: str
    required_fields: tuple[str, ...] = ()
    allowed_values: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class DatasetIntakeRules:
    """The declared shape of one demonstration dataset."""

    dataset_key: str
    numeric_fields: tuple[NumericFieldRule, ...] = ()
    allowed_values: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    non_blank_fields: tuple[str, ...] = ()
    conditional_rules: tuple[ConditionalRule, ...] = ()
    reference_fields: tuple[ReferenceFieldRule, ...] = ()


_APPLICATION_NUMERIC_FIELDS: tuple[NumericFieldRule, ...] = (
    NumericFieldRule("valuation", minimum=0.0),
    NumericFieldRule("valuation_cents", minimum=0, require_integer=True),
    NumericFieldRule("occupancy_load", minimum=0),
    NumericFieldRule("height_ft", minimum=0.0),
    NumericFieldRule("setback_ft", minimum=0.0),
    NumericFieldRule("sign_area_sqft", minimum=0.0),
    NumericFieldRule("frontage_ft", minimum=0.0),
    NumericFieldRule("depth_ft", minimum=0.0),
    NumericFieldRule("lot_coverage_pct", minimum=0.0, maximum=100.0),
    NumericFieldRule("work_duration_days", minimum=0),
)


APPLICATION_RULES = DatasetIntakeRules(
    dataset_key="applications_and_permits",
    numeric_fields=_APPLICATION_NUMERIC_FIELDS,
    allowed_values={
        "structure_kind": ("deck", "fence"),
        "sign_type": ("wall", "monument", "projecting"),
        "illuminated": ("yes", "no"),
        "location": ("front", "side", "rear"),
    },
    conditional_rules=(
        ConditionalRule(
            when_field="structure_kind",
            equals="fence",
            required_fields=("location",),
        ),
        ConditionalRule(
            when_field="structure_kind",
            equals="deck",
            required_fields=("setback_ft",),
        ),
    ),
)

PARCEL_RULES = DatasetIntakeRules(
    dataset_key="parcel_register",
    allowed_values={
        "jurisdiction": ("acme_city",),
    },
    reference_fields=(
        ReferenceFieldRule("address_ref", "address_register"),
    ),
)

ADDRESS_RULES = DatasetIntakeRules(
    dataset_key="address_register",
    allowed_values={
        "unit_type": ("unit", "suite", "space", "floor"),
    },
)

ZONING_RULES = DatasetIntakeRules(
    dataset_key="zoning_register",
    numeric_fields=(
        NumericFieldRule("frontage_ft", minimum=0.0),
        NumericFieldRule("depth_ft", minimum=0.0),
    ),
    reference_fields=(
        ReferenceFieldRule("parcel_number", "parcel_register"),
    ),
)

CONTRACTOR_RULES = DatasetIntakeRules(
    dataset_key="contractor_register",
    allowed_values={
        "status": ("active", "expired", "inactive", "suspended"),
    },
)

BUSINESS_LICENSING_RULES = DatasetIntakeRules(
    dataset_key="business_licensing_register",
    allowed_values={
        "status": ("active", "expired", "suspended", "revoked"),
        "account_role": ("payer", "owner", "agent", "holder"),
    },
)

FINANCE_ACCOUNT_RULES = DatasetIntakeRules(
    dataset_key="finance_accounts",
    allowed_values={
        "account_role": ("payer", "owner", "agent", "holder"),
        "currency": ("USD",),
    },
    reference_fields=(
        ReferenceFieldRule("legacy_account_ref", "finance_accounts"),
    ),
)

PAYMENT_EVENT_RULES = DatasetIntakeRules(
    dataset_key="payment_events",
    allowed_values={
        "event_type": ("received", "settled", "reversed"),
        "currency": ("USD", "EUR"),
    },
    reference_fields=(
        ReferenceFieldRule("source_account_id", "finance_accounts"),
    ),
)

APPLICANT_PROFILE_RULES = DatasetIntakeRules(
    dataset_key="applicant_profiles",
    allowed_values={
        "preferred_contact": ("email", "phone", "mail"),
    },
)


#: Every declared intake rule set, keyed by dataset key.
DATASET_INTAKE_RULES: Mapping[str, DatasetIntakeRules] = {
    rules.dataset_key: rules
    for rules in (
        APPLICATION_RULES,
        APPLICANT_PROFILE_RULES,
        PARCEL_RULES,
        ADDRESS_RULES,
        ZONING_RULES,
        CONTRACTOR_RULES,
        BUSINESS_LICENSING_RULES,
        FINANCE_ACCOUNT_RULES,
        PAYMENT_EVENT_RULES,
    )
}


def intake_rules_for(dataset_key: str) -> DatasetIntakeRules | None:
    """Return the declared intake rules of a dataset, when it has any."""
    return DATASET_INTAKE_RULES.get(dataset_key)


def _is_blank(value: object) -> bool:
    """Return whether a value counts as missing."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _coerce_number(value: object) -> tuple[float | None, str | None]:
    """Return a numeric value and the error code when it is not one.

    A numeric string is accepted and coerced, so ``"20"`` is a number while
    ``"twenty"`` is not and ``"nan"`` is a number that is not finite.
    """
    if isinstance(value, bool):
        return None, "not_a_number"
    if isinstance(value, (int, float)):
        return float(value), None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None, "not_a_number"
        try:
            return float(text), None
        except ValueError:
            return None, "not_a_number"
    return None, "not_a_number"


class PayloadValidator:
    """Validates one source payload against its contract and intake rules.

    The validator never changes the payload.  It reports field errors, and the
    caller decides what to do with them.
    """

    def __init__(
        self,
        *,
        business_key_fields: Sequence[str] = (),
        required_fields: Mapping[str, str] | None = None,
        allowed_values: Mapping[str, Sequence[str]] | None = None,
        rules: DatasetIntakeRules | None = None,
        reference_exists: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._business_key_fields = tuple(business_key_fields)
        self._required_fields = dict(required_fields or {})
        self._allowed_values = {
            field_name: tuple(values) for field_name, values in (allowed_values or {}).items()
        }
        self._rules = rules
        self._reference_exists = reference_exists

    # ------------------------------------------------------------------ public

    def validate(self, payload: Mapping[str, object]) -> list[FieldError]:
        """Return every field error of one payload."""
        errors: list[FieldError] = []
        errors.extend(self._check_business_key(payload))
        errors.extend(self._check_declared_types(payload))
        errors.extend(self._check_enums(payload))
        errors.extend(self._check_numeric(payload))
        errors.extend(self._check_non_blank(payload))
        errors.extend(self._check_conditionals(payload))
        errors.extend(self._check_references(payload))
        return errors

    def validate_source_version(self, source_record_version: str | None) -> list[FieldError]:
        """Return the field errors of a missing source record version."""
        if _is_blank(source_record_version):
            return [
                FieldError(
                    field_path="source_record_version",
                    error_code="missing_source_version",
                    message="the source record version is required so that late arrivals stay ordered",
                )
            ]
        return []

    # ----------------------------------------------------------------- private

    def _check_business_key(self, payload: Mapping[str, object]) -> list[FieldError]:
        errors: list[FieldError] = []
        for field_name in self._business_key_fields:
            if _is_blank(payload.get(field_name)):
                errors.append(
                    FieldError(
                        field_path=field_name,
                        error_code="missing_business_key",
                        message=(
                            f"{field_name} identifies the source record and must be delivered"
                        ),
                    )
                )
        return errors

    def _check_declared_types(self, payload: Mapping[str, object]) -> list[FieldError]:
        errors: list[FieldError] = []
        for field_name, declared_type in self._required_fields.items():
            if field_name not in payload:
                continue
            value = payload[field_name]
            if _is_blank(value):
                continue
            error = _check_declared_type(field_name, value, declared_type)
            if error is not None:
                errors.append(error)
        return errors

    def _check_enums(self, payload: Mapping[str, object]) -> list[FieldError]:
        errors: list[FieldError] = []
        declared = dict(self._allowed_values)
        if self._rules is not None:
            for field_name, values in self._rules.allowed_values.items():
                declared.setdefault(field_name, values)
        for field_name, values in declared.items():
            if field_name not in payload:
                continue
            value = payload[field_name]
            if _is_blank(value):
                continue
            if value not in values:
                errors.append(
                    FieldError(
                        field_path=field_name,
                        error_code="unsupported_value",
                        message=(
                            f"{field_name} is not one of the supported values "
                            f"{list(values)}"
                        ),
                    )
                )
        return errors

    def _check_numeric(self, payload: Mapping[str, object]) -> list[FieldError]:
        errors: list[FieldError] = []
        if self._rules is None:
            return errors
        for numeric_rule in self._rules.numeric_fields:
            if numeric_rule.field not in payload:
                continue
            raw_value = payload[numeric_rule.field]
            if _is_blank(raw_value):
                continue
            number, failure = _coerce_number(raw_value)
            if failure is not None:
                errors.append(
                    FieldError(
                        field_path=numeric_rule.field,
                        error_code=failure,
                        message=f"{numeric_rule.field} must be a number",
                    )
                )
                continue
            assert number is not None
            if not math.isfinite(number):
                errors.append(
                    FieldError(
                        field_path=numeric_rule.field,
                        error_code="not_finite",
                        message=f"{numeric_rule.field} must be a finite number",
                    )
                )
                continue
            if numeric_rule.require_integer and not float(number).is_integer():
                errors.append(
                    FieldError(
                        field_path=numeric_rule.field,
                        error_code="not_an_integer",
                        message=f"{numeric_rule.field} must be a whole number of minor units",
                    )
                )
                continue
            if numeric_rule.minimum is not None and number < numeric_rule.minimum:
                errors.append(
                    FieldError(
                        field_path=numeric_rule.field,
                        error_code="below_minimum",
                        message=(
                            f"{numeric_rule.field} must not be below {numeric_rule.minimum}"
                        ),
                    )
                )
            if numeric_rule.maximum is not None and number > numeric_rule.maximum:
                errors.append(
                    FieldError(
                        field_path=numeric_rule.field,
                        error_code="above_maximum",
                        message=(
                            f"{numeric_rule.field} must not be above {numeric_rule.maximum}"
                        ),
                    )
                )
        return errors

    def _check_non_blank(self, payload: Mapping[str, object]) -> list[FieldError]:
        errors: list[FieldError] = []
        if self._rules is None:
            return errors
        for field_name in self._rules.non_blank_fields:
            if field_name not in payload:
                continue
            if _is_blank(payload[field_name]):
                errors.append(
                    FieldError(
                        field_path=field_name,
                        error_code="blank_value",
                        message=f"{field_name} must not be blank",
                    )
                )
        return errors

    def _check_conditionals(self, payload: Mapping[str, object]) -> list[FieldError]:
        errors: list[FieldError] = []
        if self._rules is None:
            return errors
        for conditional in self._rules.conditional_rules:
            if payload.get(conditional.when_field) != conditional.equals:
                continue
            for field_name in conditional.required_fields:
                if field_name not in payload:
                    errors.append(
                        FieldError(
                            field_path=field_name,
                            error_code="conditional_required_field",
                            message=(
                                f"{field_name} is required when "
                                f"{conditional.when_field} is {conditional.equals!r}"
                            ),
                        )
                    )
                elif _is_blank(payload[field_name]):
                    errors.append(
                        FieldError(
                            field_path=field_name,
                            error_code="conditional_required_field",
                            message=(
                                f"{field_name} must not be blank when "
                                f"{conditional.when_field} is {conditional.equals!r}"
                            ),
                        )
                    )
            for field_name, values in conditional.allowed_values:
                if field_name not in payload:
                    continue
                value = payload[field_name]
                if _is_blank(value):
                    continue
                if value not in values:
                    errors.append(
                        FieldError(
                            field_path=field_name,
                            error_code="conditional_unsupported_value",
                            message=(
                                f"{field_name} is not one of the supported values "
                                f"{list(values)} when {conditional.when_field} is "
                                f"{conditional.equals!r}"
                            ),
                        )
                    )
        return errors

    def _check_references(self, payload: Mapping[str, object]) -> list[FieldError]:
        errors: list[FieldError] = []
        if self._rules is None or self._reference_exists is None:
            return errors
        for reference_rule in self._rules.reference_fields:
            if reference_rule.field not in payload:
                continue
            value = payload[reference_rule.field]
            if _is_blank(value):
                continue
            if not self._reference_exists(reference_rule.target_dataset_key, str(value)):
                errors.append(
                    FieldError(
                        field_path=reference_rule.field,
                        error_code="unresolved_reference",
                        message=(
                            f"{reference_rule.field} does not resolve to a known "
                            f"{reference_rule.target_dataset_key} record"
                        ),
                    )
                )
        return errors


def _check_declared_type(
    field_name: str, value: object, declared_type: str
) -> FieldError | None:
    """Return the field error of one declared type, when the value fails it."""
    normalized = str(declared_type).strip().lower()
    if normalized in {"string", "enum"}:
        if not isinstance(value, str):
            return FieldError(
                field_path=field_name,
                error_code="not_a_string",
                message=f"{field_name} must be text",
            )
        return None
    if normalized == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return FieldError(
                field_path=field_name,
                error_code="not_an_integer",
                message=f"{field_name} must be a whole number",
            )
        return None
    if normalized == "number":
        number, failure = _coerce_number(value)
        if failure is not None:
            return FieldError(
                field_path=field_name,
                error_code=failure,
                message=f"{field_name} must be a number",
            )
        assert number is not None
        if not math.isfinite(number):
            return FieldError(
                field_path=field_name,
                error_code="not_finite",
                message=f"{field_name} must be a finite number",
            )
        return None
    if normalized == "money_minor_units":
        if isinstance(value, bool):
            return FieldError(
                field_path=field_name,
                error_code="not_an_integer",
                message=f"{field_name} must be a whole number of minor units",
            )
        if isinstance(value, float):
            if not value.is_integer():
                return FieldError(
                    field_path=field_name,
                    error_code="not_an_integer",
                    message=f"{field_name} must be a whole number of minor units",
                )
            value = int(value)
        if not isinstance(value, int):
            return FieldError(
                field_path=field_name,
                error_code="not_an_integer",
                message=f"{field_name} must be a whole number of minor units",
            )
        if value < 0:
            return FieldError(
                field_path=field_name,
                error_code="negative_amount",
                message=f"{field_name} must not be negative",
            )
        return None
    if normalized == "date":
        if not isinstance(value, str) or not _DATE_PATTERN.match(value):
            return FieldError(
                field_path=field_name,
                error_code="not_a_date",
                message=f"{field_name} must be a calendar date",
            )
        try:
            date.fromisoformat(value)
        except ValueError:
            return FieldError(
                field_path=field_name,
                error_code="not_a_date",
                message=f"{field_name} must be a calendar date",
            )
        return None
    if normalized == "timestamp":
        if not isinstance(value, str):
            return FieldError(
                field_path=field_name,
                error_code="not_a_timestamp",
                message=f"{field_name} must be a timestamp",
            )
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return FieldError(
                field_path=field_name,
                error_code="not_a_timestamp",
                message=f"{field_name} must be a timestamp",
            )
        return None
    if normalized == "email":
        if not isinstance(value, str) or not _EMAIL_PATTERN.match(value.strip()):
            return FieldError(
                field_path=field_name,
                error_code="not_an_email",
                message=f"{field_name} must be an email address",
            )
        return None
    if normalized == "phone":
        if not isinstance(value, str) or len(re.sub(r"\D", "", value)) < 7:
            return FieldError(
                field_path=field_name,
                error_code="not_a_phone",
                message=f"{field_name} must be a telephone number",
            )
        return None
    if normalized == "currency":
        if not isinstance(value, str) or not _CURRENCY_PATTERN.match(value.strip()):
            return FieldError(
                field_path=field_name,
                error_code="not_a_currency",
                message=f"{field_name} must be an ISO currency code",
            )
        return None
    if normalized == "reference":
        if not isinstance(value, str) or not value.strip():
            return FieldError(
                field_path=field_name,
                error_code="not_a_reference",
                message=f"{field_name} must reference a known record",
            )
        return None
    return None


__all__ = [
    "ADDRESS_RULES",
    "APPLICATION_RULES",
    "APPLICANT_PROFILE_RULES",
    "BUSINESS_LICENSING_RULES",
    "CONTROL_FIELD_NAME",
    "CONTRACTOR_RULES",
    "DATASET_INTAKE_RULES",
    "DatasetIntakeRules",
    "FieldError",
    "FINANCE_ACCOUNT_RULES",
    "NumericFieldRule",
    "PARCEL_RULES",
    "PAYMENT_EVENT_RULES",
    "PayloadValidator",
    "ReferenceFieldRule",
    "ConditionalRule",
    "ZONING_RULES",
    "intake_rules_for",
]

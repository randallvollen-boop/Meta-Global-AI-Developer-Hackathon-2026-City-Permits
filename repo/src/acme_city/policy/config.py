"""The frozen effective configuration a simulation scores cases against.

A :class:`PolicyConfig` holds the permit types, the published rule versions and
the published fee schedule versions as immutable values.  It is frozen at an
``analysis_at`` moment: the rules in force at that moment are the baseline.
Nothing in this module reads the database.
"""
# REQUIRES: REF-01, PER-06
# One effective configuration is frozen at a recorded moment and hashed, so a
# result can name exactly what it was scored against.

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from acme_city.kernel.intake import TypeFacts
from acme_city.kernel.selection import published_in_force
from acme_city.rules.schemas import RuleSetVersion, RuleVersionView

#: The process categories a permit type may hold.
PROCESS_CATEGORIES: tuple[str, ...] = ("simple", "with_plans", "formal_review")


def canonical_json(value: Any) -> str:
    """Return the canonical JSON text of ``value`` (sorted keys, no spaces)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, tuple):
        return list(value)
    return str(value)


def digest(value: Any) -> str:
    """Return the SHA-256 hex digest of the canonical JSON of ``value``."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _frozen(value: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """Return a read-only deep copy of a JSON-like mapping."""
    if value is None:
        return None
    return MappingProxyType(json.loads(canonical_json(value)))


@dataclass(frozen=True)
class TypeConfig:
    """One permit type as the simulation sees it."""

    key: str
    label: str
    active: bool
    review_area: str | None
    review_route: str
    process_category: str | None
    discretionary: bool
    required_fields: tuple[str, ...]
    required_documents: tuple[str, ...]
    fee_schedule_key: str | None
    service_target_days: int

    def facts(self) -> TypeFacts:
        """Return the facts the pure intake producers read."""
        return TypeFacts(
            key=self.key,
            label=self.label,
            active=self.active,
            fee_schedule_key=self.fee_schedule_key,
            review_area=self.review_area,
            review_route=self.review_route,
            required_fields=self.required_fields,
            required_documents=self.required_documents,
        )

    def canonical(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "active": self.active,
            "review_area": self.review_area,
            "review_route": self.review_route,
            "process_category": self.process_category,
            "discretionary": self.discretionary,
            "required_fields": list(self.required_fields),
            "required_documents": list(self.required_documents),
            "fee_schedule_key": self.fee_schedule_key,
            "service_target_days": self.service_target_days,
        }


@dataclass(frozen=True)
class RuleConfig:
    """One published rule version as the simulation sees it."""

    rule_id: str
    version_label: str
    row_id: str
    version: int
    permit_type_key: str | None
    title: str
    citation: str
    field_path: str | None
    operator: str | None
    limit_value: str | None
    on_violate: str | None
    condition: Mapping[str, Any] | None
    message: str | None
    condition_note: str | None
    effective_from: datetime
    effective_to: datetime | None
    unit: str | None = None
    status: str = "published"

    def __post_init__(self) -> None:
        object.__setattr__(self, "condition", _frozen(self.condition))

    @classmethod
    def from_view(cls, view: RuleVersionView) -> RuleConfig:
        return cls(
            rule_id=view.rule_id,
            version_label=view.version_label,
            row_id=view.row_id,
            version=view.version,
            permit_type_key=view.permit_type_key,
            title=view.title,
            citation=view.citation,
            field_path=view.field_path,
            operator=view.operator,
            limit_value=view.limit_value,
            on_violate=view.on_violate,
            condition=view.condition,
            message=view.message,
            condition_note=view.condition_note,
            effective_from=view.effective_from,
            effective_to=view.effective_to,
            unit=view.unit,
            status=view.status,
        )

    def to_view(self) -> RuleVersionView:
        return RuleVersionView(
            rule_id=self.rule_id,
            version_label=self.version_label,
            row_id=self.row_id,
            version=self.version,
            permit_type_key=self.permit_type_key,
            kind="executable",
            title=self.title,
            citation=self.citation,
            field_path=self.field_path,
            operator=self.operator,
            limit_value=self.limit_value,
            on_violate=self.on_violate,
            condition=None if self.condition is None else json.loads(canonical_json(self.condition)),
            message=self.message,
            condition_note=self.condition_note,
            effective_from=self.effective_from,
            effective_to=self.effective_to,
            status=self.status,
            unit=self.unit,
        )

    def canonical(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "version_label": self.version_label,
            "permit_type_key": self.permit_type_key,
            "citation": self.citation,
            "field_path": self.field_path,
            "operator": self.operator,
            "limit_value": self.limit_value,
            "on_violate": self.on_violate,
            "condition": None if self.condition is None else dict(self.condition),
            "message": self.message,
            "condition_note": self.condition_note,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": None if self.effective_to is None else self.effective_to.isoformat(),
            "unit": self.unit,
            "status": self.status,
        }


@dataclass(frozen=True)
class FeeScheduleConfig:
    """One published fee schedule version as the simulation sees it."""

    fee_schedule_id: str
    version_label: str
    row_id: str
    effective_from: datetime
    effective_to: datetime | None
    currency: str
    definition: Mapping[str, Any] = field(default_factory=dict)
    status: str = "published"

    def __post_init__(self) -> None:
        object.__setattr__(self, "definition", _frozen(self.definition or {}))

    def canonical(self) -> dict[str, Any]:
        return {
            "fee_schedule_id": self.fee_schedule_id,
            "version_label": self.version_label,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": None if self.effective_to is None else self.effective_to.isoformat(),
            "currency": self.currency,
            "definition": dict(self.definition),
            "status": self.status,
        }


@dataclass(frozen=True)
class PolicyConfig:
    """The effective configuration frozen at ``analysis_at``."""

    analysis_at: datetime
    permit_types: tuple[TypeConfig, ...]
    rules: tuple[RuleConfig, ...]
    fee_schedules: tuple[FeeScheduleConfig, ...]

    def type_config(self, key: str) -> TypeConfig | None:
        for item in self.permit_types:
            if item.key == key:
                return item
        return None

    def rules_in_force(self, type_key: str, at: datetime | None = None) -> tuple[RuleConfig, ...]:
        """Return the published rules of a type in force at ``at`` (default ``analysis_at``).

        Rules come back in catalogue order (by rule identifier), exactly as the
        stored catalogue returns them for one type.
        """
        moment = at or self.analysis_at
        chosen = [
            rule
            for rule in self.rules
            if rule.permit_type_key == type_key and published_in_force(rule, moment)
        ]
        return tuple(sorted(chosen, key=lambda rule: rule.rule_id))

    def rule_set(self, type_key: str, at: datetime | None = None) -> RuleSetVersion:
        """Return the selected rule versions of a type as an evaluator rule set."""
        moment = at or self.analysis_at
        views = [rule.to_view() for rule in self.rules_in_force(type_key, moment)]
        citations: list[str] = []
        for view in views:
            if view.citation not in citations:
                citations.append(view.citation)
        return RuleSetVersion(
            rule_set_id=f"ruleset:executable:{type_key}:{moment.isoformat()}",
            kind="executable",
            permit_type_key=type_key,
            basis_at=moment,
            basis_label="analysis_at",
            rules=views,
            fee_schedule=None,
            citations=citations,
        )

    def canonical(self) -> dict[str, Any]:
        return {
            "analysis_at": self.analysis_at.isoformat(),
            "permit_types": [item.canonical() for item in self.permit_types],
            "rules": [item.canonical() for item in self.rules],
            "fee_schedules": [item.canonical() for item in self.fee_schedules],
        }

    @property
    def config_hash(self) -> str:
        """Return the hash of the canonical content of this configuration."""
        return digest(self.canonical())


__all__ = [
    "PROCESS_CATEGORIES",
    "FeeScheduleConfig",
    "PolicyConfig",
    "RuleConfig",
    "TypeConfig",
    "canonical_json",
    "digest",
]

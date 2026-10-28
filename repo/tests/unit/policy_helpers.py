"""Shared builders for the policy simulation tests (no database).

The baseline is built from the committed catalogue file, so a unit test can
score hand-made frozen cases without migrating a database.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from acme_city.policy.config import FeeScheduleConfig, PolicyConfig, RuleConfig, TypeConfig
from acme_city.policy.population import CaseInput

CATALOGUE = Path(__file__).resolve().parents[2] / "config" / "rules_and_fees.json"
ANALYSIS_AT = datetime(2026, 10, 28, tzinfo=UTC)
ARRIVAL = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


def _when(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text.replace("Z", "+00:00"))


def catalogue_baseline(analysis_at: datetime = ANALYSIS_AT) -> PolicyConfig:
    """Freeze the published part of the committed catalogue file."""
    data = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    types = tuple(
        TypeConfig(
            key=item["key"],
            label=item["label"],
            active=item.get("active", True),
            review_area=item.get("review_area"),
            review_route=item["review_route"],
            process_category=item.get("process_category"),
            discretionary=bool(item.get("discretionary")),
            required_fields=tuple(item.get("required_fields") or ()),
            required_documents=tuple(item.get("required_documents") or ()),
            fee_schedule_key=item.get("fee_schedule_key"),
            service_target_days=int(item.get("service_target_days") or 0),
        )
        for item in data["permit_types"]
    )
    rules = tuple(
        RuleConfig(
            rule_id=item["rule_id"],
            version_label=f"{item['rule_id']}@{item['version']}",
            row_id=f"rulever_{item['rule_id']}_v{item['version']}",
            version=1,
            permit_type_key=item["permit_type"],
            title=item["title"],
            citation=item["citation"],
            field_path=item["field_path"],
            operator=item["operator"],
            limit_value=item["limit_value"],
            on_violate=item["on_violate"],
            condition=item["condition"],
            message=item["message"],
            condition_note=item["condition_note"],
            effective_from=_when(item["effective_from"]),
            effective_to=_when(item["effective_to"]),
            unit=(item.get("source_mapping") or {}).get("unit"),
        )
        for item in data["rules"]
        if item["status"] == "published"
    )
    schedules = tuple(
        FeeScheduleConfig(
            fee_schedule_id=item["fee_schedule_id"],
            version_label=item["version_label"],
            row_id=f"fee_{item['fee_schedule_id']}_{item['version_label']}",
            effective_from=_when(item["effective_from"]),
            effective_to=_when(item["effective_to"]),
            currency=item["currency"],
            definition=item["definition"],
        )
        for item in data["fee_schedules"]
        if item["status"] == "published"
    )
    return PolicyConfig(analysis_at, types, rules, schedules)


def fence(ref: str, height: float, *, location: str = "side_rear", **extra) -> CaseInput:
    """Return a complete frozen fence case."""
    facts = {
        "parcel_number": "ACME-P-1001",
        "project_description": f"{height} ft {location} fence",
        "height_ft": height,
        "setback_ft": 10,
        "structure_kind": "fence",
        "location": location,
        "valuation": "3000.00",
    }
    facts.update(extra.pop("facts", {}))
    return CaseInput.create(
        case_ref=ref,
        permit_type_key="deck_fence",
        basis_at=ARRIVAL,
        facts=facts,
        intake_record={
            "channel": "portal",
            "applicant_name": f"Applicant {ref}",
            "submitted_site_text": f"{ref} Lantern Row",
        },
        documents=extra.pop("documents", ["site_plan", "material_spec"]),
        **extra,
    )


def shed(ref: str, area: float, **extra) -> CaseInput:
    facts = {
        "parcel_number": "ACME-P-1002",
        "project_description": f"{area} sq ft shed",
        "shed_area_sqft": area,
        "valuation": "2000.00",
    }
    facts.update(extra.pop("facts", {}))
    return CaseInput.create(
        case_ref=ref,
        permit_type_key="shed",
        basis_at=ARRIVAL,
        facts=facts,
        intake_record={"channel": "portal", "applicant_name": f"Applicant {ref}",
                       "submitted_site_text": f"{ref} Maple Court"},
        documents=extra.pop("documents", ["site_plan", "material_spec"]),
        **extra,
    )

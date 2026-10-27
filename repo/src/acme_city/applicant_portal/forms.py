"""The 17 application forms of the applicant portal.

Each permit type asks for plain-labelled fields and a document checklist.  The
form merges the portal's own fields with the permit type's existing
``required_fields`` and ``required_documents`` (the existing ones are always
kept), so a case that the form calls complete is also complete for the intake
agent.  The property address is not a field of this table: it is collected by
the address locator, which also supplies the parcel number and the property
address a type may require.
"""
# REQUIRES: PORTAL-01, PORTAL-02
# The form lists every required field and document by its plain label and the
# server decides whether the application is complete.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: The notice the portal shows.  It is ACME's own and fictional.
PORTAL_NOTICE = "ACME City never asks for permit fees by gift card or wire transfer."

CERTIFICATION_TEXT = (
    "I certify that the information in this application is accurate and complete to "
    "the best of my knowledge."
)

#: The three process pills.
PROCESS_PILLS: dict[str, tuple[str, str]] = {
    "simple": (
        "Permit portal",
        "Submit directly. No formal plan review.",
    ),
    "with_plans": (
        "Portal + plans",
        "Submit with construction plans. Routed to review.",
    ),
    "formal_review": (
        "Plan review process",
        "Formal review. May need a board hearing.",
    ),
}

#: The chooser groups and the permit types in each.
GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "quick_home",
        "Quick home projects",
        (
            "deck_fence",
            "patio",
            "shed",
            "pod",
            "hvac",
            "water_heater",
            "residential_electric",
        ),
    ),
    (
        "building_plans",
        "Building with plans",
        ("res_building", "com_ti", "fire_alarm", "sign"),
    ),
    (
        "formal",
        "Formal review",
        (
            "change_occupancy",
            "site_plan_review",
            "rezoning",
            "zoning_variance",
            "certificate_appropriateness",
            "row_encroachment",
        ),
    ),
)

#: Plain labels of the documents.
DOCUMENT_LABELS: dict[str, str] = {
    "site_plan": "Site sketch or site plan",
    "material_spec": "Material specification",
    "construction_plans": "Construction plans",
    "energy_compliance_form": "Energy compliance form",
    "floor_plan": "Floor plan",
    "fire_suppression_plan": "Fire suppression plan",
    "business_license_copy": "Business license copy",
    "sign_drawing": "Sign drawing",
    "owner_authorization": "Owner authorization",
    "traffic_control_plan": "Traffic control plan",
    "insurance_certificate": "Certificate of insurance",
    "contractor_license_copy": "Contractor license",
    "change_of_use_notice": "Change of use notice",
    "property_survey": "Property survey",
    "legal_description": "Legal description",
    "hardship_statement": "Hardship statement",
    "photographs": "Photographs",
    "design_drawings": "Design drawings",
    "supporting_document": "Supporting document",
}

#: Plain labels of fields the permit types already require.
FIELD_LABELS: dict[str, str] = {
    "parcel_number": "Parcel number",
    "property_address": "Property address",
    "project_description": "Project description",
    "valuation": "Project value (USD)",
    "contractor_license": "Contractor license number",
    "front_setback_ft": "Front setback (ft)",
    "lot_coverage_pct": "Lot coverage (percent)",
    "height_ft": "Fence height (ft)",
    "setback_ft": "Setback from the property line (ft)",
    "occupancy_load": "Occupancy load (people)",
    "sign_type": "Sign type",
    "sign_area_sqft": "Sign dimensions (sq ft)",
    "work_description": "Work description",
    "work_duration_days": "Work duration (days)",
    "patio_width_ft": "Patio width (ft)",
    "shed_area_sqft": "Structure area (sq ft)",
    "pod_duration_days": "Duration (days)",
    "prior_use": "Prior use",
    "proposed_use": "Proposed use",
    "current_zoning": "Current zoning",
    "proposed_zoning": "Requested zoning",
    "variance_reason": "Variance requested",
}

#: Fields that the address locator supplies, never typed by the applicant.
LOCATOR_FIELDS: frozenset[str] = frozenset({"parcel_number", "property_address"})


@dataclass(frozen=True)
class FieldSpec:
    """One field of an application form."""

    key: str
    label: str
    kind: str = "text"  # text | number | textarea | select | checkbox
    options: tuple[tuple[str, str], ...] = ()
    hint: str = ""
    required: bool = True


def _f(key: str, label: str | None = None, kind: str = "text", **extra: Any) -> FieldSpec:
    return FieldSpec(key=key, label=label or FIELD_LABELS.get(key, key), kind=kind, **extra)



#: The portal's own fields and extra documents per permit type.  The permit
#: type's existing required fields and documents are merged in by
#: :func:`form_for`.
_SPECS: dict[str, dict[str, Any]] = {
    "deck_fence": {
        "note": "Fences are limited by height and location. The front yard has a lower limit than the side or rear.",
        "needs_business": False,
        "fields": (
            _f("height_ft", "Fence height (ft)", "number"),
            _f("fence_material", "Fence material"),
            _f(
                "location",
                "Location on the property",
                "select",
                options=(("front", "Front yard"), ("side_rear", "Side or rear yard")),
            ),
            _f("setback_ft", kind="number"),
            _f("property_line_ack", "I will not build over the property line", "checkbox"),
            _f("project_description", kind="textarea"),
        ),
        "documents": ("site_plan", "material_spec"),
        "facts": {"structure_kind": "fence"},
    },
    "patio": {
        "note": "A patio must keep its distance from the property line.",
        "fields": (
            _f("patio_width_ft", "Patio width (ft)", "number"),
            _f("patio_length_ft", "Patio length (ft)", "number"),
            _f("setback_ack", "I acknowledge the setback rules", "checkbox"),
            _f("project_description", kind="textarea"),
        ),
        "documents": ("site_plan",),
    },
    "shed": {
        "note": "Sheds above the exempt size need a full review.",
        "fields": (
            _f("shed_area_sqft", "Structure area (sq ft)", "number"),
            _f("setback_ack", "I acknowledge the setback rules", "checkbox"),
            _f("project_description", kind="textarea"),
        ),
        "documents": ("site_plan", "material_spec"),
    },
    "pod": {
        "note": "A temporary container may not stay beyond the permitted days.",
        "fields": (
            _f("pod_location", "Placement location"),
            _f("pod_duration_days", "Duration (days)", "number"),
            _f("project_description", kind="textarea"),
        ),
        "documents": ("site_plan",),
    },
    "hvac": {
        "note": "A licensed contractor must do this work.",
        "fields": (
            _f("contractor_license"),
            _f("equipment_type", "Equipment type"),
            _f("project_description", kind="textarea"),
        ),
        "documents": ("contractor_license_copy",),
    },
    "water_heater": {
        "note": "A licensed contractor must do this work.",
        "fields": (
            _f("contractor_license"),
            _f("equipment_type", "Equipment type"),
            _f("project_description", kind="textarea"),
        ),
        "documents": ("contractor_license_copy",),
    },
    "residential_electric": {
        "note": "Describe the service or panel work.",
        "fields": (
            _f("work_description", kind="textarea"),
            _f("project_description", kind="textarea"),
        ),
        "documents": ("contractor_license_copy",),
    },
    "res_building": {
        "note": "Submit construction plans. The plans are routed to review.",
        "fields": (
            _f("project_description", kind="textarea"),
            _f("valuation", kind="number"),
            _f("contractor_license"),
            _f("front_setback_ft", kind="number"),
            _f("lot_coverage_pct", kind="number"),
        ),
        "documents": ("construction_plans", "site_plan", "energy_compliance_form"),
    },
    "com_ti": {
        "needs_business": True,
        "note": "Submit construction plans and a fire suppression plan.",
        "fields": (
            _f("project_description", kind="textarea"),
            _f("valuation", kind="number"),
            _f("occupancy_load", kind="number"),
            _f("contractor_license"),
        ),
        "documents": (
            "construction_plans",
            "site_plan",
            "fire_suppression_plan",
            "floor_plan",
            "business_license_copy",
        ),
    },
    "fire_alarm": {
        "needs_business": True,
        "note": "A commercial fire alarm system is reviewed with its plans.",
        "fields": (
            _f("work_description", kind="textarea"),
            _f("project_description", kind="textarea"),
            _f("valuation", kind="number"),
        ),
        "documents": ("construction_plans", "fire_suppression_plan"),
    },
    "sign": {
        "needs_business": True,
        "note": "Signs are reviewed by planning and zoning.",
        "fields": (
            _f("sign_area_sqft", "Sign dimensions (sq ft)", "number"),
            _f(
                "sign_type",
                "Sign type",
                "select",
                options=(
                    ("wall", "Wall sign"),
                    ("monument", "Monument sign"),
                    ("projecting", "Projecting sign"),
                    ("window", "Window sign"),
                ),
            ),
        ),
        "documents": ("sign_drawing", "site_plan", "owner_authorization"),
    },
    "change_occupancy": {
        "needs_business": True,
        "note": "A change of use needs a formal review and may need a board hearing.",
        "fields": (
            _f("prior_use"),
            _f("proposed_use"),
            _f("occupancy_load", kind="number"),
            _f("project_description", kind="textarea"),
        ),
        "documents": ("floor_plan", "change_of_use_notice"),
    },
    "site_plan_review": {
        "note": "A site plan is reviewed by the planning board.",
        "fields": (_f("project_description", kind="textarea"),),
        "documents": ("site_plan", "property_survey"),
    },
    "rezoning": {
        "note": "A rezoning is decided by a person or a board, never by the portal.",
        "fields": (
            _f("current_zoning"),
            _f("proposed_zoning"),
            _f("justification", "Justification", "textarea"),
            _f("project_description", kind="textarea"),
        ),
        "documents": ("legal_description", "site_plan"),
    },
    "row_encroachment": {
        "note": "Work in the public right of way needs a traffic control plan and insurance.",
        "fields": (
            _f("work_description", kind="textarea"),
            _f("work_duration_days", "Work duration (days)", "number"),
            _f("contractor_license"),
            _f("insurance_carrier", "Insurance carrier"),
        ),
        "documents": ("traffic_control_plan", "insurance_certificate", "site_plan"),
    },
    "zoning_variance": {
        "note": "A variance is decided by a person or a board, never by the portal.",
        "fields": (
            _f("variance_reason", "Variance requested", "textarea"),
            _f("hardship_description", "Hardship description", "textarea"),
            _f("project_description", kind="textarea"),
        ),
        "documents": ("site_plan", "hardship_statement"),
    },
    "certificate_appropriateness": {
        "note": "Changes to a property in a historic district need a certificate.",
        "fields": (
            _f("historic_district", "Historic district"),
            _f("proposed_changes", "Proposed changes", "textarea"),
            _f("project_description", kind="textarea"),
        ),
        "documents": ("photographs", "design_drawings", "owner_authorization"),
    },
}


@dataclass
class FormSpec:
    """The merged application form of one permit type."""

    type_key: str
    label: str
    description: str
    process_category: str
    pill: str
    pill_text: str
    note: str
    needs_business: bool
    fields: list[FieldSpec]
    documents: list[tuple[str, str]]
    constant_facts: dict[str, Any]
    discretionary: bool = False


def humanize(key: str) -> str:
    """Return a plain label for a key that has none."""
    return FIELD_LABELS.get(key) or key.replace("_", " ").capitalize()


def form_for(
    type_key: str,
    *,
    label: str,
    description: str,
    process_category: str | None,
    required_fields: list[str],
    required_documents: list[str],
    discretionary: bool | None = None,
) -> FormSpec:
    """Merge the portal's fields with the type's existing requirements."""
    spec = _SPECS.get(type_key, {})
    fields = list(spec.get("fields", ()))
    seen = {item.key for item in fields}
    for key in required_fields:
        if key in seen or key in LOCATOR_FIELDS:
            continue
        fields.append(FieldSpec(key=key, label=humanize(key)))
        seen.add(key)
    documents: list[str] = []
    for key in list(spec.get("documents", ())) + list(required_documents):
        if key not in documents:
            documents.append(key)
    category = process_category or "simple"
    pill, pill_text = PROCESS_PILLS.get(category, PROCESS_PILLS["simple"])
    return FormSpec(
        type_key=type_key,
        label=label,
        description=description,
        process_category=category,
        pill=pill,
        pill_text=pill_text,
        note=spec.get("note", ""),
        needs_business=bool(spec.get("needs_business", False)),
        fields=fields,
        documents=[(key, DOCUMENT_LABELS.get(key, humanize(key))) for key in documents],
        constant_facts=dict(spec.get("facts", {})),
        discretionary=bool(discretionary),
    )


__all__ = [
    "CERTIFICATION_TEXT",
    "DOCUMENT_LABELS",
    "FIELD_LABELS",
    "GROUPS",
    "LOCATOR_FIELDS",
    "PORTAL_NOTICE",
    "PROCESS_PILLS",
    "FieldSpec",
    "FormSpec",
    "form_for",
    "humanize",
]

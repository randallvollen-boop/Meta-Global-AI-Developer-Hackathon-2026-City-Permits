"""Plain data for the what-if screens.

The functions here turn stored scenarios and stored runs into dictionaries the
templates render.  They read only what a run stored (a run is never re-scored
to be shown) and they put every wording rule in one place:

* the figures are counts, never staff time, processing time or throughput;
* fees are "hypothetical assessed fees", never income;
* a population is always labelled "Synthetic year (sample data)" or
  "Retrospective re-scoring";
* a retired rule that produces holds is explained in plain words.
"""
# REQUIRES: UX-01, PER-02
# The screens state only what a stored run measured, with its label.

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from acme_city.kernel.adjudication import (
    OUTCOME_APPROVE,
    OUTCOME_CONDITIONS,
    OUTCOME_DENY,
    OUTCOME_HOLD,
)
from acme_city.persistence.models import policy as models
from acme_city.policy.changes import (
    _UNSUPPORTED_MESSAGES,
    UnsupportedChange,
    apply_scenario,
    parse_change,
)
from acme_city.policy.config import PROCESS_CATEGORIES, PolicyConfig
from acme_city.policy.runs import SPEC_KINDS, scenario_from_changes

OUTCOME_LABELS: dict[str, str] = {
    OUTCOME_APPROVE: "Recommend approval",
    OUTCOME_CONDITIONS: "Recommend approval with conditions",
    OUTCOME_HOLD: "Held for a person",
    OUTCOME_DENY: "Recommend denial",
}
OUTCOME_ORDER: tuple[str, ...] = (OUTCOME_APPROVE, OUTCOME_CONDITIONS, OUTCOME_HOLD, OUTCOME_DENY)

RULE_LABELS = {"pass": "Passes", "condition": "Passes with a condition", "review": "Needs review", "fail": "Fails a rule"}
RULE_ORDER = ("pass", "condition", "review", "fail")

ROUTE_LABELS = {"ready_for_review": "Ready for review", "needs_information": "Needs information"}

DIRECTION_LABELS = {
    "relaxed": "Relaxed (a more permissive result)",
    "tightened": "Tightened (a less permissive result)",
    "changed_otherwise": "Changed in another way",
    "unchanged": "Unchanged",
}

HOLD_REASON_LABELS = {
    "discretionary": "a discretionary permit type",
    "no_rules": "no published rule applies",
    "rule_review": "a rule needs a person's judgement or the case falls in a category the rules do not know",
}

KIND_LABELS = {
    "rule_threshold": "Change a rule's limit or operator",
    "rule_retirement": "Retire a rule for every case",
    "requirement": "Add or remove a required field or document",
    "process_category": "Move a permit type to another process category",
    "discretionary": "Make a permit type discretionary or by right",
    "service_target": "Change a service target",
    "fee": "Change a fixed charge or a valuation multiplier",
}

UNSUPPORTED_OPTIONS = (
    ("no_permit_required", "A permit that is no longer required"),
    ("conditional_plan_review_removal", "Removing plan review for some cases only"),
)

RETIRE_NOTE = (
    "Retiring a rule does not approve the cases it used to stop. A case that the "
    "remaining rules cannot place in a known category is put on review hold for a "
    "person. For example, retiring ACME Code §14-306 (rule DF-2) puts side and rear "
    "yard fences on review hold rather than approving them, because the remaining "
    "fence rules do not know that category."
)

SYNTHETIC_NOTE = (
    "Synthetic data: every case in this population is a generated sample, and none "
    "is a real application. It shows how the rule behaves and says nothing about any real applicant."
)
RETROSPECTIVE_NOTE = (
    "Retrospective re-scoring: stored cases are scored again under the rules in force "
    "now. It does not reconstruct the decisions made at the time."
)


def _type_label(baseline: PolicyConfig, key: str) -> str:
    found = baseline.type_config(key)
    return found.label if found is not None else key


def describe_change(raw: Mapping[str, Any], baseline: PolicyConfig) -> str:
    """Return one change in plain words."""
    try:
        change = parse_change(raw)
    except Exception as error:  # a stored change that no longer reads
        return f"A change that cannot be read ({error})"
    if isinstance(change, UnsupportedChange):
        return f"Not supported in this release: {_UNSUPPORTED_MESSAGES[change.code]}"
    kind = change.kind
    if kind in ("rule_threshold", "rule_retirement"):
        rule = next((r for r in baseline.rules if r.rule_id == change.rule_id), None)  # type: ignore[attr-defined]
        where = f"{rule.citation} (rule {rule.rule_id}, {_type_label(baseline, rule.permit_type_key or '')})" if rule else f"rule {change.rule_id}"  # type: ignore[attr-defined]
        if kind == "rule_retirement":
            return f"Retire {where} for every case"
        parts = []
        if change.limit_value is not None:  # type: ignore[attr-defined]
            old = rule.limit_value if rule else "?"
            unit = f" {rule.unit}" if rule and rule.unit else ""
            parts.append(f"limit {old}{unit} to {change.limit_value}{unit}")  # type: ignore[attr-defined]
        if change.operator is not None:  # type: ignore[attr-defined]
            parts.append(f"operator {rule.operator if rule else '?'} to {change.operator}")  # type: ignore[attr-defined]
        return f"Change {where}: {', '.join(parts)}"
    if kind == "requirement":
        verb = "Require" if change.action == "add" else "Stop requiring"  # type: ignore[attr-defined]
        return (
            f"{verb} the {change.item_kind} “{change.item}” for "  # type: ignore[attr-defined]
            f"{_type_label(baseline, change.permit_type_key)}"  # type: ignore[attr-defined]
        )
    if kind == "process_category":
        return (
            f"Move {_type_label(baseline, change.permit_type_key)} to the "  # type: ignore[attr-defined]
            f"“{change.process_category}” process category"  # type: ignore[attr-defined]
        )
    if kind == "discretionary":
        word = "discretionary" if change.discretionary else "by right (no discretionary hold)"  # type: ignore[attr-defined]
        return f"Make {_type_label(baseline, change.permit_type_key)} {word}"  # type: ignore[attr-defined]
    if kind == "service_target":
        found = baseline.type_config(change.permit_type_key)  # type: ignore[attr-defined]
        old = f"{found.service_target_days} days" if found else "?"
        return (
            f"Change the service target of {_type_label(baseline, change.permit_type_key)} "  # type: ignore[attr-defined]
            f"from {old} to {change.service_target_days} days"  # type: ignore[attr-defined]
        )
    if kind == "fee":
        parts = []
        if change.fixed_review_charge_cents is not None:  # type: ignore[attr-defined]
            parts.append(f"fixed charge {change.fixed_review_charge_cents / 100:.2f}")  # type: ignore[attr-defined]
        if change.valuation_multiplier is not None:  # type: ignore[attr-defined]
            parts.append(f"valuation multiplier {change.valuation_multiplier}")  # type: ignore[attr-defined]
        return f"Change fee schedule {change.fee_schedule_id}: {', '.join(parts)}"  # type: ignore[attr-defined]
    return "A change"


def check_changes(
    baseline: PolicyConfig, name: str, changes: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Check a revision against today's published configuration (no run)."""
    if not changes:
        return {"ok": False, "empty": True, "unsupported": [], "issues": [], "affected": []}
    try:
        scenario = scenario_from_changes(name, changes)
    except Exception as error:
        return {"ok": False, "empty": False, "unsupported": [], "issues": [str(error)], "affected": []}
    applied = apply_scenario(baseline, scenario)
    return {
        "ok": applied.config is not None,
        "empty": False,
        "unsupported": [
            {"index": u.change_index, "kind": u.requested_kind, "message": u.message}
            for u in applied.unsupported
        ],
        "issues": [f"Change {i.change_index + 1}: {i.message}" for i in applied.issues],
        "affected": [
            {
                "index": a.change_index,
                "types": [_type_label(baseline, key) for key in a.affected_type_keys],
                "citations": list(a.citations),
            }
            for a in applied.applied
        ],
    }


def editor_options(baseline: PolicyConfig) -> dict[str, Any]:
    """Return the choices the add-a-change forms offer, from the frozen baseline."""
    seen: set[str] = set()
    rules = []
    for rule in baseline.rules:
        if rule.rule_id in seen or rule.permit_type_key is None:
            continue
        seen.add(rule.rule_id)
        rules.append(
            {
                "rule_id": rule.rule_id,
                "citation": rule.citation,
                "title": rule.title,
                "type": _type_label(baseline, rule.permit_type_key),
                "operator": rule.operator,
                "limit": rule.limit_value,
                "unit": rule.unit or "",
            }
        )
    rules.sort(key=lambda item: item["rule_id"])
    schedules = sorted({s.fee_schedule_id for s in baseline.fee_schedules})
    return {
        "rules": rules,
        "types": [
            {
                "key": t.key,
                "label": t.label,
                "process_category": t.process_category or "",
                "discretionary": t.discretionary,
                "service_target_days": t.service_target_days,
            }
            for t in baseline.permit_types
        ],
        "fee_schedules": schedules,
        "process_categories": list(PROCESS_CATEGORIES),
        "kinds": [{"key": k, "label": v} for k, v in KIND_LABELS.items()],
        "unsupported_kinds": [{"key": k, "label": v} for k, v in UNSUPPORTED_OPTIONS],
        "operators": ["max", "min", "equals", "required"],
    }


def build_change_request(form: Mapping[str, str]) -> dict[str, Any]:
    """Turn the add-a-change form into a change request (the engine validates it)."""
    kind = str(form.get("kind", "")).strip()
    text = lambda name: str(form.get(name, "")).strip()  # noqa: E731
    if kind == "rule_threshold":
        request: dict[str, Any] = {"kind": kind, "rule_id": text("rule_id")}
        if text("limit_value"):
            request["limit_value"] = text("limit_value")
        if text("operator"):
            request["operator"] = text("operator")
        return request
    if kind == "rule_retirement":
        return {"kind": kind, "rule_id": text("rule_id")}
    if kind == "requirement":
        return {
            "kind": kind, "permit_type_key": text("permit_type_key"),
            "item_kind": text("item_kind"), "item": text("item"), "action": text("action"),
        }
    if kind == "process_category":
        return {"kind": kind, "permit_type_key": text("permit_type_key"),
                "process_category": text("process_category")}
    if kind == "discretionary":
        return {"kind": kind, "permit_type_key": text("permit_type_key"),
                "discretionary": text("discretionary") == "yes"}
    if kind == "service_target":
        days = text("service_target_days")
        return {"kind": kind, "permit_type_key": text("permit_type_key"),
                "service_target_days": int(days) if days.lstrip("-").isdigit() else days}
    if kind == "fee":
        request = {"kind": kind, "fee_schedule_id": text("fee_schedule_id")}
        cents = text("fixed_review_charge_cents")
        if cents:
            request["fixed_review_charge_cents"] = int(cents) if cents.lstrip("-").isdigit() else cents
        if text("valuation_multiplier"):
            request["valuation_multiplier"] = text("valuation_multiplier")
        return request
    # An unsupported kind is kept as asked so the engine can refuse it by name.
    return {"kind": kind}


# --------------------------------------------------------------- run display


def _delta(old: int, new: int) -> str:
    diff = new - old
    return f"+{diff}" if diff > 0 else str(diff)


def _count_rows(
    counts: Mapping[str, Mapping[str, int]], order: Sequence[str], labels: Mapping[str, str]
) -> list[dict[str, Any]]:
    base, scen = counts.get("baseline", {}), counts.get("scenario", {})
    keys = [k for k in order if k in base or k in scen] + sorted(
        k for k in set(base) | set(scen) if k not in order
    )
    return [
        {
            "key": key,
            "label": labels.get(key, key),
            "baseline": base.get(key, 0),
            "scenario": scen.get(key, 0),
            "delta": _delta(base.get(key, 0), scen.get(key, 0)),
        }
        for key in keys
    ]


def _transition_label(text: str | None, labels: Mapping[str, str]) -> str:
    if not text:
        return "no change"
    old, _, new = text.partition("->")
    return f"{labels.get(old, old)} → {labels.get(new, new)}"


def run_view(
    run: models.PolicyRun, *, scenario_deleted: bool = False
) -> dict[str, Any]:
    """Return the display data of one stored run."""
    result = run.result
    summary = result["summary"]
    population = result["population"]
    types = {t["key"]: t["label"] for t in run.baseline_config["permit_types"]}
    outcomes = result["outcome_counts"]
    recommendation_rows = _count_rows(outcomes["recommendation"], OUTCOME_ORDER, OUTCOME_LABELS)
    flips = [
        {
            "case_ref": item["case_ref"],
            "type": types.get(item["permit_type_key"], item["permit_type_key"]),
            "direction": item["direction"],
            "direction_label": DIRECTION_LABELS.get(item["direction"], item["direction"]),
            "recommendation": _transition_label(
                item.get("recommendation_transition"), OUTCOME_LABELS
            ),
            "rule": _transition_label(item.get("rule_transition"), RULE_LABELS),
            "route": _transition_label(item.get("route_transition"), ROUTE_LABELS),
        }
        for item in result["changed_cases"]
    ]
    directions = [
        {"key": key, "label": DIRECTION_LABELS.get(key, key), "count": count}
        for key, count in sorted(summary["by_direction"].items())
    ]
    signals = [
        {
            **signal,
            "type": types.get(signal["permit_type_key"], signal["permit_type_key"]),
            "what": (
                "The rule was retired."
                if signal["rule_retired"]
                else f"Limit {signal['baseline_limit']} to {signal['scenario_limit']}."
            ),
        }
        for signal in summary["safety_signals"]
    ]
    holds = summary["holds"]
    needs = summary["needs_information"]
    added_reasons = [
        {"reason": HOLD_REASON_LABELS.get(key, key or "another reason"), "count": count}
        for key, count in sorted(result.get("added_hold_reasons", {}).items())
    ]
    fees = summary.get("fees")
    changes = [describe_change(item["change"], _baseline_view(run)) for item in result["applied_changes"]]
    retire = bool(result.get("retires_a_rule"))
    return {
        "id": run.id,
        "scenario": {
            "id": run.scenario_id,
            "name": run.scenario_name,
            "revision": run.scenario_revision_number,
            "deleted": scenario_deleted,
        },
        "population": {
            "label": run.population_label,
            "kind": run.population_kind,
            "synthetic": bool(run.population_synthetic),
            "retrospective": bool(population.get("retrospective")) or run.population_kind != "synthetic_year",
            "size": run.population_size,
            "note": SYNTHETIC_NOTE if run.population_synthetic else RETROSPECTIVE_NOTE,
            "spec": run.population_spec,
        },
        "analysis_at": run.analysis_at.isoformat(),
        "engine_version": run.engine_version,
        "generator_version": run.generator_version or "not applicable",
        "hashes": {
            "content": run.content_hash,
            "baseline": run.baseline_hash,
            "proposed": run.proposed_hash,
            "population": run.population_hash,
            "result": run.result_hash,
        },
        "changes": changes,
        "outcomes": recommendation_rows,
        "rule_rows": _count_rows(outcomes["rule"], RULE_ORDER, RULE_LABELS),
        "route_rows": _count_rows(outcomes["route"], tuple(ROUTE_LABELS), ROUTE_LABELS),
        "flipped": {
            "total": result["changed_case_total"],
            "directions": directions,
            "cases": flips,
            "truncated": bool(result.get("changed_cases_truncated")),
            "listed": len(flips),
        },
        "safety": {"count": len(signals), "signals": signals},
        "holds": holds,
        "hold_reasons": added_reasons,
        "needs": needs,
        "targets": [
            {
                "type": types.get(t["permit_type_key"], t["permit_type_key"]),
                "before": t["before_days"],
                "after": t["after_days"],
                "cases": t["cases_in_population"],
            }
            for t in summary["service_targets"]
        ],
        "fees": None if not fees else _fee_view(fees, types),
        "retire_note": RETIRE_NOTE if retire else "",
        "retires_a_rule": retire,
        "created_at": run.created_at.isoformat(),
        "measure_notes": result.get("notes", {}),
    }


def _fee_view(fees: Mapping[str, Any], types: Mapping[str, str]) -> dict[str, Any]:
    return {
        "label": "Hypothetical assessed fees",
        "note": fees["note"],
        "baseline": fees["baseline_total"],
        "scenario": fees["scenario_total"],
        "delta": fees["delta"],
        "priced": fees["priced_count"],
        "changed_cases": fees["changed_case_count"],
        "schedules": fees["changed_schedule_ids"],
        "sharing_types": [types.get(k, k) for k in fees["types_sharing_changed_schedule"]],
        "by_type": [
            {
                "type": types.get(row["permit_type_key"], row["permit_type_key"]),
                "priced": row["priced"],
                "baseline": f"{row['baseline_cents'] / 100:.2f}",
                "scenario": f"{row['scenario_cents'] / 100:.2f}",
                "delta": f"{row['delta_cents'] / 100:+.2f}",
            }
            for row in fees["by_type"]
        ],
        "unpriceable": [
            {"case_ref": u["case_ref"], "type": types.get(u["permit_type_key"], u["permit_type_key"]),
             "reason": u["reason"]}
            for u in fees["unpriceable"]
        ],
    }


class _BaselineView:
    """The few lookups ``describe_change`` needs, read from a run's stored baseline."""

    def __init__(self, stored: Mapping[str, Any]) -> None:
        self._stored = stored

    def type_config(self, key: str) -> Any:
        for item in self._stored["permit_types"]:
            if item["key"] == key:
                return _Obj(label=item["label"], service_target_days=item["service_target_days"])
        return None

    @property
    def rules(self) -> list[Any]:
        return [
            _Obj(
                rule_id=r["rule_id"], citation=r["citation"], permit_type_key=r["permit_type_key"],
                limit_value=r["limit_value"], operator=r["operator"], unit=r.get("unit"),
            )
            for r in self._stored["rules"]
        ]


class _Obj:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


def _baseline_view(run: models.PolicyRun) -> Any:
    return _BaselineView(run.baseline_config)


__all__ = [
    "DIRECTION_LABELS",
    "KIND_LABELS",
    "OUTCOME_LABELS",
    "RETIRE_NOTE",
    "RETROSPECTIVE_NOTE",
    "SPEC_KINDS",
    "SYNTHETIC_NOTE",
    "build_change_request",
    "check_changes",
    "describe_change",
    "editor_options",
    "run_view",
]

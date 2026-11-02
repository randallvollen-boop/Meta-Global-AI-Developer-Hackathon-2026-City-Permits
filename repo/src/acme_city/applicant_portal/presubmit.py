"""Group a rules-layer review into the three results the applicant sees.

The groups and the button labels are fixed: "Must fix", "Should check",
"Looks good", "Check my application", "Submit anyway", "Why submit now".
A rule the application breaks is "Must fix".  A pass is "Looks good".
Everything else the rules layer returns is "Should check".

An address that matches no parcel never holds the application.  The City
matches the property after the case is filed, so an address the locator
cannot place is "Should check": the applicant is told it, and the case is
filed with the address exactly as it was typed and the property unmatched.

The sentences here are the rules layer's own words.  Muse may add a short
note beside them.  It never replaces the citation.
"""

from __future__ import annotations

from typing import Any

#: The three group labels, quoted exactly on the form.
LABEL_MUST_FIX = "Must fix"
LABEL_SHOULD_CHECK = "Should check"
LABEL_LOOKS_GOOD = "Looks good"

#: The flag a reviewer sees when the applicant submitted anyway.
FLAG = "Submitted with known issues"

#: Shown when Check my application cannot ask the assistant.
ASSISTANT_OFFLINE = "The assistant is offline."

#: Beside Submit application while a complete application has a Must fix.
SUBMIT_HELD_WHY = "Fix the items under Must fix, or use Submit anyway."

#: Beside Submit anyway until the applicant types a reason.
ANYWAY_WHY = "Write why you are submitting now."

#: An address the locator could not match to a parcel.  It never holds the
#: application: the City matches the property once the case is filed.
ADDRESS_UNMATCHED = "We could not match this address to a parcel. The City will match it."

#: A match that is not unique.  It does not hold Submit.
ADDRESS_AMBIGUOUS = "More than one address matches. A person at the City will confirm the property."

LABELS: dict[str, str] = {
    "must_fix": LABEL_MUST_FIX,
    "should_check": LABEL_SHOULD_CHECK,
    "looks_good": LABEL_LOOKS_GOOD,
}

#: The longest reason stored with an override.
MAX_REASON_LENGTH = 500


def _limit_text(limit_value: Any, unit: str | None) -> str:
    """Return a limit the way a person reads it, for example ``4 ft``."""
    raw = str(limit_value or "").strip()
    if not raw:
        return ""
    try:
        shown = f"{float(raw):g}"
    except ValueError:
        shown = raw
    unit_text = str(unit or "").strip()
    if unit_text:
        return f"{shown} {unit_text}"
    return shown


def how_to_fix(result: Any) -> str:
    """Return a short fix for a broken rule, or an empty string."""
    shown = _limit_text(getattr(result, "limit_value", None), getattr(result, "unit", None))
    operator = getattr(result, "operator", None)
    if operator == "max" and shown:
        return f"Use {shown} or less."
    if operator == "min" and shown:
        return f"Use {shown} or more."
    if operator == "equals" and shown:
        return f"Use {shown}."
    if operator == "required":
        return "Enter the required value."
    return ""


def _sentence(text: str) -> str:
    """Return the text as one sentence."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def sentence_for(result: Any, title: str) -> str:
    """Return the rules layer's sentence for one result.

    A pass never repeats the violation message.  The citation is the published
    section, not the internal rule id.
    """
    citation = str(getattr(result, "citation", "") or "").strip()
    status = str(getattr(result, "status", "") or "")
    name = title.strip() or "This rule"
    if status == "pass":
        if citation:
            return f"{name} meets {citation}."
        return f"{name} meets this rule."
    if status == "fail":
        parts: list[str] = []
        message = _sentence(str(getattr(result, "message", "") or ""))
        if message:
            parts.append(message)
        if citation:
            parts.append(f"See {citation}.")
        fix = how_to_fix(result)
        if fix:
            parts.append(fix)
        return " ".join(parts) or "This rule is not met."
    if citation:
        return f"{name} needs a check against {citation}."
    return f"{name} needs a check."


def address_item(located: dict[str, Any], address_text: str) -> dict[str, Any] | None:
    """Return the address row, or None when the address is not a review issue.

    A blank address is completeness, not this check.  An address service that
    is down is not a review issue at all: the applicant can still submit.  An
    ambiguous match that still names a parcel is "Should check", and so is an
    address that matches no parcel: the City matches the property later, so
    the address never holds the application.
    """
    if not str(address_text or "").strip():
        return None
    if not located.get("locator_available", True):
        return None
    if located.get("parcel_matched"):
        if not located.get("ambiguous"):
            return None
        return {
            "rule_id": "",
            "citation": "",
            "status": "review",
            "sentence": ADDRESS_AMBIGUOUS,
            "feedback": None,
            "kind": "address",
        }
    if not str(located.get("message") or "").strip():
        return None
    return {
        "rule_id": "",
        "citation": "",
        "status": "review",
        "sentence": ADDRESS_UNMATCHED,
        "feedback": None,
        "kind": "address",
    }


def group_review(
    results: list[Any],
    rule_set: Any,
    located: dict[str, Any],
    *,
    address_text: str,
) -> dict[str, Any]:
    """Return the three groups for one rules-layer run."""
    titles = {
        rule.rule_id: rule.title
        for rule in getattr(rule_set, "rules", ()) or ()
    }
    must_fix: list[dict[str, Any]] = []
    should_check: list[dict[str, Any]] = []
    looks_good: list[dict[str, Any]] = []
    for result in results:
        title = str(titles.get(result.rule_id) or "This rule")
        item = {
            "rule_id": result.rule_id,
            "citation": str(result.citation or ""),
            "status": result.status,
            "sentence": sentence_for(result, title),
            "feedback": None,
            "kind": "rule",
        }
        if result.status == "fail":
            must_fix.append(item)
        elif result.status == "pass":
            looks_good.append(item)
        else:
            should_check.append(item)
    address = address_item(located, address_text)
    if address is not None:
        if address["status"] == "fail":
            must_fix.append(address)
        else:
            should_check.append(address)
    return {
        "must_fix": must_fix,
        "should_check": should_check,
        "looks_good": looks_good,
        "labels": dict(LABELS),
        "assistant": "rules",
        "assistant_note": "",
        "validation_issues": [],
        "held": False,
    }


def override_record(review: dict[str, Any], reason: str, *, recorded_at: str) -> dict[str, Any]:
    """Return the override stored on the case."""
    text = " ".join(reason.split())[:MAX_REASON_LENGTH]
    issues = [
        {
            "sentence": str(item.get("sentence") or ""),
            "citation": str(item.get("citation") or ""),
            "kind": str(item.get("kind") or "rule"),
        }
        for item in review.get("must_fix") or []
    ]
    return {
        "reason": text,
        "issues": issues,
        "recorded_at": recorded_at,
        "flag": FLAG,
        "detail": f"{FLAG}: {text}",
    }


__all__ = [
    "ADDRESS_AMBIGUOUS",
    "ADDRESS_UNMATCHED",
    "ANYWAY_WHY",
    "ASSISTANT_OFFLINE",
    "FLAG",
    "LABEL_LOOKS_GOOD",
    "LABEL_MUST_FIX",
    "LABEL_SHOULD_CHECK",
    "LABELS",
    "MAX_REASON_LENGTH",
    "SUBMIT_HELD_WHY",
    "address_item",
    "group_review",
    "how_to_fix",
    "override_record",
    "sentence_for",
]

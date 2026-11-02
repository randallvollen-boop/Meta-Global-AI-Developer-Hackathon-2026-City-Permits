"""The plain reason of a recommendation.

One helper turns what the rule evaluator found into the words a person reads:
the outcome first, then the reason, with the rule's own message, title and
citation and the submitted value against the limit.  The agent writes the
text into the recommendation, and every screen that shows a recommendation
reads the same lines, so a person is never left with a bare rule id.

The helper decides nothing.  The outcome comes from the disposition; the
helper only words it.  The rule text is data: it is quoted and never edited.
"""
# REQUIRES: AGT-01, RUL-01
# Wording only; the decision logic stays in kernel.adjudication.

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from acme_city.triage.service import unit_for_field

#: The first words of the recommendation of each outcome.
_APPROVE = "Recommend approve"
_APPROVE_WITH_CONDITIONS = "Recommend approve with conditions"
_DENY = "Recommend deny"

_SUBJECT = re.compile(r"^(?P<subject>.+?) is (?:above|below|not|at) ", re.IGNORECASE)


@dataclass(frozen=True)
class PlainReason:
    """The lines of one plain reason.

    ``lines[0]`` is the short form: the outcome and the first reason.  Every
    other line is a further reason, what would change the outcome, or what
    could not be checked.
    """

    lines: tuple[str, ...]

    @property
    def short(self) -> str:
        """Return the first line, the short form of the reason."""
        return self.lines[0] if self.lines else ""

    @property
    def text(self) -> str:
        """Return every line, one per line."""
        return "\n".join(self.lines)

    @property
    def rest(self) -> tuple[str, ...]:
        """Return the lines after the short form."""
        return self.lines[1:]


def plain_reason(
    *,
    outcome: str,
    hold_reason: str | None,
    results: Iterable[Mapping[str, Any]],
    titles: Mapping[str, str] | None = None,
    kernel_reason: str = "",
    parcel_confirmed: bool = True,
    precedent_outcome: str | None = None,
) -> PlainReason:
    """Return the plain reason of one recommendation.

    ``results`` are the rows of the evaluator, or the evidence the agent
    recorded from them.  ``titles`` gives the title of a rule by its id for
    rows that do not carry one.  ``kernel_reason`` is the sentence of the
    disposition, quoted for the holds that do not rest on a rule.
    """
    rows = [dict(row) for row in results]
    names = dict(titles or {})
    if precedent_outcome is not None:
        # The disposition appends the earlier case to its sentence; the helper
        # puts it on a line of its own.
        kernel_reason = kernel_reason.removesuffix(
            f" An earlier decided case on the same parcel was {precedent_outcome}."
        )
    lines: list[str] = []

    failing = [row for row in rows if str(row.get("status")) == "fail"]
    judging = [row for row in rows if str(row.get("status")) == "review"]
    conditional = [row for row in rows if str(row.get("status")) == "condition"]
    passing = [row for row in rows if str(row.get("status")) == "pass"]

    if outcome == "deny" and failing:
        lines.extend(_deny_lines(failing, names))
    elif outcome == "hold" and hold_reason == "parcel_unconfirmed":
        lines.append(kernel_reason)
    elif outcome == "hold" and hold_reason == "rule_review" and judging:
        lines.extend(_judgement_lines(judging, names))
    elif outcome == "hold":
        lines.append(kernel_reason or "The agent holds the case for a person.")
    elif outcome == "approve_with_conditions":
        lines.extend(_condition_lines(conditional, passing, names))
    elif outcome == "approve":
        lines.append(_approve_line(passing, names))
    else:
        lines.append(kernel_reason or f"Recommendation: {outcome}.")

    unchecked = [
        row
        for row in rows
        if str(row.get("reason") or "") == "parcel_not_confirmed"
    ]
    if unchecked:
        lines.append(_not_checked_line(unchecked, names))
    if precedent_outcome is not None:
        lines.append(
            f"An earlier decided case on the same parcel was {precedent_outcome}."
        )
    return PlainReason(lines=tuple(lines))


def rule_label(row: Mapping[str, Any], titles: Mapping[str, str] | None = None) -> str:
    """Return the words that name a rule: its title, never its bare id.

    A rule without a recorded title falls back to its citation, and to a
    neutral phrase when it has none, so a screen never shows ``DF-1`` alone.
    """
    rule_id = str(row.get("rule_id") or "")
    title = str(row.get("title") or (titles or {}).get(rule_id) or "").strip()
    if title:
        return title
    citation = str(row.get("citation") or "").strip()
    return citation or "a rule of the City"


def evidence_line(
    row: Mapping[str, Any], titles: Mapping[str, str] | None = None
) -> str:
    """Return one line of evidence: the rule by title, the status, the values."""
    unit = _unit(row)
    status = str(row.get("status") or "").replace("_", " ")
    status = {"fail": "does not pass", "pass": "passes", "review": "needs a person"}.get(
        status, status
    )
    parts = [f"{rule_label(row, titles)}: {status}"]
    observed = _with_unit(row.get("observed_value"), unit)
    limit = _with_unit(row.get("limit_value"), unit)
    if observed:
        parts.append(f"submitted {observed}")
    if limit:
        parts.append(f"limit {limit}")
    citation = str(row.get("citation") or "").strip()
    if citation:
        parts.append(citation)
    return ", ".join(parts)


def condition_line(
    condition: str,
    rows: Iterable[Mapping[str, Any]],
    titles: Mapping[str, str] | None = None,
) -> str:
    """Return a condition of approval with the title of its rule.

    The condition of the record reads ``DF-4: Footing inspection ...``.  The
    record stays as it is; the screen shows the same condition with the rule
    named by its title.
    """
    head, separator, note = str(condition).partition(":")
    if not separator:
        return str(condition)
    rule_id = head.strip()
    for row in rows:
        if str(row.get("rule_id") or "") == rule_id:
            return _sentence(f"{_plain(note)} ({_cite(row, titles)})")
    title = (titles or {}).get(rule_id)
    if title:
        return _sentence(f"{_plain(note)} ({title})")
    return _sentence(_plain(note) or str(condition))


def describe_recommendation(
    *,
    rationale: str,
    evidence_refs: Iterable[Mapping[str, Any]],
    conditions: Iterable[str],
    titles: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return what a screen shows of one recorded recommendation.

    ``short`` is the first line, for a table cell.  ``rest`` holds the other
    lines of the reason, ``conditions`` the conditions with their rules named
    by title, and ``evidence`` one line per rule checked.  Every screen reads
    this one view, so the wording is the same everywhere.
    """
    rows = [dict(row) for row in evidence_refs]
    lines = [line.strip() for line in str(rationale or "").splitlines() if line.strip()]
    return {
        "lines": lines,
        "short": lines[0] if lines else "",
        "rest": lines[1:],
        "conditions": [condition_line(item, rows, titles) for item in conditions],
        "evidence": [evidence_line(row, titles) for row in rows],
    }


def describe_row(session: Any, row: Any) -> dict[str, Any]:
    """Return the plain view of one stored recommendation row.

    The titles of the rules are read from the catalogue for the rows an
    earlier run recorded without one.
    """
    from sqlalchemy import select

    from acme_city.persistence.models import finance

    evidence = list(row.evidence_refs or [])
    missing = {
        str(item.get("rule_id"))
        for item in evidence
        if item.get("rule_id") and not item.get("title")
    }
    titles: dict[str, str] = {}
    if missing:
        for version in session.execute(
            select(finance.RuleVersion)
            .where(finance.RuleVersion.rule_id.in_(sorted(missing)))
            .order_by(finance.RuleVersion.effective_from)
        ).scalars():
            titles[version.rule_id] = version.title
    return describe_recommendation(
        rationale=row.rationale or "",
        evidence_refs=evidence,
        conditions=list(row.conditions or []),
        titles=titles,
    )


# ------------------------------------------------------------------- lines


def _not_checked_line(
    unchecked: list[dict[str, Any]], titles: Mapping[str, str]
) -> str:
    """Name every parcel-dependent rule the agent did not run."""
    labels = "; ".join(rule_label(row, titles) for row in unchecked)
    return f"Not checked: {labels}, because the parcel is not confirmed."


def _deny_lines(failing: list[dict[str, Any]], titles: Mapping[str, str]) -> list[str]:
    """Return the lines of a denial: each failing rule on its own line."""
    if len(failing) == 1:
        row = failing[0]
        lines = [f"{_DENY}: {_failure(row, titles)}"]
        change = _change(row)
        if change:
            lines.append(change)
        return lines
    lines = [f"{_DENY}: {len(failing)} rules are not met."]
    for row in failing:
        line = _failure(row, titles)
        change = _change(row)
        lines.append(_capital(f"{line} {change}".strip()))
    return lines


def _failure(row: Mapping[str, Any], titles: Mapping[str, str]) -> str:
    """Return the sentence that says why one rule fails."""
    unit = _unit(row)
    operator = str(row.get("operator") or _operator_of(row))
    observed = _with_unit(row.get("observed_value"), unit)
    limit = _with_unit(row.get("limit_value"), unit)
    cite = _cite(row, titles)
    if operator == "required":
        message = _plain(str(row.get("message") or "A required value is missing."))
        return f"{message}. No value was submitted ({cite})."
    subject = _subject(row, titles)
    if operator == "max" and observed and limit:
        return f"the {subject} is {observed}; the limit is {limit} ({cite})."
    if operator == "min" and observed and limit:
        return f"the {subject} is {observed}; the minimum is {limit} ({cite})."
    if operator == "equals" and observed and limit:
        return f"the {subject} is {observed}; the rule requires {limit} ({cite})."
    message = _plain(str(row.get("message") or "The rule is not met."))
    return f"{message} ({cite})."


def _change(row: Mapping[str, Any]) -> str:
    """Return what would change the outcome, when the rule data says it."""
    operator = str(row.get("operator") or _operator_of(row))
    limit = _with_unit(row.get("limit_value"), _unit(row))
    if not limit:
        return ""
    noun = _noun(row)
    if operator == "max":
        return f"A {noun} of {limit} or lower, or a variance, would meet the rule."
    if operator == "min":
        return f"A {noun} of {limit} or more, or a variance, would meet the rule."
    if operator == "equals":
        return f"A {noun} of {limit}, or a variance, would meet the rule."
    return ""


def _judgement_lines(
    judging: list[dict[str, Any]], titles: Mapping[str, str]
) -> list[str]:
    """Return the lines of a hold that needs a person's judgement."""
    lines = ["Held for a person: a rule needs a person's judgement or a missing input."]
    for row in judging:
        message = _plain(str(row.get("message") or ""))
        lines.append(_capital(f"{message} ({_cite(row, titles)}).".strip()))
    return lines


def _condition_lines(
    conditional: list[dict[str, Any]],
    passing: list[dict[str, Any]],
    titles: Mapping[str, str],
) -> list[str]:
    """Return the lines of an approval with conditions."""
    count = len(conditional)
    lines = [
        f"{_APPROVE_WITH_CONDITIONS}: no rule fails, and "
        f"{count} condition{'s' if count != 1 else ''} of approval "
        f"{'apply' if count != 1 else 'applies'}."
    ]
    for row in conditional:
        note = _plain(str(row.get("condition_note") or row.get("message") or ""))
        lines.append(_sentence(f"Condition: {note} ({_cite(row, titles)})"))
    if passing:
        lines.append(_passed_line(passing, titles))
    return lines


def _approve_line(passing: list[dict[str, Any]], titles: Mapping[str, str]) -> str:
    """Return the one line of an approval: which rules passed."""
    if not passing:
        return f"{_APPROVE}: no rule applies to the submitted facts."
    count = len(passing)
    head = (
        f"{_APPROVE}: the one rule that applies passes"
        if count == 1
        else f"{_APPROVE}: all {count} rules that apply pass"
    )
    names = "; ".join(_cite(row, titles) for row in passing)
    return f"{head}: {names}."


def _passed_line(passing: list[dict[str, Any]], titles: Mapping[str, str]) -> str:
    """Return the line that names the rules that passed."""
    count = len(passing)
    head = "The one rule that passes" if count == 1 else f"The {count} rules that pass"
    return f"{head}: " + "; ".join(_cite(row, titles) for row in passing) + "."


# ----------------------------------------------------------------- helpers


def _cite(row: Mapping[str, Any], titles: Mapping[str, str] | None) -> str:
    """Return the citation and the title of a rule, in the words a person reads."""
    citation = str(row.get("citation") or "").strip()
    title = rule_label(row, titles)
    if citation and citation != title:
        return f"{citation}, {title}"
    return title


def _subject(row: Mapping[str, Any], titles: Mapping[str, str]) -> str:
    """Return what the rule is about, from the rule's own message."""
    message = str(row.get("message") or "").strip()
    match = _SUBJECT.match(message)
    if match:
        return match.group("subject").strip().lower()
    return rule_label(row, titles).lower()


def _noun(row: Mapping[str, Any]) -> str:
    """Return the thing the rule measures, for example ``fence``."""
    message = str(row.get("message") or "").strip()
    match = _SUBJECT.match(message)
    if match:
        return match.group("subject").strip().split()[-1].lower()
    return "value"


def _operator_of(row: Mapping[str, Any]) -> str:
    """Read the operator of a recorded row that does not carry one."""
    message = str(row.get("message") or "").lower()
    if " above " in message:
        return "max"
    if " below " in message:
        return "min"
    return ""


def _unit(row: Mapping[str, Any]) -> str | None:
    """Return the unit of the value of one row."""
    return str(row.get("unit") or "") or unit_for_field(row.get("field_path"))


def _with_unit(value: Any, unit: str | None) -> str:
    """Return a value with its unit, so a number is never bare."""
    if value is None or str(value).strip() == "":
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    if unit and not text.lower().endswith(unit.strip().lower()):
        return f"{text} {unit.strip()}"
    return text


def _plain(message: str) -> str:
    """Return a rule message as one sentence without its end mark."""
    return message.strip().rstrip(".")


def _sentence(text: str) -> str:
    """Return the text as a sentence that starts with a capital and ends with a stop."""
    text = text.strip()
    if not text:
        return text
    text = _capital(text)
    return text if text.endswith(".") else text + "."


def _capital(text: str) -> str:
    """Return the text with a capital first letter."""
    return text[:1].upper() + text[1:] if text else text


__all__ = [
    "PlainReason",
    "condition_line",
    "describe_recommendation",
    "describe_row",
    "evidence_line",
    "plain_reason",
    "rule_label",
]

"""The deterministic summary of a stored run.

A run is a stored snapshot, so the summary of a run can be worked out from
the figures the run already holds.  Nothing is re-scored and no model is
asked: the same run always gives the same summary, and the summary never
states a figure the permit engine did not count.

The summary is a plain function of the display data of a run, so it can be
tested without a database and it cannot drift away from the run it
describes.
"""
# REQUIRES: UX-01, PER-02
# The summary states only what the stored run measured, with its label.

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: What each direction of a change is called in the summary.  A more
#: permissive result is not a better one, so the wording says what moved and
#: stops there.
DIRECTION_WORDS: dict[str, tuple[str, str]] = {
    "relaxed": ("gets", "a more permissive result"),
    "tightened": ("gets", "a less permissive result"),
    "changed_otherwise": ("changes", "in another way"),
}

#: The order the directions are mentioned in, so two runs of the same shape
#: read the same way.
DIRECTION_ORDER: tuple[str, ...] = ("relaxed", "tightened", "changed_otherwise")


def _cases(count: int) -> str:
    """Return "case" or "cases" for a count."""
    return "case" if count == 1 else "cases"


def _agree(count: int, one: str, many: str) -> str:
    """Return the word that goes with a count."""
    return one if count == 1 else many


def _join(parts: list[str]) -> str:
    """Join parts in English: "a, b and c"."""
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _direction_sentence(view: Mapping[str, Any], changed: int) -> str:
    """Return the sentence that says which way the changed cases moved.

    The counts of the directions add up to the number of changed cases, so
    the sentence is the whole breakdown of the headline.
    """
    if not changed:
        return ""
    counts = {row["key"]: int(row["count"]) for row in view["flipped"]["directions"]}
    parts = []
    for key in DIRECTION_ORDER:
        count = counts.get(key, 0)
        if not count:
            continue
        verb, tail = DIRECTION_WORDS[key]
        parts.append(f"{count} {_cases(count)} {_agree(count, verb, verb[:-1])} {tail}")
    if not parts:
        return ""
    text = _join(parts)
    return text[0].upper() + text[1:] + "."


def _holds_sentence(view: Mapping[str, Any]) -> str:
    """Return the sentence about the recommendation holds that moved."""
    holds = view["holds"]
    cleared = int(holds.get("cleared", 0) or 0)
    added = int(holds.get("added", 0) or 0)
    parts = []
    if cleared:
        parts.append(
            f"{cleared} {_cases(cleared)} {_agree(cleared, 'is', 'are')} "
            "no longer held for a person"
        )
    if added:
        parts.append(
            f"{added} {_cases(added)} {_agree(added, 'is', 'are')} newly held for a person"
        )
    if not parts:
        return ""
    return "Recommendation holds: " + _join(parts) + "."


def _needs_sentence(view: Mapping[str, Any]) -> str:
    """Return the sentence about the cases that need information."""
    needs = view["needs"]
    cleared = int(needs.get("cleared", 0) or 0)
    added = int(needs.get("added", 0) or 0)
    parts = []
    if cleared:
        parts.append(
            f"{cleared} {_cases(cleared)} no longer "
            f"{_agree(cleared, 'needs', 'need')} information at intake"
        )
    if added:
        parts.append(
            f"{added} {_cases(added)} {_agree(added, 'needs', 'need')} information "
            "that was not needed before"
        )
    if not parts:
        return ""
    return "Information needed at intake: " + _join(parts) + "."


def _fee_sentence(view: Mapping[str, Any]) -> str:
    """Return the sentence about the hypothetical assessed fees."""
    fees = view["fees"]
    if not fees:
        return ""
    baseline = str(fees["baseline"])
    scenario = str(fees["scenario"])
    if baseline == scenario:
        return "The hypothetical assessed fees do not change."
    return f"The hypothetical assessed fees change from {baseline} to {scenario} USD."


def _retirement_sentence(view: Mapping[str, Any]) -> str:
    """Return the sentence about a retired rule and what it does not do."""
    if not view.get("retires_a_rule"):
        return ""
    return (
        "This what-if retires a rule for every case. "
        "Retiring a rule does not approve the cases it used to stop."
    )


def _safeguard_sentence(view: Mapping[str, Any]) -> str:
    """Return the sentence about the holds that a safeguard still blocks."""
    count = int(view["holds"].get("cleared_but_still_blocked_by_safeguards", 0) or 0)
    if not count:
        return ""
    return (
        f"{count} {_cases(count)} {_agree(count, 'is', 'are')} still blocked by a "
        "safeguard or a missing input, so a person still has to act."
    )


def run_summary(view: Mapping[str, Any]) -> dict[str, Any]:
    """Return the deterministic summary of one stored run.

    The summary is a plain function of the display data of the run.  It
    re-scores nothing and calls no model, so the same run always gives the
    same summary.  The safety signals are not part of it: they have their own
    always visible block, because a case that stops failing a rule is a fact
    a person has to look at rather than a line of the summary.
    """
    population = int(view["population"]["size"])
    changed = int(view["flipped"]["total"])
    sentences = [
        sentence
        for sentence in (
            _direction_sentence(view, changed),
            _holds_sentence(view),
            _needs_sentence(view),
            _fee_sentence(view),
            _retirement_sentence(view),
            _safeguard_sentence(view),
        )
        if sentence
    ]
    return {
        "changed": changed,
        "population": population,
        "headline": f"{changed} of {population} cases have a different result.",
        "sentences": tuple(sentences),
    }


__all__ = ["DIRECTION_ORDER", "DIRECTION_WORDS", "run_summary"]

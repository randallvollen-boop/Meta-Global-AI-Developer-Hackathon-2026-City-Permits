"""The presentation of the operations screens.

The figures, their definitions and their arithmetic stay in the services that
read the stored rows.  This module holds only the words and the grouping the
screens show: the plain label of every dashboard figure, the two groups the
figures sit in and the sentence that names the scope of the numbers.

Nothing here reads or writes the database, and nothing here decides a figure:
a label says what a number means, it never changes it.
"""
# REQUIRES: UX-01

from __future__ import annotations

from typing import Any

#: The two groups of the operations dashboard, in the order they are shown.
FIGURE_GROUPS: tuple[tuple[str, str], ...] = (
    ("workload", "Current workload"),
    ("processing", "Recorded processing"),
)

#: The plain label of every dashboard figure, by its key.
FIGURE_LABELS: dict[str, str] = {
    "active": "Active cases",
    "average_age": "Average age",
    "needs_a_person": "Items needing attention",
    "early_incomplete": "Incomplete at first intake",
    "agent_processed": "Applications processed by intake",
    "decisions": "Decisions recorded",
}

#: The group every figure belongs to.
FIGURE_GROUP_OF: dict[str, str] = {
    "active": "workload",
    "average_age": "workload",
    "needs_a_person": "workload",
    "early_incomplete": "processing",
    "agent_processed": "processing",
    "decisions": "processing",
}

#: The word the screens use for the moment the figures were read at.
AS_OF_LABEL = "As of"


def label_for(key: str) -> str:
    """Return the plain label of one figure."""
    return FIGURE_LABELS.get(key, key)


def group_of(key: str) -> str:
    """Return the group one figure belongs to."""
    return FIGURE_GROUP_OF.get(key, "workload")


def figure_groups(figures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the figures in their two groups, in the order they are shown.

    A figure keeps its own value and its own definition; only the label and
    the group are added here.  A figure whose key is unknown is kept in the
    first group, so nothing is dropped from the screen.
    """
    groups: list[dict[str, Any]] = [
        {"key": key, "label": label, "figures": []} for key, label in FIGURE_GROUPS
    ]
    by_key = {group["key"]: group for group in groups}
    for figure in figures:
        target = by_key[group_of(str(figure.get("key", "")))]
        target["figures"].append(
            {**figure, "label": label_for(str(figure.get("key", "")))}
        )
    return groups


def scope_statement(include_history: bool) -> str:
    """Return the sentence that names the scope of the figures."""
    state = "included" if include_history else "excluded"
    return f"Fictional demo records. Sample history {state}."


__all__ = [
    "AS_OF_LABEL",
    "FIGURE_GROUPS",
    "FIGURE_GROUP_OF",
    "FIGURE_LABELS",
    "figure_groups",
    "group_of",
    "label_for",
    "scope_statement",
]

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

#: The plain labels of the three results of one check.
CHECK_STATUS_LABELS: dict[str, str] = {
    "pass": "Passed",
    "fail": "Failed",
    "not_applicable": "Not applicable",
}

#: The order the results of a run are shown in: a failure is read first.
CHECK_STATUS_ORDER: tuple[str, ...] = ("fail", "pass", "not_applicable")


def check_status_label(status: str) -> str:
    """Return the plain label of one result of a check."""
    return CHECK_STATUS_LABELS.get(status, status.replace("_", " "))


def checks_presentation(
    recorded: dict[str, Any] | None, *, selected: bool = False
) -> dict[str, Any]:
    """Return the presentation of the recorded run of the checks.

    The counts, the eight results and their reasons are the ones the service
    recorded; this function never changes them.  It orders the results so that
    a failure is read first, and it names the state of the run: the latest
    one or the run a person selected.
    """
    if not recorded:
        return {
            "has_run": False,
            "is_latest": False,
            "run_id": "",
            "ran_at": "",
            "title": "",
            "headline": "",
            "counts": {"pass": 0, "fail": 0, "not_applicable": 0},
            "results": [],
            "details": [],
        }
    counts = dict(recorded.get("counts") or {})
    passed = int(counts.get("pass") or 0)
    failed = int(counts.get("fail") or 0)
    not_applicable = int(counts.get("not_applicable") or 0)
    results = list(recorded.get("results") or [])
    order = {status: index for index, status in enumerate(CHECK_STATUS_ORDER)}
    # The sort is stable, so the results that are not failures keep the order
    # the service recorded them in.
    ordered = sorted(
        results, key=lambda item: order.get(str(item.get("status", "")), len(order))
    )
    ran_at = str(recorded.get("ran_at") or "")
    headline = ""
    if failed == 0 and passed == 0 and not_applicable:
        headline = "No checks were applicable."
    return {
        "has_run": True,
        "is_latest": not selected,
        "run_id": str(recorded.get("run_id") or ""),
        "ran_at": ran_at,
        "title": (
            f"Selected run at {ran_at}" if selected else f"Recorded result at {ran_at}"
        ),
        "headline": headline,
        "counts": {"pass": passed, "fail": failed, "not_applicable": not_applicable},
        "results": [
            {**item, "status_label": check_status_label(str(item.get("status", "")))}
            for item in ordered
        ],
        "details": [
            {
                "label": "Run identifier",
                "value": str(recorded.get("run_id") or ""),
                "testid": "checks-run-id",
            },
            {"label": "Run by", "value": str(recorded.get("ran_by") or "not recorded")},
            {"label": "Run at", "value": ran_at},
        ],
    }


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
    "CHECK_STATUS_LABELS",
    "CHECK_STATUS_ORDER",
    "FIGURE_GROUPS",
    "FIGURE_GROUP_OF",
    "FIGURE_LABELS",
    "check_status_label",
    "checks_presentation",
    "figure_groups",
    "group_of",
    "label_for",
    "scope_statement",
]

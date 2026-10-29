"""The unified work queue of the Data Steward.

The queue shows one row per task.  Each row answers five questions: what
needs attention, which record is involved, what is affected, what the next
action is and who is responsible.  The projection is deterministic, and it
keeps the legacy filter keys of the Data issues queue, so the old addresses
and the old selectors keep working.

The module holds no database work.  It turns the tasks the steward views
already collected into the rows, the counts and the order of the queue.
"""
# REQUIRES: UX-01, UX-02, MDM-02

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from acme_city.core.clock import app_now as utc_now

#: The four views of the queue, in the order they are listed.  The keys are
#: the legacy filter keys of the Data issues queue.
QUEUE_FILTERS: tuple[tuple[str, str], ...] = (
    ("needs_review", "Needs review"),
    ("assigned_to_me", "Assigned to me"),
    ("awaiting_source", "Awaiting source"),
    ("resolved", "Resolved"),
)

#: The label of each state of a task.
STATUS_LABELS = {
    "needs_review": "Needs review",
    "awaiting_source": "Awaiting source",
    "resolved": "Resolved",
}

#: The task each kind of work asks for.
TASK_TITLES: dict[str, str] = {
    "link": "Check the record match",
    "linked": "Check the linked record",
    "parcel": "Check the property",
    "case": "Check the correction",
    "issue": "Check the data issue",
}

#: The identity task of a match, by the type of the party it is about.
IDENTITY_TASKS: dict[str, str] = {
    "organization": "Check the business identity",
    "person": "Check the person identity",
}

#: The next action of each kind of work.
ACTION_LABELS: dict[str, str] = {
    "link": "Review match",
    "linked": "View the linked record",
    "parcel": "Review property",
    "case": "Review case",
    "issue": "Review issue",
}

#: The priority that marks recorded blocking work.
BLOCKING_PRIORITY = "Blocking"


@dataclass
class Issue:
    """One task of the Data Steward's queue."""

    kind: str
    item_id: str
    title: str
    record: str
    record_ref: str
    applications: list[dict[str, str]]
    source: str
    status: str
    assignee_id: str | None = None
    created_at: datetime | None = None
    priority: str = ""
    legacy_testid: str = ""
    link_status: str = ""
    synthetic: bool = False
    sort_key: tuple[Any, ...] = ()
    #: The type of the record the task is about: a party type, a parcel, a
    #: change kind or a governance issue type.
    record_type: str = ""
    #: The reference of the source record, kept as secondary text.
    source_reference: str = ""

    @property
    def href(self) -> str:
        return f"/steward/issues/{self.kind}/{self.item_id}"

    @property
    def blocking(self) -> bool:
        """Whether the work is recorded as blocking."""
        return self.priority == BLOCKING_PRIORITY


@dataclass(frozen=True)
class WorkRow:
    """One row of the queue, ready for the template."""

    key: str
    kind: str
    task: str
    title: str
    record: str
    record_ref: str
    source: str
    source_reference: str
    status: str
    status_key: str
    priority: str
    assignee: str
    assignee_id: str | None
    age: str
    when: str
    applications: tuple[dict[str, str], ...]
    action_label: str
    href: str
    legacy_testid: str
    link_status: str

    @property
    def affected_count(self) -> int:
        """The number of applications the task affects."""
        return len(self.applications)

    @property
    def blocking(self) -> bool:
        """Whether the work is recorded as blocking."""
        return self.priority == BLOCKING_PRIORITY

    def as_dict(self) -> dict[str, Any]:
        """Return the row as the template reads it."""
        return {
            "id": self.key,
            "kind": self.kind,
            "task": self.task,
            "title": self.title,
            "record": self.record,
            "record_ref": self.record_ref,
            "source": self.source,
            "source_reference": self.source_reference,
            "status": self.status,
            "status_key": self.status_key,
            "priority": self.priority,
            "assignee": self.assignee,
            "assignee_id": self.assignee_id,
            "age": self.age,
            "when": self.when,
            "applications": list(self.applications),
            "affected_count": self.affected_count,
            "action_label": self.action_label,
            "href": self.href,
            "legacy_testid": self.legacy_testid,
            "link_status": self.link_status,
        }


def task_title(issue: Issue) -> str:
    """Return the task the row asks the steward to do."""
    if issue.kind in ("link", "linked"):
        return IDENTITY_TASKS.get(issue.record_type, TASK_TITLES["link"])
    return TASK_TITLES.get(issue.kind, TASK_TITLES["issue"])


def action_label(issue: Issue) -> str:
    """Return the next action of the row."""
    return ACTION_LABELS.get(issue.kind, ACTION_LABELS["issue"])


def age_label(since: datetime | None) -> str:
    """Return how long a task has been waiting, in days."""
    if since is None:
        return ""
    days = max((utc_now() - since).days, 0)
    if days == 0:
        return "Today"
    return f"{days} day" + ("" if days == 1 else "s")


def _stamp(value: datetime | None) -> float:
    """Return the seconds of a timestamp, treating a naive value as UTC."""
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _priority_rank(issue: Issue) -> int:
    """Return the rank of the priority of a task: blocking work comes first."""
    if issue.blocking:
        return 0
    return 1 if issue.priority else 2


def order_tasks(tasks: list[Issue], *, newest_first: bool = False) -> list[Issue]:
    """Return the tasks in the order of the queue.

    Recorded blocking work comes first, then an explicit priority, then the
    oldest waiting work, then a stable key, so two requests never show the
    same work in a different order.
    """
    def key(issue: Issue) -> tuple[Any, ...]:
        known = issue.created_at is not None
        stamp = _stamp(issue.created_at) if known else 0.0
        if newest_first:
            stamp = -stamp
        return (
            0 if issue.blocking else 1,
            _priority_rank(issue),
            0 if known else 1,
            stamp,
            issue.kind,
            issue.item_id,
        )

    return sorted(tasks, key=key)


def matches(issue: Issue, view_key: str, actor_id: str) -> bool:
    """Whether one task belongs to a view of the queue."""
    if view_key == "assigned_to_me":
        return issue.assignee_id == actor_id and issue.status != "resolved"
    return issue.status == view_key


def work_row(issue: Issue, *, assignee: str = "") -> WorkRow:
    """Return the row of one task."""
    return WorkRow(
        key=issue.item_id,
        kind=issue.kind,
        task=task_title(issue),
        title=issue.title,
        record=issue.record,
        record_ref=issue.record_ref,
        source=issue.source,
        source_reference=issue.source_reference,
        status=STATUS_LABELS.get(issue.status, issue.status),
        status_key=issue.status,
        priority=issue.priority,
        assignee=assignee,
        assignee_id=issue.assignee_id,
        age=age_label(issue.created_at) if issue.status != "resolved" else "",
        when=issue.created_at.isoformat() if issue.created_at else "",
        applications=tuple(issue.applications),
        action_label=action_label(issue),
        href=issue.href,
        legacy_testid=issue.legacy_testid,
        link_status=issue.link_status,
    )


def project(
    tasks: list[Issue],
    *,
    view_key: str = "needs_review",
    actor_id: str = "",
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return one view of the queue: its rows, the counts of every view and the totals.

    The counts use the same tasks as the rows, so a count never describes
    work the persona may not see.  A view counts tasks, and it reports the
    applications those tasks affect separately.
    """
    keys = [key for key, _ in QUEUE_FILTERS]
    if view_key not in keys:
        view_key = "needs_review"
    known = labels or {}
    chosen = [issue for issue in tasks if matches(issue, view_key, actor_id)]
    chosen = order_tasks(chosen, newest_first=view_key == "resolved")
    rows = [
        work_row(issue, assignee=known.get(issue.assignee_id or "", ""))
        for issue in chosen
    ]
    views = []
    for key, label in QUEUE_FILTERS:
        in_view = [issue for issue in tasks if matches(issue, key, actor_id)]
        views.append(
            {
                "key": key,
                "label": label,
                "count": len(in_view),
                "affected": sum(len(issue.applications) for issue in in_view),
                "active": key == view_key,
                "href": "/steward" if key == "needs_review" else f"/steward?filter={key}",
            }
        )
    return {
        "filter": view_key,
        "filters": views,
        "rows": [row.as_dict() for row in rows],
        "show_assignment": any(row.assignee for row in rows),
        "show_age": any(row.age for row in rows),
        "show_priority": any(row.priority for row in rows),
        "total": len(tasks),
        "affected": sum(row.affected_count for row in rows),
    }


__all__ = [
    "ACTION_LABELS",
    "BLOCKING_PRIORITY",
    "IDENTITY_TASKS",
    "Issue",
    "QUEUE_FILTERS",
    "STATUS_LABELS",
    "TASK_TITLES",
    "WorkRow",
    "action_label",
    "age_label",
    "matches",
    "order_tasks",
    "project",
    "task_title",
    "work_row",
]

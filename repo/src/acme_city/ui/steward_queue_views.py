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
from urllib.parse import quote, urlencode

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

#: The record types of the queue, in the order they are listed.  The value is
#: the filter value of the GET request.
RECORD_TYPES: tuple[tuple[str, str], ...] = (
    ("match", "Match"),
    ("property", "Property"),
    ("correction", "Correction"),
    ("issue", "Data issue"),
)

#: The record type of each kind of task.
RECORD_TYPE_BY_KIND: dict[str, str] = {
    "link": "match",
    "linked": "match",
    "parcel": "property",
    "case": "correction",
    "issue": "issue",
}

#: The record type labels, by filter value.
RECORD_TYPE_LABELS: dict[str, str] = dict(RECORD_TYPES)

#: The number of tasks one page of the queue holds.
PAGE_SIZE = 25

#: The next step of an incoming case, by the state the server recorded.  The
#: words say what happens next; they never promise a time and they never
#: decide anything.
INTAKE_NEXT_STEPS: dict[str, str] = {
    "submitted": "The intake agent reads the received documents.",
    "needs_information": "A person resolves the case.",
    "ready_for_review": "The Permit Reviewer reads the case.",
    "under_review": "The Permit Reviewer reads the case.",
    "revisions_requested": "The applicant answers the request.",
    "archived": "The case is archived. A restore returns it.",
    "issued": "The permit is issued. Nothing is waiting.",
    "denied": "The case was denied. Nothing is waiting.",
    "returned": "The case was returned. Nothing is waiting.",
}

#: The next step of a case the server holds no state for.
INTAKE_NEXT_STEP_UNKNOWN = "Open the case to see what it needs."

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
    def record_type(self) -> str:
        """The filter value of the record type of the row."""
        return RECORD_TYPE_BY_KIND.get(self.kind, "")

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
            "record_type": self.record_type,
            "record_type_label": RECORD_TYPE_LABELS.get(self.record_type, ""),
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


def matches_query(issue: Issue, query: str) -> bool:
    """Whether one task matches the search text.

    The text is looked for in the name of the record, in the reason of the
    work, in the source, in the reference of the source record and in the
    address a property work is about.
    """
    needle = query.strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        (
            issue.record,
            issue.title,
            issue.source,
            issue.source_reference,
            issue.record_ref,
            issue.item_id,
        )
    ).lower()
    return needle in haystack


def matches_record_type(issue: Issue, record_type: str) -> bool:
    """Whether one task has the record type the steward asked for."""
    if not record_type:
        return True
    return RECORD_TYPE_BY_KIND.get(issue.kind, "") == record_type


def matches_source(issue: Issue, source: str) -> bool:
    """Whether one task came from the source the steward asked for."""
    if not source:
        return True
    return issue.source == source


def queue_href(path: str = "/steward", **params: str | int | None) -> str:
    """Return the address of the queue with the given query values."""
    values = {key: value for key, value in params.items() if value not in (None, "")}
    if not values:
        return path
    return f"{path}?{urlencode(values)}"


def intake_next_step(row: dict[str, Any]) -> str:
    """Return the next step of one incoming case in plain words.

    The step follows the state the server recorded.  A case that waits for a
    person says so, and a case that is closed says so too, so the summary
    never promises a step the server does not hold.
    """
    if row.get("primary_finding"):
        return "A person resolves the recorded finding."
    return INTAKE_NEXT_STEPS.get(str(row.get("status", "")), INTAKE_NEXT_STEP_UNKNOWN)


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
    query: str = "",
    record_type: str = "",
    source: str = "",
    page: int = 1,
    page_size: int = PAGE_SIZE,
    return_path: str = "",
) -> dict[str, Any]:
    """Return one view of the queue: its rows, the counts of every view and the totals.

    The counts use the same tasks as the rows, so a count never describes
    work the persona may not see.  A view counts tasks, and it reports the
    applications those tasks affect separately.

    The search, the record type filter and the source filter narrow the rows
    of the view.  Every address the queue builds keeps the other values, so
    a steward who comes back from a case finds the same search, the same
    filters and the same page.
    """
    keys = [key for key, _ in QUEUE_FILTERS]
    if view_key not in keys:
        view_key = "needs_review"
    known = labels or {}
    in_view = [issue for issue in tasks if matches(issue, view_key, actor_id)]
    chosen = [
        issue
        for issue in in_view
        if matches_query(issue, query)
        and matches_record_type(issue, record_type)
        and matches_source(issue, source)
    ]
    chosen = order_tasks(chosen, newest_first=view_key == "resolved")
    pages = max((len(chosen) + page_size - 1) // page_size, 1)
    page = min(max(page, 1), pages)
    start = (page - 1) * page_size
    shown = chosen[start : start + page_size]
    rows = [
        work_row(issue, assignee=known.get(issue.assignee_id or "", "")).as_dict()
        for issue in shown
    ]
    if return_path:
        for row, issue in zip(rows, shown):
            row["href"] = f"{issue.href}?back={quote(return_path, safe='')}"
    views = []
    for key, label in QUEUE_FILTERS:
        in_other = [issue for issue in tasks if matches(issue, key, actor_id)]
        views.append(
            {
                "key": key,
                "label": label,
                "count": len(in_other),
                "affected": sum(len(issue.applications) for issue in in_other),
                "active": key == view_key,
                "href": queue_href(
                    "/steward",
                    filter=None if key == "needs_review" else key,
                    q=query,
                    record_type=record_type,
                    source=source,
                ),
            }
        )
    record_types = [
        {
            "value": value,
            "label": label,
            "count": sum(1 for issue in in_view if matches_record_type(issue, value)),
            "active": value == record_type,
            "href": queue_href(
                "/steward",
                filter=None if view_key == "needs_review" else view_key,
                q=query,
                record_type=value,
                source=source,
            ),
        }
        for value, label in RECORD_TYPES
    ]
    sources = [
        {
            "value": name,
            "label": name,
            "count": sum(1 for issue in in_view if issue.source == name),
            "active": name == source,
            "href": queue_href(
                "/steward",
                filter=None if view_key == "needs_review" else view_key,
                q=query,
                record_type=record_type,
                source=name,
            ),
        }
        for name in sorted({issue.source for issue in in_view})
    ]
    return {
        "filter": view_key,
        "filters": views,
        "rows": rows,
        "query": query,
        "clear_href": queue_href(
            "/steward",
            filter=None if view_key == "needs_review" else view_key,
            q=query,
        ),
        "record_type": record_type,
        "record_types": record_types,
        "source": source,
        "sources": sources,
        "show_assignment": any(row["assignee"] for row in rows),
        "show_age": any(row["age"] for row in rows),
        "show_priority": any(row["priority"] for row in rows),
        "total": len(tasks),
        "affected": sum(row["affected_count"] for row in rows),
        "matched": len(chosen),
        "paging": {
            "page": page,
            "pages": pages,
            "total": len(chosen),
            "first": start + 1 if chosen else 0,
            "last": min(start + page_size, len(chosen)),
        },
    }


__all__ = [
    "ACTION_LABELS",
    "BLOCKING_PRIORITY",
    "IDENTITY_TASKS",
    "INTAKE_NEXT_STEPS",
    "INTAKE_NEXT_STEP_UNKNOWN",
    "Issue",
    "PAGE_SIZE",
    "QUEUE_FILTERS",
    "RECORD_TYPES",
    "RECORD_TYPE_BY_KIND",
    "STATUS_LABELS",
    "TASK_TITLES",
    "WorkRow",
    "action_label",
    "age_label",
    "intake_next_step",
    "matches",
    "matches_query",
    "matches_record_type",
    "matches_source",
    "order_tasks",
    "project",
    "queue_href",
    "task_title",
    "work_row",
]

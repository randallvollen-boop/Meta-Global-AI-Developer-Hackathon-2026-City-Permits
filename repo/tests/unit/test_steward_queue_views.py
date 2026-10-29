"""The unified queue projection of the Data Steward.

The projection turns the tasks the steward views collected into the rows of
one view: what needs attention, which record is involved, what is affected,
what the next action is and who is responsible.  The order is deterministic,
the counts use the same tasks as the rows, and the legacy filter keys keep
working.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02, MDM-02

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from acme_city.ui import steward_queue_views as queue

#: A moment in the demonstration, so the age of a task is readable.
NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)

#: The acting persona of the queue.
STEWARD = "persona_data_steward"


def task(
    item_id: str = "case_1",
    *,
    kind: str = "link",
    status: str = "needs_review",
    created_at: datetime | None = NOW - timedelta(days=3),
    assignee_id: str | None = None,
    priority: str = "",
    record_type: str = "organization",
    source_reference: str = "PER-AP-0003",
    applications: list[dict[str, str]] | None = None,
) -> queue.Issue:
    """Return one task of the queue."""
    return queue.Issue(
        kind=kind,
        item_id=item_id,
        title="Is PER-AP-0003 the same as Cedarline Coffee Roasters LLC?",
        record="Cedarline Coffee Roasters LLC",
        record_ref="record:party_cedarline",
        applications=applications if applications is not None else [],
        source="Finance business licences",
        status=status,
        assignee_id=assignee_id,
        created_at=created_at,
        priority=priority,
        legacy_testid="match-proposal",
        link_status="proposed",
        record_type=record_type,
        source_reference=source_reference,
    )


def applications(count: int) -> list[dict[str, str]]:
    """Return ``count`` affected applications."""
    return [
        {
            "number": f"PERM-2026-{index:04d}",
            "href": f"/permits/app_{index}",
            "status": "Submitted",
        }
        for index in range(count)
    ]


def test_a_row_answers_the_five_questions_of_a_work_item() -> None:
    """The row names the task, the record, the impact, the action and the owner."""
    row = queue.work_row(
        task(applications=applications(2), assignee_id=STEWARD),
        assignee="Data Steward",
    )
    assert row.task == "Check the business identity"
    assert row.record == "Cedarline Coffee Roasters LLC"
    assert row.source == "Finance business licences"
    assert row.source_reference == "PER-AP-0003"
    assert row.affected_count == 2
    assert row.action_label == "Review match"
    assert row.assignee == "Data Steward"
    assert row.href == "/steward/issues/link/case_1"


def test_the_task_names_the_kind_of_record_it_is_about() -> None:
    """A person is not a business, and a parcel is a property."""
    assert queue.task_title(task(record_type="person")) == "Check the person identity"
    assert queue.task_title(task(record_type="organization")) == "Check the business identity"
    assert queue.task_title(task(record_type="")) == "Check the record match"
    assert queue.task_title(task(kind="parcel", record_type="parcel")) == "Check the property"
    assert queue.task_title(task(kind="case")) == "Check the correction"
    assert queue.task_title(task(kind="issue")) == "Check the data issue"


def test_blocking_work_comes_first_and_then_the_oldest_waiting_work() -> None:
    """Recorded blocking work leads, then an explicit priority, then the oldest."""
    old = task("old", created_at=NOW - timedelta(days=9))
    new = task("new", created_at=NOW - timedelta(days=1))
    blocking = task("blocking", priority=queue.BLOCKING_PRIORITY)
    ordered = queue.order_tasks([new, old, blocking])
    assert [issue.item_id for issue in ordered] == ["blocking", "old", "new"]


def test_the_order_is_stable_for_two_tasks_of_the_same_age() -> None:
    """Two tasks of the same age keep a stable order."""
    first = task("a_task")
    second = task("b_task")
    ordered = queue.order_tasks([second, first])
    assert [issue.item_id for issue in ordered] == ["a_task", "b_task"]
    assert [issue.item_id for issue in queue.order_tasks([first, second])] == [
        "a_task",
        "b_task",
    ]


def test_the_resolved_view_shows_the_newest_decision_first() -> None:
    """Resolved work is read newest first."""
    old = task("old", status="resolved", created_at=NOW - timedelta(days=9))
    new = task("new", status="resolved", created_at=NOW - timedelta(days=1))
    ordered = queue.order_tasks([old, new], newest_first=True)
    assert [issue.item_id for issue in ordered] == ["new", "old"]


def test_the_counts_use_the_same_tasks_as_the_rows() -> None:
    """A count never describes work the persona may not see."""
    tasks = [
        task("one"),
        task("two", status="awaiting_source"),
        task("three", status="resolved"),
        task("four", assignee_id=STEWARD),
    ]
    view = queue.project(tasks, view_key="needs_review", actor_id=STEWARD)
    counts = {entry["key"]: entry["count"] for entry in view["filters"]}
    assert counts == {
        # The task of the steward is in Needs review as well: the work is
        # open, and being assigned does not move it out of the queue.
        "needs_review": 2,
        "assigned_to_me": 1,
        "awaiting_source": 1,
        "resolved": 1,
    }
    assert [row["id"] for row in view["rows"]] == ["four", "one"]


def test_one_task_affecting_three_applications_counts_as_one_task() -> None:
    """A task is counted once, and its affected applications separately."""
    tasks = [task("one", applications=applications(3))]
    view = queue.project(tasks, view_key="needs_review", actor_id=STEWARD)
    assert view["filters"][0]["count"] == 1
    assert view["filters"][0]["affected"] == 3
    assert view["affected"] == 3
    assert view["rows"][0]["affected_count"] == 3


def test_the_legacy_filter_keys_keep_working() -> None:
    """The four views of the Data issues queue keep their keys and labels."""
    assert [key for key, _ in queue.QUEUE_FILTERS] == [
        "needs_review",
        "assigned_to_me",
        "awaiting_source",
        "resolved",
    ]
    assert [label for _, label in queue.QUEUE_FILTERS] == [
        "Needs review",
        "Assigned to me",
        "Awaiting source",
        "Resolved",
    ]
    # An unknown key falls back to the first view instead of failing.
    view = queue.project([task()], view_key="not_a_view", actor_id=STEWARD)
    assert view["filter"] == "needs_review"
    assert len(view["rows"]) == 1


def test_assigned_to_me_shows_only_the_work_of_that_persona() -> None:
    """The filter of the persona shows their own open work."""
    tasks = [
        task("mine", assignee_id=STEWARD),
        task("theirs", assignee_id="persona_city_administrator"),
        task("unassigned"),
    ]
    view = queue.project(tasks, view_key="assigned_to_me", actor_id=STEWARD)
    assert [row["id"] for row in view["rows"]] == ["mine"]


def test_unassigned_work_stays_in_needs_review() -> None:
    """Matching work nobody owns is still work to do."""
    tasks = [task("unassigned")]
    view = queue.project(tasks, view_key="needs_review", actor_id=STEWARD)
    assert [row["id"] for row in view["rows"]] == ["unassigned"]
    assigned = queue.project(tasks, view_key="assigned_to_me", actor_id=STEWARD)
    assert assigned["rows"] == []


def test_an_empty_queue_has_no_rows() -> None:
    """An empty queue shows no row and no count."""
    view = queue.project([], view_key="needs_review", actor_id=STEWARD)
    assert view["rows"] == []
    assert view["total"] == 0
    assert view["affected"] == 0
    assert all(entry["count"] == 0 for entry in view["filters"])


def test_the_rows_keep_the_keys_the_template_reads() -> None:
    """The row keeps every key the shared template reads."""
    row = queue.project([task()], view_key="needs_review", actor_id=STEWARD)["rows"][0]
    for key in (
        "id",
        "kind",
        "href",
        "title",
        "record",
        "record_ref",
        "applications",
        "source",
        "status_key",
        "status",
        "assignee",
        "age",
        "when",
        "priority",
        "legacy_testid",
        "link_status",
    ):
        assert key in row, key
    assert row["legacy_testid"] == "match-proposal"
    assert row["status_key"] == "needs_review"
    assert row["status"] == "Needs review"


def test_the_age_of_a_task_is_read_in_days() -> None:
    """A task that waits shows how long it has been waiting."""
    today = datetime.now(UTC)
    assert queue.age_label(today - timedelta(days=3)) == "3 days"
    assert queue.age_label(today - timedelta(days=1)) == "1 day"
    assert queue.age_label(today) == "Today"
    assert queue.age_label(None) == ""

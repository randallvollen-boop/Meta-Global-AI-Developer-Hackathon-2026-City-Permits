"""The operations dashboard (S10): every figure is a count over stored rows."""
# REQUIRES: UX-01, SEC-02

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.core.ids import new_id
from acme_city.ops.dashboard import (
    ACTIVE_STATUSES,
    PROCESSING_GROUP,
    WORKLOAD_GROUP,
    dashboard,
)
from acme_city.permits.queues import INTAKE_TABS
from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.models import permit
from acme_city.persistence.session import SessionFactory, transaction

from ops_helpers import build_template, copy_of

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def template(tmp_path_factory) -> Path:
    return build_template(tmp_path_factory.mktemp("ops-dash"))


@pytest.fixture()
def session(template, tmp_path):
    settings = copy_of(template, tmp_path)
    factory = SessionFactory(settings.database_url)
    with transaction(factory) as open_session:
        yield open_session
    factory.dispose()


def figure(view, key):
    return next(item for item in view["figures"] if item["key"] == key)


def add_run(session, application_id: str, outcome: str, minutes: int) -> None:
    session.add(
        agent_models.AgentRun(
            id=new_id("act"),
            correlation_id=new_id("corr"),
            agent_key="intake",
            application_id=application_id,
            service_identity_id="service_agent_intake",
            started_at=NOW + timedelta(minutes=minutes),
            outcome=outcome,
            inputs={"revision": 1},
        )
    )
    session.flush()


def test_the_active_set_is_the_p3b_active_saved_view() -> None:
    assert ACTIVE_STATUSES == next(t["statuses"] for t in INTAKE_TABS if t["key"] == "active")


def test_active_cases_and_average_age_match_independent_arithmetic(session) -> None:
    view = dashboard(session, now=NOW)
    rows = [
        r
        for r in session.execute(select(permit.Application)).scalars()
        if r.status in ACTIVE_STATUSES and not r.synthetic
    ]
    assert figure(view, "active")["value"] == len(rows) > 0
    ages = [(NOW - r.initial_submitted_at).total_seconds() / 86400 for r in rows if r.initial_submitted_at]
    assert figure(view, "average_age")["value"] == round(sum(ages) / len(ages), 1)
    for item in view["figures"]:
        assert item["definition"], item["key"]  # every figure states its definition


def test_agent_processed_counts_distinct_applications_not_runs(session) -> None:
    add_run(session, "app_d02", "completed", 1)
    add_run(session, "app_d02", "completed", 2)  # a rerun adds a run row, not an application
    add_run(session, "app_d03", "needs_information", 3)
    add_run(session, "app_d04", "failed", 4)  # failed is not completed
    view = dashboard(session, now=NOW)
    assert figure(view, "agent_processed")["value"] == 2


def test_early_incomplete_share_uses_the_first_run_of_each_application(session) -> None:
    add_run(session, "app_d02", "needs_information", 1)   # first run needs information
    add_run(session, "app_d02", "completed", 2)           # later run does not change it
    add_run(session, "app_d03", "completed", 3)           # first run completed
    add_run(session, "app_d03", "needs_information", 4)   # later run does not change it
    add_run(session, "app_d04", "failed", 5)              # counts in the denominator only
    view = dashboard(session, now=NOW)
    item = figure(view, "early_incomplete")
    assert item["value"] == 1 and item["display"] == "33% (1 of 3)"


def test_early_incomplete_says_so_when_no_run_exists(session) -> None:
    assert figure(dashboard(session, now=NOW), "early_incomplete")["display"] == "no intake run yet"


def test_decisions_by_outcome_count_decision_rows(session) -> None:
    view = dashboard(session, now=NOW)
    by_outcome = Counter(d.outcome for d in session.execute(select(permit.Decision)).scalars() if not d.synthetic)
    assert figure(view, "decisions")["value"] == sum(by_outcome.values())
    shown = {row["label"]: row["count"] for row in view["decision_rows"]}
    assert shown["Approved"] == by_outcome["approved"]


def test_needs_a_person_adds_needs_information_and_held_recommendations(session) -> None:
    session.get(permit.Application, "app_d02").status = "needs_information"
    session.add(
        permit.Recommendation(
            id=new_id("rec"),
            application_id="app_d03",
            proposed_outcome="hold",
            status="pending",
        )
    )
    session.flush()
    view = dashboard(session, now=NOW)
    item = figure(view, "needs_a_person")
    assert item["value"] == 2 and "(1)" in item["definition"]


def test_every_figure_names_its_group_and_its_plain_label(session) -> None:
    view = dashboard(session, now=NOW)
    groups = {item["key"]: item["group"] for item in view["figures"]}
    assert groups == {
        "active": WORKLOAD_GROUP,
        "average_age": WORKLOAD_GROUP,
        "needs_a_person": WORKLOAD_GROUP,
        "early_incomplete": PROCESSING_GROUP,
        "agent_processed": PROCESSING_GROUP,
        "decisions": PROCESSING_GROUP,
    }
    labels = {item["key"]: item["label"] for item in view["figures"]}
    assert labels["active"] == "Active cases"
    assert labels["average_age"] == "Average age of active cases"
    assert labels["needs_a_person"] == "Items needing attention"
    assert labels["early_incomplete"] == "Incomplete at first intake"
    assert labels["agent_processed"] == "Applications processed by intake"
    assert labels["decisions"] == "Decisions recorded"


def test_the_items_needing_attention_name_their_two_components(session) -> None:
    session.get(permit.Application, "app_d02").status = "needs_information"
    session.add(
        permit.Recommendation(
            id=new_id("rec"),
            application_id="app_d03",
            proposed_outcome="hold",
            status="pending",
        )
    )
    session.flush()
    item = figure(dashboard(session, now=NOW), "needs_a_person")
    # The calculation is unchanged: the two components are added together.
    assert item["value"] == 2
    assert [part["value"] for part in item["components"]] == [1, 1]
    assert item["components"][0]["label"] == "Applications in needs information"
    assert item["components"][1]["label"] == "Recommendations held for a person"
    # The figure says what it is not: it is not a count of distinct cases.
    assert "not of distinct cases" in item["definition"]


def test_the_charts_have_a_table_and_a_total_that_matches(session) -> None:
    view = dashboard(session, now=NOW)
    status = next(c for c in view["charts"] if c["testid"] == "chart-status")
    assert status["total"] == view["applications_counted"]
    assert "<svg" in status["svg"] and "<title>" in status["svg"]
    for chart in view["charts"]:
        assert chart["definition"]


def test_the_synthetic_history_is_left_out_by_default_and_labelled_when_included(session, template) -> None:
    from acme_city.fixtures.synthetic import load_synthetic_year

    load_synthetic_year(session, seed=20261028, count=40)
    session.flush()
    plain = dashboard(session, now=NOW)
    both = dashboard(session, synthetic="include", now=NOW)
    assert plain["synthetic"]["available"] and plain["synthetic"]["mode"] == "exclude"
    assert "left out" in plain["synthetic"]["note"]
    assert both["synthetic"]["mode"] == "include" and "labelled as synthetic" in both["synthetic"]["note"]
    assert both["applications_counted"] == plain["applications_counted"] + 40
    assert figure(both, "decisions")["value"] > figure(plain, "decisions")["value"]


def test_an_empty_chart_has_no_svg_and_the_page_says_so(session) -> None:
    view = dashboard(session, now=NOW)
    backlog = next(c for c in view["charts"] if c["testid"] == "chart-backlog")
    assert backlog["rows"] == [] and backlog["svg"] == ""

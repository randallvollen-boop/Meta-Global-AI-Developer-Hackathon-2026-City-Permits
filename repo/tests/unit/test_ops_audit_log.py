"""The audit log (S11): classification, filters, paging and record links."""
# REQUIRES: SEC-03, UX-01

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from acme_city.core.ids import new_id
from acme_city.ops.audit_log import PAGE_SIZE, actor_type_of, audit_log, identity_sets
from acme_city.ui.ops_views import audit_action_label, audit_presentation
from acme_city.persistence.models import audit, governance
from acme_city.persistence.session import SessionFactory, transaction

from ops_helpers import build_template, copy_of


@pytest.fixture(scope="module")
def template(tmp_path_factory) -> Path:
    return build_template(tmp_path_factory.mktemp("ops-audit"))


@pytest.fixture()
def session(template, tmp_path):
    settings = copy_of(template, tmp_path)
    factory = SessionFactory(settings.database_url)
    with transaction(factory) as open_session:
        yield open_session
    factory.dispose()


def event(session, actor_id, action="test.action", target_type="", target_id="", minutes=0):
    session.add(
        audit.AuditEvent(
            id=new_id("audit"),
            correlation_id=new_id("corr"),
            occurred_at=datetime(2026, 10, 28, 9, 0, tzinfo=UTC) + timedelta(minutes=minutes),
            actor_id=actor_id,
            actor_role_ids=[],
            action=action,
            target_type=target_type or None,
            target_id=target_id or None,
            outcome="accepted",
        )
    )
    session.flush()


def test_the_actor_type_comes_from_the_identity_rows_not_the_string(session) -> None:
    people, agents = identity_sets(session)
    assert "persona_permit_reviewer" in people
    assert agents == {"service_agent_intake", "service_agent_adjudication"}
    assert actor_type_of("persona_permit_reviewer", people, agents) == "person"
    assert actor_type_of("service_agent_intake", people, agents) == "agent"
    assert actor_type_of("service_custodian_gis", people, agents) == "system"  # a service identity, not an agent
    assert actor_type_of(None, people, agents) == "system"
    # a string that merely looks like an agent is not one
    assert actor_type_of("service_agent_made_up", people, agents) == "system"
    assert actor_type_of("persona_made_up", people, agents) == "system"


def test_a_staff_user_added_in_administration_is_a_person(session) -> None:
    session.add(
        governance.Actor(
            id=new_id("actor"), actor_id="staff_new_clerk", label="New Clerk",
            selectable=False, persona_role="Permit Reviewer",
        )
    )
    session.flush()
    people, agents = identity_sets(session)
    assert actor_type_of("staff_new_clerk", people, agents) == "person"


def test_filters_by_actor_type_action_and_search(session) -> None:
    event(session, "persona_permit_reviewer", "permit.decide", "decision", "decision_x", 1)
    event(session, "service_agent_intake", "agent.run.intake", "application", "app_d02", 2)
    event(session, None, "system.sweep", "", "", 3)
    assert {r["actor_type"] for r in audit_log(session, actor_type="agent")["rows"]} == {"agent"}
    assert {r["actor_type"] for r in audit_log(session, actor_type="person")["rows"]} == {"person"}
    systems = audit_log(session, actor_type="system")["rows"]
    assert systems and {r["actor_type"] for r in systems} == {"system"}
    assert [r["action"] for r in audit_log(session, action="permit.decide")["rows"]] == ["permit.decide"]
    found = audit_log(session, search="app_d02")["rows"]
    assert [r["action"] for r in found] == ["agent.run.intake"]
    assert audit_log(session, search="no-such-thing")["total"] == 0


def test_newest_first_and_paged(session) -> None:
    for number in range(PAGE_SIZE + 5):
        event(session, "persona_data_steward", "test.paged", minutes=number + 10)
    first = audit_log(session, action="test.paged")
    second = audit_log(session, action="test.paged", page=2)
    assert first["total"] == PAGE_SIZE + 5 and first["pages"] == 2 and len(first["rows"]) == PAGE_SIZE
    assert len(second["rows"]) == 5
    assert first["rows"][0]["occurred_at"] > first["rows"][-1]["occurred_at"]
    assert first["rows"][-1]["occurred_at"] > second["rows"][0]["occurred_at"]
    assert audit_log(session, action="test.paged", page=99)["page"] == 2  # clamped


def test_rows_link_to_their_record_by_target_type_with_a_text_fallback(session) -> None:
    event(session, "persona_data_steward", "a", "application", "app_d02", 1)
    event(session, "persona_data_steward", "b", "policy_run", "polrun_1", 2)
    event(session, "persona_data_steward", "c", "help_request", "helpreq_1", 3)
    event(session, "persona_data_steward", "d", "reason_code", "rc_1", 4)  # no page
    rows = {r["action"]: r for r in audit_log(session, actor_type="person")["rows"] if r["action"] in {"a", "b", "c", "d"}}
    assert rows["a"]["href"] == "/permits/app_d02"
    assert rows["b"]["href"] == "/policy/runs/polrun_1"
    assert rows["c"]["href"] == "/ops/support?request=helpreq_1"
    assert rows["d"]["href"] == "" and rows["d"]["target_type"] == "reason_code"


def test_a_decision_event_links_to_the_case_it_belongs_to(session) -> None:
    from ops_helpers import add_decision

    decision = add_decision(session)
    event(session, "persona_permit_reviewer", "permit.decide", "decision", decision.id)
    row = audit_log(session, action="permit.decide")["rows"][0]
    assert row["href"] == f"/permits/{decision.application_id}"


def test_the_audit_presenter_keeps_raw_values_and_adds_readable_event_fields() -> None:
    view = audit_presentation(
        {
            "rows": [{"action": "support.help_request.answer", "outcome": "accepted", "actor_type": "person", "target_type": "help_request", "target_id": "help_1"}],
            "actions": ["support.help_request.answer", "made.up_action"],
        }
    )
    row = view["rows"][0]
    assert row["action"] == "support.help_request.answer"
    assert row["action_label"] == "Answered help request"
    assert row["outcome_label"] == "Recorded"
    assert row["actor_type_label"] == "person"
    assert row["target_label"] == "help_request help_1"
    assert view["actions"] == [
        {"key": "support.help_request.answer", "label": "Answered help request"},
        {"key": "made.up_action", "label": "Made Up Action"},
    ]
    assert audit_action_label("") == "Recorded event"

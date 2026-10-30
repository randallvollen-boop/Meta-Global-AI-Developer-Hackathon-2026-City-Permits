"""The moves whose status rules are written inline in a service match the map.

Run application checks, Correct the application record, Revert the agent
recommendation and Issue the permit keep their status rules inside the
service code, so the map cannot import them.  Each test puts one fictional
case in every status a stored application can hold, runs the real service,
and compares what happened with the map: a source status must move to the
target, and every other status must be refused or left unchanged.
"""
# REQUIRES: PER-03, PER-04
# The described life cycle is checked against the services themselves.

from __future__ import annotations

from types import SimpleNamespace

import pytest

from acme_city.agents.recommendation import revert
from acme_city.core.config import Settings
from acme_city.core.errors import AcmeError
from acme_city.permits import lifecycle_map as lm
from acme_city.permits.issuance import PermitIssuanceService
from acme_city.permits.schemas import ReviseApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.persistence.models import permit
from acme_city.persistence.session import SessionFactory
from test_lifecycle_service import context_for, make_case, seeded  # noqa: F401 - seeded is a fixture

#: Every status a stored application can hold.  Draft is the applicant's form
#: before the application row exists, so no service runs on it.
STORED = tuple(item.key for item in lm.STATUSES if item.key != "draft")


def _move(key: str) -> lm.Move:
    return next(move for move in lm.MOVES if move.key == key)


def _outcomes(settings: Settings, act) -> dict[str, str]:
    """Return the status each stored status ends in after ``act`` (refusal keeps it)."""
    results: dict[str, str] = {}
    factory = SessionFactory(settings.database_url)
    try:
        for status in STORED:
            with factory() as session:
                application = make_case(session, status=status)
                try:
                    act(session, application)
                except AcmeError:
                    pass
                session.flush()
                results[status] = application.status
                session.rollback()
    finally:
        factory.dispose()
    return results


def _assert_matches(move: lm.Move, outcomes: dict[str, str]) -> None:
    moved = {status for status, after in outcomes.items() if after != status}
    assert moved == set(move.sources), (move.key, sorted(moved ^ set(move.sources)))
    assert {outcomes[status] for status in moved} == {move.target}, move.key


def test_run_application_checks_moves_exactly_the_mapped_statuses(seeded: Settings) -> None:  # noqa: F811
    def act(session, application) -> None:
        PermitService(session).evaluate(application.id, context_for(session, "persona_permit_reviewer"))

    _assert_matches(_move("validate"), _outcomes(seeded, act))


def test_correct_the_application_record_moves_exactly_the_mapped_statuses(seeded: Settings) -> None:  # noqa: F811
    def act(session, application) -> None:
        PermitService(session).revise(
            ReviseApplicationCommand(
                application_id=application.id,
                reason="A fictional correction.",
                expected_version=application.version,
            ),
            context_for(session, "persona_permit_reviewer"),
        )

    _assert_matches(_move("revise"), _outcomes(seeded, act))


def test_revert_the_agent_recommendation_moves_exactly_the_mapped_statuses(seeded: Settings) -> None:  # noqa: F811
    def act(session, application) -> None:
        recommendation = permit.Recommendation(
            id=f"recommendation_probe_{application.id}",
            application_id=application.id,
            proposed_outcome="approve",
            status="pending",
            version=1,
        )
        session.add(recommendation)
        session.flush()
        revert(
            session,
            recommendation_id=recommendation.id,
            application_id=application.id,
            reason="A fictional reason.",
            actor=context_for(session, "persona_permit_reviewer"),
        )

    _assert_matches(_move("revert_recommendation"), _outcomes(seeded, act))


@pytest.mark.parametrize("status", STORED)
def test_issue_is_blocked_by_status_everywhere_but_the_mapped_source(seeded: Settings, status: str) -> None:  # noqa: F811
    decision = SimpleNamespace(id="decision_probe", status="current", stale=False, outcome="approved")
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = make_case(session, status=status)
            codes = {blocker.code for blocker in PermitIssuanceService(session).blockers(application, decision)}
            assert ("application_not_approved" not in codes) == (status in _move("issue").sources)
            session.rollback()
    finally:
        factory.dispose()

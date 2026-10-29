"""LOGIC-001: the assessment expected version is checked and assessments do not fork."""
# REQUIRES: SEC-01, SEC-02
# A wrong expected application version is a conflict; concurrent assessments leave one current.

from __future__ import annotations

import threading

from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.finance import service as finance_service
from acme_city.finance.schemas import AssessmentCommand, ReassessmentCommand
from acme_city.finance.service import FinanceService
from acme_city.persistence.models import finance
from acme_city.persistence.session import SessionFactory, transaction

ADMIN = ActorContext(actor_id="persona_city_administrator")


def test_a_wrong_expected_application_version_is_a_conflict(audit_client, pick) -> None:
    pick(audit_client, "persona_city_administrator")
    current = audit_client.get("/api/permits/applications/app_synth_001").json()
    version = current["application_version"]
    refused = audit_client.post(
        "/api/finance/assessments",
        json={"application_id": "app_synth_001", "expected_application_version": version + 7},
    )
    assert refused.status_code == 409, refused.text
    accepted = audit_client.post(
        "/api/finance/assessments",
        json={"application_id": "app_synth_001", "expected_application_version": version},
    )
    assert accepted.status_code == 200, accepted.text


def test_concurrent_reassessments_leave_one_current_assessment(audit_settings, monkeypatch) -> None:
    factory = SessionFactory(audit_settings.database_url)
    try:
        with transaction(factory) as session:
            FinanceService(session).assess(AssessmentCommand(application_id="app_synth_001"), ADMIN)

        barrier = threading.Barrier(2)
        real_new_id = finance_service.new_id

        def new_id(prefix: str) -> str:
            if prefix == "assess":
                try:
                    barrier.wait(timeout=2)  # both writers have read the same previous assessment
                except threading.BrokenBarrierError:
                    pass
            return real_new_id(prefix)

        monkeypatch.setattr(finance_service, "new_id", new_id)
        errors: list[BaseException] = []

        def run() -> None:
            try:
                with transaction(factory) as session:
                    FinanceService(session).reassess(
                        ReassessmentCommand(application_id="app_synth_001", carry_forward=True),
                        ADMIN,
                    )
            except BaseException as error:  # noqa: BLE001 - recorded for the assertion
                errors.append(error)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not errors, errors
        with factory() as session:
            rows = session.execute(
                select(finance.Assessment).where(
                    finance.Assessment.application_id == "app_synth_001"
                )
            ).scalars().all()
            current = [row for row in rows if row.status == "current"]
            assert len(current) == 1, [(row.version, row.status) for row in rows]
            assert len({row.version for row in rows}) == len(rows)
    finally:
        factory.dispose()

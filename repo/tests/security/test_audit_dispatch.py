"""AUTHZ-003, API-002, LOGIC-003: the change dispatcher is authorized, bounded and claimed once."""
# REQUIRES: SEC-01, SEC-02
# Dispatch needs the change.case.transition grant on every entry point, a bounded
# batch, and each pending command is answered by exactly one concurrent dispatcher.

from __future__ import annotations

import re
import threading

from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.changes import dispatcher as dispatcher_module
from acme_city.changes.dispatcher import ChangeDispatcher
from acme_city.changes.schemas import ChangeRequestCommand, ChangeTransitionCommand
from acme_city.changes.service import ChangeService
from acme_city.persistence.models import change
from acme_city.persistence.session import SessionFactory, transaction

ADDRESS_PAYLOAD = {
    "address_id": "GIS-AD-0400",
    "street_number": "400",
    "street_name": "Lantern Row",
    "street_type": "Row",
    "municipality": "ACME City",
    "region": "AC",
    "postcode": "ACM-01499",
    "source_string": "400 Lantern Row",
    "parcel_number": "ACME-P-1001",
}


def _csrf(client, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def test_the_dispatch_ui_action_needs_the_transition_grant(audit_client, pick) -> None:
    pick(audit_client, "persona_applicant")
    token = _csrf(audit_client, "/apply")
    refused = audit_client.post(
        "/ui/actions/change.dispatch",
        data={"csrf_token": token, "action_id": "change.dispatch", "next": "/apply"},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert refused.status_code == 403, refused.text
    pick(audit_client, "persona_data_steward")
    token = _csrf(audit_client, "/steward")
    allowed = audit_client.post(
        "/ui/actions/change.dispatch",
        data={"csrf_token": token, "action_id": "change.dispatch", "next": "/steward"},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert allowed.status_code == 200, allowed.text


def test_the_dispatch_batch_size_is_bounded(audit_client, pick) -> None:
    pick(audit_client, "persona_data_steward")
    assert audit_client.post("/api/changes/dispatch?limit=1000000").status_code == 422
    assert audit_client.post("/api/changes/dispatch?limit=0").status_code == 422
    assert audit_client.post("/api/changes/dispatch?limit=100").status_code == 200


def _approved_change(session) -> None:
    steward = ActorContext(actor_id="persona_data_steward")
    delegate = ActorContext(actor_id="service_delegate_steward")
    service = ChangeService(session)
    view = service.request(
        ChangeRequestCommand(
            target_type="source_record",
            target_id="gis/address_register/GIS-AD-0400",
            title="Fictional correction of an official address",
            reason="the postcode of the official address is wrong in the demonstration",
            proposed_value=dict(ADDRESS_PAYLOAD),
        ),
        steward,
    )
    case_id = view.change_case_id
    for status, who, extra in (
        ("in_review", steward, {}),
        ("awaiting_approval", steward, {}),
        ("approved", delegate, {"approver_actor_id": "service_delegate_steward"}),
        ("sent_to_source", steward, {}),
    ):
        service.transition(
            ChangeTransitionCommand(change_case_id=case_id, to_status=status, **extra), who
        )


def test_two_concurrent_dispatchers_answer_a_command_once(audit_settings, monkeypatch) -> None:
    factory = SessionFactory(audit_settings.database_url)
    try:
        with transaction(factory) as session:
            _approved_change(session)
        with factory() as session:
            pending = session.execute(
                select(change.SourceCommand).where(change.SourceCommand.status == "pending")
            ).scalars().all()
            assert len(pending) == 1

        barrier = threading.Barrier(2)
        real_adapter_for = dispatcher_module.adapter_for

        def adapter_for(*args, **kwargs):
            adapter = real_adapter_for(*args, **kwargs)
            real_apply = adapter.apply

            def apply(command, actor):
                try:
                    barrier.wait(timeout=2)  # both dispatchers reach the source together
                except threading.BrokenBarrierError:
                    pass
                return real_apply(command, actor)

            adapter.apply = apply
            return adapter

        monkeypatch.setattr(dispatcher_module, "adapter_for", adapter_for)
        results: list[int] = []
        errors: list[BaseException] = []

        def run() -> None:
            try:
                with transaction(factory) as session:
                    results.append(ChangeDispatcher(session).dispatch_pending(limit=25).dispatched)
            except BaseException as error:  # noqa: BLE001 - recorded for the assertion
                errors.append(error)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not errors, errors
        assert sum(results) == 1, results
    finally:
        factory.dispose()

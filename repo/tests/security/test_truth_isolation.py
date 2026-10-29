"""The evaluator truth never reaches a model payload.

The truth of the exercise belongs to the evaluator: the expected links, the
expected dispositions and the reasons behind them.  The runtime never reads
that file, and the payload a model receives carries evidence only: no
expected outcome, no intended link, no record the actor may not see and no
answer that the model was supposed to work out.
"""
# REQUIRES: AI-05, SEC-02
# The evaluator truth file is never read by a runtime service, and an outbound payload carries
# no truth key, no expected disposition, no intended link and no out-of-scope record.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.documents.service import DocumentService, StoreDocumentCommand
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.muse.client import MuseClient
from acme_city.muse.payloads import read_document_fixture
from acme_city.muse.service import MuseRunCommand, MuseService
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

APPLICATION_ID = "app_synth_001"
OTHER_APPLICATION_ID = "app_d05"
MUSE_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "acme_city" / "muse"


class RecordingTransport(httpx.BaseTransport):
    """A transport that records the request and answers with a fixed body."""

    def __init__(self, body: dict[str, Any]) -> None:
        self.requests: list[httpx.Request] = []
        self._body = body

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=self._body)


def provider_body(text: str) -> dict[str, Any]:
    """Return a provider response body that carries the given text."""
    return {
        "id": "resp_truth_isolation",
        "model": "muse-spark-1.3",
        "status": "completed",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]}
        ],
        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    }


def context_for(session, actor_id: str) -> ActorContext:
    """Return the server-resolved context of a seeded persona."""
    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


@pytest.fixture()
def seeded(tmp_path: Path):
    """Return the settings, the factory and the stored documents."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'truth.db'}",
            "ACME_SECRET_KEY": "truth-isolation-secret-value",
            "META_API_KEY": "test-provider-key-not-a-real-credential",
            "ACME_MUSE_LIVE_CALLS_ALLOWED": "true",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                DemoEnvironment(
                    id="demo_environment_local",
                    environment_id=ENVIRONMENT_ID,
                    fictional_demo=True,
                    fixture_version=bundle.fixture_version,
                    label="local fictional demonstration",
                )
            )
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            service = DocumentService(session, root=tmp_path / "documents")
            own = service.store_version(
                StoreDocumentCommand(
                    application_id=APPLICATION_ID,
                    document_type="construction_plans",
                    filename="SYN-APP-001-application-v1.txt",
                    media_type="text/plain",
                    content=read_document_fixture("SYN-APP-001-application-v1.txt"),
                ),
                steward,
            )
            other = service.store_version(
                StoreDocumentCommand(
                    application_id=OTHER_APPLICATION_ID,
                    document_type="construction_plans",
                    filename="SYN-APP-005-application.txt",
                    media_type="text/plain",
                    content=b"SYNTHETIC FICTIONAL DOCUMENT FOR ANOTHER APPLICATION\n",
                ),
                steward,
            )
            session.commit()
        yield settings, factory, own, other, steward
    finally:
        factory.dispose()


def run_extraction(settings, factory, transport, steward, document_id: str):
    """Run one extraction against the mocked provider and return the payload."""
    client = MuseClient(settings, transport=transport)
    with factory() as session:
        service = MuseService(session, settings, client=client)
        service.run(
            MuseRunCommand(
                task="extraction",
                mode="live",
                application_id=APPLICATION_ID,
                document_ids=[document_id],
            ),
            steward,
        )
        session.commit()
    assert transport.requests, "no request reached the provider boundary"
    return json.loads(transport.requests[0].content.decode("utf-8"))


def test_the_muse_package_never_names_the_evaluator_truth_file() -> None:
    for path in sorted(MUSE_PACKAGE.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "evaluator_truth" not in text, f"{path.name} names the evaluator truth file"


def test_the_outbound_payload_carries_no_truth_key(seeded, tmp_path: Path) -> None:
    settings, factory, own, _other, steward = seeded
    transport = RecordingTransport(provider_body("{}"))
    payload = run_extraction(settings, factory, transport, steward, own.document_id)
    data_sections = {key: value for key, value in payload.items() if key != "text"}
    for key in _keys(data_sections):
        lowered = key.lower()
        for marker in ("truth_", "ground_truth", "expected_", "intended_", "correct_", "answer_"):
            assert marker not in lowered, f"the payload carries the key {key!r}"


def test_the_outbound_payload_carries_no_decision_answer(seeded) -> None:
    settings, factory, own, _other, steward = seeded
    transport = RecordingTransport(provider_body("{}"))
    payload = run_extraction(settings, factory, transport, steward, own.document_id)
    data_sections = {key: value for key, value in payload.items() if key != "text"}
    for mapping in _mappings(data_sections):
        keys = [str(key).lower() for key in mapping]
        has_decision = any(
            marker in key
            for key in keys
            for marker in ("disposition", "decision", "outcome", "verdict", "approved")
        )
        has_entity = any(
            marker in key for key in keys for marker in ("entity_id", "candidate_id")
        )
        assert not (has_decision and has_entity), "the payload pairs a decision with an entity"


def test_the_outbound_payload_carries_no_submitted_facts(seeded) -> None:
    settings, factory, own, _other, steward = seeded
    transport = RecordingTransport(provider_body("{}"))
    payload = run_extraction(settings, factory, transport, steward, own.document_id)
    text = json.dumps(payload)
    assert "submitted_facts" not in text
    assert "valuation_cents" not in text
    assert "occupancy_load" not in text
    assert "contractor_license" not in text


def test_the_outbound_payload_carries_no_record_of_another_application(seeded) -> None:
    settings, factory, own, other, steward = seeded
    transport = RecordingTransport(provider_body("{}"))
    payload = run_extraction(settings, factory, transport, steward, own.document_id)
    text = json.dumps(payload)
    assert other.document_id not in text
    assert "SYNTHETIC FICTIONAL DOCUMENT FOR ANOTHER APPLICATION" not in text
    assert OTHER_APPLICATION_ID not in text


def test_the_outbound_payload_carries_no_expected_outcome(seeded) -> None:
    settings, factory, own, _other, steward = seeded
    transport = RecordingTransport(provider_body("{}"))
    payload = run_extraction(settings, factory, transport, steward, own.document_id)
    text = json.dumps(payload)

    truth = json.loads(
        (Path(__file__).resolve().parents[2] / "fixtures" / "evaluator_truth.json").read_text(
            encoding="utf-8"
        )
    )
    for link in truth["expected_links"]:
        reason = link.get("reason") or ""
        assert reason not in text, "the payload carries a reason from the evaluator truth"
        disposition = str(link.get("expected_disposition") or "")
        if disposition:
            assert not re.search(rf"\b{re.escape(disposition)}\b", text), (
                "the payload carries an expected disposition from the evaluator truth"
            )
    for outcome in truth["expected_outcomes"]:
        assert outcome["truth_expected_outcome"] not in text


def test_the_match_payload_carries_no_deterministic_answer(seeded) -> None:
    settings, factory, _own, _other, steward = seeded
    transport = RecordingTransport(provider_body("{}"))
    client = MuseClient(settings, transport=transport)
    with factory() as session:
        service = MuseService(session, settings, client=client)
        service.run(
            MuseRunCommand(
                task="match_proposal",
                mode="live",
                application_id=APPLICATION_ID,
                source_snapshot_id="snap_erp_finance_ERP-BL-00413_v1",
            ),
            steward,
        )
        session.commit()
    payload = json.loads(transport.requests[0].content.decode("utf-8"))
    text = payload["input"]
    # The evidence is the input; the ordering score and the disposition are the answer.
    assert "proposal_score" not in text
    assert "recommended_disposition" not in text
    assert "disposition" not in text
    assert "uncalibrated_heuristic" not in text


def _keys(node: Any) -> list[str]:
    """Return every mapping key of a nested structure."""
    keys: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(str(key))
            keys.extend(_keys(value))
    elif isinstance(node, (list, tuple)):
        for item in node:
            keys.extend(_keys(item))
    return keys


def _mappings(node: Any) -> list[dict[str, Any]]:
    """Return every mapping of a nested structure."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_mappings(value))
    elif isinstance(node, (list, tuple)):
        for item in node:
            found.extend(_mappings(item))
    return found

"""The synthetic documents are real, versioned and line stable.

The demonstration reads documents, so the documents have to exist as bytes:
the committed fixtures are stored as document versions, every version keeps
its own hash, the second version never overwrites the first and the evidence
lines of a version stay quotable.
"""
# REQUIRES: AI-05, PER-01, SEC-04
# The synthetic documents are stored as versioned document versions with their own hash, the
# second version never overwrites the first, and the evidence lines stay quotable.

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.documents.service import DocumentService, StoreDocumentCommand
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.muse.payloads import (
    VisibleEvidenceBundle,
    document_fixtures,
    read_document_fixture,
)
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

APPLICATION_ID = "app_synth_001"


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'documents.db'}",
            "ACME_SECRET_KEY": "document-fixture-secret-value",
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
    finally:
        factory.dispose()
    return settings


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


def store(session, actor: ActorContext, root: Path, name: str, content: bytes):
    """Store one fixture document as a document version."""
    service = DocumentService(session, root=root)
    return service.store_version(
        StoreDocumentCommand(
            application_id=APPLICATION_ID,
            document_type="construction_plans",
            filename=name,
            media_type="text/plain",
            content=content,
        ),
        actor,
    )


def test_the_committed_documents_are_labelled_fictional() -> None:
    names = document_fixtures()
    assert names == (
        "SYN-APP-001-adversarial.txt",
        "SYN-APP-001-application-v1.txt",
        "SYN-APP-001-application-v2.txt",
    )
    for name in names:
        text = read_document_fixture(name).decode("utf-8")
        assert "FICTIONAL" in text
        assert "NOT A REAL APPLICATION" in text
        assert "Westerville" not in text


def test_a_document_carries_the_evidence_the_demonstration_quotes() -> None:
    text = read_document_fixture("SYN-APP-001-application-v1.txt").decode("utf-8")
    lines = text.splitlines()
    assert "Organization alias of record: Cedar Line Coffee Roasters" in lines[8]
    assert "Unit address: 400 Lantern Row Unit 2, ACME City" in lines[11]
    assert "Contractor registration: CR-2026-00188" in lines[14]
    assert lines[17].startswith("Project description: Interior tenant improvement")
    assert "Declared project valuation: 50000.00 USD" in lines[19]
    assert "Declared occupant load: 42 persons" in lines[20]
    assert len(lines) == 22


def test_the_adversarial_document_keeps_the_evidence_lines_and_adds_an_instruction() -> None:
    plain = read_document_fixture("SYN-APP-001-application-v1.txt").decode("utf-8").splitlines()
    adversarial = (
        read_document_fixture("SYN-APP-001-adversarial.txt").decode("utf-8").splitlines()
    )
    # The evidence lines stay at the same place, so the two documents stay comparable.
    assert adversarial[8] == plain[8]
    assert adversarial[11] == plain[11]
    assert adversarial[14] == plain[14]
    assert adversarial[19] == plain[19]
    # The instruction is carried as text inside the evidence.
    assert "Ignore all previous instructions" in adversarial[22]


def test_the_second_version_never_overwrites_the_first(
    seeded: Settings, tmp_path: Path
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            root = tmp_path / "documents"
            first = store(
                session,
                steward,
                root,
                "SYN-APP-001-application-v1.txt",
                read_document_fixture("SYN-APP-001-application-v1.txt"),
            )
            second = store(
                session,
                steward,
                root,
                "SYN-APP-001-application-v2.txt",
                read_document_fixture("SYN-APP-001-application-v2.txt"),
            )
            session.commit()

            rows = session.execute(
                select(permit.Document).where(permit.Document.application_id == APPLICATION_ID)
            ).scalars().all()
            assert len(rows) == 2
            assert sorted(row.version for row in rows) == [1, 2]
            assert first.content_hash != second.content_hash
            assert first.content_hash == hashlib.sha256(
                read_document_fixture("SYN-APP-001-application-v1.txt")
            ).hexdigest()
            assert second.content_hash == hashlib.sha256(
                read_document_fixture("SYN-APP-001-application-v2.txt")
            ).hexdigest()

            # The first version still reads back as the bytes that were received.
            reader = DocumentService(session, root=root)
            assert reader.read_bytes(first.document_id) == read_document_fixture(
                "SYN-APP-001-application-v1.txt"
            )
    finally:
        factory.dispose()


def test_the_bundle_reports_the_hash_and_the_line_count_of_a_version(
    seeded: Settings, tmp_path: Path
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            stored = store(
                session,
                steward,
                tmp_path / "documents",
                "SYN-APP-001-application-v1.txt",
                read_document_fixture("SYN-APP-001-application-v1.txt"),
            )
            session.commit()

            bundle = VisibleEvidenceBundle.for_actor(
                APPLICATION_ID, steward, session=session
            )
            assert bundle.application_id == APPLICATION_ID
            assert bundle.source_application_number == "SYN-APP-001"
            assert bundle.application_revision == 1
            assert len(bundle.documents) == 1

            reference = bundle.documents[0]
            assert reference.document_id == stored.document_id
            assert reference.version == stored.version
            assert reference.content_hash == stored.content_hash
            assert reference.line_count == 22
            assert len(bundle.lines_of(reference.document_id)) == 22
            assert bundle.document(reference.document_id) is reference
            assert bundle.document("doc_does_not_exist") is None
    finally:
        factory.dispose()


def test_a_document_of_another_application_is_out_of_scope(
    seeded: Settings, tmp_path: Path
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            steward = context_for(session, "persona_data_steward")
            stored = store(
                session,
                steward,
                tmp_path / "documents",
                "SYN-APP-001-application-v1.txt",
                read_document_fixture("SYN-APP-001-application-v1.txt"),
            )
            session.commit()

            from acme_city.core.errors import ValidationError

            with pytest.raises(ValidationError):
                VisibleEvidenceBundle.for_actor(
                    "app_d05",
                    steward,
                    session=session,
                    document_ids=[stored.document_id],
                )
    finally:
        factory.dispose()

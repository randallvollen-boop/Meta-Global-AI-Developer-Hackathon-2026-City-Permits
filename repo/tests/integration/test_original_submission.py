"""The original submission opens from the permit workspace.

The permit workspace offers "Open the original submission", which opens the
read-only application page in a new tab.  The page lists each document with
an "Open" link, and the link serves the stored file in its own form: a PDF as
a PDF, an image as an image, text as plain UTF-8 text.  Nothing is ever served
as HTML or SVG, a file outside the document store is never read, and a
persona without the read grant, or an applicant outside the record scope, gets
no file.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, SEC-01, SEC-04

from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.documents.service import DOCUMENT_ROOT
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
TEXT = "ACME CITY FICTIONAL DOCUMENT\nSite plan, fence, front yard.\n".encode()
HTML = b"<html><script>alert(1)</script></html>"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'original-submission.db'}",
            "ACME_SECRET_KEY": "original-submission-secret-value",
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


@pytest.fixture()
def client(environment: Settings) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def store() -> Iterator[Path]:
    """A scratch directory inside the document store, removed afterwards."""
    root = Path.cwd() / DOCUMENT_ROOT / f"_original_submission_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def add_document(
    environment: Settings,
    application_id: str,
    path: Path,
    content: bytes,
    *,
    hash_of: bytes | None = None,
    document_type: str = "site_plan",
) -> str:
    """Record one document row whose file is ``path`` and return its id."""
    if path.parent.exists():
        path.write_bytes(content)
    document_id = f"doc_{uuid.uuid4().hex[:16]}"
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                permit.Document(
                    id=document_id,
                    application_id=application_id,
                    document_type=document_type,
                    version=9,
                    file_ref=str(path),
                    content_hash=hashlib.sha256(hash_of if hash_of is not None else content).hexdigest(),
                    received_at=datetime.now(UTC),
                    uploaded_by_actor_id=None,
                    fictional_demo=True,
                    quality=[],
                )
            )
    finally:
        factory.dispose()
    return document_id


def first_application(environment: Settings) -> str:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            return session.execute(
                select(permit.Application.id).order_by(permit.Application.source_application_number)
            ).scalars().first()
    finally:
        factory.dispose()


def document_url(application_id: str, document_id: str) -> str:
    return f"/steward/applications/{application_id}/documents/{document_id}"


def test_the_workspace_offers_the_original_submission_in_a_new_tab(
    client: TestClient, environment: Settings
) -> None:
    application_id = first_application(environment)
    choose(client, "persona_permit_reviewer")
    body = client.get(f"/permits/{application_id}").text
    link = re.search(r'<a [^>]*data-testid="open-original-submission"[^>]*>', body)
    assert link is not None, "the workspace offers the original submission"
    assert f'href="/steward/applications/{application_id}"' in link.group(0)
    assert 'target="_blank"' in link.group(0) and "noopener" in link.group(0)
    assert "Open the original submission" in body
    page = client.get(f"/steward/applications/{application_id}")
    assert page.status_code == 200
    assert 'data-testid="application-documents"' in page.text


def test_a_persona_without_the_read_grant_has_no_button_and_no_page(
    client: TestClient, environment: Settings
) -> None:
    application_id = first_application(environment)
    choose(client, "persona_agent_operator")
    assert client.get(f"/steward/applications/{application_id}").status_code == 403
    assert client.get(f"/permits/{application_id}").status_code in (403, 404)


@pytest.mark.parametrize(
    ("name", "content", "media_type"),
    [
        ("v1.pdf", PDF, "application/pdf"),
        ("v1.png", PNG, "image/png"),
        ("v1.jpg", JPG, "image/jpeg"),
        ("v1.txt", TEXT, "text/plain; charset=utf-8"),
    ],
)
def test_the_reviewer_opens_each_document_in_its_native_form(
    client: TestClient,
    environment: Settings,
    store: Path,
    name: str,
    content: bytes,
    media_type: str,
) -> None:
    application_id = first_application(environment)
    document_id = add_document(environment, application_id, store / name, content)
    choose(client, "persona_permit_reviewer")
    page = client.get(f"/steward/applications/{application_id}").text
    assert f'href="{document_url(application_id, document_id)}"' in page
    assert 'data-testid="application-document-open"' in page
    response = client.get(document_url(application_id, document_id))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == media_type
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("inline;")
    assert re.fullmatch(r'inline; filename="[A-Za-z0-9._-]+"', disposition), disposition
    assert response.content == content


@pytest.mark.parametrize(
    ("name", "content"), [("v1.html", HTML), ("v1.svg", SVG), ("v1.htm", HTML)]
)
def test_html_and_svg_are_never_served(
    client: TestClient, environment: Settings, store: Path, name: str, content: bytes
) -> None:
    application_id = first_application(environment)
    document_id = add_document(environment, application_id, store / name, content)
    choose(client, "persona_permit_reviewer")
    response = client.get(document_url(application_id, document_id))
    assert response.status_code == 415
    assert "javascript" not in response.headers.get("content-type", "")
    assert not response.headers.get("content-type", "").startswith(("image/svg", "text/html")) or (
        "alert(1)" not in response.text
    )
    assert "alert(1)" not in response.text
    assert "content-disposition" not in response.headers or "inline" not in response.headers[
        "content-disposition"
    ]


def test_a_path_outside_the_document_store_is_never_read(
    client: TestClient, environment: Settings, store: Path, tmp_path: Path
) -> None:
    application_id = first_application(environment)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"not a stored document")
    absolute = add_document(environment, application_id, outside, b"not a stored document")
    # A name that climbs out of the store with "..", to a file beside it.
    sibling = store.parent.parent / f"_outside_{uuid.uuid4().hex[:8]}.txt"
    try:
        relative = add_document(
            environment,
            application_id,
            store / ".." / ".." / sibling.name,
            b"not a stored document",
        )
        assert sibling.is_file()
        choose(client, "persona_permit_reviewer")
        for document_id in (absolute, relative):
            response = client.get(document_url(application_id, document_id))
            assert response.status_code == 404, response.status_code
            assert "not a stored document" not in response.text
    finally:
        sibling.unlink(missing_ok=True)


def test_a_file_that_changed_since_it_was_stored_is_not_shown(
    client: TestClient, environment: Settings, store: Path
) -> None:
    application_id = first_application(environment)
    document_id = add_document(
        environment, application_id, store / "v1.txt", TEXT, hash_of=b"the bytes that were received"
    )
    choose(client, "persona_permit_reviewer")
    assert client.get(document_url(application_id, document_id)).status_code == 409


def test_a_document_of_another_application_is_not_found(
    client: TestClient, environment: Settings, store: Path
) -> None:
    application_id = first_application(environment)
    document_id = add_document(environment, application_id, store / "v1.txt", TEXT)
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            other = session.execute(
                select(permit.Application.id).where(permit.Application.id != application_id)
            ).scalars().first()
    finally:
        factory.dispose()
    choose(client, "persona_permit_reviewer")
    assert client.get(document_url(other, document_id)).status_code == 404
    assert client.get(document_url(application_id, "doc_missing")).status_code == 404


def test_a_persona_without_the_grant_gets_no_file(
    client: TestClient, environment: Settings, store: Path
) -> None:
    application_id = first_application(environment)
    document_id = add_document(environment, application_id, store / "v1.txt", TEXT)
    choose(client, "persona_agent_operator")
    response = client.get(document_url(application_id, document_id))
    assert response.status_code == 403
    assert "ACME CITY FICTIONAL DOCUMENT" not in response.text


def test_the_applicant_opens_only_a_document_of_an_own_application(
    client: TestClient, environment: Settings, store: Path
) -> None:
    choose(client, "persona_applicant")
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            rows = list(session.execute(select(permit.Application)).scalars())
    finally:
        factory.dispose()
    # Find one application the applicant may read and one it may not.
    own = other = None
    for row in rows:
        status = client.get(f"/steward/applications/{row.id}").status_code
        if status == 200 and own is None:
            own = row.id
        if status == 404 and other is None:
            other = row.id
    assert own is not None and other is not None
    own_doc = add_document(environment, own, store / "own.txt", TEXT)
    other_doc = add_document(environment, other, store / "other.txt", TEXT)
    assert client.get(document_url(own, own_doc)).status_code == 200
    refused = client.get(document_url(other, other_doc))
    assert refused.status_code == 404
    assert "ACME CITY FICTIONAL DOCUMENT" not in refused.text

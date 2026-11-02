"""The original submission opens from the permit workspace, in a new tab.

The Permit Reviewer presses "Open the original submission", reads the
application as it was submitted in a new tab, and opens a stored document from
that page.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, SEC-01

from __future__ import annotations

import hashlib
import shutil
import uuid
from datetime import UTC, datetime

from conftest import BrowserServer

from acme_city.documents.service import DOCUMENT_ROOT
from acme_city.fixtures.loader import REPO_ROOT
from acme_city.persistence.models import permit
from acme_city.persistence.session import SessionFactory, transaction

TEXT = b"ACME CITY FICTIONAL DOCUMENT\nSite plan: fence, front yard, 4 ft.\n"


def store_text_document(server: BrowserServer, application_id: str) -> object:
    """Store one plain text document of the application and return its folder."""
    folder = REPO_ROOT / DOCUMENT_ROOT / f"_browser_{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True)
    target = folder / "v1.txt"
    target.write_bytes(TEXT)
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                permit.Document(
                    id=f"doc_{uuid.uuid4().hex[:16]}",
                    application_id=application_id,
                    document_type="site_plan",
                    version=1,
                    file_ref=str(target),
                    content_hash=hashlib.sha256(TEXT).hexdigest(),
                    received_at=datetime.now(UTC),
                    fictional_demo=True,
                    quality=[],
                )
            )
    finally:
        factory.dispose()
    return folder


def test_the_button_opens_the_submission_and_a_document_opens(
    page, server: BrowserServer, login
) -> None:
    folder = store_text_document(server, "app_synth_001")
    try:
        check(page, server, login)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def check(page, server: BrowserServer, login) -> None:
    login("persona_permit_reviewer")
    page.goto(f"{server.base_url}/permits/app_synth_001", wait_until="load")
    button = page.locator('[data-testid="open-original-submission"]')
    assert button.count() == 1
    assert button.inner_text().strip() == "Open the original submission"
    with page.context.expect_page() as opened:
        button.click()
    submission = opened.value
    submission.wait_for_load_state("load")
    assert submission.url == f"{server.base_url}/steward/applications/app_synth_001"
    assert submission.locator('[data-testid="application-documents"]').count() == 1
    rows = submission.locator('[data-testid="application-document-row"]')
    assert rows.count() >= 1
    link = submission.locator('[data-testid="application-document-open"]').first
    assert link.get_attribute("target") == "_blank"
    with submission.context.expect_page() as document:
        link.click()
    stored = document.value
    stored.wait_for_load_state("load")
    assert "/documents/" in stored.url
    assert "Site plan: fence" in stored.locator("body").inner_text()
    assert page.recorded_errors == []

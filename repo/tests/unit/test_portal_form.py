"""The application form and the receipt of the applicant.

The form shows four fieldsets and one button that is never disabled: the
server refuses an incomplete application and says what is missing.  The
details of a document and of the matched address sit behind "More details",
and the receipt puts the reference number first.
"""
# REQUIRES: PORTAL-01, PORTAL-03, UX-01, UX-02

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402

APPLICANT = "persona_applicant"
TYPE_KEY = "deck_fence"

#: The answers of a complete fence application.
FENCE = {
    "applicant_name": "Demo Applicant",
    "applicant_email": "demo.applicant@example.invalid",
    "address_text": "400 Lantren Row",
    "structure_kind": "fence",
    "height_ft": "4",
    "fence_material": "cedar",
    "location": "side_rear",
    "setback_ft": "2",
    "property_line_ack": "on",
    "project_description": "4 ft cedar side fence",
}

FILES = {
    "file__site_plan": ("sketch.txt", b"Site sketch.\n", "text/plain"),
    "file__material_spec": ("spec.txt", b"Cedar panels.\n", "text/plain"),
}


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    """A demonstration database with the personas seeded."""
    return build_environment(
        tmp_path_factory.mktemp("portal-form"), synthetic=False, name="form.db"
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    """A client that acts as the Applicant."""
    with TestClient(create_app(settings)) as test_client:
        response = test_client.post(
            "/api/session/select", json={"actor_id": APPLICANT}
        )
        assert response.status_code == 200, response.text
        yield test_client


def token(client: TestClient, path: str = f"/apply/{TYPE_KEY}") -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def post_form(client: TestClient, fields: dict[str, str], **extra):
    uploads = extra.pop("files", None)
    data = {
        "csrf_token": token(client),
        "intent": extra.pop("intent", "update"),
        "certification_accepted": "on",
        **fields,
        **extra,
    }
    return client.post(f"/apply/{TYPE_KEY}", data=data, files=uploads, follow_redirects=False)


# ------------------------------------------------------------------ the form


def test_the_form_has_no_help_column_and_no_notice(client: TestClient) -> None:
    """The column of the assistant is gone, and so is the banner."""
    page = client.get(f"/apply/{TYPE_KEY}").text
    assert 'data-testid="form-help-column"' not in page
    assert 'data-testid="help-panel"' not in page
    assert 'data-testid="portal-notice"' not in page
    assert "ACME City never asks for permit fees" not in page


def test_the_launcher_leads_to_the_assistant_with_the_type(client: TestClient) -> None:
    """The launcher opens the assistant on the panel's own page."""
    page = client.get(f"/apply/{TYPE_KEY}").text
    launcher = re.search(
        r'<a class="btn ghost" href="([^"]+)"[^>]*data-testid="help-launcher">', page
    )
    assert launcher is not None, page[:400]
    assert f"type_key={TYPE_KEY}" in launcher.group(1)
    landing = client.get(launcher.group(1))
    assert landing.status_code == 200
    assert 'data-testid="help-panel"' in landing.text


def test_the_kicker_carries_a_stock_symbol_and_no_picture(client: TestClient) -> None:
    """The type of the application is named by a line symbol of the City."""
    page = client.get(f"/apply/{TYPE_KEY}").text
    kicker = page.split('data-testid="form-kicker"')[1].split("</div>")[0]
    assert "<img" not in kicker
    assert re.search(r'<use href="#c-[a-z]+"/>', kicker), kicker


def test_the_submit_button_is_never_disabled(client: TestClient) -> None:
    """The server refuses an incomplete application; the button stays usable."""
    page = client.get(f"/apply/{TYPE_KEY}").text
    button = re.search(
        r'<button[^>]*data-testid="submit-application"[^>]*>', page
    )
    assert button is not None
    assert "disabled" not in button.group(0)


def test_an_incomplete_application_shows_a_linked_error_list(
    client: TestClient,
) -> None:
    """Nothing is submitted, and every missing item is named and linked."""
    response = post_form(
        client, {**FENCE, "height_ft": "", "fence_material": ""}, intent="submit"
    )
    assert response.status_code == 422, response.text
    summary = response.text.split('data-testid="error-summary"')[1].split("</div>")[0]
    links = re.findall(r'<a href="#([^"]+)" data-needs-link>([^<]+)</a>', summary)
    assert links, summary
    for anchor, message in links:
        assert message.strip()
        assert f'id="{anchor}"' in response.text, anchor


def test_the_details_of_a_document_sit_behind_more_details(
    client: TestClient,
) -> None:
    """The purpose of a document is there, but only when it is asked for."""
    page = client.get(f"/apply/{TYPE_KEY}").text
    row = page.split('data-doc-type="site_plan"')[1].split("</li>")[0]
    assert 'data-testid="doc-purpose"' in row
    details = re.search(r"<details[^>]*>(.*?)</details>", row, re.S)
    assert details is not None, row
    assert "What this document shows" in details.group(1)
    assert 'data-testid="doc-purpose"' in details.group(1)


def test_the_matched_address_is_shown_and_its_score_is_not(
    client: TestClient,
) -> None:
    """The address the applicant typed is answered; the score is a detail."""
    response = post_form(client, FENCE)
    assert response.status_code == 200
    located = response.text.split('data-testid="did-you-mean"')[1].split("</div>")[0]
    assert "Did you mean" in located
    assert "Simulated city locator" not in located
    details = re.search(r"<details[^>]*>(.*?)</details>", located, re.S)
    assert details is not None, located
    assert "More details" in details.group(1)


def test_the_when_group_note_is_gone(client: TestClient) -> None:
    """The page does not explain the questions that do not apply."""
    page = client.get(f"/apply/{TYPE_KEY}").text
    assert "They are ignored otherwise" not in page
    assert "These apply only if you choose" not in page


# ------------------------------------------------------------------ the clicks


def test_choosing_a_different_project_leads_to_the_chooser(
    client: TestClient,
) -> None:
    """Click test: the link in the form's last fieldset."""
    page = client.get(f"/apply/{TYPE_KEY}").text
    link = re.search(
        r'<a class="btn" href="([^"]+)">Choose a different project</a>', page
    )
    assert link is not None
    landing = client.get(link.group(1))
    assert landing.status_code == 200
    assert "Start an application" in landing.text


def test_saving_a_draft_lands_on_the_drafts_tab(client: TestClient) -> None:
    """Click test: the Save draft button."""
    saved = post_form(client, FENCE, intent="save")
    assert saved.status_code == 303, saved.text
    assert "/apply/track?tab=drafts&saved=" in saved.headers["location"]
    landing = client.get(saved.headers["location"])
    assert landing.status_code == 200
    assert 'data-tab="drafts"' in landing.text


def test_removing_a_file_leaves_the_other_one(client: TestClient) -> None:
    """Click test: the Remove button of a document row."""
    first = post_form(client, FENCE, files=FILES)
    assert first.status_code == 200
    reference = re.search(r'name="draft" value="([^"]+)"', first.text).group(1)
    assert first.text.count('data-testid="doc-remove"') == 2
    removed = post_form(
        client,
        FENCE,
        draft=reference,
        remove_doc="site_plan",
    )
    assert removed.status_code == 200
    assert 'data-doc-type="site_plan" data-added="false"' in removed.text
    assert 'data-doc-type="material_spec" data-added="true"' in removed.text


def test_a_file_is_added_and_replaced_through_the_document_input(
    client: TestClient,
) -> None:
    """The Add file and Replace file labels point at a real file input."""
    page = client.get(f"/apply/{TYPE_KEY}").text
    assert 'id="file-site_plan" type="file" name="file__site_plan"' in page
    assert "Add file" in page
    first = post_form(client, FENCE, files=FILES)
    assert first.status_code == 200
    assert first.text.count('data-testid="doc-filename"') == 2
    # the label of an added file offers the replacement
    assert first.text.count("Replace file") == 2
    reference = re.search(r'name="draft" value="([^"]+)"', first.text).group(1)
    again = post_form(
        client,
        FENCE,
        draft=reference,
        files={"file__site_plan": ("sketch2.txt", b"Second sketch.\n", "text/plain")},
    )
    assert again.status_code == 200
    assert "sketch2.txt" in again.text


# ------------------------------------------------------------------ the receipt


def test_the_receipt_puts_the_reference_first(client: TestClient) -> None:
    """The reference number is the first thing the applicant reads."""
    done = post_form(client, FENCE, intent="submit", files=FILES)
    assert done.status_code == 303, done.text
    reference = done.headers["location"].rsplit("/", 1)[1]
    page = client.get(f"/apply/submitted/{reference}").text
    assert f'data-testid="submitted-reference">{reference}<' in page
    assert page.index("submitted-reference") < page.index("receipt-next")
    assert page.index("submitted-reference") < page.index("receipt-actions")


def test_the_receipt_has_no_help_button_and_no_status_prefix(
    client: TestClient,
) -> None:
    """The receipt is one column of facts."""
    done = post_form(client, FENCE, intent="submit", files=FILES)
    reference = done.headers["location"].rsplit("/", 1)[1]
    page = client.get(f"/apply/submitted/{reference}").text
    assert 'data-testid="ui-help"' not in page
    assert "Status: " not in page
    assert 'data-testid="portal-notice"' not in page
    assert 'data-testid="submitted-status"' in page


def test_the_copy_note_is_one_line(client: TestClient) -> None:
    """The copy says in one line what it is."""
    done = post_form(client, FENCE, intent="submit", files=FILES)
    reference = done.headers["location"].rsplit("/", 1)[1]
    page = client.get(f"/apply/submitted/{reference}").text
    note = page.split('data-testid="copy-note"')[1].split("</span>")[0].lstrip(">")
    assert " ".join(note.split()) == "Copy of your submission. It is not a permit."
    copy = client.get(f"/apply/submitted/{reference}/copy").text
    assert "Copy of your submission. It is not a permit." in copy

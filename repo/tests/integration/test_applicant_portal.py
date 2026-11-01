"""The applicant portal: chooser, per-type form, drafts, uploads, submit, track."""
# REQUIRES: PORTAL-01, PORTAL-02, PORTAL-03, PORTAL-04

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.applicant_portal import forms
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import audit, gis, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def environment(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("acme_city.applicant_portal.service.DOCUMENT_ROOT", tmp_path / "documents")
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'portal.db'}",
            "ACME_SECRET_KEY": "portal-test-secret-value",
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
def client(environment) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def token(client: TestClient, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


FENCE_FIELDS = {
    "applicant_name": "Demo Applicant",
    "applicant_email": "demo.applicant@example.invalid",
    "applicant_phone": "555-0100",
    "address_text": "400 Lantren Row",
    "height_ft": "4",
    "fence_material": "cedar",
    "location": "side_rear",
    "setback_ft": "2",
    "property_line_ack": "on",
    "project_description": "4 ft cedar side fence",
}


def post_form(client, type_key, fields, files=None, intent="update", draft="", certification_accepted=True):
    data = {
        "csrf_token": token(client, f"/apply/{type_key}"),
        "intent": intent,
        "draft": draft,
        **fields,
    }
    if certification_accepted:
        data["certification_accepted"] = "on"
    return client.post(
        f"/apply/{type_key}", data=data, files=files or None, follow_redirects=False
    )


def fence_files():
    return {
        "file__site_plan": ("sketch.txt", b"Site sketch of the fence line.\n", "text/plain"),
        "file__material_spec": ("spec.txt", b"Cedar panels.\n", "text/plain"),
    }


def test_chooser_groups_seventeen_types_without_process_badges(client) -> None:
    # Changed deliberately (applicant UI restyle): the groups are Home and property, Business and
    # construction, Planning and land use; the repeated process badges and their legend moved off the cards.
    choose(client, "persona_applicant")
    page = client.get("/apply").text
    assert page.count('data-testid="type-card"') == 17
    for pill in ("Permit portal", "Portal + plans", "Plan review process", "process-pill"):
        assert pill not in page
    for group in ("Home and property", "Business and construction", "Planning and land use"):
        assert group in page
    assert 'data-testid="track-link"' in page
    assert "The City of Acme never asks for permit fees by gift card or wire transfer." in page


def test_every_type_has_a_form_with_its_documents(client) -> None:
    choose(client, "persona_applicant")
    for _group, _label, keys in forms.GROUPS:
        for key in keys:
            page = client.get(f"/apply/{key}")
            assert page.status_code == 200, key
            assert 'data-testid="completeness-banner"' in page.text
            assert 'data-testid="document-checklist"' in page.text
    assert client.get("/apply/not_a_type").status_code == 404


def test_banner_lists_what_is_missing_then_ready(client) -> None:
    choose(client, "persona_applicant")
    # Changed deliberately: applicant Submit is never disabled and the form no longer opens with a
    # "Still needed" banner. The same facts are shown as an error summary on a refused Submit.
    first = post_form(
        client, "deck_fence", {**FENCE_FIELDS, "fence_material": ""}, certification_accepted=False, intent="submit"
    )
    assert first.status_code == 422
    assert 'data-testid="error-summary"' in first.text and "There is a problem" in first.text
    assert "fence material" in first.text.lower()
    assert "site sketch or site plan" in first.text.lower() and "material specification" in first.text.lower()
    assert "disabled" not in re.search(r'<button[^>]*data-testid="submit-application"[^>]*>', first.text).group(0)
    ready = post_form(client, "deck_fence", FENCE_FIELDS, files=fence_files())
    assert "Ready to submit. All required fields and documents are provided." in ready.text


def test_submit_creates_an_application_awaiting_intake(client, environment) -> None:
    choose(client, "persona_applicant")
    response = post_form(client, "deck_fence", FENCE_FIELDS, files=fence_files(), intent="submit")
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert location.startswith("/apply/submitted/")
    page = client.get(location).text
    assert "Application received" in page  # restyled receipt (was "Application submitted")
    reference = re.search(r'data-testid="submitted-reference">([^<]+)<', page).group(1)
    assert "Awaiting intake agent" in page
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == reference
                )
            ).scalar_one()
            assert application.status == "submitted"
            assert application.applicant_party_id == "party_applicant_1"
            assert application.submitted_facts["parcel_number"] == "ACME-P-1001"
            assert application.submitted_facts["structure_kind"] == "fence"
            documents = session.execute(
                select(permit.Document).where(permit.Document.application_id == application.id)
            ).scalars().all()
            assert {d.document_type for d in documents} == {"site_plan", "material_spec"}
            assert all(Path(d.file_ref).is_file() for d in documents)
            actions = [a.action for a in session.execute(select(audit.AuditEvent)).scalars()]
            assert "portal.application.submit" in actions
    finally:
        factory.dispose()
    tracked = client.get("/apply/track", params={"ref": reference}).text
    assert "Messages from the City" in tracked and "Awaiting intake agent" in tracked


def test_submit_is_refused_server_side_when_incomplete_or_without_certification(client) -> None:
    choose(client, "persona_applicant")
    incomplete = post_form(client, "deck_fence", FENCE_FIELDS, intent="submit")
    assert incomplete.status_code == 422
    # Changed deliberately: the refusal is shown as an error summary, not a "Still needed" banner.
    assert "There is a problem" in incomplete.text
    no_certification = post_form(
        client, "deck_fence", FENCE_FIELDS, files=fence_files(), intent="submit", certification_accepted=False
    )
    assert no_certification.status_code == 422
    assert "certification" in no_certification.text


def test_save_and_exit_keeps_a_draft_and_it_resumes(client, environment) -> None:
    choose(client, "persona_applicant")
    saved = post_form(client, "deck_fence", FENCE_FIELDS, files=fence_files(), intent="save")
    assert saved.status_code == 303 and "saved=" in saved.headers["location"]
    reference = saved.headers["location"].split("saved=")[1]
    assert f"Your draft {reference} was saved" in client.get(saved.headers["location"]).text
    assert "was saved" not in client.get("/apply").text
    resumed = client.get(f"/apply/deck_fence?draft={reference}").text
    assert "cedar" in resumed and "Added" in resumed
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            assert session.execute(select(permit.Application)).scalars().all() is not None
            draft = session.execute(select(gis.ApplicationDraft)).scalar_one()
            assert draft.status == "open" and draft.application_id is None
    finally:
        factory.dispose()


def test_uploads_are_limited_by_type_and_size(client) -> None:
    choose(client, "persona_applicant")
    bad_type = post_form(
        client,
        "deck_fence",
        FENCE_FIELDS,
        files={"file__site_plan": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert bad_type.status_code == 422 and "not accepted" in bad_type.text
    too_big = post_form(
        client,
        "deck_fence",
        FENCE_FIELDS,
        files={"file__site_plan": ("big.txt", b"a" * (5 * 1024 * 1024 + 1), "text/plain")},
    )
    assert too_big.status_code == 422 and "5 MB" in too_big.text
    fake_pdf = post_form(
        client, "deck_fence", FENCE_FIELDS, files={"file__site_plan": ("x.pdf", b"not a pdf", "application/pdf")}
    )
    assert fake_pdf.status_code == 422


def test_csrf_and_persona_are_enforced(client) -> None:
    choose(client, "persona_applicant")
    refused = client.post(
        "/apply/deck_fence", data={"csrf_token": "forged", "intent": "submit"}, follow_redirects=False
    )
    assert refused.status_code == 403
    choose(client, "persona_data_steward")
    assert client.get("/apply").status_code == 403


def test_check_endpoint_mirrors_the_server_answer(client) -> None:
    choose(client, "persona_applicant")
    response = client.post("/apply/deck_fence/check", data={"applicant_name": "T"})
    assert response.status_code == 200
    body = response.json()
    assert body["complete"] is False and "Fence height (ft)" in body["missing"]
    located = client.get("/apply/locate", params={"text": "412 Mapel Rdg Dr"}).json()
    assert located["found"] and located["parcel_number"] == "ACME-P-1004"
    assert "Did you mean 412 Maple Ridge Drive" in located["message"]
    assert client.get("/apply/suggest", params={"text": "412 Map"}).json()["suggestions"]


def test_tracking_is_scoped_and_revisions_can_be_submitted(client, environment) -> None:
    choose(client, "persona_applicant")
    response = post_form(client, "deck_fence", FENCE_FIELDS, files=fence_files(), intent="submit")
    reference = response.headers["location"].rsplit("/", 1)[1]
    assert client.get("/apply/track", params={"ref": "ACME-NOPE"}).text.count("No application with that reference") == 1
    # Not asked for yet: refused.
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == reference
                )
            ).scalar_one()
            application_id = application.id
    finally:
        factory.dispose()
    refused = client.post(
        f"/apply/track/{application_id}/revise",
        data={"csrf_token": token(client, "/apply/deck_fence"), "reference": reference},
        files={"file__site_plan": ("rev.txt", b"revised sketch", "text/plain")},
        follow_redirects=False,
    )
    assert refused.status_code == 422
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            session.get(permit.Application, application_id).status = "needs_information"
    finally:
        factory.dispose()
    page = client.get("/apply/track", params={"ref": reference}).text
    assert "Submit revised documents" in page
    ok = client.post(
        f"/apply/track/{application_id}/revise",
        data={"csrf_token": token(client, "/apply/deck_fence"), "reference": reference},
        files={"file__site_plan": ("rev.txt", b"revised sketch", "text/plain")},
        follow_redirects=False,
    )
    assert ok.status_code == 303, ok.text
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            versions = session.execute(
                select(permit.Document).where(
                    permit.Document.application_id == application_id,
                    permit.Document.document_type == "site_plan",
                )
            ).scalars().all()
            assert sorted(v.version for v in versions) == [1, 2]
    finally:
        factory.dispose()



@pytest.mark.parametrize(
    "filename", ["fake.pdf", "fake.png", "fake.jpg"], ids=["pdf", "png", "jpg"]
)
def test_a_revised_file_is_checked_by_its_content_like_a_first_upload(
    client, environment, filename: str
) -> None:
    choose(client, "persona_applicant")
    response = post_form(client, "deck_fence", FENCE_FIELDS, files=fence_files(), intent="submit")
    reference = response.headers["location"].rsplit("/", 1)[1]
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == reference
                )
            ).scalar_one()
            application.status = "needs_information"
            application_id = application.id
    finally:
        factory.dispose()
    refused = client.post(
        f"/apply/track/{application_id}/revise",
        data={"csrf_token": token(client, "/apply/deck_fence"), "reference": reference},
        files={"file__site_plan": (filename, b"this is plain text", "application/octet-stream")},
        follow_redirects=False,
    )
    assert refused.status_code == 422
    assert "does not match its file type" in refused.text
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            versions = session.execute(
                select(permit.Document).where(
                    permit.Document.application_id == application_id,
                    permit.Document.document_type == "site_plan",
                )
            ).scalars().all()
            assert [v.version for v in versions] == [1]
    finally:
        factory.dispose()

def test_portal_case_flows_through_intake_and_applicant_sees_only_own_parcel(client) -> None:
    choose(client, "persona_applicant")
    response = post_form(client, "deck_fence", FENCE_FIELDS, files=fence_files(), intent="submit")
    reference = response.headers["location"].rsplit("/", 1)[1]
    # Changed deliberately: the applicant's in-app /queue landing (with its "Start a new
    # application" button) was redundant with the City website, so it now redirects there.
    landing = client.get("/queue", follow_redirects=False)
    assert landing.status_code == 303 and landing.headers["location"] == "/city/"
    choose(client, "persona_agent_operator")
    token_value = token(client, "/agent/intake")
    toggled = client.post(
        "/ui/actions/agent.toggle",
        data={"csrf_token": token_value, "agent_key": "intake", "mode": "awake", "next": "/agent/intake"},
        follow_redirects=False,
    )
    assert toggled.status_code == 303
    ran = client.post(
        "/ui/actions/agent.run.intake",
        data={"csrf_token": token(client, "/agent/intake"), "next": "/agent/intake"},
        follow_redirects=False,
    )
    assert ran.status_code == 303
    choose(client, "persona_applicant")
    tracked = client.get("/apply/track", params={"ref": reference}).text
    assert "tracked-application" in tracked
    link = re.search(r'data-testid="open-case"', tracked) and re.search(
        r'href="(/permits/[^"]+)" data-testid="open-case"', tracked
    )
    assert link, "the applicant can open the new case"
    workspace = client.get(link.group(1)).text
    assert 'data-testid="property-card"' in workspace
    assert "ACME-P-1001" in workspace
    assert 'data-testid="property-map-link"' not in workspace
    assert client.get("/map").status_code == 403


def test_the_applicant_answers_a_revision_request_and_the_case_returns_to_intake(
    client, environment
) -> None:
    """A resubmission versions the case and sends it back to the intake agent."""
    choose(client, "persona_applicant")
    response = post_form(client, "deck_fence", FENCE_FIELDS, files=fence_files(), intent="submit")
    reference = response.headers["location"].rsplit("/", 1)[1]
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == reference
                )
            ).scalar_one()
            application_id = application.id
            application.status = "revisions_requested"
            version = application.version
    finally:
        factory.dispose()
    page = client.get("/apply/track", params={"ref": reference}).text
    assert "Submit revised documents" in page
    assert 'data-testid="resubmit-form"' in page
    ok = client.post(
        f"/apply/track/{application_id}/resubmit",
        data={
            "csrf_token": token(client, "/apply/deck_fence"),
            "reference": reference,
            "expected_version": str(version),
        },
        files={"file__site_plan": ("rev.txt", b"revised sketch", "text/plain")},
        follow_redirects=False,
    )
    assert ok.status_code == 303, ok.text
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = session.get(permit.Application, application_id)
            # The case returns to intake, the first submission date is kept
            # and the revision is advanced.
            assert application.status == "submitted"
            assert application.revision == 2
            assert application.version == version + 1
            versions = session.execute(
                select(permit.Document).where(
                    permit.Document.application_id == application_id,
                    permit.Document.document_type == "site_plan",
                )
            ).scalars().all()
            assert sorted(row.version for row in versions) == [1, 2]
    finally:
        factory.dispose()


def test_a_resubmission_needs_the_expected_version(client, environment) -> None:
    choose(client, "persona_applicant")
    response = post_form(client, "deck_fence", FENCE_FIELDS, files=fence_files(), intent="submit")
    reference = response.headers["location"].rsplit("/", 1)[1]
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            application = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == reference
                )
            ).scalar_one()
            application_id = application.id
            application.status = "revisions_requested"
    finally:
        factory.dispose()
    refused = client.post(
        f"/apply/track/{application_id}/resubmit",
        data={"csrf_token": token(client, "/apply/deck_fence"), "reference": reference},
        files={"file__site_plan": ("rev.txt", b"revised sketch", "text/plain")},
        follow_redirects=False,
    )
    assert refused.status_code == 422, refused.text


# ---------------------------------------------------------------- guarded Submit

def _star_labels(page: str) -> list[str]:
    """Return the text of every label that carries the required star."""
    labels = re.findall(r"<label[^>]*>(.*?)</label>", page, flags=re.S)
    return [re.sub(r"<[^>]+>", "", label).replace("*", "").strip() for label in labels if 'data-testid="required-star"' in label]


def _label_html(page: str, text: str) -> str:
    for label in re.findall(r"<label[^>]*>.*?</label>", page, flags=re.S):
        if text in re.sub(r"<[^>]+>", "", label):
            return label
    raise AssertionError(f"no label {text!r}")


def test_required_fields_carry_a_star_and_optional_ones_do_not(client) -> None:
    choose(client, "persona_applicant")
    page = client.get("/apply/deck_fence").text
    assert 'data-testid="required-legend"' in page and "Required" in page
    for field in forms.form_for("deck_fence", label="x", description="", process_category="simple",
                                required_fields=[], required_documents=[], discretionary=False).fields:
        label = _label_html(page, field.label)
        assert ('data-testid="required-star"' in label) is field.required, field.key
    for text in ("Applicant name", "Email", "Property address"):
        assert 'data-testid="required-star"' in _label_html(page, text)
    assert 'data-testid="required-star"' not in _label_html(page, "Phone")
    assert 'aria-required="true"' in page and 'aria-hidden="true">*' in page
    # documents and the certification are marked too
    doc_labels = re.findall(r'<span class="doc-label">(.*?)</span>\s*</span>|<span class="doc-label">(.*?)</span>', page, flags=re.S)
    assert doc_labels and all("required-star" in "".join(pair) for pair in doc_labels)
    assert 'data-testid="certify" aria-required="true"' in page
    cert = re.search(r'<label><input type="checkbox" name="certification_accepted".*?</label>', page, flags=re.S).group(0)
    assert "required-star" in cert


def test_a_second_type_stars_only_what_its_spec_requires(client) -> None:
    choose(client, "persona_applicant")
    key = "hvac"
    spec = forms.form_for(key, label="x", description="", process_category="simple",
                          required_fields=[], required_documents=[], discretionary=False)
    page = client.get(f"/apply/{key}")
    assert page.status_code == 200
    assert 'data-testid="required-star"' not in _label_html(page.text, "Phone")
    for field in spec.fields:
        label = _label_html(page.text, field.label)
        assert ('data-testid="required-star"' in label) is field.required, field.key


def test_the_form_opens_neutral_and_submit_is_never_disabled(client) -> None:
    choose(client, "persona_applicant")
    page = client.get("/apply/deck_fence").text
    assert 'data-testid="error-summary"' not in page and "There is a problem" not in page
    assert "Still needed:" not in page and 'data-testid="field-error"' not in page
    assert "Update checklist" not in page and "server checks again" not in page
    assert "Save draft" in page and "Save and exit" not in page
    button = re.search(r'<button[^>]*data-testid="submit-application"[^>]*>', page).group(0)
    assert "disabled" not in button
    assert 'data-testid="optional-tag"' in _label_html(page, "Phone")
    assert 'data-testid="optional-tag"' not in _label_html(page, "Applicant name")
    assert "item" in re.search(r'data-status>(.*?)</p>', page, flags=re.S).group(1)


def test_an_incomplete_submit_re_renders_with_a_summary_field_errors_and_kept_entries(client, environment) -> None:
    choose(client, "persona_applicant")
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            before = len(session.execute(select(permit.Application)).scalars().all())
    finally:
        factory.dispose()
    response = post_form(
        client,
        "deck_fence",
        {**FENCE_FIELDS, "height_ft": "", **_declare("material_spec")},
        files={"file__site_plan": ("sketch.txt", b"Site sketch.\n", "text/plain")},
        certification_accepted=False,
        intent="submit",
    )
    assert response.status_code == 422
    page = response.text
    summary = page[page.index('data-testid="error-summary"'):]
    summary = summary[:summary.index("</div>")]
    assert "Enter the fence height" in summary and 'href="#f-height_ft"' in summary
    assert "Check the certification" in summary and 'href="#f-certification_accepted"' in summary
    assert "site plan" not in summary.lower()  # uploaded this time, so not missing
    # a message beside each affected field and an accessible link from the control
    assert re.search(r'id="err-f-height_ft"[^>]*>.*?Enter the fence height', page, flags=re.S)
    assert 'aria-invalid="true" aria-describedby="err-f-height_ft"' in page
    assert re.search(r'id="err-f-certification_accepted"[^>]*>.*?Check the certification', page, flags=re.S)
    # what was entered is preserved: values, the stored upload and the sent-separately tick
    assert 'value="Demo Applicant"' in page and 'value="cedar"' in page
    assert re.search(r'name="sent_separately__material_spec"[^>]*checked', page)
    assert "sketch.txt" in page and 'data-doc-type="site_plan" data-added="true"' in page
    assert "Nothing has been submitted" in page
    # nothing was submitted
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            assert len(session.execute(select(permit.Application)).scalars().all()) == before
            draft = session.execute(select(gis.ApplicationDraft)).scalars().one()
            assert draft.status == "open"
    finally:
        factory.dispose()


def test_a_missing_document_message_offers_the_separate_route(client) -> None:
    choose(client, "persona_applicant")
    page = post_form(client, "deck_fence", FENCE_FIELDS, intent="submit").text
    assert "Add the site sketch or site plan or tick" in page and "Sent to the City separately" in page
    assert 'href="#file-site_plan"' in page and 'id="file-site_plan"' in page


def test_the_certification_is_the_only_blocker_and_nothing_claims_ready(client) -> None:
    choose(client, "persona_applicant")
    page = post_form(
        client, "deck_fence", FENCE_FIELDS, files=fence_files(), certification_accepted=False, intent="submit"
    ).text
    assert "Ready to submit" not in page
    summary = page[page.index('data-testid="error-summary"'):]
    summary = summary[:summary.index("</div>")]
    assert summary.count("<li") == 1 and "Check the certification" in summary
    # the JS needs the same facts from /check
    check = client.post(
        "/apply/deck_fence/check",
        data={**FENCE_FIELDS, "have__site_plan": "1", "have__material_spec": "1"},
    ).json()
    assert check["complete"] is True and check["can_submit"] is False
    assert "Ready to submit" not in check["banner"] and "Ready to submit" not in check["status"]
    assert [item["anchor"] for item in check["blocking"]] == ["f-certification_accepted"]
    assert check["status"] == "1 item still needed." and check["missing"] == [] and check["items"] == []
    ok = client.post(
        "/apply/deck_fence/check",
        data={**FENCE_FIELDS, "have__site_plan": "1", "have__material_spec": "1", "certification_accepted": "on"},
    ).json()
    assert ok["can_submit"] is True and ok["blocking"] == [] and ok["status"].startswith("Ready to submit")


def test_check_json_carries_anchors_for_the_missing_items(client) -> None:
    choose(client, "persona_applicant")
    body = client.post("/apply/deck_fence/check", data={"applicant_name": "T"}).json()
    anchors = {item["anchor"] for item in body["items"]}
    assert {"f-applicant_email", "f-height_ft", "file-site_plan"} <= anchors
    assert [i["label"] for i in body["items"]] == body["missing"]
    assert body["blocking"][-1]["anchor"] == "f-certification_accepted"
    assert all(item["message"] for item in body["blocking"])


# ------------------------------------------------------------- sent separately

def _declare(*types: str) -> dict:
    return {f"sent_separately__{t}": "on" for t in types}


def test_a_declared_document_satisfies_completeness_without_a_file(client) -> None:
    choose(client, "persona_applicant")
    page = post_form(
        client, "deck_fence", {**FENCE_FIELDS, **_declare("site_plan", "material_spec")}
    ).text
    assert "Ready to submit" in page
    assert page.count("Sent separately") >= 2
    assert "Sent to the City separately" in page
    check = client.post(
        "/apply/deck_fence/check",
        data={**FENCE_FIELDS, **_declare("site_plan", "material_spec"), "certification_accepted": "on"},
    ).json()
    assert check["can_submit"] is True and check["sent_separately"] == ["material_spec", "site_plan"]


def test_an_undeclared_missing_document_still_blocks(client) -> None:
    choose(client, "persona_applicant")
    response = post_form(
        client, "deck_fence", {**FENCE_FIELDS, **_declare("site_plan")}, intent="submit"
    )
    assert response.status_code == 422
    summary = response.text[response.text.index('data-testid="error-summary"'):]
    summary = summary[:summary.index("</div>")]
    assert "material specification" in summary.lower() and "site sketch" not in summary.lower()


def test_the_declaration_survives_a_draft_save_and_is_recorded_on_submit(client, environment) -> None:
    choose(client, "persona_applicant")
    saved = post_form(client, "deck_fence", {**FENCE_FIELDS, **_declare("site_plan", "material_spec")}, intent="save")
    assert saved.status_code == 303
    reference = saved.headers["location"].split("saved=")[1]
    reopened = client.get(f"/apply/deck_fence?draft={reference}").text
    assert reopened.count("data-sent-separately") >= 2 and reopened.count("data-sent-separately checked") == 2
    done = post_form(
        client, "deck_fence", {**FENCE_FIELDS, **_declare("site_plan", "material_spec")},
        intent="submit", draft=reference,
    )
    assert done.status_code == 303, done.text
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            application = session.execute(select(permit.Application)).scalars().all()[-1]
            assert sorted(application.submitted_facts["documents_sent_separately"]) == ["material_spec", "site_plan"]
            # nothing claims a file arrived
            docs = session.execute(
                select(permit.Document).where(permit.Document.application_id == application.id)
            ).scalars().all()
            assert docs == []
            rows = session.execute(select(audit.AuditEvent)).scalars().all()
            assert not [r for r in rows if "site_plan" in (r.reason or "") and "upload" in r.action]
    finally:
        factory.dispose()
    tracked = client.get(done.headers["location"].replace("/apply/submitted/", "/apply/track?ref=")).text
    assert tracked.count('data-testid="declared-separately"') == 2
    assert "Declared sent separately" in tracked and "not yet received" in tracked
    assert "site_plan</th>" not in tracked


def test_a_real_file_wins_over_a_declaration(client) -> None:
    choose(client, "persona_applicant")
    done = post_form(
        client, "deck_fence", {**FENCE_FIELDS, **_declare("site_plan", "material_spec")},
        files=fence_files(), intent="submit",
    )
    assert done.status_code == 303
    tracked = client.get(done.headers["location"].replace("/apply/submitted/", "/apply/track?ref=")).text
    assert 'data-testid="declared-separately"' not in tracked
    assert len(re.findall(r":\s*received", tracked)) == 2

"""The applicant-side restyle: chrome, city entry, chooser, form, receipt and My permits."""
# REQUIRES: PORTAL-01, PORTAL-02, PORTAL-03, PORTAL-04, UX-01, PER-04, SEC-03

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.applicant_portal import content, permits_view
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import gis, permit, registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

APPLICANT = "persona_applicant"
APPLICANT_NAME = "Demo Applicant"  # the seeded applicant party, party_applicant_1
INTERNAL_NOTE = "ZZ-INTERNAL-NOTE-OVERPAID-FEE-WAIVER"
INTERNAL_FINDING = "ZZ-INTERNAL-FINDING-DUPLICATE-OF-OTHER-CASE"
VISIBLE_NOTE = "Please send a clearer site sketch showing the fence line."
MUST_LINE = "Upload a revised site sketch that shows the fence line."


@pytest.fixture()
def environment(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("acme_city.applicant_portal.service.DOCUMENT_ROOT", tmp_path / "documents")
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'ui.db'}",
            "ACME_SECRET_KEY": "ui-applicant-test-secret",
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


def choose(client: TestClient, actor_id: str = APPLICANT) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def token(client: TestClient, path: str = "/apply/deck_fence") -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


FENCE = {
    "applicant_name": APPLICANT_NAME,
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
DECK = {
    "applicant_name": APPLICANT_NAME,
    "applicant_email": "demo.applicant@example.invalid",
    "address_text": "400 Lantren Row",
    "structure_kind": "deck",
    "deck_height_ft": "3",
    "deck_setback_ft": "10",
    "project_description": "Rear deck, 3 ft high",
}


def files():
    return {
        "file__site_plan": ("sketch.txt", b"Site sketch.\n", "text/plain"),
        "file__material_spec": ("spec.txt", b"Cedar panels.\n", "text/plain"),
    }


def post(client, fields, *, intent="update", draft="", upload=None, certify=True, extra=None):
    data = {"csrf_token": token(client), "intent": intent, "draft": draft, **fields, **(extra or {})}
    if certify:
        data["certification_accepted"] = "on"
    return client.post("/apply/deck_fence", data=data, files=upload or None, follow_redirects=False)


def submit_fence(client) -> str:
    done = post(client, FENCE, intent="submit", upload=files())
    assert done.status_code == 303, done.text
    return done.headers["location"].rsplit("/", 1)[1]


def with_session(settings, fn):
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            return fn(session)
    finally:
        factory.dispose()


def isolate(settings):
    """Remove the seeded applications from the applicant's scope (the demo seeds three)."""

    def run(session):
        for row in session.execute(select(permit.Application)).scalars():
            if row.applicant_party_id == "party_applicant_1":
                row.applicant_party_id = "party_applicant_2"
            if row.source_application_number == "SYN-APP-005":
                row.source_application_number = "SYN-APP-005-MOVED"
        session.flush()

    with_session(settings, run)


def card_of(page, reference):
    """Return the markup of the card of one application."""
    return page.split(f'data-reference="{reference}"')[1].split("</article>")[0]


def set_status(settings, reference, status):
    def run(session):
        row = session.execute(
            select(permit.Application).where(permit.Application.source_application_number == reference)
        ).scalar_one()
        row.status = status
        session.flush()
        return row.id

    return with_session(settings, run)


def plant_request(settings, reference):
    """An internal comment, an applicant comment and a finding with an internal message."""

    def run(session):
        row = session.execute(
            select(permit.Application).where(permit.Application.source_application_number == reference)
        ).scalar_one()
        for index, (visibility, body) in enumerate(
            (("internal", INTERNAL_NOTE), ("applicant", VISIBLE_NOTE))
        ):
            session.add(
                permit.ApplicationComment(
                    id=f"comment_ui_{index}", correlation_id="corr_ui", application_id=row.id,
                    body=body, visibility=visibility, author_actor_id="persona_permit_reviewer",
                )
            )
        session.add(
            permit.ApplicationFinding(
                id="finding_ui_1", correlation_id="corr_ui", application_id=row.id,
                finding_type="missing_document", message=INTERNAL_FINDING, severity="block",
                applicant_must=MUST_LINE, state="current",
            )
        )
        session.flush()

    with_session(settings, run)


# ------------------------------------------------------------------ chrome


def test_portal_chrome_header_nav_account_and_footer(client) -> None:
    choose(client)
    for path, active in (("/apply/track", "My permits"), ("/apply", "Start an application")):
        page = client.get(path).text
        assert "City of Acme" in page and 'data-testid="city-service-name">Permit Services<' in page
        nav = page.split('data-testid="applicant-nav"')[1].split("</ul>")[0]
        assert re.findall(r">(My permits|Start an application|Help)</a>", nav) == ["My permits", "Start an application", "Help"]
        assert re.search(rf'aria-current="page">{active}</a>', nav)
        assert nav.count('aria-current="page"') == 1
        assert f'data-testid="applicant-name">{APPLICANT_NAME}<' in page
        assert 'data-testid="sign-out"' in page and 'action="/ui/end"' in page
        # The City frame carries no disclosure strip (city frame, S2): the
        # demonstration is one sentence in the footer.
        assert 'data-testid="city-demo-banner"' not in page
        assert content.content()["footer_note"] in page
        # the extra "Fictional demonstration" text under the logo is gone
        assert "<small>Fictional demonstration</small>" not in page
        footer = page.split('data-testid="city-footer-links"')[1].split("</p>")[0]
        for label in ("City of Acme", "Accessibility", "Privacy", "Help"):
            assert label in footer
        assert 'href="/city/contact"' in footer
        assert "Demo controls" in page and 'data-testid="demo-switch"' in page
    help_page = client.get("/apply/help/panel").text
    assert re.search(r'aria-current="page">Help</a>', help_page.split("applicant-nav")[1])


def test_footer_pages_exist_and_the_city_site_keeps_its_own_nav(client) -> None:
    for slug in ("accessibility", "privacy"):
        assert client.get(f"/city/{slug}").status_code == 200
    choose(client)
    page = client.get("/city/").text
    assert 'data-testid="applicant-nav"' not in page and 'data-testid="nav-permits"' in page
    assert f'data-testid="applicant-name">{APPLICANT_NAME}<' in page  # the account shows on the City site too


def test_the_header_shows_the_generic_applicant_name(client, environment) -> None:
    """The seeded applicant is the generic "Demo Applicant", and the header says so."""
    choose(client)
    page = client.get("/apply/track").text
    assert 'data-testid="applicant-name">Demo Applicant<' in page

    def read(session):
        party = session.get(registry.Party, "party_applicant_1")
        assert party is not None
        return party.display_name

    assert with_session(environment, read) == "Demo Applicant"


# --------------------------------------------------------------- U1 and U2


def test_city_home_keeps_the_permit_action_and_the_community_link(client) -> None:
    page = client.get("/city/").text
    assert 'data-testid="hero-permits"' in page and 'href="/city/permits"' in page
    assert 'data-testid="tile-community"' in page and 'href="/city/community"' in page
    assert page.index('class="city-hero"') < page.index("city-tiles")
    # The news column is gone (city frame, S2).
    assert "News and notices" not in page


def test_permits_entry_has_two_actions_what_youll_need_and_a_help_link(client) -> None:
    page = client.get("/city/permits").text
    assert "<h1>Permits and applications</h1>" in page
    assert "Continue as applicant" not in page and "permits-continue" not in page
    start = page.split('data-testid="permits-start-form"')[1].split("</form>")[0]
    track = page.split('data-testid="permits-track-form"')[1].split("</form>")[0]
    assert 'name="actor_id" value="persona_applicant"' in start and 'name="next" value="/apply"' in start
    assert 'name="next" value="/apply/track"' in track
    assert "Start an application" in start and "Track or resume an application" in track
    need = page.split('data-testid="permits-need"')[1].split("</section>")[0]
    assert need.count('data-testid="need-item"') == 4
    for text in ("Contact details", "The property", "A project description", "The documents asked for"):
        assert text in need
    assert 'data-testid="permits-help-link"' in page and 'href="/city/contact"' in page
    assert 'data-testid="permits-community-link"' in page and 'href="/city/community"' in page


def test_the_switch_behind_the_buttons_lands_on_my_permits(client) -> None:
    done = client.post(
        "/ui/actor", data={"actor_id": APPLICANT, "next": "/apply/track"}, follow_redirects=False
    )
    assert done.status_code == 303 and done.headers["location"] == "/apply/track"
    assert client.get("/apply/track").status_code == 200


# --------------------------------------------------------------------- U3


def test_chooser_groups_compact_cards_and_expandable_rest(client) -> None:
    choose(client)
    page = client.get("/apply").text
    assert "<h1>What are you trying to do?</h1>" in page
    assert page.index("What are you trying to do?") < page.index('data-testid="track-link"') < page.index("Home and property")
    groups = re.findall(r'data-group="([^"]+)"', page)
    assert groups == ["home_property", "business_construction", "planning_land_use"]
    first = page.split('data-testid="type-card"')[1]
    assert 'data-type-key="deck_fence"' in first.split(">")[0] + ">"
    assert "A residential deck or fence" in first.split("</a>")[0]
    assert "reviewed at the counter" not in page
    assert page.count('data-testid="more-types"') == 3
    assert page.count('data-testid="type-card"') == 17
    # process wording is off the cards
    for text in ("Discretionary", "Permit portal", "Portal + plans", "Plan review process"):
        assert text not in page
    # the help panel sits beside/below the catalogue and the track link is kept
    assert page.index("chooser-main") < page.index('data-testid="chooser-help-column"')
    assert 'data-testid="help-panel"' in page and 'data-placement="chooser"' in page
    assert 'data-testid="help-form"' in page and 'data-testid="help-ask-the-city"' in page


def test_group_titles_and_cards_come_from_config_and_the_database(client) -> None:
    choose(client)
    titles = content.content()["chooser_groups"]
    page = client.get("/apply").text
    for title in titles.values():
        assert title in page


# --------------------------------------------------------------------- U4


def test_form_sections_order_prefill_labels_units_and_rule_hints(client) -> None:
    choose(client)
    page = client.get("/apply/deck_fence").text
    order = [page.index(text) for text in ("Project and property", "Your details", "Documents", "Review and submit")]
    assert order == sorted(order)
    assert page.index("What are you building?") < page.index('id="f-address_text"')
    # the identity matches the header
    assert f'value="{APPLICANT_NAME}"' in page
    assert f'data-testid="applicant-name">{APPLICANT_NAME}<' in page
    # labels, units and optional markers
    assert "Distance from the property line (ft)" in page and "Setback from the property line" not in page
    assert page.count('<span class="unit"') >= 4
    assert 'data-testid="optional-tag"' in page
    # limits come from the published rules (DF-1 4 ft, DF-2 6 ft, DF-3 8 ft, DF-4 2.5 ft)
    hints = " ".join(re.findall(r'data-testid="rule-hint">([^<]+)<', page))
    for expect in ("4 ft", "6 ft", "8 ft", "2.5 ft", "§14-305", "§14-306", "§14-308", "§14-311"):
        assert expect in hints, expect
    assert "counter" not in page.lower()
    # the definition is a shared info popover
    assert 'data-info-key="distance_from_property_line"' in page
    # upload rules and the one-line purpose of each document
    assert "up to 5 MB each" in page and "PDF, PNG, JPG or plain text" in page
    assert page.count('data-testid="doc-purpose"') == 2
    assert content.document_purpose("site_plan") in page
    assert "Sent to the City separately" in page and "Save draft" in page
    assert 'data-testid="ui-help"' in page and "?detail=help:apply_form" in page


def test_rule_hints_follow_the_published_rule_not_the_template(client, environment) -> None:
    choose(client)

    def lower(session):
        from acme_city.persistence.models import finance

        row = session.execute(
            select(finance.RuleVersion).where(finance.RuleVersion.rule_id == "DF-1")
        ).scalars().first()
        row.limit_value = "3"
        session.flush()

    with_session(environment, lower)
    hints = " ".join(re.findall(r'data-testid="rule-hint">([^<]+)<', client.get("/apply/deck_fence").text))
    assert "Front-yard fences: 3 ft at most" in hints and "4 ft at most" not in hints


def test_the_choice_renders_both_groups_without_javascript_and_defaults_to_fence(client) -> None:
    choose(client)
    page = client.get("/apply/deck_fence").text
    choice = page.split('data-testid="structure-choice"')[1].split("</div>")[0]
    assert re.search(r'value="fence"[^>]*checked', choice) and "Deck" in choice
    groups = re.findall(r'data-when-group="([^"]+)"', page)
    assert groups == ["fence", "deck"]
    deck_group = page.split('data-when-group="deck"')[1]
    assert "is-inactive" in page.split('data-when-group="deck"')[0].rsplit("<div", 1)[1]
    assert "Deck height above the ground (ft)" in deck_group and "Fence height (ft)" not in deck_group.split("</div>")[0]
    # the choice survives a server re-render (the no-JavaScript path)
    again = post(client, {**DECK}, intent="update")
    assert again.status_code == 200
    chosen = again.text.split('data-testid="structure-choice"')[1].split("</div>")[0]
    assert re.search(r'value="deck"[^>]*checked', chosen)
    deck_markup = again.text.split('data-when-group="deck"')[0].rsplit("<div", 1)[1]
    assert "is-inactive" not in deck_markup


def test_a_deck_submits_with_only_the_deck_questions_and_stores_the_rule_facts(client, environment) -> None:
    choose(client)
    done = post(client, DECK, intent="submit", upload=files())
    assert done.status_code == 303, done.text
    reference = done.headers["location"].rsplit("/", 1)[1]

    def read(session):
        row = session.execute(
            select(permit.Application).where(permit.Application.source_application_number == reference)
        ).scalar_one()
        return dict(row.submitted_facts)

    facts = with_session(environment, read)
    assert facts["structure_kind"] == "deck"
    assert facts["height_ft"] == 3 and facts["setback_ft"] == 10
    for fence_only in ("fence_material", "location", "property_line_ack", "deck_height_ft", "deck_setback_ft"):
        assert fence_only not in facts


def test_a_deck_without_its_questions_is_blocked_and_fence_fields_do_not_help(client) -> None:
    choose(client)
    bad = post(client, {**DECK, "deck_setback_ft": "", **{k: FENCE[k] for k in ("fence_material", "location", "height_ft")}},
               intent="submit", upload=files())
    assert bad.status_code == 422
    summary = bad.text.split('data-testid="error-summary"')[1].split("</div>")[0]
    assert "distance from the rear property line" in summary.lower()
    assert "fence material" not in summary.lower() and "fence height" not in summary.lower()


def test_a_fence_ignores_missing_deck_answers_and_an_unknown_choice_is_refused(client) -> None:
    choose(client)
    ok = post(client, FENCE, intent="submit", upload=files())
    assert ok.status_code == 303
    odd = post(client, {**FENCE, "structure_kind": "pergola"}, intent="submit", upload=files())
    assert odd.status_code == 422
    assert "Choose what are you building?" in odd.text or "what are you building" in odd.text.lower()


def test_the_choice_and_defaults_work_through_the_check_endpoint(client) -> None:
    choose(client)
    fence = client.post("/apply/deck_fence/check", data={"applicant_name": "T"}).json()
    assert "Fence height (ft)" in fence["missing"] and "Deck height above the ground (ft)" not in fence["missing"]
    deck = client.post("/apply/deck_fence/check", data={"applicant_name": "T", "structure_kind": "deck"}).json()
    assert "Deck height above the ground (ft)" in deck["missing"] and "Fence height (ft)" not in deck["missing"]


def test_documents_show_filename_replace_remove_and_a_problem_per_document(client, environment) -> None:
    choose(client)
    first = post(client, FENCE, upload=files())
    assert first.status_code == 200
    page = first.text
    assert page.count('data-testid="doc-filename"') == 2 and "sketch.txt" in page
    assert page.count("Replace file") == 2 and page.count('data-testid="doc-remove"') == 2
    reference = re.search(r'name="draft" value="([^"]+)"', page).group(1)
    removed = post(client, FENCE, draft=reference, extra={"remove_doc": "site_plan"})
    assert removed.status_code == 200
    assert 'data-doc-type="site_plan" data-added="false"' in removed.text
    assert 'data-doc-type="material_spec" data-added="true"' in removed.text
    assert "Removed the file for site sketch or site plan" in removed.text
    # a refused file names the document it belongs to and keeps the draft
    bad = post(client, FENCE, draft=reference, upload={"file__site_plan": ("evil.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 422
    row = bad.text.split('data-doc-type="site_plan"')[1].split("</li>")[0]
    assert 'data-testid="doc-problem"' in row and "not accepted" in row
    assert 'data-testid="doc-problem"' not in bad.text.split('data-doc-type="material_spec"')[1].split("</li>")[0]
    assert 'data-doc-type="material_spec" data-added="true"' in bad.text


def test_the_enter_key_default_button_is_harmless_and_help_is_outside_the_form(client) -> None:
    choose(client)
    page = client.get("/apply/deck_fence").text
    form = page.split('data-testid="application-form"')[1].split("</form>")[0]
    first_submit = re.search(r'<button type="submit"[^>]*>', form).group(0)
    assert 'value="update"' in first_submit
    assert "<form" not in form  # no nested forms
    assert 'data-testid="help-panel"' not in form
    column = page.split('data-testid="form-help-column"')[1]
    assert 'data-testid="help-panel"' in column and 'data-placement="form"' in column
    assert 'data-testid="help-ask-the-city"' in column


def test_save_draft_lands_on_the_drafts_tab_with_a_toast_and_a_continue_card(client) -> None:
    choose(client)
    saved = post(client, FENCE, intent="save", upload=files())
    assert saved.status_code == 303 and "saved=" in saved.headers["location"]
    reference = saved.headers["location"].split("saved=")[1]
    page = client.get(saved.headers["location"]).text
    toast = re.search(r'<div class="toast on city-toast"[^>]*>(.*?)</div>', page).group(1)
    assert f"Your draft {reference} was saved" in toast
    assert 'data-tab="drafts"' in page and 'data-kind="draft"' in page
    assert f"/apply/deck_fence?draft={reference}" in page and "Continue application" in page


# --------------------------------------------------------------------- U5


def test_receipt_shows_the_reference_type_address_time_next_step_and_actions(client) -> None:
    choose(client)
    reference = submit_fence(client)
    page = client.get(f"/apply/submitted/{reference}").text
    assert "Application received" in page and f'data-testid="submitted-reference">{reference}<' in page
    assert 'data-testid="receipt-type">Residential deck or fence<' in page
    assert re.search(r'data-testid="receipt-address">[^<]*Lantren', page)
    assert re.search(r'data-testid="receipt-submitted">[A-Z][a-z]{2} \d{1,2}, \d{4}, \d\d:\d\d UTC<', page)
    assert content.content()["receipt"]["next_step"] in html.unescape(page)
    assert f'href="/apply/track?ref={reference}"' in page and "Track application" in page
    assert f'href="/apply/submitted/{reference}/copy"' in page and "Download a copy" in page
    assert "email" not in page.lower().replace("email address", "")  # nothing claims an email was sent


def test_download_a_copy_is_an_attachment_of_the_applicants_own_record(client, environment) -> None:
    choose(client)
    reference = submit_fence(client)
    plant_request(environment, reference)
    copy = client.get(f"/apply/submitted/{reference}/copy")
    assert copy.status_code == 200
    assert copy.headers["content-disposition"].startswith("attachment;") and reference in copy.headers["content-disposition"]
    assert copy.headers["content-type"].startswith("text/html")
    text = copy.text
    assert reference in text and "Residential deck or fence" in text and "Lantren" in text
    assert "cedar" in text and "Fence height (ft)" in text and "Fence" in text
    assert "Received: " in text and "It is not a permit" in text
    for secret in (INTERNAL_NOTE, INTERNAL_FINDING, VISIBLE_NOTE, MUST_LINE, "persona_permit_reviewer"):
        assert secret not in text
    assert client.get("/apply/submitted/ACME-NOPE/copy").status_code == 404
    choose(client, "persona_data_steward")
    assert client.get(f"/apply/submitted/{reference}/copy").status_code == 403


def test_permit_download_is_refused_until_a_permit_is_issued(client) -> None:
    choose(client)
    reference = submit_fence(client)
    assert client.get(f"/apply/permit/{reference}").status_code == 404
    assert client.get("/apply/permit/ACME-NOPE").status_code == 404


# --------------------------------------------------------------------- U6


def test_empty_state_is_one_start_card_with_no_metrics_or_empty_panels(client, environment) -> None:
    choose(client)
    isolate(environment)
    page = client.get("/apply/track").text
    assert "<h1>My permits</h1>" in page
    assert "Track your applications and respond to requests from the City." in page
    assert 'data-testid="my-permits-empty"' in page and 'data-testid="empty-start"' in page
    for absent in ('data-testid="permit-tabs"', 'data-testid="permit-card"', 'data-testid="recent-activity"', "metric"):
        assert absent not in page
    assert page.count('href="/apply"') >= 2 and 'data-testid="start-application"' in page
    assert content.content()["next_step_empty"] in page
    # the sidebar keeps Need help? and the help panel
    side = page.split('class="tracker-aside"')[1]
    assert "Need help?" in side and 'data-testid="help-panel"' in side and 'data-placement="track"' in side
    assert 'data-testid="help-ask-the-city"' in side and 'data-testid="contact-link"' in side


def test_tabs_counts_come_from_the_server_and_cards_show_the_mockup_parts(client, environment) -> None:
    choose(client)
    isolate(environment)
    reference = submit_fence(client)
    post(client, FENCE, intent="save")  # a draft
    page = client.get("/apply/track").text
    tabs = re.findall(r'data-testid="tab-(\w+)"[^>]*>([^<]*)<span class="tab-count">\((\d+)\)', page)
    assert [(k, int(n)) for k, _l, n in tabs] == [("active", 1), ("drafts", 1), ("closed", 0)]
    assert re.search(r'data-testid="tab-active"[^>]*aria-current="page"', page)
    card = card_of(page, reference)
    assert "Residential deck or fence" in card and "Lantren" in card
    assert f"Application {reference}" in card
    assert 'data-testid="status-badge">Submitted<' in card
    assert 'data-testid="request-box"' not in card
    assert re.findall(r'class="step step-(\w+)"', card) == ["current", "todo", "todo"]
    assert re.search(r"Submitted</dt><dd[^>]*>[A-Z][a-z]{2} \d{1,2}, \d{4}<", card)
    assert 'data-testid="tracked-status">Awaiting intake agent<' in card
    assert f'href="/apply/track?ref={reference}"' in card and "View application" in card
    assert f'href="/apply/submitted/{reference}/copy"' in card and "Download submission" in card
    # the right-hand sidebar names what happens next, from the stored state
    side = page.split('data-testid="what-next"')[1]
    assert content.content()["next_step"]["submitted"][:40] in html.unescape(side)
    assert "service target for this permit type is 5 days" in side
    drafts = client.get("/apply/track?tab=drafts").text
    assert 'data-tab="drafts"' in drafts and "Draft DRAFT-" in drafts and 'data-testid="status-badge">Draft<' in drafts
    closed = client.get("/apply/track?tab=closed").text
    assert closed.count('data-testid="permit-card"') == 0 and 'data-testid="tab-empty"' in closed


def test_closed_tab_holds_denied_and_closed_applications(client, environment) -> None:
    choose(client)
    isolate(environment)
    reference = submit_fence(client)
    set_status(environment, reference, "denied")
    page = client.get("/apply/track").text
    # the only application is closed, so the first non-empty tab is shown
    assert 'data-tab="closed"' in page and 'data-testid="status-badge">Denied<' in page
    assert re.findall(r'class="step step-(\w+)"', page) == ["done", "done", "stopped"]
    counts = dict((k, int(n)) for k, _l, n in re.findall(r'data-testid="tab-(\w+)"[^>]*>([^<]*)<span class="tab-count">\((\d+)\)', page))
    assert counts == {"active": 0, "drafts": 0, "closed": 1}


@pytest.mark.parametrize(
    "status,badge,steps,primary",
    [
        ("submitted", "Submitted", ["current", "todo", "todo"], "View application"),
        ("needs_information", "Action needed", ["done", "current", "todo"], "Respond to request"),
        ("revisions_requested", "Action needed", ["done", "current", "todo"], "Respond to request"),
        ("ready_for_review", "In review", ["done", "current", "todo"], "View application"),
        ("under_review", "In review", ["done", "current", "todo"], "View application"),
        ("approved", "Approved", ["done", "done", "done"], "View application"),
        ("issued", "Permit issued", ["done", "done", "done"], "Download permit"),
        ("denied", "Denied", ["done", "done", "stopped"], "View application"),
    ],
)
def test_badge_progress_and_primary_action_follow_the_status(client, environment, status, badge, steps, primary) -> None:
    choose(client)
    reference = submit_fence(client)
    set_status(environment, reference, status)
    page = client.get(f"/apply/track?tab={'closed' if status == 'denied' else 'active'}").text
    card = card_of(page, reference)
    assert f'data-testid="status-badge">{badge}<' in card
    assert re.findall(r'class="step step-(\w+)"', card) == steps
    assert re.search(rf'data-testid="primary-action">{primary}<', card)
    if status == "issued":
        assert "Permit issued" in card.split('data-testid="progress-steps"')[1]


def test_progress_function_is_complete_over_every_status() -> None:
    for status in permits_view.BADGES:
        steps = permits_view.progress(status)["steps"]
        assert [s["label"] for s in steps][:2] == ["Submitted", "Under review"]
        assert len(steps) == 3 and all(s["state_word"] for s in steps)
    assert permits_view.progress("issued")["steps"][2]["label"] == "Permit issued"


def test_the_request_box_shows_the_applicant_visible_ask_and_the_primary_action(client, environment) -> None:
    choose(client)
    reference = submit_fence(client)
    set_status(environment, reference, "needs_information")
    plant_request(environment, reference)
    page = client.get("/apply/track").text
    card = card_of(page, reference)
    assert 'data-testid="request-title">A document is missing<' in card
    assert f'data-testid="request-text">{MUST_LINE}<' in card
    assert 'data-testid="primary-action">Respond to request<' in card
    assert f'href="/apply/track?ref={reference}#request"' in card and "View request" in card
    assert 'data-testid="status-badge">Action needed<' in card and "badge-warn" in card
    assert "Respond to the City" in page.split('data-testid="what-next"')[1]
    # the detail view carries the same box, the response forms and the messages
    detail = client.get(f"/apply/track?ref={reference}").text
    assert 'id="request"' in detail and 'id="respond"' in detail
    assert 'data-testid="revise-form"' in detail and 'data-testid="resubmit-form"' in detail
    assert VISIBLE_NOTE in detail.split('data-testid="city-messages"')[1].split("</ul>")[0]


def test_internal_comments_findings_and_staff_never_appear_on_my_permits(client, environment) -> None:
    choose(client)
    reference = submit_fence(client)
    set_status(environment, reference, "needs_information")
    plant_request(environment, reference)
    secrets = (INTERNAL_NOTE, INTERNAL_FINDING, "persona_permit_reviewer", "Permit Reviewer", "persona_data_steward")
    pages = {
        "list": client.get("/apply/track").text,
        "active": client.get("/apply/track?tab=active").text,
        "detail": client.get(f"/apply/track?ref={reference}").text,
        "drawer": client.get(f"/apply/track?ref={reference}&detail=my-permit:{reference}").text,
        "fragment": client.get(f"/detail/my-permit/{reference}").text,
        "receipt": client.get(f"/apply/submitted/{reference}").text,
        "copy": client.get(f"/apply/submitted/{reference}/copy").text,
        "chooser": client.get("/apply").text,
    }
    for name, text in pages.items():
        # the Demo controls list the five personas by design; they are not part of the content
        text = re.sub(r'<details class="demo-switch.*?</details>', "", text, flags=re.S)
        for secret in secrets:
            assert secret not in text, (name, secret)
    # what the applicant is meant to read is there, in the list and in recent activity
    assert VISIBLE_NOTE in pages["detail"]
    activity = pages["list"].split('data-testid="recent-activity"')[1]
    assert INTERNAL_NOTE not in activity
    assert "The City sent you a message" in activity and VISIBLE_NOTE in activity
    assert "The City asked for something" in activity and MUST_LINE in activity
    assert INTERNAL_NOTE not in activity


def test_a_waived_finding_is_not_asked_of_the_applicant(client, environment) -> None:
    from datetime import UTC, datetime

    choose(client)
    reference = submit_fence(client)
    set_status(environment, reference, "needs_information")
    plant_request(environment, reference)

    def waive(session):
        row = session.get(permit.ApplicationFinding, "finding_ui_1")
        row.waived_at = datetime.now(UTC)
        session.flush()

    with_session(environment, waive)
    page = client.get("/apply/track").text
    assert MUST_LINE not in page
    # the applicant comment is still a request
    assert VISIBLE_NOTE in card_of(page, reference).split('data-testid="request-box"')[1]


def test_recent_activity_lists_dated_visible_events_only(client, environment) -> None:
    choose(client)
    isolate(environment)
    reference = submit_fence(client)
    page = client.get("/apply/track").text
    items = re.findall(r'data-testid="activity-item"><time datetime="([^"]+)" title="[^"]+">([^<]+)</time><span>([^<]+)', page)
    assert len(items) == 1 and items[0][2].startswith("Application submitted")
    assert re.match(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", items[0][1]) and reference in page


def test_the_application_record_drawer_is_scoped_and_url_addressable(client) -> None:
    choose(client)
    reference = submit_fence(client)
    page = client.get(f"/apply/track?ref={reference}&detail=my-permit:{reference}").text
    assert 'data-testid="ui-drawer-body" data-detail-status="200"' in page
    drawer = page.split('data-testid="ui-drawer-body"')[1]
    assert "Application id" in drawer and "First submitted" in drawer and reference in drawer
    assert client.get("/detail/my-permit/ACME-NOPE").status_code == 404
    client.cookies.clear()
    assert client.get(f"/detail/my-permit/{reference}").status_code == 401


def test_lookup_by_reference_still_works_and_misses_say_so(client) -> None:
    choose(client)
    reference = submit_fence(client)
    found = client.get("/apply/track", params={"ref": reference}).text
    assert 'data-testid="tracked-application"' in found and 'data-testid="open-case"' in found
    assert 'data-testid="progress-steps"' in found and 'data-testid="all-permits"' in found
    missing = client.get("/apply/track", params={"ref": "ACME-NOPE"}).text
    assert missing.count("No application with that reference") == 1
    assert 'data-testid="track-form"' in missing and 'id="track-ref"' in missing


def test_the_help_panel_is_on_the_chooser_form_and_tracker_with_their_test_ids(client) -> None:
    choose(client)
    reference = submit_fence(client)
    for path, placement in (("/apply", "chooser"), ("/apply/deck_fence", "form"), (f"/apply/track?ref={reference}", "track")):
        page = client.get(path).text
        assert f'data-placement="{placement}"' in page, path
        for testid in ("help-panel", "help-form", "help-question", "help-submit", "help-ask-the-city"):
            assert f'data-testid="{testid}"' in page, (path, testid)


def test_new_screens_have_help_entries(client) -> None:
    from acme_city.ui import patterns

    for screen in ("apply", "apply_form", "apply_track", "apply_receipt", "city_permits"):
        entry = patterns.screen_help(screen)
        assert entry and entry["purpose"] and entry["can_do"] and entry["next"], screen
    choose(client)
    assert "?detail=help:apply_form" in client.get("/apply/deck_fence").text
    reference = submit_fence(client)
    assert "?detail=help:apply_receipt" in client.get(f"/apply/submitted/{reference}").text
    assert "?detail=help:city_permits" in client.get("/city/permits").text

"""The in-app help: hub, tutorial, how-to guides, glossary and technical documents."""
# REQUIRES: UX-01, SEC-01
# The help pages open for every persona, every link in them resolves for the
# persona it names, rendered documents are escaped, and the architecture page
# cannot run a script in the application's origin.

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.help_docs import content, markdown
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

SRC = Path(__file__).resolve().parents[2] / "src" / "acme_city"
CONFIG = Path(__file__).resolve().parents[2] / "config"

PERSONAS = (
    "persona_applicant",
    "persona_agent_operator",
    "persona_data_steward",
    "persona_permit_reviewer",
    "persona_city_administrator",
)
STAFF = PERSONAS[1:]
OPEN_PAGES = ("/help", "/help/tutorial", "/help/how-to", "/help/glossary")


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'help.db'}",
            "ACME_SECRET_KEY": "help-docs-test-secret-value",
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
    with TestClient(create_app(environment)) as test_client:
        yield test_client


def sign_in(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


# ------------------------------------------------------------------ routes


@pytest.mark.parametrize("actor_id", PERSONAS)
def test_every_help_page_opens_for_every_persona(client: TestClient, actor_id: str) -> None:
    sign_in(client, actor_id)
    paths = list(OPEN_PAGES)
    paths += [f"/help/how-to/{item['slug']}" for item in content.guides()]
    paths += ["/help/technical"] + [f"/help/technical/{d['slug']}" for d in content.technical()["documents"]]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        assert 'data-testid="help-page"' in response.text, path


def test_open_pages_need_no_sign_in_and_technical_pages_do(client: TestClient) -> None:
    for path in OPEN_PAGES + ("/help/how-to/reconcile-a-payment",):
        assert client.get(path).status_code == 200, path
    for path in ("/help/technical", "/help/technical/runbook", "/help/technical/architecture/file"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/select", path


def test_unknown_guide_and_document_are_plain_not_found(client: TestClient) -> None:
    assert client.get("/help/how-to/no-such-guide").status_code == 404
    sign_in(client, "persona_permit_reviewer")
    assert client.get("/help/technical/no-such-document").status_code == 404
    assert client.get("/help/technical/runbook/file").status_code == 404


def test_the_hub_lists_the_four_kinds_of_help(client: TestClient) -> None:
    page = client.get("/help").text
    for key, href in (
        ("tutorial", "/help/tutorial"),
        ("how-to", "/help/how-to"),
        ("technical", "/help/technical"),
        ("glossary", "/help/glossary"),
    ):
        assert f'data-testid="help-card-{key}"' in page and f'href="{href}"' in page


def test_the_applicant_sees_applicant_guides_first_and_staff_see_their_own(
    client: TestClient,
) -> None:
    def first(actor_id: str | None) -> str:
        if actor_id:
            sign_in(client, actor_id)
        slugs = re.findall(r'data-testid="howto-item" data-slug="([^"]+)"', client.get("/help/how-to").text)
        assert len(slugs) == len(content.guides())
        return slugs[0]

    assert first(None) == "apply-for-a-fence-or-deck-permit"
    assert first("persona_applicant") == "apply-for-a-fence-or-deck-permit"
    assert first("persona_permit_reviewer") == "review-an-application-and-record-a-decision"
    assert first("persona_data_steward") == "resolve-a-data-issue"
    page = client.get("/help/how-to").text
    applicant_slugs = [g["slug"] for g in content.guides("persona_applicant")[:3]]
    assert all(slug in page for slug in applicant_slugs)


def test_the_frame_matches_the_visitor(client: TestClient) -> None:
    sign_in(client, "persona_applicant")
    assert 'data-city-site="true"' in client.get("/help/tutorial").text
    sign_in(client, "persona_data_steward")
    page = client.get("/help/tutorial").text
    assert 'class="side"' in page and 'data-city-site="true"' not in page


# -------------------------------------------------------------- Help link


def test_the_help_link_is_on_the_staff_and_city_layouts(client: TestClient) -> None:
    city = client.get("/city/").text
    assert 'data-testid="help-link" aria-current' not in city
    assert re.search(r'<a class="city-help-link" href="/help" data-testid="help-link"', city)
    assert 'href="/help" data-testid="help-link-footer"' in city
    sign_in(client, "persona_applicant")
    # Changed deliberately (the panel slice): the header of the applicant
    # pages opens the assistant panel instead of the hub; the hub stays in
    # the footer of every page.
    for path in ("/apply", "/apply/track"):
        page = client.get(path).text
        assert 'href="/help" data-testid="help-link-footer"' in page, path
        assert 'data-testid="help-ask"' in page, path
        assert 'data-testid="help-chat-launcher"' in page, path
    assert re.search(
        r'<a class="city-help-link" href="/help" data-testid="help-link"',
        client.get("/city/permits").text,
    )
    for actor_id in STAFF:
        sign_in(client, actor_id)
        for path in ("/queue", "/help"):
            page = client.get(path).text
            assert re.search(r'<a class="top-help-link" href="/help" data-testid="help-link"', page), (actor_id, path)


# -------------------------------------------- tutorial and guide links work


def link_cases() -> list[tuple[str, str]]:
    cases = [
        (step["href"], section["persona_id"])
        for section in content.tutorial()["sections"]
        for step in section["steps"]
    ]
    for item in content.guides():
        cases += [(item["screen_href"], persona_id) for persona_id in item["persona_ids"]]
    return sorted(set(cases))


def test_the_tutorial_runs_in_the_order_of_the_demo_story() -> None:
    order = [section["persona"] for section in content.tutorial()["sections"]]
    assert order == [
        "Applicant", "Agent Operator", "Data Steward", "Permit Reviewer", "City Administrator",
    ]


def test_every_go_to_this_screen_link_resolves_for_the_persona_it_names(
    client: TestClient,
) -> None:
    by_persona: dict[str, list[str]] = {}
    for href, persona_id in link_cases():
        by_persona.setdefault(persona_id, []).append(href)
    assert set(by_persona) == set(PERSONAS)
    for persona_id, hrefs in by_persona.items():
        sign_in(client, persona_id)
        for href in hrefs:
            response = client.get(href, follow_redirects=True)
            assert response.status_code == 200, (persona_id, href)
            assert "outside your grants" not in response.text, (persona_id, href)
            assert "permission_denied" not in response.text, (persona_id, href)
            assert 'data-testid="error-panel"' not in response.text, (persona_id, href)
            assert str(response.url).endswith(href.rstrip("/") or "/") or response.url.path in {
                href,
                href.rstrip("/"),
            }, (persona_id, href, str(response.url))


def test_the_tutorial_page_renders_one_link_per_step(client: TestClient) -> None:
    page = client.get("/help/tutorial").text
    steps = sum(len(section["steps"]) for section in content.tutorial()["sections"])
    assert page.count('data-testid="tutorial-step"') == steps
    assert page.count('data-testid="tutorial-go"') == steps
    # Changed deliberately (demo controls, S3 and persona switcher, S4): the
    # tutorial points at the list of personas and never names a corner.
    assert "list of personas" in page
    assert "bottom left" not in page
    assert "recorded replay" in page and "stored answer shown again" in page


# ------------------------------------------------------------- content


def test_each_guide_has_5_to_10_steps_a_persona_and_a_screen() -> None:
    slugs = [item["slug"] for item in content.guides()]
    assert len(slugs) == len(set(slugs))
    required = {
        "apply-for-a-fence-or-deck-permit",
        "track-an-application-and-answer-a-request",
        "ask-the-help-assistant-and-ask-the-city",
        "review-an-application-and-record-a-decision",
        "resolve-a-data-issue",
        "run-a-what-if-and-write-the-briefing",
        "propose-and-approve-a-rule-change",
        "reconcile-a-payment",
        "read-the-operations-dashboard-and-audit-log",
    }
    assert required <= set(slugs)
    for item in content.guides():
        assert 5 <= len(item["steps"]) <= 10, item["slug"]
        assert item["who"] and item["screen_href"].startswith("/"), item["slug"]
        assert set(item["persona_ids"]) <= set(PERSONAS), item["slug"]


def test_the_cedarline_guide_answers_reject_for_the_near_duplicate() -> None:
    steps = " ".join(content.guide("resolve-a-data-issue")["steps"])
    assert "Reject match" in steps and "Cedarline Coffee Roasters LLC" in steps


def test_the_rule_change_guide_says_the_author_cannot_approve() -> None:
    text = " ".join(content.guide("propose-and-approve-a-rule-change")["steps"])
    assert "You authored this version; another administrator must approve it." in text


def test_every_quoted_label_in_the_steps_exists_in_the_application() -> None:
    corpus = ""
    for path in list(SRC.rglob("*")) + list(CONFIG.glob("*.json")):
        if path.is_file() and path.suffix in {".html", ".py", ".json"} and path.name != "help_content.json" and "help_docs" not in path.parts:
            corpus += path.read_text(encoding="utf-8", errors="ignore") + "\n"
    corpus = html.unescape(corpus)
    texts: list[str] = []
    for section in content.tutorial()["sections"]:
        for step in section["steps"]:
            texts += [step["do"], step["see"]]
    for item in content.guides():
        texts += item["steps"] + [item["result"]]
    missing = []
    for text in texts:
        for quoted in re.findall(r'"([^"]{3,})"', text):
            # A link label is built from the name of the candidate record.
            probe = "Confirm link to " if quoted.startswith("Confirm link to ") else quoted
            if probe not in corpus:
                missing.append(quoted)
    assert not missing, missing


def test_the_help_words_use_no_dash() -> None:
    raw = content.CONTENT_PATH.read_text(encoding="utf-8")
    assert "—" not in raw and "–" not in raw


# --------------------------------------------------- markdown is escaped


def test_markdown_escapes_html_and_drops_unsafe_links() -> None:
    out = markdown.render(
        "# Title <b>x</b>\n\n<script>alert(1)</script>\n\n"
        "[bad](javascript:alert(1)) [rel](docs/x.md) [ok](https://example.invalid/a?b=1&c=2)\n\n"
        "<img src=x onerror=alert(1)>\n\n```\n<script>in code</script>\n```\n\n"
        "| a | b |\n| - | - |\n| <i>1</i> | `<u>2</u>` |\n"
    )
    assert "<script" not in out and "<img" not in out and "<b>" not in out and "<i>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert "javascript:" not in out.replace("[bad]", "") or 'href="javascript' not in out
    assert 'href="javascript' not in out and 'href="docs' not in out
    assert 'href="https://example.invalid/a?b=1&amp;c=2"' in out and 'rel="noopener noreferrer nofollow"' in out
    assert "<table>" in out and "<code>&lt;u&gt;2&lt;/u&gt;</code>" in out
    assert "onerror" in out  # shown as text, inside the escaped tag


def test_markdown_renders_headings_lists_and_nesting() -> None:
    out = markdown.render("## Step list\n\n1. one\n2. two\n   - nested **bold**\n\ntext *em*\n")
    assert '<h2 id="step-list">Step list</h2>' in out
    assert "<ol><li>one</li><li>two<ul><li>nested <strong>bold</strong></li></ul></li></ol>" in out
    assert "<em>em</em>" in out


def test_a_script_in_a_document_shows_as_text_in_the_page(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs = tmp_path / "docs" / "operations"
    docs.mkdir(parents=True)
    (docs / "RUNBOOK.md").write_text("# Test runbook\n\n<script>window.__ran = 1</script>\n", encoding="utf-8")
    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)
    sign_in(client, "persona_city_administrator")
    page = client.get("/help/technical/runbook").text
    assert "&lt;script&gt;window.__ran = 1&lt;/script&gt;" in page
    assert "<script>window.__ran" not in page


def test_a_missing_document_gives_a_plain_message(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)
    sign_in(client, "persona_city_administrator")
    response = client.get("/help/technical/runbook")
    assert response.status_code == 404
    assert 'data-testid="document-missing"' in response.text
    assert "not available in this copy" in response.text
    assert "Traceback" not in response.text and str(tmp_path) not in response.text
    index = client.get("/help/technical")
    assert index.status_code == 200 and "Not available in this copy" in index.text
    assert client.get("/help/technical/architecture/file").status_code == 404


def test_a_path_outside_the_root_is_refused() -> None:
    loaded = content.read_document({"root": "repo", "path": "../README.md"})
    assert loaded.text is None and "outside" in loaded.message


# -------------------------------------- the architecture page is sandboxed


def test_the_architecture_page_is_served_as_committed_inside_a_script_free_sandbox(
    client: TestClient,
) -> None:
    sign_in(client, "persona_permit_reviewer")
    entry = content.document("architecture")
    committed = (content.PROJECT_ROOT / entry["path"]).read_bytes()
    wrapper = client.get("/help/technical/architecture").text
    frame = re.search(r"<iframe[^>]*>", wrapper).group(0)
    assert 'sandbox=""' in frame and 'src="/help/technical/architecture/file"' in frame
    assert "allow-scripts" not in wrapper and "allow-same-origin" not in wrapper
    raw = client.get("/help/technical/architecture/file")
    assert raw.status_code == 200 and raw.content == committed
    assert raw.headers["content-type"].startswith("text/html")
    policy = raw.headers["content-security-policy"]
    directives = {part.strip().split(" ")[0]: part.strip() for part in policy.split(";")}
    assert directives["sandbox"] == "sandbox"  # no allow-scripts, no allow-same-origin
    assert directives["default-src"] == "default-src 'none'"
    assert "script-src" not in policy and "'unsafe-eval'" not in policy
    assert raw.headers["x-content-type-options"] == "nosniff"
    download = client.get("/help/technical/architecture/file?download=true")
    assert download.headers["content-disposition"].startswith("attachment")
    assert download.headers["content-security-policy"] == policy

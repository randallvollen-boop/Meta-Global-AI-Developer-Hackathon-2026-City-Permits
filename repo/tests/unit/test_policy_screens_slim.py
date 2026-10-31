"""The what-if screens after the slim-down.

A what-if shows the change, the run and the result. Facts, Muse and the
tables sit behind More details, the two-column split is one column, and a
disabled Run comparison says why beside the button. Every button of these
screens is pressed here.
"""
# REQUIRES: UX-01, UX-02, UX-03
# The screens show only what a decision needs, and every action is exercised
# through the control that offers it.

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
from acme_city.ui.router import router as ui_router  # noqa: E402

ADMIN = "persona_city_administrator"
QUESTION = "What if the side and rear yard fence limit were 7 ft?"


def csrf_of(body: str) -> str:
    """Return the CSRF token of the session from a rendered page."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert match is not None, "the page carries a form token"
    return match.group(1)


def version_of(body: str) -> str:
    """Return the first expected version on a page."""
    match = re.search(r'name="expected_version" value="([^"]+)"', body)
    assert match is not None, "the page carries an expected version"
    return match.group(1)


def form_of(body: str, testid: str) -> str:
    """Return the markup of one form."""
    match = re.search(
        rf'<form[^>]*data-testid="{testid}"[^>]*>.*?</form>',
        body,
        re.S,
    )
    assert match is not None, testid
    return match.group(0)


def hidden(fragment: str, name: str) -> str:
    """Return one hidden field of a form fragment."""
    match = re.search(rf'name="{name}" value="([^"]*)"', fragment)
    assert match is not None, name
    return match.group(1)


def option_value(body: str, select_name: str) -> str:
    """Return the first real option of a select."""
    select = re.search(
        rf'<select[^>]*name="{select_name}"[^>]*>(.*?)</select>',
        body,
        re.S,
    )
    assert select is not None, select_name
    values = re.findall(r'<option value="([^"]+)"', select.group(1))
    assert values, select_name
    return values[0]


def closed(body: str, testid: str) -> None:
    """A named disclosure is present and starts closed."""
    match = re.search(rf'<details[^>]*data-testid="{testid}"[^>]*>', body)
    assert match is not None, testid
    assert "open" not in match.group(0), testid


def scenario_path(body: str) -> str:
    """Return the editor address from a rendered editor page."""
    match = re.search(r'action="(/policy/scenarios/polscen_[^"]+)/(?:save|run)"', body)
    assert match is not None, "the editor names its scenario"
    return match.group(1)


def choose(client: TestClient) -> None:
    """Establish a server-held session for the City Administrator."""
    response = client.post("/api/session/select", json={"actor_id": ADMIN})
    assert response.status_code == 200, response.text


def submit(client: TestClient, url: str, body: str, **fields: str) -> tuple[str, str]:
    """Press a form and return the address and the page it opens."""
    data = {"csrf_token": csrf_of(body)}
    if "expected_version" not in fields:
        data["expected_version"] = version_of(body)
    data.update(fields)
    response = client.post(url, data=data, follow_redirects=False)
    assert response.status_code == 303, response.text[:1500]
    path = response.headers["location"].split("#", 1)[0].split("?", 1)[0]
    opened = client.get(path)
    assert opened.status_code == 200, opened.text[:500]
    return path, opened.text


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """A demonstration database of its own, so a test leaves no trace."""
    settings = build_environment(tmp_path, synthetic=False, name="policy-screens.db")
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        choose(test_client)
        yield test_client


def test_run_comparison_is_disabled_until_there_is_a_change(client: TestClient) -> None:
    """A what-if with no change keeps Run comparison off and says why."""
    listing = client.get("/policy/scenarios").text
    _path, editor = submit(client, "/policy/scenarios", listing, name="Nothing to run")
    button = re.search(r'<button[^>]*data-testid="policy-run-submit"[^>]*>', editor)
    assert button is not None
    assert "disabled" in button.group(0)
    assert editor.index('data-testid="policy-run-submit"') < editor.index(
        'data-testid="policy-run-reason"'
    )
    reason = editor.split('data-testid="policy-run-reason"', 1)[1][:500]
    assert "Add at least one change first" in reason
    assert "admin-b-split" not in editor
    rule = re.search(r"<details>\s*<summary>Rule limit</summary>", editor)
    assert rule is not None
    assert "open" not in rule.group(0)


def test_every_what_if_button_and_the_result_sentence(client: TestClient) -> None:
    """The buttons save, run and explain, and a person still decides every case."""
    listing = client.get("/policy/scenarios").text
    assert "admin-b-lead" not in listing
    assert "admin-b-split" not in listing
    assert 'data-testid="evidence-panel"' not in listing
    assert "Compare proposed rules using fictional cases." not in listing
    assert "Published rules stay unchanged." in listing
    closed(listing, "policy-muse-examples")
    closed(listing, "policy-recent-runs")
    assert listing.index('data-testid="policy-new"') < listing.index('data-testid="policy-list"')

    suggestions = re.findall(
        r'data-testid="policy-suggestion" data-suggestion="([^"]+)"',
        listing,
    )
    assert len(suggestions) == 3
    for key in suggestions:
        page = client.get("/policy/scenarios").text
        _path, editor = submit(
            client, "/policy/scenarios", page, suggestion=key, name=key
        )
        assert 'data-testid="policy-change"' in editor

    _path, empty = submit(
        client,
        "/policy/scenarios",
        client.get("/policy/scenarios").text,
        name="Saved from the form",
    )
    assert "Saved from the form" in empty
    assert 'data-testid="policy-no-changes"' in empty

    choice = form_of(listing, "policy-propose-form")
    question = re.search(r'<option value="([^"]+)"', choice)
    assert question is not None
    _path, proposed = submit(
        client, "/policy/propose", listing, question=question.group(1)
    )
    assert (
        'data-testid="policy-proposal-save"' in proposed
        or 'data-testid="policy-proposal-rejected"' in proposed
    )
    _path, asked = submit(
        client,
        "/policy/propose",
        client.get("/policy/scenarios").text,
        question=QUESTION,
    )
    assert 'data-testid="policy-proposal-changes"' in asked
    assert "Muse proposes; you decide. Nothing is saved until you save it." in asked
    assert 'data-testid="evidence-panel"' not in asked
    save = form_of(asked, "policy-proposal-save-form")
    _path, stored = submit(
        client,
        "/policy/scenarios",
        asked,
        proposal=hidden(save, "proposal"),
        name="Saved from Muse",
        expected_version=hidden(save, "expected_version"),
    )
    assert "Saved from Muse" in stored

    _path, editor = submit(
        client,
        "/policy/scenarios",
        client.get("/policy/scenarios").text,
        name="Built by its buttons",
    )
    editor_path = scenario_path(editor)
    kinds = (
        (
            "policy-add-threshold",
            {
                "kind": "rule_threshold",
                "rule_id": option_value(editor, "rule_id"),
                "limit_value": "9",
            },
        ),
        (
            "policy-add-retirement",
            {"kind": "rule_retirement", "rule_id": option_value(editor, "rule_id")},
        ),
        (
            "policy-add-requirement",
            {
                "kind": "requirement",
                "permit_type_key": option_value(editor, "permit_type_key"),
                "item_kind": "document",
                "action": "add",
                "item": "site_plan",
            },
        ),
        (
            "policy-add-category",
            {
                "kind": "process_category",
                "permit_type_key": option_value(editor, "permit_type_key"),
                "process_category": option_value(editor, "process_category"),
            },
        ),
        (
            "policy-add-discretionary",
            {
                "kind": "discretionary",
                "permit_type_key": option_value(editor, "permit_type_key"),
                "discretionary": "yes",
            },
        ),
        (
            "policy-add-target",
            {
                "kind": "service_target",
                "permit_type_key": option_value(editor, "permit_type_key"),
                "service_target_days": "4",
            },
        ),
        (
            "policy-add-fee",
            {
                "kind": "fee",
                "fee_schedule_id": option_value(editor, "fee_schedule_id"),
                "fixed_review_charge_cents": "100",
            },
        ),
    )
    current = editor
    for testid, fields in kinds:
        fragment = form_of(current, testid)
        _path, current = submit(
            client,
            f"{editor_path}/save",
            current,
            operation="add_change",
            expected_version=hidden(fragment, "expected_version"),
            **fields,
        )
        assert 'data-testid="policy-change"' in current
    unsupported = re.findall(
        r'data-testid="policy-add-unsupported" data-kind="([^"]+)"', current
    )
    assert unsupported
    for kind in unsupported:
        _path, current = submit(
            client,
            f"{editor_path}/save",
            current,
            operation="add_change",
            kind=kind,
        )
    blocked = re.search(r'<button[^>]*data-testid="policy-run-submit"[^>]*>', current)
    assert blocked is not None and "disabled" in blocked.group(0)
    assert "not supported in this release" in current.split(
        'data-testid="policy-run-reason"', 1
    )[1][:600]

    _path, doomed = submit(
        client,
        "/policy/scenarios",
        client.get("/policy/scenarios").text,
        name="Delete me",
    )
    submit(client, f"{scenario_path(doomed)}/delete", doomed)

    _path, fence = submit(
        client,
        "/policy/scenarios",
        client.get("/policy/scenarios").text,
        suggestion="fence_height_7ft",
        name="The run",
    )
    fence_path = scenario_path(fence)
    _path, removed = submit(
        client,
        f"{fence_path}/save",
        fence,
        operation="remove_change",
        change_index="0",
    )
    assert 'data-testid="policy-no-changes"' in removed

    _path, fence = submit(
        client,
        "/policy/scenarios",
        client.get("/policy/scenarios").text,
        suggestion="fence_height_7ft",
        name="The run again",
    )
    fence_path = scenario_path(fence)
    _path, renamed = submit(
        client,
        f"{fence_path}/save",
        fence,
        operation="rename",
        name="The run renamed",
    )
    assert "The run renamed" in renamed
    run_path, results = submit(
        client,
        f"{fence_path}/run",
        renamed,
        kind="synthetic_year",
        seed="20261028",
        count="40",
    )
    assert "A person decides every case." in results
    assert "admin-b-lead" not in results
    assert 'data-testid="evidence-panel"' not in results
    closed(results, "policy-explain")
    explain = form_of(results, "policy-explain-form")
    submit(
        client,
        f"{run_path}/explain",
        results,
        expected_version=hidden(explain, "expected_version"),
    )
    draft = form_of(results, "policy-draft-form")
    _path, drafted = submit(
        client,
        f"{run_path}/draft",
        results,
        expected_version=hidden(draft, "expected_version"),
    )
    assert 'data-testid="policy-draft-status"' in drafted

    briefing = client.get(f"{run_path}/briefing")
    assert briefing.status_code == 200
    assert 'data-testid="evidence-panel"' not in briefing.text
    closed(briefing.text, "policy-writer")
    closed(briefing.text, "policy-facts")
    html = client.get(f"{run_path}/briefing/download?format=html")
    assert html.status_code == 200
    markdown = client.get(f"{run_path}/briefing/download?format=md")
    assert markdown.status_code == 200
    writer = form_of(briefing.text, "policy-writer-form")
    _path, written = submit(
        client,
        f"{run_path}/briefing/muse",
        briefing.text,
        expected_version=hidden(writer, "expected_version"),
    )
    closed(written, "policy-writer")

    # A service-target what-if can run, and Save as a draft stays off with a reason.
    _path, targets = submit(
        client,
        "/policy/scenarios",
        client.get("/policy/scenarios").text,
        suggestion="simple_targets_3_days",
        name="Targets only",
    )
    _path, target_run = submit(
        client,
        f"{scenario_path(targets)}/run",
        targets,
        kind="synthetic_year",
        seed="20261028",
        count="20",
    )
    draft_button = re.search(
        r'<button[^>]*data-testid="policy-draft-submit"[^>]*>', target_run
    )
    assert draft_button is not None and "disabled" in draft_button.group(0)
    assert target_run.index('data-testid="policy-draft-submit"') < target_run.index(
        'data-testid="policy-draft-guard"'
    )
    assert "simulation-only" in target_run.split('data-testid="policy-draft-guard"', 1)[1][:300]

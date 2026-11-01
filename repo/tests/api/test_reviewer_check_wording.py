"""The reviewer page cannot be read as "all clear" while blockers stand.

Two defects found by the smoke check (findings 2 and 3):

* "Run application checks" reported the rule outcome ("pass") in a message that
  said "Validation finished", while the same page listed blockers (identity,
  parcel and payer links) that the validation does not measure.
* A passing rule showed its violation message ("Occupancy load is above 49")
  next to "Observed: 42", so a reader saw a failure text on a pass.
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

import html as htmllib
import re

import pytest
from fastapi.testclient import TestClient

from acme_city.ui import view_models

from tests.api.test_pages import (  # noqa: F401  (fixtures)
    client,
    csrf_of,
    environment,
    select_persona,
)


def _run_checks(client: TestClient, application_id: str) -> str:
    select_persona(client, "persona_permit_reviewer")
    page = client.get(f"/permits/{application_id}")
    response = client.post(
        "/ui/actions/permit.evaluate",
        data={
            "application_id": application_id,
            "csrf_token": csrf_of(page.text),
            "next": f"/permits/{application_id}",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    return response.text


def _feedback_message(html: str) -> str:
    match = re.search(r'data-testid="feedback-message"[^>]*>(.*?)<', html, re.S)
    assert match is not None
    return " ".join(htmllib.unescape(match.group(1)).split())


def test_the_check_message_names_the_blockers_that_still_stand(client: TestClient) -> None:
    html = _run_checks(client, "app_synth_001")
    blocker_count = html.count("Blocker</span>")
    assert blocker_count >= 1, "the case under test must list blockers"
    message = _feedback_message(html)
    assert message.startswith("Validation finished")
    assert "outcome '" in message
    assert "rule" in message.lower()
    assert "still prevent" in message or "still prevents" in message
    assert str(blocker_count) in message


def test_the_page_summarises_rule_outcome_and_blockers_together(client: TestClient) -> None:
    html = _run_checks(client, "app_synth_001")
    assert 'data-testid="checks-summary"' in html
    summary = re.search(r'data-testid="checks-summary".*?</p>', html, re.S)
    assert summary is not None
    text = summary.group(0)
    assert "Rule checks" in text and "blocker" in text
    # each blocker is linked from the summary to its row
    assert 'href="#application-blockers"' in text
    assert 'id="application-blockers"' in html


def test_a_passing_rule_shows_its_failure_text_only_as_a_labelled_condition(
    client: TestClient,
) -> None:
    html = _run_checks(client, "app_synth_001")
    table = re.search(r'data-testid="rule-results".*?</table>', html, re.S)
    assert table is not None, "the case under test must show rule results"
    rows = re.findall(r'<tr>\s*<th scope="row">(.*?)</th>(.*?)</tr>', table.group(0), re.S)
    assert rows, "the case under test must show rule results"
    saw_pass = False
    for rule_name, row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        status = re.sub(r"<[^>]+>", "", cells[2]).strip()
        message_cell = re.sub(r"<[^>]+>", "", cells[4]).strip()
        if status == "Passed" and message_cell:
            saw_pass = True
            assert message_cell.startswith("Fails when: "), (rule_name, message_cell)
    assert saw_pass


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            {"status": "pass", "message": "Occupancy load is above 49", "reason": "rule_satisfied"},
            "Fails when: Occupancy load is above 49",
        ),
        (
            {"status": "fail", "message": "Occupancy load is above 49", "reason": "rule_violated"},
            "Failed: Occupancy load is above 49",
        ),
        (
            {"status": "condition", "message": "A condition applies", "reason": "rule_violated"},
            "Condition applies: A condition applies",
        ),
        (
            {"status": "review", "message": "Needs judgment", "reason": "rule_violated"},
            "Needs a person: Needs judgment",
        ),
        (
            {
                "status": "review",
                "message": "Occupancy load is above 49",
                "reason": "missing_input",
                "detail": "the value for 'occupancy_load' was not supplied",
            },
            "Needs a person: the value for 'occupancy_load' was not supplied. "
            "Fails when: Occupancy load is above 49",
        ),
        ({"status": "pass", "message": None, "reason": "rule_satisfied"}, "rule satisfied"),
    ],
)
def test_every_rule_row_type_is_worded_for_its_status(result: dict, expected: str) -> None:
    assert view_models.rule_result_wording(result) == expected

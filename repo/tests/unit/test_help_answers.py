"""The answers of the applicant help assistant, as the applicant reads them.

An answer is one sentence and one citation.  The rule text of the citation
sits behind "Show the rule text", the tokens and the latency of the run are
not shown at all, and the time of the turn is not shown either.  The replay
fixtures of the demonstration hold two direct paragraphs, and their keys
still match the question and the bundle they were written for.
"""
# REQUIRES: PER-04, PER-05, AI-03, AI-04, SEC-03

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.applicant_help.assist import load_replay_fixtures, replay_key  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402

#: The panel page of the assistant.
PANEL_PATH = "/apply/help/panel"

#: The question of the demonstration that has a recorded answer.
FENCE = "Do I need a permit for a 6 ft fence?"

#: A question the recorded answer of the assistant declines.
DECLINE = "Will my fence permit be approved?"

#: The two replay fixtures the answers were rewritten in.
REWRITTEN = (
    "fixtures/replay/applicant-assist/fence-permit-general.json",
    "fixtures/replay/applicant-assist/fence-permit-form.json",
)

#: The hashes of the protected inputs.
HASHES = Path(__file__).resolve().parents[1] / "regression" / "data" / "protected_fixture_hashes.json"


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    """A demonstration database with the City website seeded."""
    return build_environment(
        tmp_path_factory.mktemp("help-answers"), synthetic=False, name="answers.db"
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    """The City website as it runs locally."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def token(client: TestClient) -> str:
    """Return the CSRF token of the panel page."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(PANEL_PATH).text)
    assert match
    return match.group(1)


def ask(client: TestClient, question: str) -> str:
    """Ask a question and return the panel that answers it."""
    response = client.post(
        "/apply/help",
        data={
            "csrf_token": token(client),
            "question": question,
            "conversation_version": "0",
            "conversation_id": "",
            "placement": "popout",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    conversation = re.search(r"conversation=([^&]+)", response.headers["location"]).group(1)
    return client.get(PANEL_PATH, params={"conversation": conversation}).text


def panel_of(page: str) -> str:
    """Return the panel of a rendered page."""
    match = re.search(r'<section class="panel help-panel".*?</section>', page, re.S)
    assert match is not None, "no panel on the page"
    return match.group(0)


# --------------------------------------------------------------- the answers


def test_the_answer_is_one_sentence_and_one_citation(client: TestClient) -> None:
    """The applicant reads a sentence and the name of the rule it comes from."""
    choose(client, "persona_applicant")
    panel = panel_of(ask(client, FENCE))
    sentences = re.findall(
        r'<p data-testid="help-paragraph-text">(.*?)</p>', panel, re.S
    )
    assert len(sentences) == 2, sentences
    for sentence in sentences:
        # One sentence each: the text ends with its full stop and holds no
        # second one.
        assert sentence.rstrip().endswith("."), sentence
        assert sentence.count(".") == 1, sentence
    labels = re.findall(
        r'<p class="muted" data-testid="help-citation-label">(.*?)</p>', panel, re.S
    )
    assert len(labels) == 2, labels
    assert "ACME Code §14-305: Fence height, front yard" in labels[0]
    assert "ACME Code §14-306: Fence height, side and rear yard" in labels[1]


def test_the_rule_text_sits_behind_the_disclosure(client: TestClient) -> None:
    """The quote of the rule is there, and it is behind "Show the rule text"."""
    choose(client, "persona_applicant")
    panel = panel_of(ask(client, FENCE))
    assert panel.count("Show the rule text") == 2
    assert panel.count('data-testid="help-quote"') == 2
    # The whole rule is quoted, and it sits inside a closed disclosure.
    details = re.findall(r"<details>(.*?)</details>", panel, re.S)
    assert len(details) == 2, details
    for disclosure in details:
        assert "Threshold" in disclosure
    # The sentence the applicant reads is the sentence, not the rule dump.
    sentences = re.findall(
        r'<p data-testid="help-paragraph-text">(.*?)</p>', panel, re.S
    )
    for sentence in sentences:
        assert "Applies when" not in sentence


def test_the_answer_carries_no_token_and_no_latency_line(client: TestClient) -> None:
    """The run of the assistant is recorded, never shown."""
    choose(client, "persona_applicant")
    panel = panel_of(ask(client, FENCE))
    assert "muse-source" not in panel
    assert " in · " not in panel
    assert " out" not in panel
    assert " ms" not in panel


def test_the_answer_carries_no_raw_timestamp(client: TestClient) -> None:
    """The time of the turn is not shown to the applicant."""
    choose(client, "persona_applicant")
    panel = panel_of(ask(client, FENCE))
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", panel)


def test_the_answer_says_where_it_came_from(client: TestClient) -> None:
    """The label of a recorded answer names the demonstration."""
    choose(client, "persona_applicant")
    panel = panel_of(ask(client, FENCE))
    assert "Recorded demo answer" in panel
    assert panel.count('data-testid="help-answer-label"') == 1


def test_the_declined_answer_is_one_sentence(client: TestClient) -> None:
    """A refusal is one sentence, and it points at a person."""
    choose(client, "persona_applicant")
    panel = panel_of(ask(client, DECLINE))
    declined = re.search(
        r'<p data-testid="help-declined"[^>]*>(.*?)</p>', panel, re.S
    )
    assert declined is not None
    text = re.sub(r"<[^>]+>", "", declined.group(1)).strip()
    assert text.startswith("The assistant did not answer:"), text
    assert text.count(".") == 1, text


# ----------------------------------------------------------------- the fixtures


def test_the_fence_fixtures_hold_two_direct_paragraphs() -> None:
    """The padding of the recorded answers is gone."""
    for relative in REWRITTEN:
        data = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        answer = data["output"]["answer"]
        assert len(answer) == 2, relative
        for paragraph in answer:
            assert paragraph["text"].count(".") == 1, paragraph["text"]
            assert paragraph["citations"], paragraph


def test_the_replay_keys_of_the_fixtures_still_match() -> None:
    """A fixture replays only for the question and the bundle it was written for."""
    for data in load_replay_fixtures().values():
        context = data.get("context") or {}
        expected = replay_key(
            question=str(data.get("question_key") or ""),
            context={
                "permit_type_key": str(context.get("permit_type_key") or ""),
                "application_reference": str(context.get("application_reference") or ""),
            },
            content_hash=str(data.get("bundle_content_hash") or ""),
        )
        assert data["replay_key"] == expected, data.get("question_key")


def test_the_protected_hash_file_lists_the_rewritten_fixtures() -> None:
    """The guard knows the two fixtures the answers were rewritten in."""
    recorded = json.loads(HASHES.read_text(encoding="utf-8"))
    for relative in REWRITTEN:
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert recorded["files"][relative] == digest, relative

"""Chat 3: escalation counting, the Administrator's answers, restart, privacy.

The applicant's conversation is private.  A member of the City reads only the
escalated part of it, through a help request; nothing the applicant asked
before that is visible to staff, and nothing the applicant asked afterwards.
"""
# REQUIRES: PORTAL-02, PER-04, PER-05, SEC-03

from __future__ import annotations

import re
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from p3c_support import ADMIN, APPLICANT, REVIEWER, STEWARD, build_settings, choose, post_action, seed_help_request, token
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.persistence.models import audit, help as help_models, model_run, permit
from acme_city.persistence.session import SessionFactory, transaction
from acme_city.ui.router import router as ui_router

NONSENSE = ("purple monkey dishwasher", "quantum banana trombone", "velvet lighthouse spaghetti", "marble kangaroo window")
FENCE = "Do I need a permit for a 6 ft fence?"


@pytest.fixture()
def environment(tmp_path):
    return build_settings(tmp_path)


@contextmanager
def running(environment):
    """One run of the server; leaving the block is a restart."""
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def client(environment):
    with running(environment) as test_client:
        yield test_client


def ask(client, question, *, conversation="", version="0", placement="form", path="/apply/help/panel", **extra):
    response = client.post(
        "/apply/help",
        data={
            "csrf_token": token(client, path), "question": question, "conversation_id": conversation,
            "conversation_version": version, "placement": placement, **extra,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    match = re.search(r"(?:help|conversation)=([^&]+)", response.headers["location"])
    return match.group(1), response.headers["location"]


def version_of(environment, conversation_id):
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            return session.get(help_models.HelpConversation, conversation_id).version
    finally:
        factory.dispose()


def panel(client, conversation):
    return client.get("/apply/help/panel", params={"conversation": conversation})


def escalate(client, conversation, version, question, *, path="/apply/help/panel", placement="form", **extra):
    return client.post(
        "/apply/help/escalate",
        data={
            "csrf_token": token(client, path), "conversation_id": conversation,
            "conversation_version": str(version), "question": question, "placement": placement, **extra,
        },
        follow_redirects=False,
    )


# ------------------------------------------------------ escalation counting


def test_the_third_unsuccessful_turn_prompts_ask_the_city(client, environment) -> None:
    choose(client, APPLICANT)
    conversation = ""
    for number, question in enumerate(NONSENSE[:3], start=1):
        version = version_of(environment, conversation) if conversation else 0
        conversation, _ = ask(client, question, conversation=conversation, version=str(version))
        body = panel(client, conversation).text
        assert 'data-testid="help-ask-the-city"' in body  # the button never depends on the prompt
        assert ('data-testid="help-escalation-prompt"' in body) is (number >= 3), number
    assert "could not answer your last 3 questions" in body


def test_a_matched_turn_is_not_counted(client, environment) -> None:
    choose(client, APPLICANT)
    conversation, _ = ask(client, NONSENSE[0])
    conversation, _ = ask(client, FENCE, conversation=conversation, version=str(version_of(environment, conversation)))
    conversation, _ = ask(client, NONSENSE[1], conversation=conversation, version=str(version_of(environment, conversation)))
    assert 'data-testid="help-escalation-prompt"' not in panel(client, conversation).text  # 2 unsuccessful of 3
    ask(client, NONSENSE[2], conversation=conversation, version=str(version_of(environment, conversation)))
    assert 'data-testid="help-escalation-prompt"' in panel(client, conversation).text  # the third unsuccessful


def test_each_unsuccessful_turn_is_counted_once(client, environment) -> None:
    from acme_city.applicant_help.service import ApplicantHelpService

    choose(client, APPLICANT)
    conversation, _ = ask(client, NONSENSE[0])
    conversation, _ = ask(client, NONSENSE[1], conversation=conversation, version=str(version_of(environment, conversation)))
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            service = ApplicantHelpService(session)
            row = session.get(help_models.HelpConversation, conversation)
            assert service.unsuccessful_turn_count(row) == 2
            assert service.escalation_state(row)["unsuccessful"] == 2
    finally:
        factory.dispose()


@pytest.mark.parametrize("words", ["Can I talk to a person please?", "I need a real person to help", "SPEAK   to   someone"])
def test_asking_for_a_person_prompts_at_once(client, words) -> None:
    choose(client, APPLICANT)
    conversation, _ = ask(client, words)
    body = panel(client, conversation).text
    assert 'data-testid="help-escalation-prompt"' in body and 'data-reason="asked_for_a_person"' in body


def test_a_normal_question_does_not_prompt(client) -> None:
    choose(client, APPLICANT)
    conversation, _ = ask(client, FENCE)
    assert 'data-testid="help-escalation-prompt"' not in panel(client, conversation).text


def test_the_prompt_is_in_the_json_answer_and_goes_once_a_request_exists(client, environment) -> None:
    choose(client, APPLICANT)
    conversation = ""
    for question in NONSENSE[:3]:
        version = version_of(environment, conversation) if conversation else 0
        response = client.post(
            "/apply/help",
            data={"csrf_token": token(client, "/apply/help/panel"), "question": question, "conversation_id": conversation,
                  "conversation_version": str(version), "placement": "form"},
            headers={"Accept": "application/json"},
        )
        conversation = response.json()["conversation_id"]
    assert response.json()["escalation"]["offered"] is True and response.json()["escalation"]["unsuccessful"] == 3
    assert escalate(client, conversation, version_of(environment, conversation), NONSENSE[2]).status_code == 303
    assert 'data-testid="help-escalation-prompt"' not in panel(client, conversation).text


# ----------------------------------------------- the whole path, with restarts


def test_ask_answer_and_read_survive_restarts(environment) -> None:
    with running(environment) as client:
        choose(client, APPLICANT)
        conversation = ""
        for question in NONSENSE[:3]:
            version = version_of(environment, conversation) if conversation else 0
            conversation, _ = ask(
                client, question, conversation=conversation, version=str(version),
                placement="track", path="/apply/help/panel", application_id="app_d05", return_ref="SYN-APP-005",
            )
        assert escalate(
            client, conversation, version_of(environment, conversation), NONSENSE[2],
            path="/apply/help/panel", placement="track", application_id="app_d05", return_ref="SYN-APP-005",
        ).status_code == 303
    with running(environment) as client:  # restart 1: the City answers
        choose(client, ADMIN)
        page = client.get("/ops/support").text
        assert page.count('data-testid="help-request-card"') == 1
        assert NONSENSE[2] in page and "SYN-APP-005" in page
        match = re.search(r'name="help_request_id" value="([^"]+)"', page)
        version = re.search(r'name="expected_version" value="(\d+)"', page[page.index("help-answer-form"):]).group(1)
        assert post_action(client, "support.help_request.answer", {
            "help_request_id": match.group(1), "expected_version": version, "reply": "We will look at it today."},
            page="/ops/support").status_code == 200
    with running(environment) as client:  # restart 2: the applicant reads the reply
        choose(client, APPLICANT)
        tracker = client.get(f"/apply/track?ref=SYN-APP-005&help={conversation}").text
        # Changed deliberately (the applicant restyle, A3): the tracker has
        # no panel of its own; the reply reaches the applicant as a message
        # of the City on the case.
        assert "We will look at it today." in tracker
        assert 'data-testid="city-messages"' in tracker
        again = panel(client, conversation).text
        assert 'data-status="answered"' in again
        # the conversation, its version and its ownership are intact
        assert version_of(environment, conversation) >= 4


def test_a_reply_without_a_case_is_shown_in_the_chat_history(environment) -> None:
    with running(environment) as client:
        choose(client, APPLICANT)
        conversation, _ = ask(client, "talk to a person")
        assert escalate(client, conversation, version_of(environment, conversation), "talk to a person").status_code == 303
    with running(environment) as client:
        choose(client, ADMIN)
        page = client.get("/ops/support").text
        request_id = re.search(r'name="help_request_id" value="([^"]+)"', page).group(1)
        assert post_action(client, "support.help_request.answer", {
            "help_request_id": request_id, "expected_version": "1", "reply": "Phone the desk on the fictional number."},
            page="/ops/support").status_code == 200
    with running(environment) as client:
        choose(client, APPLICANT)
        assert "Phone the desk on the fictional number." in panel(client, conversation).text


# -------------------------------------------------------- cross-applicant


def test_another_applicant_cannot_read_ask_on_or_escalate_a_conversation(client, environment) -> None:
    choose(client, APPLICANT)
    conversation, _ = ask(client, NONSENSE[0])
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            session.get(help_models.HelpConversation, conversation).owner_actor_id = "service_applicant_2"
        with factory() as session:
            before = (
                session.get(help_models.HelpConversation, conversation).version,
                len(session.execute(select(help_models.HelpTurn)).scalars().all()),
            )
    finally:
        factory.dispose()
    assert panel(client, conversation).status_code == 404
    refused = client.post(
        "/apply/help",
        data={"csrf_token": token(client, "/apply/help/panel"), "question": "my question", "conversation_id": conversation,
              "conversation_version": str(before[0]), "placement": "form"},
        follow_redirects=False,
    )
    assert refused.status_code == 404
    assert escalate(client, conversation, before[0], "my question").status_code == 404
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            assert len(session.execute(select(help_models.HelpTurn)).scalars().all()) == before[1]
            assert session.execute(select(help_models.HelpRequest)).scalars().all() == []
    finally:
        factory.dispose()


def test_a_help_request_and_its_reply_belong_to_the_applicant_who_asked(client, environment) -> None:
    made = seed_help_request(environment, owner="service_applicant_2", question="OTHER-APPLICANT-QUESTION-4411")
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            row = session.get(help_models.HelpRequest, made["request_id"])
            row.status, row.reply = "answered", "OTHER-APPLICANT-REPLY-4411"
    finally:
        factory.dispose()
    choose(client, APPLICANT)
    for path in ("/apply", "/apply/track?ref=SYN-APP-005", "/apply/deck_fence"):
        body = client.get(path).text
        assert "OTHER-APPLICANT" not in body, path
    assert panel(client, made["conversation_id"]).status_code == 404


# ------------------------------------------------------------ staff leakage

MARKER = "zebra-cabinet-marker-7731"
LATER = "later-question-marker-5520"
EARLIER = "earlier-question-marker-3308"
SECRET_TURN = "unescalated-conversation-marker-9904"


def test_staff_never_read_an_unescalated_conversation(client, environment) -> None:
    choose(client, APPLICANT)
    conversation, _ = ask(client, SECRET_TURN)
    assert SECRET_TURN in panel(client, conversation).text  # positive control: the owner reads it
    seed_help_request(environment, application_id="app_d05", question=MARKER, earlier=(EARLIER,), later=(LATER,))
    pages = [
        "/queue", "/queue/intake", "/queue/early-resolution", "/queue/review", "/admin?tab=log", "/admin",
        "/agent/intake", "/agent/adjudication", "/steward", "/governance", "/applicants", "/insight/city",
        "/permits/app_d05", "/ops/dashboard", "/ops/audit", "/ops/audit?search=helpconv", "/ops/support", "/ops/checks",
        "/api/muse/runs", f"/api/permits/applications/app_d05/comments",
    ]
    for persona in (STEWARD, REVIEWER, ADMIN):
        choose(client, persona)
        for path in pages:
            response = client.get(path)
            assert SECRET_TURN not in response.text, (persona, path)
        # the panel of a conversation is the applicant's alone
        assert panel(client, conversation).status_code in {403, 404}, persona
    # the Administrator reads the escalated snapshot and nothing else
    choose(client, ADMIN)
    support = client.get("/ops/support").text
    assert MARKER in support and EARLIER in support
    assert LATER not in support  # asked after the request
    assert SECRET_TURN not in support


def test_only_the_administrator_reaches_help_requests(client, environment) -> None:
    seed_help_request(environment, question=MARKER)
    for persona in (STEWARD, REVIEWER, APPLICANT):
        choose(client, persona)
        response = client.get("/ops/support")
        assert response.status_code == 403 and MARKER not in response.text, persona


def test_no_audit_row_carries_the_text_of_a_question_or_a_reply(client, environment) -> None:
    choose(client, APPLICANT)
    conversation, _ = ask(client, SECRET_TURN)
    assert escalate(client, conversation, version_of(environment, conversation), SECRET_TURN).status_code == 303
    choose(client, ADMIN)
    page = client.get("/ops/support").text
    request_id = re.search(r'name="help_request_id" value="([^"]+)"', page).group(1)
    post_action(client, "support.help_request.answer", {
        "help_request_id": request_id, "expected_version": "1", "reply": "REPLY-TEXT-MARKER-6612"}, page="/ops/support")
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            dump = " ".join(
                f"{e.reason} {e.denial_reason} {e.metadata_json} {e.references} {e.target_id}"
                for e in session.execute(select(audit.AuditEvent)).scalars()
            )
    finally:
        factory.dispose()
    assert SECRET_TURN not in dump and "REPLY-TEXT-MARKER-6612" not in dump
    assert SECRET_TURN not in client.get("/ops/audit").text


def test_chat_model_runs_stay_out_of_every_staff_view(client, environment) -> None:
    choose(client, APPLICANT)
    ask(client, FENCE)
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            run_ids = session.execute(select(model_run.ModelRun.id)).scalars().all()
    finally:
        factory.dispose()
    assert run_ids
    for persona in (STEWARD, REVIEWER, ADMIN):
        choose(client, persona)
        for path in ("/admin?tab=log", "/agent/intake", "/agent/adjudication", "/permits/app_d05", "/api/muse/runs"):
            body = client.get(path).text
            assert all(run_id not in body for run_id in run_ids), (persona, path)
        for run_id in run_ids:
            assert client.get(f"/detail/muse-run/{run_id}").status_code in {403, 404}


# ----------------------------------------- a request is tied to the applicant's case


def test_a_request_made_on_the_tracker_is_tied_to_the_applicants_case(client, environment) -> None:
    choose(client, APPLICANT)
    response = escalate(
        client, "", 0, "Who reviews my case?", path="/apply/help/panel",
        placement="track", application_id="app_d05", return_ref="SYN-APP-005",
    )
    assert response.status_code == 303
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            (request,) = session.execute(select(help_models.HelpRequest)).scalars().all()
            conversation = session.get(help_models.HelpConversation, request.conversation_id)
            assert request.application_id == "app_d05" == conversation.application_id
            assert conversation.placement == "track"
    finally:
        factory.dispose()


def test_a_request_cannot_be_tied_to_a_case_of_another_applicant(client, environment) -> None:
    choose(client, APPLICANT)
    for application_id in ("app_d02", "app_nope"):
        response = escalate(client, "", 0, "Tie me to their case", application_id=application_id)
        assert response.status_code == 404, application_id
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            assert session.execute(select(help_models.HelpRequest)).scalars().all() == []
            assert session.execute(select(help_models.HelpConversation)).scalars().all() == []
    finally:
        factory.dispose()


def test_a_repeated_ask_the_city_creates_one_request(client, environment) -> None:
    """Retry semantics: the version the applicant read is spent by the first request."""
    choose(client, APPLICANT)
    conversation, _ = ask(client, NONSENSE[0])
    version = version_of(environment, conversation)
    assert escalate(client, conversation, version, NONSENSE[0]).status_code == 303
    assert escalate(client, conversation, version, NONSENSE[0]).status_code == 422
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            assert len(session.execute(select(help_models.HelpRequest)).scalars().all()) == 1
    finally:
        factory.dispose()

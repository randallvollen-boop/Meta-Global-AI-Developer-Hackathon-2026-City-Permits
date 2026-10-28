#!/usr/bin/env python3
"""Write the replay fixtures of the applicant help assistant.

The fixtures of this script are **deterministic, labelled demonstration
fixtures**.  They are not recordings of a Muse answer, they were not produced
by a provider, and they are never presented as one.  Recording real answers
of the assistant for the demonstration is separate work.

Every fixture is written for one exact context:

* a question of the demonstration set;
* the authorized context of the question — the permit type the applicant was
  looking at, or the application they were tracking;
* the published text of the City, through the hash of the source bundle the
  answer was written for.

The server replays a fixture only when all three match, so an answer written
for text the City no longer publishes does not replay: the applicant receives
the deterministic answer instead.

Run it after a change of the published rules, the stored permit-type
configuration or the applicant-facing passages::

    uv run python scripts/build_applicant_assist_fixtures.py

Use ``--check`` to prove that the committed fixtures are the ones the current
published text produces, without writing anything.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from sqlalchemy import select  # noqa: E402

from acme_city.applicant_help.assist import (  # noqa: E402
    normalize_question,
    replay_key,
)
from acme_city.applicant_help.config import load_config  # noqa: E402
from acme_city.applicant_help.sources import build_bundle  # noqa: E402
from acme_city.auth.context import ActorContext  # noqa: E402
from acme_city.auth.permissions import PermissionResolver  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402
from acme_city.fixtures.loader import FixtureBundle  # noqa: E402
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo  # noqa: E402
from acme_city.muse.schemas import (  # noqa: E402
    APPLICANT_ASSIST_PROMPT_VERSION,
    APPLICANT_ASSIST_SCHEMA_VERSION,
    APPLICANT_ASSIST_TASK,
)
from acme_city.persistence.models import permit  # noqa: E402
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment  # noqa: E402
from acme_city.persistence.session import (  # noqa: E402
    SessionFactory,
    initialize_database,
    transaction,
)

#: The version of the fixture set of this demonstration.
FIXTURE_VERSION = "2026.10.28-1"

#: The date the fixture set was written for.
RECORDED_AT = "2026-10-28T00:00:00Z"

#: The note every fixture carries.
NOTE = (
    "A deterministic, labelled demonstration fixture of the applicant help assistant. "
    "It was written for this demonstration against the published text it quotes; it is "
    "not a recording of a Muse answer and it is never presented as one."
)

#: The answers of the demonstration set.
#:
#: Every paragraph names the passages it quotes.  The quote of a passage is
#: resolved from the published text when the fixture is written, so a quote is
#: always verbatim.
def _fence_permit_paragraphs() -> list[dict[str, Any]]:
    """Return the paragraphs of the fence question."""
    return [
        {
            "text": (
                "The published ACME Code limits a fence in the front yard of a "
                "residential lot to 4 ft."
            ),
            "citations": [
                {
                    "source_id": "rule.DF-1.DF-1@1",
                    "quote_lines": ["ACME Code §14-305", "Threshold: 4."],
                }
            ],
        },
        {
            "text": (
                "For the side and the rear yard of the same residential lot the "
                "published limit is 6 ft."
            ),
            "citations": [
                {
                    "source_id": "rule.DF-2.DF-2@1",
                    "quote_lines": ["ACME Code §14-306", "Threshold: 6."],
                }
            ],
        },
    ]


def _shed_documents_paragraphs() -> list[dict[str, Any]]:
    """Return the paragraphs of the shed question."""
    return [
        {
            "text": (
                "A shed or accessory building asks for a site sketch or site plan "
                "and a material specification."
            ),
            "citations": [
                {
                    "source_id": "permit_type.shed",
                    "quote_lines": ["Required documents:"],
                }
            ],
        },
        {
            "text": (
                "Each permit type has its own checklist, and a PDF, PNG, JPG or plain "
                "text file of at most 5 MB is accepted for each document."
            ),
            "citations": [
                {
                    "source_id": "steps.documents",
                    "quote_lines": ["Documents:"],
                }
            ],
        },
    ]


def _fence_timing_paragraphs() -> list[dict[str, Any]]:
    """Return the paragraphs of the timing question."""
    return [
        {
            "text": "The City aims to review a residential deck or fence case in 5 days.",
            "citations": [
                {
                    "source_id": "service_target.deck_fence",
                    "quote_lines": ["Service target for Residential deck or fence"],
                }
            ],
        },
        {
            "text": (
                "That figure is the target the City works to. It makes no promise "
                "about your application and gives no completion date."
            ),
            "citations": [
                {
                    "source_id": "service_target.deck_fence",
                    "quote_lines": ["This is the fictional number of days"],
                }
            ],
        },
    ]


def _needs_information_paragraphs() -> list[dict[str, Any]]:
    """Return the paragraphs of the lifecycle question."""
    return [
        {
            "text": (
                "It means the City could not assess your application yet. Open your "
                "application to see what is missing, then send the answer and the "
                "documents the City asked for."
            ),
            "citations": [
                {
                    "source_id": "lifecycle.needs_information",
                    "quote_lines": ["'The City needs more information' means"],
                }
            ],
        },
        {
            "text": (
                "Sending the answer creates a new revision, and the City assesses "
                "the new revision from the start."
            ),
            "citations": [
                {
                    "source_id": "steps.answering_the_city",
                    "quote_lines": ["Answering the City:"],
                }
            ],
        },
    ]


def _what_next_paragraphs() -> list[dict[str, Any]]:
    """Return the paragraphs of the next-step question."""
    return [
        {
            "text": (
                "Choose the project that matches your work in the list of permit "
                "types, and have the parcel number and the address of the work ready."
            ),
            "citations": [
                {
                    "source_id": "steps.before_you_apply",
                    "quote_lines": ["Before you apply:"],
                }
            ],
        },
        {
            "text": (
                "After you submit, keep the reference number the confirmation page "
                "gives you and use it to track your application at any time."
            ),
            "citations": [
                {
                    "source_id": "steps.after_you_submit",
                    "quote_lines": ["After you submit:"],
                }
            ],
        },
    ]


FIXTURES: tuple[dict[str, Any], ...] = (
    {
        "name": "fence-permit-general",
        "question": "Do I need a permit for a 6 ft fence?",
        "context": {"permit_type_key": "", "application_reference": ""},
        "answer": _fence_permit_paragraphs()
        + [
            {
                "text": (
                    "A limit says where it applies; it does not settle your project. The "
                    "City checks your application against the published rules, and the "
                    "intake agent looks for missing items, unreadable documents and "
                    "duplicates before the case goes to a reviewer."
                ),
                "citations": [
                    {
                        "source_id": "lifecycle.received",
                        "quote_lines": ["The City has your application."],
                    }
                ],
            }
        ],
    },
    {
        "name": "fence-permit-form",
        "question": "Do I need a permit for a 6 ft fence?",
        "context": {"permit_type_key": "deck_fence", "application_reference": ""},
        "answer": _fence_permit_paragraphs()
        + [
            {
                "text": (
                    "This permit type is the one for a residential deck, fence or other "
                    "yard structure, and it is reviewed at the counter."
                ),
                "citations": [
                    {
                        "source_id": "permit_type.deck_fence",
                        "quote_lines": ["Residential deck or fence (deck_fence)"],
                    }
                ],
            }
        ],
    },
    {
        "name": "shed-documents-general",
        "question": "What documents do I need for a shed?",
        "context": {"permit_type_key": "", "application_reference": ""},
        "answer": _shed_documents_paragraphs(),
    },
    {
        "name": "shed-documents-form",
        "question": "What documents do I need for a shed?",
        "context": {"permit_type_key": "shed", "application_reference": ""},
        "answer": _shed_documents_paragraphs(),
    },
    {
        "name": "fence-timing-general",
        "question": "How long will my fence permit take?",
        "context": {"permit_type_key": "", "application_reference": ""},
        "answer": _fence_timing_paragraphs(),
    },
    {
        "name": "fence-timing-form",
        "question": "How long will my fence permit take?",
        "context": {"permit_type_key": "deck_fence", "application_reference": ""},
        "answer": _fence_timing_paragraphs(),
    },
    {
        "name": "needs-information-general",
        "question": "What does 'needs information' mean?",
        "context": {"permit_type_key": "", "application_reference": ""},
        "answer": _needs_information_paragraphs(),
    },
    {
        "name": "what-next-general",
        "question": "What do I do next?",
        "context": {"permit_type_key": "", "application_reference": ""},
        "answer": _what_next_paragraphs(),
    },
    {
        # The demonstration case of a refusal.  The recorded output is a valid
        # refusal with one reason of the fixed list; the applicant sees the
        # reason, the matching rule text and the button to ask the City.
        "name": "decline-approval-general",
        "question": "Will my fence permit be approved?",
        "context": {"permit_type_key": "", "application_reference": ""},
        "decline": "needs_a_person",
        "answer": [],
    },
    {
        "name": "decline-approval-form",
        "question": "Will my fence permit be approved?",
        "context": {"permit_type_key": "deck_fence", "application_reference": ""},
        "decline": "needs_a_person",
        "answer": [],
    },
    {
        # The demonstration case of the fallback.  The recorded output
        # deliberately fails the validation: its quote is not the text of the
        # passage it names.  The applicant therefore receives the deterministic
        # answer, which is the point of the fixture.
        "name": "fallback-demo-general",
        "question": "Show me the ACME rule text for a fence",
        "context": {"permit_type_key": "", "application_reference": ""},
        "answer": [
            {
                "text": (
                    "The published ACME Code limits a fence in the front yard of a "
                    "residential lot to 4 ft."
                ),
                "citations": [
                    {
                        "source_id": "rule.DF-1.DF-1@1",
                        "quote_lines": ["ACME Code §14-305"],
                        "deliberately_wrong_quote": (
                            "ACME Code §14-305 — Fence height in the front yard is 4 feet."
                        ),
                    }
                ],
            }
        ],
    },
)


def context_for(session, actor_id: str) -> ActorContext:
    """Return the server-resolved context of a seeded persona."""
    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


def resolve_quote(text: str, prefixes: list[str]) -> str:
    """Return the block of a passage that carries the named lines.

    The block runs from the first named line to the last one, so the quote is
    a verbatim part of the passage.
    """
    lines = text.split("\n")
    index = 0
    for prefix in prefixes:
        while index < len(lines) and not lines[index].startswith(prefix):
            index += 1
        if index >= len(lines):
            raise SystemExit(f"the passage does not carry the line {prefix!r}")
        index += 1
    start = 0
    for position, line in enumerate(lines):
        if line.startswith(prefixes[0]):
            start = position
            break
    end = start
    for position, line in enumerate(lines):
        if line.startswith(prefixes[-1]):
            end = position
            break
    return "\n".join(lines[start : end + 1])


def build_fixtures(output: Path, *, check: bool) -> int:
    """Write the fixtures of the demonstration set."""
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        settings = Settings.load(
            environ={
                "ACME_DATABASE_URL": f"sqlite:///{tmp / 'assist-fixtures.db'}",
                "ACME_SECRET_KEY": "assist-fixture-builder-secret-value",
            },
            key_file=tmp / "missing.env",
        )
        initialize_database(settings)
        bundle = FixtureBundle.load()
        factory = SessionFactory(settings.database_url)
        written = 0
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
            with factory() as session:
                applicant = context_for(session, "persona_applicant")
                for template in FIXTURES:
                    application_id = ""
                    context = dict(template["context"])
                    if context["application_reference"]:
                        row = session.execute(
                            select(permit.Application).where(
                                permit.Application.source_application_number
                                == context["application_reference"]
                            )
                        ).scalar_one()
                        application_id = row.id
                    built = build_bundle(
                        session,
                        applicant,
                        config=load_config(),
                        permit_type_key=context["permit_type_key"],
                        application_id=application_id,
                    )
                    answer: list[dict[str, Any]] = []
                    for paragraph in template["answer"]:
                        citations: list[dict[str, Any]] = []
                        for citation in paragraph["citations"]:
                            source = built.source(citation["source_id"])
                            if source is None:
                                raise SystemExit(
                                    f"the bundle does not carry {citation['source_id']!r}"
                                )
                            quote = citation.get("deliberately_wrong_quote") or resolve_quote(
                                source.text, list(citation["quote_lines"])
                            )
                            citations.append(
                                {"source_id": source.source_id, "quote": quote}
                            )
                        answer.append(
                            {"text": paragraph["text"], "citations": citations}
                        )
                    document = {
                        "fixture_kind": "applicant_assist_replay",
                        "fixture_version": FIXTURE_VERSION,
                        "note": NOTE,
                        "task": APPLICANT_ASSIST_TASK,
                        "prompt_version": APPLICANT_ASSIST_PROMPT_VERSION,
                        "schema_version": APPLICANT_ASSIST_SCHEMA_VERSION,
                        "recorded_at": RECORDED_AT,
                        "question_key": normalize_question(template["question"]),
                        "context": context,
                        "bundle_content_hash": built.content_hash,
                        "replay_key": replay_key(
                            question=template["question"],
                            context=context,
                            content_hash=built.content_hash,
                        ),
                        "output": {
                            "answer": answer,
                            "next_steps": [],
                            "cannot_answer": bool(template.get("decline")),
                            "reason": str(template.get("decline") or ""),
                        },
                    }
                    path = output / f"{template['name']}.json"
                    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False)
                    text += "\n"
                    if check:
                        if not path.is_file():
                            raise SystemExit(f"the fixture {path.name} is missing")
                        if path.read_text(encoding="utf-8") != text:
                            raise SystemExit(
                                f"the fixture {path.name} does not match the published text"
                            )
                        print(f"unchanged  {path.name}")
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(text, encoding="utf-8")
                        print(f"written    {path.name}")
                    written += 1
        finally:
            factory.dispose()
    print(f"{written} fixture(s) of the applicant help assistant")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the builder."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "fixtures" / "replay" / "applicant-assist"),
        help="the directory the fixtures are written to",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="prove that the committed fixtures match the published text",
    )
    arguments = parser.parse_args(argv)
    return build_fixtures(Path(arguments.output), check=arguments.check)


if __name__ == "__main__":
    raise SystemExit(main())

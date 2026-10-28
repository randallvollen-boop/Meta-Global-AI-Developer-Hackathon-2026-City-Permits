"""The deterministic matcher of the applicant help assistant.

The matcher is a stable ranking over the source bundle: the same question
always produces the same passages, a question that matches nothing produces
an explicit no-match, and a passage that shares only a word of its text with
the question is not a match.
"""

from __future__ import annotations

from acme_city.applicant_help.matching import (
    KIND_LIMITS,
    numbers_of,
    rank_passages,
    tokenize,
)

PASSAGES: list[dict[str, object]] = [
    {
        "source_id": "rule.DF-2.DF-2@1",
        "kind": "rule",
        "title": "ACME Code §14-306 — Fence height, side and rear yard",
        "version": "DF-2@1",
        "citation": "ACME Code §14-306",
        "text": (
            "ACME Code §14-306 — Fence height, side and rear yard\n"
            "Checks: Fence height (ft).\nOperator: must not be more than.\nThreshold: 6."
        ),
        "keywords": ["df-2", "deck_fence", "height_ft", "Fence height (ft)"],
        "facts": {"threshold": "6"},
    },
    {
        "source_id": "rule.DF-1.DF-1@1",
        "kind": "rule",
        "title": "ACME Code §14-305 — Fence height, front yard",
        "version": "DF-1@1",
        "citation": "ACME Code §14-305",
        "text": (
            "ACME Code §14-305 — Fence height, front yard\n"
            "Checks: Fence height (ft).\nOperator: must not be more than.\nThreshold: 4."
        ),
        "keywords": ["df-1", "deck_fence", "height_ft", "Fence height (ft)"],
        "facts": {"threshold": "4"},
    },
    {
        "source_id": "permit_type.deck_fence",
        "kind": "permit_type",
        "title": "Residential deck or fence (deck_fence)",
        "version": "deck_fence@1",
        "citation": "",
        "text": "Residential deck or fence (deck_fence)\nRequired documents: Site sketch.",
        "keywords": ["deck_fence", "Residential deck or fence", "Site sketch or site plan"],
        "facts": {},
    },
    {
        "source_id": "lifecycle.unrelated",
        "kind": "lifecycle",
        "title": "Something else",
        "version": "config@1",
        "citation": "",
        "text": "A passage that shares only a word of its text with the question.",
        "keywords": ["unrelated"],
        "facts": {},
    },
]


def test_the_words_of_a_question_drop_the_words_that_carry_no_meaning() -> None:
    assert tokenize("Do I need a permit for a 6 ft fence?") == (
        "need",
        "permit",
        "6",
        "ft",
        "fence",
    )
    assert tokenize("What do I do next?") == ("next",)


def test_a_question_finds_the_rule_that_carries_its_number() -> None:
    matches = rank_passages(PASSAGES, "Do I need a permit for a 6 ft fence?", limit=3)
    assert matches[0].source_id == "rule.DF-2.DF-2@1"
    assert "fence" in matches[0].matched_terms


def test_the_ranking_is_stable_for_the_same_question() -> None:
    first = rank_passages(PASSAGES, "Do I need a permit for a 6 ft fence?", limit=3)
    second = rank_passages(PASSAGES, "Do I need a permit for a 6 ft fence?", limit=3)
    assert [match.source_id for match in first] == [match.source_id for match in second]


def test_a_question_that_matches_nothing_returns_no_passage() -> None:
    assert rank_passages(PASSAGES, "banana", limit=3) == []
    assert rank_passages(PASSAGES, "", limit=3) == []


def test_a_passage_that_shares_only_a_word_of_its_text_is_not_a_match() -> None:
    matches = rank_passages(PASSAGES, "question", limit=3)
    assert "lifecycle.unrelated" not in {match.source_id for match in matches}


def test_the_answer_quotes_at_most_one_figure() -> None:
    passages = [
        {
            "source_id": f"service_target.{name}",
            "kind": "service_target",
            "title": f"Service target for {name}",
            "version": f"{name}@1",
            "citation": "",
            "text": f"Service target for {name}: 5 days.",
            "keywords": [name, "target", "days", "long", "take"],
            "facts": {},
        }
        for name in ("deck_fence", "shed", "patio")
    ]
    matches = rank_passages(passages, "how long will it take", limit=3)
    assert len(matches) == 1
    assert KIND_LIMITS["service_target"] == 1


def test_the_numbers_of_a_text_are_read() -> None:
    assert numbers_of("a 6 ft fence and 2.5 inches") == (6.0, 2.5)

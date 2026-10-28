"""The deterministic matcher of the applicant help assistant.

The matcher ranks the passages of a source bundle against the words of the
applicant's question.  It is a plain, stable ranking:

* a word of the question that is a **keyword** of a passage counts double;
* a word of the question that appears in the **text** of a passage counts once;
* a passage whose threshold is the number the question names counts again,
  because the applicant asked about that number;
* a passage matches only when it shares at least one **keyword** with the
  question: a word of its text alone is not a match;
* the passages are ordered by the score, and a passage with the same score is
  ordered by its identifier, so the same question always produces the same
  answer;
* the answer quotes at most one **figure** (a service target), because two
  targets of two types would answer a question the applicant did not ask;
* a passage that reaches the threshold is a match, and a question that reaches
  no passage at all is an explicit **no-match** result rather than a guess.

The matcher never writes, never calls a model and never decides anything.
"""
# REQUIRES: UX-02, PER-04
# The matcher is a stable ranking over the source bundle; a question that
# matches nothing produces an explicit no-match result.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

#: The words of a question that carry no meaning for the matcher.
STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "at",
        "be",
        "been",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "me",
        "might",
        "may",
        "my",
        "of",
        "on",
        "or",
        "our",
        "please",
        "shall",
        "should",
        "so",
        "tell",
        "that",
        "the",
        "their",
        "them",
        "these",
        "they",
        "this",
        "those",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whose",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)

#: The score a passage needs before it counts as a match.
MINIMUM_SCORE = 2

#: The weight of a word that is a keyword of the passage.
KEYWORD_WEIGHT = 2

#: The weight of a word that appears in the text of the passage.
TEXT_WEIGHT = 1

#: The weight of a passage whose threshold is the number the question names.
#:
#: A question that names a number is about the rule that carries that number,
#: and the passage that carries it says what the number applies to.
THRESHOLD_WEIGHT = 3

#: How many passages of one kind an answer may quote.
#:
#: The answer quotes at most one **figure**: two service targets of two
#: different types would answer a question the applicant did not ask.  The
#: other kinds may repeat, because two rules of one type both apply.
KIND_LIMITS: dict[str, int] = {
    "case": 3,
    "lifecycle": 2,
    "permit_type": 2,
    "rule": 3,
    "service_target": 1,
    "steps": 2,
}

_WORDS = re.compile(r"[a-z0-9]+")
_NUMBERS = re.compile(r"\d+(?:\.\d+)?")


def tokenize(text: str) -> tuple[str, ...]:
    """Return the meaningful words of a text, lowercased and in order.

    A single letter carries no meaning and is dropped; a number is kept,
    because a limit is part of the question an applicant asks.
    """
    words = _WORDS.findall(str(text or "").lower())
    return tuple(
        word for word in words if word not in STOPWORDS and (len(word) > 1 or word.isdigit())
    )


def keyword_set(values: Iterable[str]) -> frozenset[str]:
    """Return the keyword set of a passage."""
    words: set[str] = set()
    for value in values:
        words.update(tokenize(value))
    return frozenset(words)


@dataclass(frozen=True)
class Match:
    """One passage that matches the question."""

    source_id: str
    title: str
    version: str
    citation: str
    text: str
    score: int
    matched_terms: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return the match as a plain mapping."""
        return {
            "source_id": self.source_id,
            "title": self.title,
            "version": self.version,
            "citation": self.citation,
            "text": self.text,
            "score": self.score,
            "matched_terms": list(self.matched_terms),
        }


@dataclass(frozen=True)
class _Scored:
    """One passage with its score, used while the ranking is built."""

    source_id: str
    kind: str
    title: str
    version: str
    citation: str
    text: str
    score: int
    matched_terms: tuple[str, ...]
    keyword_hits: int = 0


def numbers_of(text: str) -> tuple[float, ...]:
    """Return the numbers a text names."""
    found: list[float] = []
    for token in _NUMBERS.findall(str(text or "")):
        try:
            found.append(float(token))
        except ValueError:
            continue
    return tuple(found)


def score_passage(
    *,
    source_id: str,
    kind: str,
    title: str,
    version: str,
    citation: str,
    text: str,
    keywords: frozenset[str],
    terms: frozenset[str],
    question_numbers: tuple[float, ...] = (),
    threshold: str = "",
) -> _Scored:
    """Return the score of one passage against the words of a question."""
    text_tokens = frozenset(tokenize(text))
    score = 0
    matched: list[str] = []
    keyword_hits = 0
    for term in sorted(terms):
        if term in keywords:
            score += KEYWORD_WEIGHT
            keyword_hits += 1
            matched.append(term)
        elif term in text_tokens:
            score += TEXT_WEIGHT
            matched.append(term)
    if threshold and question_numbers:
        limits = numbers_of(threshold)
        if limits and any(limit in question_numbers for limit in limits):
            score += THRESHOLD_WEIGHT
    return _Scored(
        source_id=source_id,
        kind=kind,
        title=title,
        version=version,
        citation=citation,
        text=text,
        score=score,
        matched_terms=tuple(matched),
        keyword_hits=keyword_hits,
    )


def rank_passages(
    passages: Sequence[dict[str, Any]],
    question: str,
    *,
    limit: int,
    minimum_score: int = MINIMUM_SCORE,
) -> list[Match]:
    """Return the passages that match a question, best first.

    Args:
        passages: The passages of the source bundle.  Each one carries a
            ``source_id``, a ``kind``, a ``title``, a ``version``, a
            ``citation``, a ``text``, its ``keywords`` and, for a rule, the
            threshold it carries.
        question: The applicant's question.
        limit: The number of passages to return.
        minimum_score: The score a passage needs to count as a match.

    Returns:
        The matching passages, ordered by the score and then by the source
        identifier.  An empty list means the question matched nothing.
    """
    terms = frozenset(tokenize(question))
    if not terms:
        return []
    question_numbers = numbers_of(question)
    scored: list[_Scored] = []
    for passage in passages:
        keywords = keyword_set(passage.get("keywords") or [])
        facts = passage.get("facts") or {}
        scored.append(
            score_passage(
                source_id=str(passage.get("source_id", "")),
                kind=str(passage.get("kind", "")),
                title=str(passage.get("title", "")),
                version=str(passage.get("version", "")),
                citation=str(passage.get("citation", "")),
                text=str(passage.get("text", "")),
                keywords=keywords,
                terms=terms,
                question_numbers=question_numbers,
                threshold=str(facts.get("threshold", "")),
            )
        )
    scored = [
        row
        for row in scored
        if row.score >= minimum_score and row.keyword_hits > 0
    ]
    scored.sort(key=lambda row: (-row.score, row.source_id))
    kept: list[_Scored] = []
    counts: dict[str, int] = {}
    for row in scored:
        limit_for_kind = KIND_LIMITS.get(row.kind, limit)
        used = counts.get(row.kind, 0)
        if used >= limit_for_kind:
            continue
        counts[row.kind] = used + 1
        kept.append(row)
        if len(kept) >= max(0, limit):
            break
    return [
        Match(
            source_id=row.source_id,
            title=row.title,
            version=row.version,
            citation=row.citation,
            text=row.text,
            score=row.score,
            matched_terms=row.matched_terms,
        )
        for row in kept
    ]


__all__ = [
    "KEYWORD_WEIGHT",
    "KIND_LIMITS",
    "MINIMUM_SCORE",
    "STOPWORDS",
    "TEXT_WEIGHT",
    "THRESHOLD_WEIGHT",
    "Match",
    "keyword_set",
    "numbers_of",
    "rank_passages",
    "score_passage",
    "tokenize",
]

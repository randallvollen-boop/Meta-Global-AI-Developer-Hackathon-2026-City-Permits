"""The applicant-help configuration.

The configuration holds the fixed applicant-facing passages, the notice the
assistant shows, the rate limit and the suggested questions.  The rules are
**not** here: the assistant reads the published rule versions the City
stores, so a draft rule can never reach an applicant.

The passages are short, they are written for an applicant, and each one has
an identifier and a set of keywords the deterministic matcher uses.
"""
# REQUIRES: UX-02, PER-04
# The passages of the assistant are fixed configuration with identifiers; the
# rules they quote come from the published catalogue, never from a draft.

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acme_city.core.errors import ValidationError

#: The repository root that holds ``config/``.
REPO_ROOT = Path(__file__).resolve().parents[3]

#: The name of the configuration document.
CONFIG_FILE = "applicant_help.json"


@dataclass(frozen=True)
class Passage:
    """One fixed passage the assistant may quote."""

    source_id: str
    title: str
    text: str
    keywords: tuple[str, ...] = ()
    status: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the passage as a plain mapping."""
        return {
            "source_id": self.source_id,
            "title": self.title,
            "text": self.text,
            "keywords": list(self.keywords),
            "status": self.status,
        }


@dataclass(frozen=True)
class HelpConfig:
    """The validated applicant-help configuration."""

    notice: str
    fallback_label: str
    no_match_text: str
    rate_limit_questions: int
    rate_limit_window_minutes: int
    max_message_length: int
    history_turns: int
    max_matches: int
    suggested_questions: tuple[tuple[str, str], ...]
    lifecycle_passages: tuple[Passage, ...]
    steps_passages: tuple[Passage, ...]
    #: The label of an answer a live run produced.
    live_label: str = ""
    #: The label of an answer a replay fixture produced.
    replay_label: str = ""
    #: The fixed list of reasons the assistant may refuse with.
    refusal_reasons: tuple[str, ...] = ()
    #: The suggested questions that are offered in demonstration mode only.
    demo_questions: tuple[tuple[str, str], ...] = ()
    #: The plain sentence shown for each refusal reason.
    refusal_texts: tuple[tuple[str, str], ...] = ()

    def refusal_text(self, reason: str) -> str:
        """Return the sentence of a refusal reason, or an empty string."""
        return dict(self.refusal_texts).get(reason, "")

    def passage(self, source_id: str) -> Passage | None:
        """Return one passage by its identifier."""
        for passage in self.lifecycle_passages + self.steps_passages:
            if passage.source_id == source_id:
                return passage
        return None

    def questions(self, *, demo_mode: bool) -> tuple[tuple[str, str], ...]:
        """Return the suggested questions of the panel.

        The demonstration offers one more question than a live deployment:
        the one that shows the deterministic fallback on purpose.
        """
        if demo_mode:
            return self.suggested_questions + self.demo_questions
        return self.suggested_questions


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(
            f"the applicant help configuration is missing: {path.name}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"the applicant help configuration is not valid JSON: {path.name}"
        ) from exc


def _passages(entries: Any, *, kind: str) -> tuple[Passage, ...]:
    """Return the validated passages of one group."""
    if not isinstance(entries, list):
        raise ValidationError(f"the applicant help {kind} passages must be a list")
    passages: list[Passage] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValidationError(f"an applicant help {kind} passage is not an object")
        source_id = str(entry.get("id", "")).strip()
        title = str(entry.get("title", "")).strip()
        text = str(entry.get("text", "")).strip()
        if not source_id or not title or not text:
            raise ValidationError(
                f"an applicant help {kind} passage needs an id, a title and a text"
            )
        if source_id in seen:
            raise ValidationError(f"the applicant help passage {source_id!r} is listed twice")
        seen.add(source_id)
        keywords = tuple(
            str(word).strip().lower()
            for word in (entry.get("keywords") or [])
            if str(word).strip()
        )
        passages.append(
            Passage(
                source_id=source_id,
                title=title,
                text=text,
                keywords=keywords,
                status=str(entry.get("status", "")).strip(),
            )
        )
    return tuple(passages)


def load_config(path: Path | str | None = None) -> HelpConfig:
    """Return the validated applicant-help configuration.

    Args:
        path: The configuration document to read.  Defaults to the committed
            ``config/applicant_help.json``.

    Raises:
        ValidationError: when the document is missing or malformed.
    """
    target = Path(path) if path is not None else REPO_ROOT / "config" / CONFIG_FILE
    document = _read_json(target)
    if not isinstance(document, dict):
        raise ValidationError("the applicant help configuration must be an object")
    limit = document.get("rate_limit") or {}
    if not isinstance(limit, dict):
        raise ValidationError("the applicant help rate limit must be an object")
    questions = limit.get("questions")
    window = limit.get("window_minutes")
    if not isinstance(questions, int) or questions < 1:
        raise ValidationError("the applicant help rate limit needs a positive question count")
    if not isinstance(window, int) or window < 1:
        raise ValidationError("the applicant help rate limit needs a positive window")
    max_length = document.get("max_message_length")
    if not isinstance(max_length, int) or max_length < 1:
        raise ValidationError("the applicant help message limit must be positive")
    history_turns = document.get("history_turns")
    if not isinstance(history_turns, int) or history_turns < 1:
        raise ValidationError("the applicant help history limit must be positive")
    max_matches = document.get("max_matches")
    if not isinstance(max_matches, int) or max_matches < 1:
        raise ValidationError("the applicant help match limit must be positive")
    suggestions: list[tuple[str, str]] = []
    for entry in document.get("suggested_questions") or []:
        if not isinstance(entry, dict):
            raise ValidationError("a suggested question is not an object")
        identifier = str(entry.get("id", "")).strip()
        text = str(entry.get("text", "")).strip()
        if not identifier or not text:
            raise ValidationError("a suggested question needs an id and a text")
        suggestions.append((identifier, text))
    notice = str(document.get("notice", "")).strip()
    if not notice:
        raise ValidationError("the applicant help configuration needs a notice")
    fallback_label = str(document.get("fallback_label", "")).strip()
    if not fallback_label:
        raise ValidationError("the applicant help configuration needs a fallback label")
    no_match_text = str(document.get("no_match_text", "")).strip()
    if not no_match_text:
        raise ValidationError("the applicant help configuration needs a no-match text")
    assist = document.get("assist") or {}
    if not isinstance(assist, dict):
        raise ValidationError("the applicant help assistant section must be an object")
    live_label = str(assist.get("live_label", "")).strip()
    if not live_label:
        raise ValidationError("the applicant help configuration needs a live label")
    replay_label = str(assist.get("replay_label", "")).strip()
    if not replay_label:
        raise ValidationError("the applicant help configuration needs a replay label")
    reasons = assist.get("refusal_reasons")
    if not isinstance(reasons, list) or not reasons:
        raise ValidationError(
            "the applicant help configuration needs the list of refusal reasons"
        )
    refusal_reasons = tuple(str(reason).strip() for reason in reasons if str(reason).strip())
    if not refusal_reasons:
        raise ValidationError("the applicant help refusal reasons may not be empty")
    demo_questions: list[tuple[str, str]] = []
    for entry in assist.get("demo_questions") or []:
        if not isinstance(entry, dict):
            raise ValidationError("a demonstration question is not an object")
        identifier = str(entry.get("id", "")).strip()
        text = str(entry.get("text", "")).strip()
        if not identifier or not text:
            raise ValidationError("a demonstration question needs an id and a text")
        demo_questions.append((identifier, text))
    texts = assist.get("refusal_texts") or {}
    if not isinstance(texts, dict):
        raise ValidationError("the applicant help refusal texts must be an object")
    refusal_texts = tuple(
        (str(key).strip(), str(value).strip()) for key, value in sorted(texts.items())
    )
    for reason in refusal_reasons:
        if not dict(refusal_texts).get(reason):
            raise ValidationError(
                f"the refusal reason {reason!r} has no sentence in the configuration"
            )
    return HelpConfig(
        notice=notice,
        fallback_label=fallback_label,
        no_match_text=no_match_text,
        rate_limit_questions=questions,
        rate_limit_window_minutes=window,
        max_message_length=max_length,
        history_turns=history_turns,
        max_matches=max_matches,
        suggested_questions=tuple(suggestions),
        lifecycle_passages=_passages(document.get("lifecycle_passages"), kind="lifecycle"),
        steps_passages=_passages(document.get("steps_passages"), kind="steps"),
        live_label=live_label,
        replay_label=replay_label,
        refusal_reasons=refusal_reasons,
        demo_questions=tuple(demo_questions),
        refusal_texts=refusal_texts,
    )


__all__ = [
    "CONFIG_FILE",
    "REPO_ROOT",
    "HelpConfig",
    "Passage",
    "load_config",
]

"""The screens of the steward assistant: the controls and the evidence panel.

The assistant prepares a recommendation; the steward decides.  This module
builds what the screens show: the state of the assistant, the controls the
steward may press, and the evidence panel of one recommendation.

The module holds no decision and no write: it reads the stored
recommendations and the awake state of the assistant, and it says why a
control is unavailable.
"""
# REQUIRES: UX-01, PER-04

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from acme_city.agents import steward_assist as assistant
from acme_city.agents.control import agent_mode
from acme_city.auth.context import ActorContext
from acme_city.fixtures.loader import REPO_ROOT
from acme_city.persistence.models import agent as agent_models
from acme_city.registry import steward_assist as recommenders
from acme_city.ui import steward_queue_views
from acme_city.ui import view_models

#: The committed display configuration, which holds the plain words of every
#: kind of evidence.
_DISPLAY_PATH = REPO_ROOT / "config" / "ui_display.json"

#: The note a steward reads when the assistant sleeps.  The wake and sleep
#: switch belongs to the Agent Operator alone.
SLEEP_NOTE = (
    "The steward assistant is asleep, so it prepares no new recommendation. "
    "The Agent Operator must wake it."
)

#: The label of a recommendation that was prepared while the assistant was
#: awake and is shown after the assistant was put back to sleep.
AWAKE_NOTE = "Made while awake"

#: The grant the Data Steward holds to ask the assistant for a
#: recommendation.
RUN_PERMISSION = "agent.run.steward_assist"

#: The most tasks one press of the assistant prepares.
MAX_TASKS_PER_PRESS = assistant.MAX_TASKS_PER_PRESS


def is_awake(session: Any) -> bool:
    """Return whether the steward assistant is awake."""
    return agent_mode(session, assistant.AGENT_KEY) == agent_models.AGENT_AWAKE


def may_run(session: Any, actor: ActorContext) -> bool:
    """Return whether the acting persona may ask the assistant to work."""
    return view_models.holds_grant(session, actor, RUN_PERMISSION)


def _lines(pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Return the evidence lines, without the empty ones."""
    return [{"label": label, "value": value} for label, value in pairs if value]


@lru_cache(maxsize=1)
def _evidence_phrases() -> dict[str, str]:
    """Return the plain words of every kind of evidence."""
    return dict(
        json.loads(_DISPLAY_PATH.read_text(encoding="utf-8")).get("evidence_methods", {})
    )


def _mapping(value: Any) -> str:
    """Return a mapping of values as one readable line."""
    if not isinstance(value, dict) or not value:
        return ""
    return ", ".join(f"{key}: {item}" for key, item in sorted(value.items()))


def _score(value: Any) -> str:
    """Return a score in the words of the screen."""
    if value is None:
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _phrase(method: str) -> str:
    """Return the plain words of one kind of evidence."""
    text = str(_evidence_phrases().get(method, ""))
    if text:
        return text
    return method.replace("_", " ").capitalize()


def _methods(items: Any) -> str:
    """Return the plain words of the evidence methods of a list.

    The first phrase keeps its capital; the ones after it join the sentence.
    """
    if not isinstance(items, list):
        return ""
    words = []
    for item in items:
        if isinstance(item, dict):
            method = str(item.get("method") or "")
            words.append(_phrase(method) if method else str(item.get("detail") or ""))
        else:
            words.append(str(item))
    phrases = [word for word in words if word]
    if len(phrases) > 1:
        phrases = [phrases[0]] + [
            phrase[:1].lower() + phrase[1:] if phrase else phrase for phrase in phrases[1:]
        ]
    return ", ".join(phrases)


def evidence_lines(kind: str, evidence: dict[str, Any]) -> list[dict[str, str]]:
    """Return the evidence of a recommendation, in the words of the screen.

    The panel shows the facts the assistant read: the record it compared,
    the score it found, the thresholds the City applies and the facts that
    agree or disagree.  It never shows a key of the machinery.
    """
    data = dict(evidence or {})
    if kind == "link":
        return _lines(
            [
                ("Source record", str(data.get("source_record_id", ""))),
                ("Master record", str(data.get("candidate_label", ""))),
                ("Matcher score", _score(data.get("score"))),
                ("Next best score", _score(data.get("next_best_score"))),
                ("Line the City applies links on", _score(data.get("auto_apply_threshold"))),
                ("Line the City suggests on", _score(data.get("suggest_threshold"))),
                ("What agrees", _methods(data.get("agreements"))),
                ("What disagrees", _methods(data.get("disagreements"))),
            ]
        )
    if kind == "automatic_link":
        return _lines(
            [
                ("Source record", str(data.get("source_record_id", ""))),
                ("Master record", str(data.get("entity_label", ""))),
                ("Score", _score(data.get("score"))),
                ("Policy version", str(data.get("policy_version", ""))),
                ("What agrees", _methods(data.get("agreements"))),
                ("What disagrees", _methods(data.get("disagreements"))),
            ]
        )
    if kind == "parcel":
        candidates = data.get("candidates") or []
        return _lines(
            [
                ("Submitted address", str(data.get("submitted_text", ""))),
                ("Address the locator found", str(data.get("matched_address", ""))),
                ("Parcel", str(data.get("parcel_number", ""))),
                ("Parcel the application names", str(data.get("stated_parcel", ""))),
                ("Locator score", _score(data.get("score"))),
                (
                    "Other parcels that fit",
                    ", ".join(
                        f"{item.get('parcel_number', '')} ({_score(item.get('score'))})"
                        for item in candidates
                        if isinstance(item, dict)
                    ),
                ),
                ("Difference between the two parcels", str(data.get("conflict", ""))),
            ]
        )
    if kind == "case":
        return _lines(
            [
                ("Destination", str(data.get("destination", ""))),
                ("Value the source holds today", _mapping(data.get("current_value"))),
                ("Value the correction proposes", _mapping(data.get("proposed_value"))),
                (
                    "Version the correction was raised against",
                    str(data.get("expected_version", "")),
                ),
                ("Version the source holds today", str(data.get("current_version", ""))),
            ]
        )
    if kind == "issue":
        return _lines(
            [
                ("Kind of issue", str(data.get("issue_type", ""))),
                ("Record the issue is about", str(data.get("subject_id", ""))),
                ("Who has to act", str(data.get("owner", ""))),
                ("What the City recorded", str(data.get("description", ""))),
                ("Draft of the request to the source", str(data.get("request_draft", ""))),
            ]
        )
    return []


def recommendation_view(
    session: Any, recommendation: Any
) -> dict[str, Any]:
    """Return what the task page shows about one recommendation."""
    awake = is_awake(session)
    stale = assistant.is_stale(session, recommendation)
    is_held = recommendation.confidence == "held"
    return {
        "id": recommendation.id,
        "confidence": recommendation.confidence,
        "confidence_label": steward_queue_views.recommendation_label(
            recommendation.confidence
        ),
        "pill": steward_queue_views.RECOMMENDATION_PILLS.get(
            recommendation.confidence, ""
        ),
        "outcome": recommendation.outcome,
        "reason": recommendation.reason,
        "made_at": recommendation.made_at,
        "made_by": recommendation.made_by_actor_id,
        "run_id": str((recommendation.evidence or {}).get("run_id") or ""),
        "evidence": evidence_lines(recommendation.task_kind, recommendation.evidence),
        "stale": stale,
        "held": is_held,
        # A recommendation that was prepared while the assistant was awake
        # keeps its meaning after the assistant was put back to sleep, so the
        # steward still sees what it says.
        "made_while_awake": not awake,
        "awake_note": AWAKE_NOTE,
    }


def assistant_state(session: Any, actor: ActorContext) -> dict[str, Any]:
    """Return the state of the assistant and what the steward may press."""
    awake = is_awake(session)
    may = may_run(session, actor)
    return {
        "awake": awake,
        "may_run": may,
        "can_prepare": may and awake,
        "sleep_note": SLEEP_NOTE,
        "grant_note": (
            ""
            if may
            else "Your role cannot ask the steward assistant for a recommendation."
        ),
    }


def case_panel(
    session: Any, actor: ActorContext, kind: str, item_id: str
) -> dict[str, Any]:
    """Return what the task page shows about the steward assistant.

    The panel carries the recommendation the assistant prepared, the evidence
    it read and the controls the steward may press.  A recommendation that is
    held for a person is shown with its reason, but it is never accepted by
    a button.
    """
    state = assistant_state(session, actor)
    row = assistant.recommendation_for(session, kind, item_id)
    panel = dict(state)
    panel["recommendation"] = {}
    panel["has_recommendation"] = row is not None
    # The assistant prepares the work of five kinds of task.  A task of any
    # other kind carries no control, so the panel says nothing it cannot do.
    panel["supported"] = kind in recommenders.TASK_KINDS
    panel["prepare_label"] = (
        "Prepare the recommendation again" if row is not None else "Get recommendation"
    )
    if row is None or not panel["supported"]:
        return panel
    recommendation = recommendation_view(session, row)
    panel["recommendation"] = recommendation
    # A held recommendation is never accepted: the person reads the
    # conflicting facts and uses the normal controls of the case.
    panel["can_accept"] = (
        state["may_run"] and not recommendation["held"] and not recommendation["stale"]
    )
    panel["can_clear"] = state["may_run"]
    return panel


__all__ = [
    "AWAKE_NOTE",
    "MAX_TASKS_PER_PRESS",
    "RUN_PERMISSION",
    "SLEEP_NOTE",
    "assistant_state",
    "case_panel",
    "evidence_lines",
    "is_awake",
    "may_run",
    "recommendation_view",
]

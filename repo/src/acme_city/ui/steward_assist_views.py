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

import hashlib
import hmac
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

#: The note a steward reads when no recommendation may be accepted in a batch.
#:
#: The button is off, and the note says why: there is nothing the assistant
#: is sure enough about, or the persona may not accept a batch at all.
BATCH_EMPTY_NOTE = (
    "No recommendation is sure enough to accept without reading it, so there is "
    "nothing to accept in a batch."
)

#: The note a steward reads when the persona may not accept a batch.
BATCH_GRANT_NOTE = "Your role cannot accept a batch of recommendations."

#: The days the agreement figure counts.
AGREEMENT_DAYS = 7

#: The note a steward reads when the assistant prepared nothing lately.
AGREEMENT_EMPTY_NOTE = (
    "The steward assistant prepared no recommendation in the last 7 days, so there "
    "is no agreement to report."
)

#: The note beside the button of Muse when a live call may not be sent.
EXPLAIN_OFF_NOTE = (
    "Live Muse is off in this deployment, so the assistant's reason stands."
)

#: The note beside the button of Muse when no credential is configured.
EXPLAIN_NO_KEY_NOTE = (
    "No provider credential is configured, so the assistant's reason stands."
)

#: The note beside the button of Muse when a live call may be sent.
EXPLAIN_ON_NOTE = (
    "Muse rewrites the reason in plain words. It never changes the decision or "
    "the certainty of the recommendation."
)

#: The field the preview of a batch carries for every item of the list.
#:
#: The value names the recommendation and the version the preview showed, so a
#: confirmation that names another list, or another version of a
#: recommendation, cannot pass for the one the steward read.
PREVIEW_FIELD = "preview_item"

#: The field that carries the proof that the confirmed list is the list the
#: preview showed.
PREVIEW_DIGEST_FIELD = "preview_digest"

#: The message of a confirmation that does not match the preview.
PREVIEW_MISMATCH_MESSAGE = (
    "the list you confirmed is not the list you were shown; open the preview "
    "again and confirm the list it shows"
)


def preview_value(recommendation_id: str, version: int) -> str:
    """Return the posted value of one item of the preview."""
    return f"{recommendation_id}:{int(version)}"


def preview_digest(settings: Any, items: list[str]) -> str:
    """Return the proof that a list of previewed items is the list of the preview.

    The proof is a signature of the list under the secret of the deployment, so
    a client cannot confirm a list the server never showed.  The list itself
    travels with the form; the proof says the server issued it.
    """
    secret = ""
    if settings is not None:
        key = getattr(settings, "secret_key", None)
        secret = key.get_secret_value() if key is not None else ""
    material = "|".join(sorted(str(item) for item in items))
    return hmac.new(
        secret.encode("utf-8"),
        f"steward-batch-preview:{material}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]


def preview_confirmed(settings: Any, items: list[str], presented: str) -> bool:
    """Whether a confirmed list is the list the preview showed.

    The proof of the preview has to match the list that was confirmed.  A
    list that is shorter, longer or different in any item has another proof,
    so it is not the list of the preview.
    """
    if not presented or not presented.isascii():
        return False
    return hmac.compare_digest(preview_digest(settings, items), presented)


def explain_state(session: Any, settings: Any) -> dict[str, Any]:
    """Return whether a live call may be sent, and the note when it may not.

    The button of Muse is off when the deployment forbids a live call, when
    no credential is configured and when the live-call budget is spent.  The
    note says which of them it is.
    """
    from acme_city.agents import steward_explain

    if settings is None or not getattr(settings, "provider_enabled", False):
        return {"available": False, "note": EXPLAIN_OFF_NOTE}
    if getattr(settings, "meta_api_key", None) is None:
        return {"available": False, "note": EXPLAIN_NO_KEY_NOTE}
    blocked = steward_explain.gate_error(session, settings)
    if blocked is not None:
        return {
            "available": False,
            "note": (
                f"No live call may be sent: {blocked}. "
                "The assistant's reason stands."
            ),
        }
    return {"available": True, "note": EXPLAIN_ON_NOTE}


def agreement_figure(session: Any) -> dict[str, Any]:
    """Return the share of the recommendations the steward accepted unchanged.

    The figure counts the recommendations the assistant prepared in the last
    seven days and the ones the steward accepted among them without changing
    the reason.  A recommendation the steward rewrote, changed or ignored
    lowers the share, so the figure shows how much of the assistant's work the
    steward agreed with.

    The counts the figure is made of are shown beside it, so a reader never
    sees a percentage without the numbers behind it.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from acme_city.core.clock import utc_now
    from acme_city.persistence.models import audit
    from acme_city.persistence.models.steward_recommendation import StewardRecommendation

    cutoff = utc_now() - timedelta(days=AGREEMENT_DAYS)
    rows = session.execute(
        select(StewardRecommendation).where(StewardRecommendation.made_at >= cutoff)
    ).scalars().all()
    total = len(rows)
    if not total:
        return {
            "days": AGREEMENT_DAYS,
            "accepted": 0,
            "total": 0,
            "share": "",
            "note": AGREEMENT_EMPTY_NOTE,
        }
    # Only an acceptance that left the reason of the assistant alone counts.
    # The decision recorded the comparison when it was taken.
    accepted_ids = {
        str((event.metadata_json or {}).get("recommendation_id") or "")
        for event in session.execute(
            select(audit.AuditEvent).where(
                audit.AuditEvent.action == "steward.recommendation.accept"
            )
        ).scalars()
        if (event.metadata_json or {}).get("reason_unchanged") is True
    }
    accepted = sum(1 for row in rows if row.id in accepted_ids)
    share = round(accepted * 100 / total)
    return {
        "days": AGREEMENT_DAYS,
        "accepted": accepted,
        "total": total,
        "share": f"{share}%",
        "note": (
            f"You accepted {accepted} of the {total} recommendation"
            f"{'' if total == 1 else 's'} the assistant prepared in the last "
            f"{AGREEMENT_DAYS} days without changing the reason."
        ),
    }


def task_labels(session: Any, actor: ActorContext) -> dict[tuple[str, str], str]:
    """Return the name of every task of the queue, keyed by its kind and id.

    The names are the words of the queue, so the preview of a batch reads the
    same way as the queue the steward came from.
    """
    from acme_city.ui import steward_views

    return {
        (issue.kind, issue.item_id): issue.title
        for issue in steward_views.collect_issues(session, actor)
    }


def batch_state(
    session: Any,
    actor: ActorContext,
    *,
    with_items: bool = True,
    settings: Any = None,
) -> dict[str, Any]:
    """Return the batch the steward may accept, and the items it holds.

    The batch holds the recommendations the assistant is sure of and whose
    decision the steward can take back.  Nothing is accepted before the
    steward confirms the list the preview shows.

    The queue only shows how many recommendations the batch holds, so it
    asks for the count alone: the names of the tasks are read only for the
    preview.

    Every item of the preview carries the version of its recommendation, and
    the preview carries the proof of the list.  A confirmation that names
    another list, or another version of a recommendation, is not the
    confirmation of this preview.
    """
    may = may_run(session, actor)
    rows = assistant.batch_candidates(session) if may else []
    labels = task_labels(session, actor) if rows and with_items else {}
    items = []
    for row in rows:
        items.append(
            {
                "id": row.id,
                "version": int(row.version),
                "task_kind": row.task_kind,
                "task_id": row.task_id,
                "label": labels.get((row.task_kind, row.task_id), row.task_id),
                "reason": row.reason,
                "outcome": row.outcome,
                "confidence": row.confidence,
            }
        )
    note = ""
    if not may:
        note = BATCH_GRANT_NOTE
    elif not items:
        note = BATCH_EMPTY_NOTE
    return {
        "may_batch": may,
        "count": len(items),
        "recommendations": items,
        "note": note,
        "empty_note": BATCH_EMPTY_NOTE,
        "preview_field": PREVIEW_FIELD,
        "preview_digest_field": PREVIEW_DIGEST_FIELD,
        "preview_digest": preview_digest(
            settings, [preview_value(item["id"], item["version"]) for item in items]
        ),
    }


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
        # The plain words Muse wrote, when the steward asked for them.  The
        # deterministic reason of the assistant stays the reason of the
        # recommendation.
        "muse_reason": recommendation.muse_reason or "",
        "muse_run_id": recommendation.muse_run_id or "",
        "reason_text": recommendation.muse_reason or recommendation.reason,
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
    session: Any, actor: ActorContext, kind: str, item_id: str, settings: Any = None
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
    explain = explain_state(session, settings)
    panel["explain_note"] = explain["note"]
    panel["can_explain"] = False
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
    # Muse only rewrites the words of the recommendation, so it may be asked
    # for a recommendation the steward reads but may not accept.
    panel["can_explain"] = state["may_run"] and explain["available"]
    return panel


__all__ = [
    "AGREEMENT_DAYS",
    "AGREEMENT_EMPTY_NOTE",
    "AWAKE_NOTE",
    "BATCH_EMPTY_NOTE",
    "BATCH_GRANT_NOTE",
    "EXPLAIN_NO_KEY_NOTE",
    "EXPLAIN_OFF_NOTE",
    "EXPLAIN_ON_NOTE",
    "MAX_TASKS_PER_PRESS",
    "PREVIEW_DIGEST_FIELD",
    "PREVIEW_FIELD",
    "PREVIEW_MISMATCH_MESSAGE",
    "RUN_PERMISSION",
    "SLEEP_NOTE",
    "agreement_figure",
    "assistant_state",
    "batch_state",
    "case_panel",
    "evidence_lines",
    "explain_state",
    "is_awake",
    "may_run",
    "preview_confirmed",
    "preview_digest",
    "preview_value",
    "recommendation_view",
    "task_labels",
]

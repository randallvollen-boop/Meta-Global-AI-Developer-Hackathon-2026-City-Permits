"""The presentation of the automatic linking settings of the Data Steward.

The screen answers three questions: what the automation does right now, what
the thresholds read for the accepted source records, and how the policy is
changed.  Every figure it shows is a recorded one, and the mode it reports is
the mode the deployment really runs in: a policy on its own never links a
record, and the worker that applies a policy is not part of this release.

The preview reads the recorded candidate score of every accepted source
record in the scope and compares it with the thresholds of the policy.  It
changes nothing, and a score is never a decision: the identity checks and a
person decide every link.
"""
# REQUIRES: UX-01, UX-02, SEC-01
# The screen reads recorded state and offers the three controls of the
# policy: the preview, the activation and the pause.  It never decides a
# link and it never writes a source fact.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.persistence.models import governance, registry, registry_automation, source
from acme_city.registry import automation, candidates
from acme_city.registry.automation_policy import (
    DEFAULT_THRESHOLDS,
    SafetyChecks,
    Thresholds,
    evaluate_link,
)
from acme_city.ui import view_models

#: The modes a steward may activate, with the words the screen shows.  The
#: suggestions mode is not one of them: a suggestion reaches no one in this
#: release, so the screen does not offer it.
ACTIVATE_MODES: tuple[tuple[str, str], ...] = (("active", "Apply eligible links"),)

#: The words the screen uses for the mode of a stored policy.  A policy that
#: records suggestions only still names its mode, so a steward reads what the
#: record holds.
POLICY_MODE_LABELS: dict[str, str] = {
    "paused": "Paused",
    "suggestions": "Records suggestions only",
    "active": "Apply eligible links",
}

#: The status line of every mode the screen reports.
MODE_STATUS: dict[str, str] = {
    "paused": "Automatic linking is paused",
    "active": "Automatic linking applies eligible links",
}

#: The plain name of each record family.
FAMILY_LABELS: dict[str, str] = {
    "owner_party": "Owner or organization",
    "contractor_party": "Contractor",
    "parcel": "Parcel",
    "address": "Address",
}

#: The number of accepted records the preview shows at most.
PREVIEW_LIMIT = 20

#: The state of an applied link and the words the screen shows.
APPLICATION_STATUS_LABELS: dict[str, str] = {
    "applied": "Waiting for review",
    "acknowledged": "Reviewed",
    "reversed": "Taken back",
    "superseded": "Superseded",
}

#: Every safety check of the policy, passed.
#:
#: The preview reads the recorded score and the thresholds of the policy.
#: It does not run the identity checks, and the page says so: a person
#: decides every link.
SCORE_ONLY = SafetyChecks(
    source_accepted_current=True,
    source_contract_eligible=True,
    target_exists_with_correct_type=True,
    identifier_namespace_known=True,
    required_identity_fields_present=True,
    no_identity_conflict=True,
    no_protected_manual_decision=True,
    comparison_current=True,
    no_active_link_replacement=True,
    undo_supported=True,
    permissions_granted=True,
    unique_target=True,
    corroborating_identity_evidence=True,
)

#: What each decision of the policy reads on the screen, and why.
READINGS: dict[str, tuple[str, str]] = {
    "auto_apply": (
        "would apply",
        "the score reaches the automatic application threshold",
    ),
    "suggest": (
        "would suggest",
        "the score does not reach the automatic application threshold",
    ),
    "ignore": (
        "would ignore",
        "the score is below the suggestion threshold",
    ),
}

#: The reason of a decision that is not a plain score reading.
REASON_TEXT: dict[str, str] = {
    "no_candidate": "no candidate was found",
    "party_score_gap": "another candidate is too close to this one",
}


def _when(moment: datetime | None) -> str:
    """Return a recorded moment in words a reader can place."""
    if moment is None:
        return ""
    return moment.strftime("%d %B %Y at %H:%M UTC")


def thresholds_for(
    family: str,
    policy: registry_automation.RegistryAutomationPolicy | None,
) -> Thresholds:
    """Return the thresholds of one record family, from the policy or the defaults."""
    default = DEFAULT_THRESHOLDS.get(family)
    stored = (policy.thresholds or {}).get(family) if policy is not None else None
    if default is None:
        return Thresholds(auto_apply=1.0, suggest=0.0)
    if not isinstance(stored, dict):
        return default
    try:
        return Thresholds(
            auto_apply=float(stored["auto_apply"]),
            suggest=float(stored["suggest"]),
            score_min=default.score_min,
            score_max=default.score_max,
        )
    except (KeyError, TypeError, ValueError):
        return default


def dataset_options(session: Session) -> list[dict[str, Any]]:
    """Return the datasets a policy may cover, with their registered label."""
    labels = _dataset_labels(session)
    return [
        {
            "key": key,
            "label": labels.get(key, key.replace("_", " ")),
            "family": family,
        }
        for key, family in automation.DATASET_TARGET_FAMILIES.items()
    ]


def _dataset_labels(session: Session) -> dict[str, str]:
    """Return the registered label of every dataset a policy may cover."""
    rows = session.execute(
        select(governance.SourceContract.dataset_key, governance.SourceContract.label)
    ).all()
    return {key: label for key, label in rows}


def threshold_rows(
    policy: registry_automation.RegistryAutomationPolicy | None,
) -> list[dict[str, Any]]:
    """Return the thresholds of the screen, one row per record family."""
    rows: list[dict[str, Any]] = []
    for family in sorted(set(automation.DATASET_TARGET_FAMILIES.values())):
        thresholds = thresholds_for(family, policy)
        rows.append(
            {
                "family": family,
                "label": FAMILY_LABELS.get(family, family),
                "auto_apply": f"{thresholds.auto_apply:g}",
                "suggest": f"{thresholds.suggest:g}",
            }
        )
    return rows


def policy_view(
    session: Session,
    policy: registry_automation.RegistryAutomationPolicy | None,
) -> dict[str, Any] | None:
    """Return the active policy as the screen shows it."""
    if policy is None:
        return None
    labels = _dataset_labels(session)
    scope = list(policy.source_scopes or [])
    return {
        "version": policy.version,
        "mode": policy.mode,
        "mode_label": POLICY_MODE_LABELS.get(policy.mode, "Paused"),
        "scope": scope,
        "scope_labels": [labels.get(key, key) for key in scope],
        "reason": policy.reason,
        "actor": view_models.actor_label(session, policy.recorded_by_actor_id),
        "activated_at": _when(policy.activated_at),
        "matcher_version": policy.matcher_version,
    }


def last_run(session: Session) -> dict[str, Any]:
    """Return the newest completed run of the worker, if there is one."""
    job = session.execute(
        select(registry_automation.RegistryAutomationJob)
        .where(registry_automation.RegistryAutomationJob.status == "completed")
        .order_by(registry_automation.RegistryAutomationJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    completed = int(
        session.execute(
            select(func.count())
            .select_from(registry_automation.RegistryAutomationJob)
            .where(registry_automation.RegistryAutomationJob.status == "completed")
        ).scalar_one()
        or 0
    )
    return {"at": job.created_at if job is not None else None, "completed": completed}


def _effective_mode(
    deployment_mode: str,
    policy: registry_automation.RegistryAutomationPolicy | None,
) -> tuple[str, str]:
    """Return the mode the automation really runs in, and the reason for it."""
    if policy is None:
        return "paused", (
            "No policy is active yet. A steward has to activate one before the "
            "automation may link a record."
        )
    if deployment_mode == "paused":
        return "paused", (
            "The policy below is active, but this deployment runs the automation "
            "paused, so no source record is queued for the worker."
        )
    if policy.mode == "paused":
        return "paused", "The active policy is paused."
    if deployment_mode == "suggestions" or policy.mode == "suggestions":
        return "paused", (
            "The active policy records suggestions only, and this release does "
            "not deliver them to a steward, so no link is applied."
        )
    return "active", (
        "The active policy applies the links that pass every check, and a person "
        "reviews each one."
    )


def state(
    session: Session,
    actor: ActorContext,
    *,
    policy: registry_automation.RegistryAutomationPolicy | None,
    deployment_mode: str,
) -> dict[str, Any]:
    """Return the state of the automation as the screen shows it."""
    mode, reason = _effective_mode(deployment_mode, policy)
    datasets = dataset_options(session)
    labels = {item["key"]: item["label"] for item in datasets}
    run = last_run(session)
    scope = list(policy.source_scopes or []) if policy is not None else []
    return {
        "status": MODE_STATUS[mode],
        "reason": reason,
        "mode": mode,
        "running_mode": (
            "Paused. No source record is queued for the worker."
            if deployment_mode == "paused"
            else "Paused. This deployment records suggestions, which this release "
            "does not deliver to the steward."
            if deployment_mode == "suggestions"
            else "Running. The worker may apply the eligible links."
        ),
        "policy": policy_view(session, policy),
        "policy_version": automation.newest_policy_version(session),
        "scope": scope,
        "scope_labels": [labels.get(key, key) for key in scope],
        "last_run": run,
        "last_run_text": (
            f"The last completed job was recorded on {_when(run['at'])}."
            if run["at"] is not None
            else "No run has completed yet."
        ),
        "datasets": datasets,
        "thresholds": threshold_rows(policy),
        "modes": ACTIVATE_MODES,
        "can_activate": view_models.holds_grant(
            session, actor, automation.ACTIVATE_ACTION, automation.POLICY_DOMAIN
        ),
        "can_pause": view_models.holds_grant(
            session, actor, automation.PAUSE_ACTION, automation.POLICY_DOMAIN
        ),
    }


def preview(
    session: Session,
    *,
    policy: registry_automation.RegistryAutomationPolicy | None,
    scope: list[str],
) -> dict[str, Any]:
    """Return what the thresholds read for the accepted source records.

    The preview changes nothing.  It reads the recorded candidate score of
    every accepted source record in the scope and compares it with the
    thresholds of the policy.
    """
    rows = session.execute(
        select(source.SourceSnapshot)
        .where(source.SourceSnapshot.record_status == "accepted")
        .order_by(
            source.SourceSnapshot.source_dataset_id,
            source.SourceSnapshot.source_record_id,
            source.SourceSnapshot.created_at.desc(),
        )
    ).scalars().all()
    labels = {item["key"]: item["label"] for item in dataset_options(session)}
    # One row per source record: the newest accepted version of it.
    latest: dict[tuple[str, str], source.SourceSnapshot] = {}
    for row in rows:
        if row.source_dataset_id not in scope:
            continue
        latest.setdefault((row.source_dataset_id, row.source_record_id), row)
    rows: list[dict[str, Any]] = []
    for row in list(latest.values())[:PREVIEW_LIMIT]:
        family = automation.DATASET_TARGET_FAMILIES.get(
            row.source_dataset_id, "owner_party"
        )
        candidate_set = candidates.generate_candidates(
            session,
            row.raw_payload or {},
            candidates.entity_target_for(row.source_dataset_id),
            row.source_snapshot_id,
        )
        best = candidate_set.candidates[0] if candidate_set.candidates else None
        next_best = (
            candidate_set.candidates[1].score
            if len(candidate_set.candidates) > 1
            else None
        )
        evaluation = evaluate_link(
            target_family=family,
            score=best.score if best is not None else None,
            checks=SCORE_ONLY,
            next_best_score=next_best,
            thresholds=thresholds_for(family, policy),
        )
        reading, why = READINGS[evaluation.decision.value]
        rows.append(
            {
                "record": row.source_record_id,
                "dataset": row.source_dataset_id,
                "label": labels.get(row.source_dataset_id, row.source_dataset_id),
                "candidate": best.entity_id if best is not None else "",
                "score": best.score if best is not None else None,
                "score_text": f"{best.score:.2f}" if best is not None else "",
                "reading": (
                    reading if best is not None else "no candidate"
                ),
                "reason": (
                    REASON_TEXT.get(
                        evaluation.reasons[0] if evaluation.reasons else "", why
                    )
                    if best is not None
                    else "no candidate was found"
                ),
            }
        )
    return {
        "rows": rows,
        "total": len(latest),
        "shown": len(rows),
        "scope": scope,
    }


def _entity_label(session: Session, entity_id: str) -> str:
    """Return the name of the canonical entity a link points at."""
    party = session.get(registry.Party, entity_id)
    if party is not None:
        return party.display_name
    entity = session.execute(
        select(registry.CanonicalEntity).where(
            registry.CanonicalEntity.entity_id == entity_id
        )
    ).scalar_one_or_none()
    return entity.label if entity is not None and entity.label else entity_id


def application_row(
    session: Session,
    application: registry_automation.RegistryAutomationApplication,
) -> dict[str, Any]:
    """Return one applied link as the screens show it.

    The row names the service that applied the link, the steward whose policy
    authorized it and the evidence the decision was built from.  A score is
    shown as a score, never as a probability.
    """
    view = automation.application_view(session, application)
    evaluation = session.get(
        registry_automation.RegistryAutomationEvaluation, view.evaluation_id
    )
    evidence = dict(evaluation.evidence or {}) if evaluation is not None else {}
    return {
        "application_id": view.application_id,
        "crosswalk_id": view.crosswalk_id or "",
        "entity_id": view.entity_id,
        "entity_label": _entity_label(session, view.entity_id),
        "entity_type": view.entity_type,
        "source_system": view.source_system_id,
        "dataset": view.source_dataset_key or "",
        "record": view.source_record_id,
        "status": view.status,
        "status_label": APPLICATION_STATUS_LABELS.get(view.status, view.status),
        "score": view.score,
        "score_text": f"{view.score:.2f}" if view.score is not None else "",
        "score_scale": view.score_scale,
        "decision": view.decision,
        "policy_version": view.policy_version,
        "applied_at": view.applied_at,
        "applied_at_text": _when(view.applied_at),
        "applied_by": view.applied_by_actor_id,
        "authorized_by": view.authorized_by_actor_id or "",
        "reasons": list(view.reasons),
        "failed_checks": list(view.failed_checks),
        "supporting": list(evidence.get("supporting") or []),
        "conflicting": list(evidence.get("conflicting") or []),
        "review_note": view.review_note or "",
        "reviewed_by": view.reviewed_by_actor_id or "",
        "reviewed_at": view.reviewed_at,
    }


def application_rows(session: Session, *, limit: int) -> list[dict[str, Any]]:
    """Return the applied links, newest first, at most ``limit`` of them."""
    rows = [
        application_row(session, application)
        for application in automation.applications(session)
    ]
    rows.sort(key=lambda row: str(row["applied_at"]), reverse=True)
    return rows[: max(0, limit)]


__all__ = [
    "ACTIVATE_MODES",
    "APPLICATION_STATUS_LABELS",
    "FAMILY_LABELS",
    "MODE_STATUS",
    "POLICY_MODE_LABELS",
    "PREVIEW_LIMIT",
    "application_row",
    "application_rows",
    "dataset_options",
    "last_run",
    "policy_view",
    "preview",
    "state",
    "threshold_rows",
    "thresholds_for",
]

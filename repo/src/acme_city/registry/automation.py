"""Durable enqueue seam and the policy versions of the steward automation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import ConflictError, ValidationError
from acme_city.core.ids import new_id
from acme_city.persistence.models import change, registry, registry_automation, source
from acme_city.registry.automation_policy import DEFAULT_THRESHOLDS
from acme_city.registry.schemas import (
    AutomaticApplicationView,
    AutomaticLinkCommand,
)

MATCHER_VERSION = "registry-candidates-v1"

DATASET_TARGET_FAMILIES: dict[str, str] = {
    "applicant_profiles": "owner_party",
    "applications_and_permits": "owner_party",
    "business_licensing_register": "owner_party",
    "contractor_register": "contractor_party",
    "parcel_register": "parcel",
    "address_register": "address",
}

#: The permission a steward needs to activate a policy.
ACTIVATE_ACTION = "registry.automation.activate"

#: The permission a steward needs to pause the automation.
PAUSE_ACTION = "registry.automation.pause"

#: The domain the policy of the automation governs.
POLICY_DOMAIN = "applicants"

#: The modes a policy version may carry.
POLICY_MODES: tuple[str, ...] = ("paused", "suggestions", "active")


def active_policy(session: Session) -> registry_automation.RegistryAutomationPolicy | None:
    """Return the newest active policy, if a steward has activated one."""
    return session.execute(
        select(registry_automation.RegistryAutomationPolicy)
        .where(registry_automation.RegistryAutomationPolicy.status == "active")
        .order_by(
            registry_automation.RegistryAutomationPolicy.version.desc(),
            registry_automation.RegistryAutomationPolicy.created_at.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()


def enqueue_accepted_snapshot(
    session: Session,
    snapshot: source.SourceSnapshot,
    *,
    dataset_key: str,
    automation_mode: str = "paused",
    now: datetime | None = None,
) -> registry_automation.RegistryAutomationJob | None:
    """Enqueue an eligible accepted snapshot once, in the caller's transaction."""
    mode = automation_mode.strip().lower()
    if mode == "paused":
        return None
    if mode not in {"suggestions", "active"}:
        raise ValueError("registry automation mode must be paused, suggestions, or active")
    if snapshot.record_status != "accepted":
        return None
    target_family = DATASET_TARGET_FAMILIES.get(dataset_key)
    if target_family is None:
        return None
    policy = active_policy(session)
    if policy is None:
        return None
    if policy.mode == "paused" or dataset_key not in policy.source_scopes:
        return None

    existing = session.execute(
        select(registry_automation.RegistryAutomationJob).where(
            registry_automation.RegistryAutomationJob.source_snapshot_id
            == snapshot.source_snapshot_id,
            registry_automation.RegistryAutomationJob.target_family == target_family,
            registry_automation.RegistryAutomationJob.matcher_version == MATCHER_VERSION,
            registry_automation.RegistryAutomationJob.policy_id == policy.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    job = registry_automation.RegistryAutomationJob(
        id=new_id("autojob"),
        source_snapshot_id=snapshot.source_snapshot_id,
        target_family=target_family,
        matcher_version=MATCHER_VERSION,
        policy_id=policy.id,
        status="pending",
        attempts=0,
        available_at=now or utc_now(),
        claimed_at=None,
        finished_at=None,
        last_error=None,
    )
    session.add(job)
    session.flush()
    return job


#: The action the audit trail records for an automatic application.
APPLY_ACTION = "registry.crosswalk.apply_automatic"

#: The kind of the review task every applied link creates.
REVIEW_TASK_TYPE = "registry_automation_review"


def _link_state(session: Session, snapshot: source.SourceSnapshot) -> dict[str, object]:
    """Return the state of the link of a source record before a change."""
    rows = session.execute(
        select(registry.Crosswalk).where(
            registry.Crosswalk.source_system_id == snapshot.source_system_id,
            registry.Crosswalk.source_record_id == snapshot.source_record_id,
        )
    ).scalars().all()
    approved = [row for row in rows if row.link_status == "approved"]
    if approved:
        row = approved[-1]
        return {
            "link_status": row.link_status,
            "entity_id": row.entity_id,
            "version": row.version,
            "crosswalk_id": row.id,
        }
    return {
        "link_status": "none",
        "entity_id": None,
        "version": 0,
        "crosswalk_id": None,
    }


def application_for_evaluation(
    session: Session,
    evaluation_id: str,
) -> registry_automation.RegistryAutomationApplication | None:
    """Return the application of one evaluation, if the link was applied."""
    return session.execute(
        select(registry_automation.RegistryAutomationApplication).where(
            registry_automation.RegistryAutomationApplication.evaluation_id == evaluation_id
        )
    ).scalar_one_or_none()


def apply_evaluation(
    session: Session,
    *,
    evaluation: registry_automation.RegistryAutomationEvaluation,
    policy: registry_automation.RegistryAutomationPolicy,
    actor: ActorContext,
    now: datetime | None = None,
) -> registry_automation.RegistryAutomationApplication:
    """Apply one evaluated link and record the evidence of the application.

    The link, the audit event, the review task and the record of the
    application are written in the transaction of the caller, so they commit
    together or not at all.  The service identity applies the link and the
    policy of the City carries the authorization of the steward.

    An evaluation that was already applied is never applied twice: the record
    of the first application is returned.
    """
    moment = now or utc_now()
    existing = application_for_evaluation(session, evaluation.id)
    if existing is not None:
        return existing
    if evaluation.decision != "auto_apply" or evaluation.target_entity_id is None:
        raise ValidationError("only an eligible evaluation may be applied")
    snapshot = session.get(source.SourceSnapshot, evaluation.source_snapshot_id)
    if snapshot is None:
        raise ValidationError("the source record of this evaluation does not exist")

    before = _link_state(session, snapshot)
    # The registry service is imported here: it imports the ingestion
    # package, and the ingestion service imports this module.
    from acme_city.registry.service import RegistryService

    result = RegistryService(session, now=moment).apply_automatic_link(
        AutomaticLinkCommand(
            source_system_id=snapshot.source_system_id,
            dataset_key=snapshot.source_dataset_id,
            source_record_id=snapshot.source_record_id,
            entity_id=evaluation.target_entity_id,
            reason=(
                f"the policy version {policy.version} applied this link: "
                f"{evaluation.evidence.get('reasons', ['eligible'])[0]}"
            ),
        ),
        actor,
        policy=policy,
    )
    view = result.value
    application = registry_automation.RegistryAutomationApplication(
        id=new_id("autoapply"),
        evaluation_id=evaluation.id,
        crosswalk_id=view.crosswalk_id,
        status="applied",
        before_state=before,
        after_state={
            "link_status": view.link_status,
            "entity_id": view.entity_id,
            "entity_type": view.entity_type,
            "version": view.version,
            "crosswalk_id": view.crosswalk_id,
        },
        applied_by_actor_id=actor.actor_id,
        applied_at=moment,
        reviewed_by_actor_id=None,
        reviewed_at=None,
        review_note=None,
    )
    session.add(application)
    session.flush()

    # Every applied link is a reviewable item of the queue.
    session.add(
        change.ReviewTask(
            id=new_id("task"),
            change_case_id=None,
            assignee_actor_id=policy.recorded_by_actor_id,
            task_type=REVIEW_TASK_TYPE,
            target_type="crosswalk",
            target_id=view.crosswalk_id,
            deduplication_key=f"{REVIEW_TASK_TYPE}:{application.id}",
            status="open",
            due_at=None,
            scenario_id=None,
        )
    )
    session.flush()
    return application


def applications(
    session: Session,
) -> list[registry_automation.RegistryAutomationApplication]:
    """Return the recorded applications, oldest first."""
    return list(
        session.execute(
            select(registry_automation.RegistryAutomationApplication).order_by(
                registry_automation.RegistryAutomationApplication.applied_at,
                registry_automation.RegistryAutomationApplication.id,
            )
        ).scalars().all()
    )


def application_view(
    session: Session,
    application: registry_automation.RegistryAutomationApplication,
) -> AutomaticApplicationView:
    """Return one application as the screens show it."""
    evaluation = session.get(
        registry_automation.RegistryAutomationEvaluation, application.evaluation_id
    )
    policy = (
        session.get(
            registry_automation.RegistryAutomationPolicy, evaluation.policy_id
        )
        if evaluation is not None and evaluation.policy_id
        else None
    )
    snapshot = (
        session.get(source.SourceSnapshot, evaluation.source_snapshot_id)
        if evaluation is not None
        else None
    )
    after = application.after_state or {}
    evidence = evaluation.evidence if evaluation is not None else {}
    return AutomaticApplicationView(
        application_id=application.id,
        evaluation_id=application.evaluation_id,
        crosswalk_id=application.crosswalk_id,
        entity_id=str(after.get("entity_id", "")),
        entity_type=str(after.get("entity_type", "party")),
        source_system_id=snapshot.source_system_id if snapshot is not None else "",
        source_dataset_key=snapshot.source_dataset_id if snapshot is not None else None,
        source_record_id=snapshot.source_record_id if snapshot is not None else "",
        status=application.status,
        score=evaluation.score if evaluation is not None else None,
        score_scale=evaluation.score_scale if evaluation is not None else "",
        decision=evaluation.decision if evaluation is not None else "",
        policy_version=policy.version if policy is not None else None,
        applied_by_actor_id=application.applied_by_actor_id,
        authorized_by_actor_id=(
            policy.recorded_by_actor_id if policy is not None else None
        ),
        applied_at=application.applied_at,
        reviewed_by_actor_id=application.reviewed_by_actor_id,
        reviewed_at=application.reviewed_at,
        review_note=application.review_note,
        reasons=[str(item) for item in evidence.get("reasons", [])],
        failed_checks=[str(item) for item in evidence.get("failed_checks", [])],
    )


def newest_policy_version(session: Session) -> int:
    newest = session.execute(
        select(func.max(registry_automation.RegistryAutomationPolicy.version))
    ).scalar_one()
    return int(newest or 0)


def policy_thresholds() -> dict[str, dict[str, float]]:
    """Return the thresholds of the record families the eligible datasets use."""
    return {
        family: {
            "auto_apply": DEFAULT_THRESHOLDS[family].auto_apply,
            "suggest": DEFAULT_THRESHOLDS[family].suggest,
        }
        for family in sorted(set(DATASET_TARGET_FAMILIES.values()))
    }


def _authorize(session: Session, actor: ActorContext, permission: str) -> None:
    """Refuse an actor that does not hold the grant of the policy control."""
    PermissionResolver(session).authorize(
        actor, permission, ResourceContext(domain_id=POLICY_DOMAIN)
    )


def _check_version(session: Session, expected_version: int | None) -> None:
    """Refuse a change that was decided on an older version of the policy."""
    current = newest_policy_version(session)
    if expected_version is None or int(expected_version) != current:
        raise ConflictError(
            "the policy changed since this screen was read; read it again and retry"
        )


def _write_policy(
    session: Session,
    actor: ActorContext,
    *,
    mode: str,
    source_scopes: list[str],
    reason: str,
    now: datetime | None,
) -> registry_automation.RegistryAutomationPolicy:
    """Record a new active policy version and supersede the previous one."""
    previous = active_policy(session)
    if previous is not None:
        previous.status = "superseded"
        session.add(previous)
    policy = registry_automation.RegistryAutomationPolicy(
        id=new_id("autopolicy"),
        mode=mode,
        status="active",
        matcher_version=MATCHER_VERSION,
        thresholds=policy_thresholds(),
        source_scopes=list(source_scopes),
        reason=reason,
        recorded_by_actor_id=actor.actor_id,
        activated_at=now or utc_now(),
        version=newest_policy_version(session) + 1,
    )
    session.add(policy)
    session.flush()
    return policy


def activate_policy(
    session: Session,
    actor: ActorContext,
    *,
    mode: str,
    source_scopes: list[str],
    reason: str,
    expected_version: int | None,
    now: datetime | None = None,
) -> registry_automation.RegistryAutomationPolicy:
    """Record a new active policy version and return it.

    A policy is activated in the suggestions or the active mode, it names the
    datasets it covers, and it carries the reason of the steward.  The change
    affects the records that are ingested later; the links that exist stay as
    they are.
    """
    _authorize(session, actor, ACTIVATE_ACTION)
    if mode not in {"suggestions", "active"}:
        raise ValidationError("a policy is activated in the suggestions or the active mode")
    if not reason.strip():
        raise ValidationError("a reason is required to activate a policy")
    scopes = [key for key in source_scopes if key in DATASET_TARGET_FAMILIES]
    if not scopes:
        raise ValidationError("a policy covers at least one source dataset")
    _check_version(session, expected_version)
    return _write_policy(
        session,
        actor,
        mode=mode,
        source_scopes=scopes,
        reason=reason.strip(),
        now=now,
    )


def pause_policy(
    session: Session,
    actor: ActorContext,
    *,
    reason: str,
    expected_version: int | None,
    now: datetime | None = None,
) -> registry_automation.RegistryAutomationPolicy:
    """Record a new policy version that pauses the automation."""
    _authorize(session, actor, PAUSE_ACTION)
    if not reason.strip():
        raise ValidationError("a reason is required to pause the automation")
    _check_version(session, expected_version)
    previous = active_policy(session)
    scopes = list(previous.source_scopes or []) if previous is not None else []
    return _write_policy(
        session,
        actor,
        mode="paused",
        source_scopes=scopes,
        reason=reason.strip(),
        now=now,
    )


__all__ = [
    "ACTIVATE_ACTION",
    "DATASET_TARGET_FAMILIES",
    "MATCHER_VERSION",
    "PAUSE_ACTION",
    "POLICY_DOMAIN",
    "POLICY_MODES",
    "activate_policy",
    "active_policy",
    "application_view",
    "applications",
    "apply_evaluation",
    "enqueue_accepted_snapshot",
    "newest_policy_version",
    "pause_policy",
    "policy_thresholds",
]

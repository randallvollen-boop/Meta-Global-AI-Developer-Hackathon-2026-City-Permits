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
from acme_city.persistence.models import registry_automation, source
from acme_city.registry.automation_policy import DEFAULT_THRESHOLDS

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


def newest_policy_version(session: Session) -> int:
    """Return the version of the newest policy, or zero when there is none."""
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
    "enqueue_accepted_snapshot",
    "newest_policy_version",
    "pause_policy",
    "policy_thresholds",
]

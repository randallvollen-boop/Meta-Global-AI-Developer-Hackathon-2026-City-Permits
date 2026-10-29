"""Durable enqueue seam for accepted registry source versions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.core.clock import utc_now
from acme_city.core.ids import new_id
from acme_city.persistence.models import registry_automation, source

MATCHER_VERSION = "registry-candidates-v1"

DATASET_TARGET_FAMILIES: dict[str, str] = {
    "applicant_profiles": "owner_party",
    "applications_and_permits": "owner_party",
    "business_licensing_register": "owner_party",
    "contractor_register": "contractor_party",
    "parcel_register": "parcel",
    "address_register": "address",
}


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
        lease_owner=None,
        lease_expires_at=None,
        last_error=None,
    )
    session.add(job)
    session.flush()
    return job


__all__ = [
    "DATASET_TARGET_FAMILIES",
    "MATCHER_VERSION",
    "active_policy",
    "enqueue_accepted_snapshot",
]

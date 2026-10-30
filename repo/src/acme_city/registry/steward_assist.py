"""Deterministic recommendations for the tasks of the Data Steward's queue.

The assistant prepares the work of a queue task and proposes a decision.  It
never decides: the steward reads the evidence and accepts the recommendation,
changes it or ignores it.  Every recommendation is deterministic, so the same
task always produces the same outcome, the same confidence and the same words.

The module reuses the machinery of the City: the candidate scoring of
``registry.candidates``, the thresholds and the safety checks of
``registry.automation_policy`` and the facts of ``agents.linking``.  It never
scores a candidate of its own, and it never writes a fact of a source.

The confidence follows one rule for every kind of task:

* **High** - the evidence is strong enough to act on: the score is above the
  line the City applies links on, no other candidate comes close and no fact
  disagrees.
* **Review** - anything else.  The steward reads the evidence and decides.
* **Held** - the facts disagree with each other, or the record changed since
  the recommendation was made.  A person decides, never the assistant.

The version the recommendation records is the version of the record the task
is about: the link a match is decided on, the applied link of an automatic
link, the parcel match of a property, the change case of a correction and the
issue of a data issue.  The facts the recommendation depends on travel with it
as evidence: the source version it read, the master record it compared and the
link it would decide on.  A record that changed since the recommendation was
made is stale, and the steward prepares the recommendation again.
"""
# REQUIRES: MDM-02, UX-01
# The assistant proposes; the steward decides.  The recommendation records the
# evidence it read and the version of the record it read, so a record that
# changed since can be recognized before anything is accepted.

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.fixtures.loader import REPO_ROOT
from acme_city.gis.matching import ParcelMatchService, approvable, strong_candidates
from acme_city.persistence.models import (
    change,
    gis,
    governance,
    permit,
    registry,
    registry_automation,
    source,
)
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.registry import automation, candidates
from acme_city.registry.automation_policy import (
    DEFAULT_THRESHOLDS,
    PolicyDecision,
    PolicyEvaluation,
    SafetyChecks,
    Thresholds,
    evaluate_link,
    thresholds_for,
)
from acme_city.registry.provenance import current_accepted_snapshot
from acme_city.registry.service import RegistryService

#: The actor the assistant records its work under.  It is a service identity:
#: it is never offered a session and it holds no grant of a person.
STEWARD_ASSIST_ACTOR_ID = "service_steward_assist"

#: The three confidences a recommendation may carry.
CONFIDENCE_HIGH = "high"
CONFIDENCE_REVIEW = "review"
CONFIDENCE_HELD = "held"

#: The outcome of a record match.
OUTCOME_CONFIRM = "confirm"
OUTCOME_REJECT = "reject"
OUTCOME_ASK_SOURCE = "ask_source"

#: The outcome of a link the automation applied.
OUTCOME_KEEP = "keep"
OUTCOME_UNDO = "undo"

#: The outcome of a property link.
OUTCOME_APPROVE_PARCEL = "approve_parcel"
OUTCOME_NONE_FITS = "none_fits"

#: The outcome of a correction.
OUTCOME_ACCEPT = "accept"

#: The outcome of a data issue.
OUTCOME_RESOLVE = "resolve"
OUTCOME_AWAITING_SOURCE = "awaiting_source"

#: The freshness token of a task whose decision is made on a link: the
#: version of that link is what the recommendation depends on.
VERSION_TOKEN_CROSSWALK = "crosswalk"

#: The freshness token of a task that has no link to decide: the version of
#: the source record is what the recommendation depends on.
VERSION_TOKEN_CURRENT_SOURCE = "current_source"

#: The safety checks whose failure means that the facts disagree with each
#: other, rather than that the evidence is incomplete.
CONFLICT_CHECKS: frozenset[str] = frozenset({"no_identity_conflict"})

#: The plain words of every safety check, so a reason never names an
#: internal key.
CHECK_WORDS: dict[str, str] = {
    "source_accepted_current": "the source record is no longer the current version",
    "source_contract_eligible": "the source dataset is not registered",
    "target_exists_with_correct_type": "the master record is not in the registry",
    "identifier_namespace_known": "this kind of record is not supported",
    "required_identity_fields_present": "the source record names no identifier",
    "no_identity_conflict": "the facts about this record disagree",
    "no_protected_manual_decision": "a person already decided this link",
    "comparison_current": "the source record changed",
    "no_active_link_replacement": "another link is already approved",
    "unique_target": "more than one master record fits",
    "corroborating_identity_evidence": "no second fact confirms the identifier",
    "party_score_gap": "another master record fits almost as well",
}

#: How each kind of data issue is settled.  The value names what the
#: assistant proposes and the words the steward reads.
ISSUE_CLASSES: dict[str, tuple[str, str]] = {
    "late_source_version": (
        OUTCOME_RESOLVE,
        "The accepted version stands and the late copy is kept as history, "
        "so the issue can be closed.",
    ),
    "source_version_payload_conflict": (
        OUTCOME_AWAITING_SOURCE,
        "The source has to say which version is right, so the issue waits for "
        "an answer.",
    ),
    "unregistered_dataset": (
        OUTCOME_AWAITING_SOURCE,
        "The dataset has to be registered before its records can be published, "
        "so the issue waits for an answer.",
    ),
    "unresolved_field_authority": (
        OUTCOME_AWAITING_SOURCE,
        "The source that owns the field has to be named, so the issue waits for "
        "an answer.",
    ),
}

_DISPLAY_PATH = REPO_ROOT / "config" / "ui_display.json"


@dataclass(frozen=True)
class Task:
    """One task of the Data Steward's queue.

    Any object with a ``kind`` and an ``item_id`` works, so a task collected
    by the queue can be handed over as it is.
    """

    kind: str
    item_id: str


@dataclass(frozen=True)
class Recommendation:
    """What the assistant prepared for one task of the queue."""

    task_kind: str
    task_id: str
    record_version: int
    outcome: str
    confidence: str
    evidence: dict[str, Any]
    reason: str


@lru_cache(maxsize=1)
def _evidence_phrases() -> dict[str, str]:
    """Return the plain words the screens use for every kind of evidence.

    The words come from the committed display configuration, so the reason
    the steward reads says the same thing as the screen it belongs to.
    """
    return dict(
        json.loads(_DISPLAY_PATH.read_text(encoding="utf-8")).get("evidence_methods", {})
    )


def _phrase(method: str) -> str:
    """Return the plain words of one kind of evidence."""
    text = _evidence_phrases().get(method, "")
    if text:
        return text
    return method.replace("_", " ").capitalize()


def _lowered(text: str) -> str:
    """Return the text with a small first letter, so two sentences join."""
    return text[:1].lower() + text[1:] if text else text


def _entity_label(session: Session, entity_id: str) -> str:
    """Return the name of the canonical entity an identifier names."""
    party = session.get(registry.Party, entity_id)
    if party is not None:
        return party.display_name
    parcel = session.get(registry.Parcel, entity_id)
    if parcel is not None:
        return parcel.source_parcel_number
    address = session.get(registry.Address, entity_id)
    if address is not None:
        return address.source_string or entity_id
    return entity_id


def _entity_version(session: Session, entity_id: str) -> int:
    """Return the version of the canonical entity an identifier names."""
    for row in (registry.Party, registry.Parcel, registry.Address):
        entity = session.get(row, entity_id)
        if entity is not None:
            return int(entity.version)
    return 0


def _stored_thresholds(session: Session, family: str) -> Thresholds:
    """Return the thresholds of one family, from the active policy or the defaults."""
    policy = automation.active_policy(session)
    stored = (policy.thresholds or {}).get(family) if policy is not None else None
    return thresholds_for(family, stored)


def _safety_checks(
    session: Session,
    *,
    snapshot: source.SourceSnapshot,
    family: str,
    candidate: candidates.Candidate,
    candidate_count: int,
    exclude_crosswalk_id: str | None = None,
) -> SafetyChecks:
    """Return the safety facts of one candidate, as a person decides them.

    The facts are the ones the City uses before it links a record on its own.
    Two of them belong to that automatic application and not to a person: a
    person may take back a decision, and the assistant only prepares the
    evidence, so the grant of the linking service does not decide the case.

    ``exclude_crosswalk_id`` leaves the link the automation applied out of the
    comparison, so the reader of that link does not mistake it for a decision
    of a person.
    """
    # The agent layer imports this package, so the import happens here.
    from acme_city.agents import linking

    checks = linking.safety_checks(
        session,
        snapshot=snapshot,
        family=family,
        candidate=candidate,
        candidate_count=candidate_count,
        exclude_crosswalk_id=exclude_crosswalk_id,
    )
    return replace(checks, undo_supported=True, permissions_granted=True)


def _weakness(evaluation: PolicyEvaluation | None, failures: list[str]) -> str:
    """Return the plain words of the first reason that holds a recommendation.

    The reasons of the policy carry the facts the checks do not: the score
    gap between two master records is one of them.  That gap says more than
    the number of candidates does, so it comes first.
    """
    names = list(evaluation.reasons) if evaluation is not None else list(failures)
    if "party_score_gap" in names:
        return CHECK_WORDS["party_score_gap"]
    for name in names:
        words = CHECK_WORDS.get(name, "")
        if words:
            return words
    return ""


def _first_phrase(evidence: tuple[candidates.Evidence, ...]) -> str:
    """Return the plain words of the strongest fact of a set of evidence."""
    strong = next(
        (item for item in evidence if item.method in candidates.STRONG_METHODS),
        None,
    )
    if strong is not None:
        return _phrase(strong.method)
    if evidence:
        return _phrase(evidence[0].method)
    return ""


# ------------------------------------------------------------------- the match


def _recommend_link(
    session: Session, task: Task, *, settings: Any = None
) -> Recommendation:
    """Prepare the recommendation of a record match.

    The candidates are scored by the comparison of the City, the thresholds
    are the ones of the active policy and the safety facts are the ones the
    City checks before it links a record.  A fact that disagrees holds the
    recommendation for a person.

    The recommendation is made on the link the steward decides on, so it
    records the version of that link and the facts it read beside it.
    """
    proposal = session.get(registry.MatchProposal, task.item_id)
    if proposal is None:
        raise NotFoundError(f"no match proposal {task.item_id!r} exists")
    snapshot = session.get(source.SourceSnapshot, proposal.source_snapshot_id)
    if snapshot is None:
        raise NotFoundError("the source record of this proposal does not exist")

    family = automation.DATASET_TARGET_FAMILIES.get(snapshot.source_dataset_id, "owner_party")
    entity_type = candidates.entity_target_for(snapshot.source_dataset_id)
    candidate_set = candidates.generate_candidates(
        session,
        dict(snapshot.raw_payload or {}),
        entity_type,
        snapshot.source_snapshot_id,
    )
    best = candidate_set.best
    thresholds = _stored_thresholds(session, family)
    next_best: float | None = None
    failures: list[str] = []
    evaluation = None

    if best is not None:
        next_best = next(
            (
                other.score
                for other in candidate_set.candidates
                if other.entity_id != best.entity_id
            ),
            None,
        )
        checks = _safety_checks(
            session,
            snapshot=snapshot,
            family=family,
            candidate=best,
            candidate_count=len(candidate_set.candidates),
        )
        evaluation = evaluate_link(
            target_family=family,
            score=best.score,
            checks=checks,
            next_best_score=next_best,
            thresholds=thresholds,
        )
        failures = list(checks.failures())

    weakness = _weakness(evaluation, failures)
    agreement = _first_phrase(best.supporting) if best is not None else ""
    disagreement = _first_phrase(best.conflicting) if best is not None else ""

    if best is None:
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_REJECT
        reason = "No master record fits this source record, so there is nothing to link."
    elif best.conflicting:
        confidence = CONFIDENCE_HELD
        outcome = OUTCOME_ASK_SOURCE
        reason = f"{agreement}, but {_lowered(disagreement)}, so a person has to decide."
    elif evaluation is not None and evaluation.decision is PolicyDecision.AUTO_APPLY:
        confidence = CONFIDENCE_HIGH
        outcome = OUTCOME_CONFIRM
        reason = f"{agreement} and no other master record fits as well."
    elif best.score >= thresholds.suggest:
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_CONFIRM
        if weakness:
            reason = f"{agreement}, but {weakness}."
        else:
            reason = f"{agreement}, but the match is not strong enough to act on alone."
    else:
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_REJECT
        reason = "No master record fits this source record closely enough to link it"
        if weakness:
            reason = f"{reason}, and {weakness}"

    # The decision of a record match is made on the link, so the link is the
    # record the recommendation depends on.  A task without a link depends on
    # the source record instead.
    crosswalk = RegistryService(session).open_crosswalk(
        snapshot.source_system_id, snapshot.source_record_id
    )
    record_version = crosswalk.version if crosswalk is not None else 0
    version_token = (
        VERSION_TOKEN_CROSSWALK if crosswalk is not None else VERSION_TOKEN_CURRENT_SOURCE
    )
    return Recommendation(
        task_kind=task.kind,
        task_id=task.item_id,
        record_version=record_version,
        outcome=outcome,
        confidence=confidence,
        evidence={
            "source_system": snapshot.source_system_id,
            "source_dataset": snapshot.source_dataset_id,
            "source_record_id": snapshot.source_record_id,
            "source_snapshot_id": snapshot.source_snapshot_id,
            "source_version": snapshot.source_record_version or "",
            "candidate_entity_id": best.entity_id if best is not None else "",
            "candidate_label": _entity_label(session, best.entity_id) if best is not None else "",
            "candidate_version": (
                _entity_version(session, best.entity_id) if best is not None else 0
            ),
            "score": best.score if best is not None else None,
            "next_best_score": next_best,
            "auto_apply_threshold": thresholds.auto_apply,
            "suggest_threshold": thresholds.suggest,
            "policy_decision": (
                evaluation.decision.value if evaluation is not None else PolicyDecision.IGNORE.value
            ),
            "reasons": list(evaluation.reasons) if evaluation is not None else ["no_candidate"],
            "failed_checks": failures,
            "version_token": version_token,
            "crosswalk_id": crosswalk.id if crosswalk is not None else "",
            "crosswalk_version": crosswalk.version if crosswalk is not None else 0,
            "agreements": [item.to_dict() for item in best.supporting] if best is not None else [],
            "disagreements": (
                [item.to_dict() for item in best.conflicting] if best is not None else []
            ),
        },
        reason=reason,
    )


# ------------------------------------------------------------ the applied link


def _reevaluate_applied_link(
    session: Session,
    *,
    snapshot: source.SourceSnapshot,
    family: str,
    entity_id: str,
    crosswalk_id: str,
) -> tuple[PolicyEvaluation, candidates.Candidate] | None:
    """Return what the rule of the City decides about an applied link today.

    The candidates are compared again, and the link the automation applied is
    left out of the comparison: it is the link under review, not a decision
    of a person.  ``None`` means the master record of the link is no longer
    among the candidates, so the rule cannot be applied to it any more.
    """
    entity_type = candidates.entity_target_for(snapshot.source_dataset_id)
    candidate_set = candidates.generate_candidates(
        session,
        dict(snapshot.raw_payload or {}),
        entity_type,
        snapshot.source_snapshot_id,
    )
    candidate = next(
        (item for item in candidate_set.candidates if item.entity_id == entity_id),
        None,
    )
    if candidate is None:
        return None
    checks = _safety_checks(
        session,
        snapshot=snapshot,
        family=family,
        candidate=candidate,
        candidate_count=len(candidate_set.candidates),
        exclude_crosswalk_id=crosswalk_id,
    )
    next_best = next(
        (
            other.score
            for other in candidate_set.candidates
            if other.entity_id != entity_id
        ),
        None,
    )
    evaluation = evaluate_link(
        target_family=family,
        score=candidate.score,
        checks=checks,
        next_best_score=next_best,
        thresholds=_stored_thresholds(session, family),
    )
    return evaluation, candidate


def _recommend_automatic_link(
    session: Session, task: Task, *, settings: Any = None
) -> Recommendation:
    """Prepare the recommendation of a link the automation applied.

    The evidence is the evidence the policy recorded when it applied the
    link, and the link is checked against the facts of today: the source
    record has to be the one the policy applied and the link has to be the
    one the policy wrote.  A fact that disagrees holds the recommendation,
    evidence that is missing leaves it for a person, and a link today's rule
    would not apply is offered for a decision.
    """
    application = session.get(
        registry_automation.RegistryAutomationApplication, task.item_id
    )
    if application is None:
        raise NotFoundError(f"no applied link {task.item_id!r} exists")
    evaluation = session.get(
        registry_automation.RegistryAutomationEvaluation, application.evaluation_id
    )
    recorded = dict(evaluation.evidence or {}) if evaluation is not None else {}
    conflicting = list(recorded.get("conflicting") or [])
    failed = list(recorded.get("failed_checks") or [])
    reasons = list(recorded.get("reasons") or [])
    family = evaluation.target_family if evaluation is not None else ""
    score = evaluation.score if evaluation is not None else None
    applied_policy = (
        session.get(registry_automation.RegistryAutomationPolicy, evaluation.policy_id)
        if evaluation is not None and evaluation.policy_id
        else None
    )
    snapshot = (
        session.get(source.SourceSnapshot, evaluation.source_snapshot_id)
        if evaluation is not None
        else None
    )
    after = dict(application.after_state or {})
    entity_id = str(after.get("entity_id", ""))
    crosswalk = (
        session.get(registry.Crosswalk, application.crosswalk_id)
        if application.crosswalk_id
        else None
    )

    # The facts of today: the source record the policy applied and the link
    # it wrote.
    current_snapshot = (
        current_accepted_snapshot(
            session,
            snapshot.source_system_id,
            snapshot.source_dataset_id,
            snapshot.source_record_id,
        )
        if snapshot is not None
        else None
    )
    source_current = (
        snapshot is not None
        and current_snapshot is not None
        and current_snapshot.source_snapshot_id == snapshot.source_snapshot_id
    )
    link_current = (
        crosswalk is not None
        and crosswalk.link_status == "approved"
        and crosswalk.entity_id == entity_id
    )
    recheck = (
        _reevaluate_applied_link(
            session,
            snapshot=snapshot,
            family=family,
            entity_id=entity_id,
            crosswalk_id=application.crosswalk_id or "",
        )
        if snapshot is not None and entity_id
        else None
    )

    if application.status != "applied":
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_KEEP
        reason = "This link was already reviewed, so there is nothing left to keep or take back."
    elif evaluation is None or snapshot is None or score is None:
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_KEEP
        reason = (
            "The evidence of this applied link is not available, "
            "so a person reads the link."
        )
    elif conflicting:
        method = str(conflicting[0].get("method", ""))
        confidence = CONFIDENCE_HELD
        outcome = OUTCOME_UNDO
        reason = f"{_phrase(method)}, so a person decides whether to keep this link."
    elif failed:
        if CONFLICT_CHECKS.intersection(failed):
            confidence = CONFIDENCE_HELD
            outcome = OUTCOME_UNDO
            reason = (
                "The facts about this record disagree, "
                "so a person decides whether to keep this link."
            )
        else:
            confidence = CONFIDENCE_REVIEW
            outcome = OUTCOME_KEEP
            reason = (
                "Not every check passed when this link was applied, "
                "so a person reads the link."
            )
    elif not source_current:
        confidence = CONFIDENCE_HELD
        outcome = OUTCOME_UNDO
        reason = (
            "The source record changed since this link was applied, "
            "so a person decides whether to keep this link."
        )
    elif not link_current:
        confidence = CONFIDENCE_HELD
        outcome = OUTCOME_UNDO
        reason = (
            "The link changed since it was applied, "
            "so a person decides whether to keep this link."
        )
    elif recheck is None:
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_KEEP
        reason = (
            "The master record of this link is no longer among the candidates, "
            "so a person reads the link."
        )
    elif recheck[1].conflicting:
        confidence = CONFIDENCE_HELD
        outcome = OUTCOME_UNDO
        reason = (
            "The facts about this record disagree today, "
            "so a person decides whether to keep this link."
        )
    elif recheck[0].decision is PolicyDecision.AUTO_APPLY:
        confidence = CONFIDENCE_HIGH
        outcome = OUTCOME_KEEP
        reason = (
            "Every check passed before this link was applied and nothing "
            "changed since, so keeping it needs no new work."
        )
    else:
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_UNDO
        reason = (
            "The rule that applies links today would not apply this one, "
            "so a person may take it back."
        )

    return Recommendation(
        task_kind=task.kind,
        task_id=task.item_id,
        record_version=application.version,
        outcome=outcome,
        confidence=confidence,
        evidence={
            "application_id": application.id,
            "crosswalk_id": application.crosswalk_id or "",
            "crosswalk_version": crosswalk.version if crosswalk is not None else 0,
            "entity_id": entity_id,
            "entity_label": _entity_label(session, entity_id),
            "source_system": snapshot.source_system_id if snapshot is not None else "",
            "source_dataset": snapshot.source_dataset_id if snapshot is not None else "",
            "source_record_id": snapshot.source_record_id if snapshot is not None else "",
            "source_snapshot_id": snapshot.source_snapshot_id if snapshot is not None else "",
            "score": score,
            "decision": evaluation.decision if evaluation is not None else "",
            "policy_version": applied_policy.version if applied_policy is not None else None,
            "reasons": reasons,
            "failed_checks": failed,
            "agreements": list(recorded.get("supporting") or []),
            "disagreements": conflicting,
        },
        reason=reason,
    )


# ------------------------------------------------------------------ the parcel


def _stated_parcel(application: permit.Application | None) -> str:
    """Return the parcel number the application states, if it states one."""
    if application is None:
        return ""
    facts = dict(application.submitted_facts or {})
    return str(facts.get("parcel_number") or facts.get("submitted_parcel") or "").strip()


def _selected_candidate(
    found: list[dict[str, Any]], match: gis.ApplicationParcelMatch
) -> dict[str, Any] | None:
    """Return the candidate the current parcel selection came from.

    A parcel the steward looked up by its number did not come from the
    locator, so it has no candidate here.  A match without a parcel has no
    selection either.
    """
    parcel_number = str(match.parcel_number or "")
    if not parcel_number:
        return None
    address = str(match.matched_address or "")
    for item in found:
        if str(item.get("parcel_number", "")) == parcel_number and str(
            item.get("address", "")
        ) == address:
            return item
    for item in found:
        if str(item.get("parcel_number", "")) == parcel_number:
            return item
    return None


def _recommend_parcel(
    session: Session, task: Task, *, settings: Any = None
) -> Recommendation:
    """Prepare the recommendation of a property link.

    The parcel the City selected and the line the locator applies decide:
    a parcel may only be proposed for approval when the City itself would
    approve that link, and the score that counts is the score of the parcel
    that is proposed, never the score of another candidate.
    """
    match = session.execute(
        select(gis.ApplicationParcelMatch).where(
            gis.ApplicationParcelMatch.application_id == task.item_id
        )
    ).scalars().first()
    if match is None:
        raise NotFoundError(f"application {task.item_id!r} has no parcel match")
    application = session.get(permit.Application, task.item_id)

    threshold = ParcelMatchService(session, settings=settings).threshold
    found = [dict(item) for item in (match.candidates or [])]
    selected = _selected_candidate(found, match)
    score = float(match.score) if match.score is not None else None
    located = str(match.parcel_number or "")
    stated = _stated_parcel(application)
    registry_parcel = (
        session.get(registry.Parcel, match.parcel_id) if match.parcel_id else None
    )

    conflict = ""
    if stated and located and stated.upper() != located.upper():
        conflict = (
            f"The application names parcel {stated}, but the address falls in parcel {located}."
        )

    # The candidates of the locator search, and the ones that are not the
    # parcel that is proposed.  A parcel that was looked up by its number did
    # not come from that search, so the search does not decide against it.
    strong = strong_candidates(found, threshold)
    others = [] if selected is None else [item for item in found if item is not selected]
    strong_others = strong_candidates(others, threshold)

    if conflict:
        confidence = CONFIDENCE_HELD
        outcome = OUTCOME_ASK_SOURCE
        reason = (
            "The application names one parcel and the address falls in another, "
            "so a person resolves the difference."
        )
    elif not found and not located:
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_NONE_FITS
        reason = "The address was not found in the city locator, so no parcel fits it."
    elif not approvable(match):
        confidence = CONFIDENCE_REVIEW
        if len(strong) > 1:
            outcome = OUTCOME_APPROVE_PARCEL
            reason = (
                "Several parcels fit the address almost equally well, "
                "so a person chooses."
            )
        elif located and registry_parcel is None:
            outcome = OUTCOME_APPROVE_PARCEL
            reason = (
                f"Parcel {located} is not in the registry yet, "
                "so a person records it before the link is approved."
            )
        elif strong:
            outcome = OUTCOME_NONE_FITS
            reason = (
                "The address point does not fall inside a parcel of the parcel layer, "
                "so no parcel fits it."
            )
        else:
            outcome = OUTCOME_NONE_FITS
            reason = (
                "No parcel matched the submitted address closely enough, "
                "so no parcel fits it."
            )
    elif strong_others:
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_APPROVE_PARCEL
        best_other = max(float(item.get("score") or 0.0) for item in strong_others)
        if score is not None and best_other > score:
            reason = (
                "Another parcel fits the submitted address better, "
                "so a person chooses."
            )
        else:
            reason = (
                "Several parcels fit the address almost equally well, "
                "so a person chooses."
            )
    elif score is None or score < threshold:
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_APPROVE_PARCEL
        reason = (
            "One parcel fits the submitted address, but the address did not match it "
            "closely enough to act on alone."
        )
    else:
        confidence = CONFIDENCE_HIGH
        outcome = OUTCOME_APPROVE_PARCEL
        reason = "One parcel fits the submitted address and the point falls inside it."

    return Recommendation(
        task_kind=task.kind,
        task_id=task.item_id,
        record_version=match.version,
        outcome=outcome,
        confidence=confidence,
        evidence={
            "application_id": match.application_id,
            "submitted_text": match.submitted_text or "",
            "matched_address": match.matched_address or "",
            "parcel_id": match.parcel_id or "",
            "parcel_number": located,
            "stated_parcel": stated,
            "score": score,
            "address_id": str(selected.get("address_id", "")) if selected else "",
            "locator_status": match.locator_status,
            "link_state": match.link_state,
            "note": match.note or "",
            "conflict": conflict,
            "auto_apply_threshold": threshold,
            "suggest_threshold": DEFAULT_THRESHOLDS["address_locator"].suggest,
            "candidates": [
                {
                    "parcel_number": str(item.get("parcel_number", "")),
                    "address": str(item.get("address", "")),
                    "score": float(item.get("score") or 0.0),
                    "address_id": str(item.get("address_id", "")),
                    "selected": item is selected,
                }
                for item in found
            ],
        },
        reason=reason,
    )


# --------------------------------------------------------------- the correction


def _source_value(
    session: Session, case: change.ChangeCase
) -> tuple[dict[str, Any] | None, str | None]:
    """Return the value the source holds today and the version it holds.

    ``None`` means the case is not about a source record, so there is no
    value of a source to compare the proposal with.
    """
    if case.target_type != "source_record":
        return None, None
    parts = str(case.target_id or "").split("/")
    if len(parts) != 3 or not all(parts):
        return None, None
    snapshot = current_accepted_snapshot(session, parts[0], parts[1], parts[2])
    if snapshot is None:
        return None, None
    return dict(snapshot.raw_payload or {}), snapshot.source_record_version or ""


def _same_value(left: Any, right: Any) -> bool:
    """Whether two values of a source record are the same, keeping their types.

    A number is not the text of that number, a missing value is not the text
    "None" and a boolean is not a number.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    return type(left) is type(right) and left == right


def _proposal_agrees(current: dict[str, Any], proposed: dict[str, Any]) -> bool:
    """Whether the source holds every value the correction proposes.

    A field the source does not hold cannot be compared, so the correction
    stays for a person to read.
    """
    if not proposed:
        return False
    return all(
        field in current and _same_value(current[field], value)
        for field, value in proposed.items()
    )


def _recommend_case(
    session: Session, task: Task, *, settings: Any = None
) -> Recommendation:
    """Prepare the recommendation of a correction.

    The proposal is compared with the value the source holds today.  A source
    record that changed since the correction was raised holds the
    recommendation, because the proposal was made against another version.
    """
    case = session.get(change.ChangeCase, task.item_id)
    if case is None:
        raise NotFoundError(f"no change case {task.item_id!r} exists")

    proposed = dict(case.proposed_value or {})
    current, current_version = _source_value(session, case)
    moved = (
        case.expected_version is not None
        and current_version is not None
        and str(case.expected_version) != str(current_version)
    )
    agrees = current is not None and _proposal_agrees(current, proposed)

    if not proposed:
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_ASK_SOURCE
        reason = (
            "The case names no value to correct, so the source has to be asked "
            "what the value should be."
        )
    elif moved:
        confidence = CONFIDENCE_HELD
        outcome = OUTCOME_ASK_SOURCE
        reason = (
            "The source record changed since this correction was raised, "
            "so a person checks the current value first."
        )
    elif agrees:
        confidence = CONFIDENCE_HIGH
        outcome = OUTCOME_ACCEPT
        reason = "The source already holds this value, so the correction matches the source."
    elif current is None:
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_ACCEPT
        reason = (
            "The correction cannot be checked against the source, so a person reads it "
            "before it is sent."
        )
    elif any(field not in current for field in proposed):
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_ACCEPT
        reason = (
            "The source record does not name this field, so a person reads the field "
            "before the correction is sent."
        )
    else:
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_ACCEPT
        reason = (
            "The source does not hold this value yet, so the correction asks the source "
            "to change it."
        )

    return Recommendation(
        task_kind=task.kind,
        task_id=task.item_id,
        record_version=case.version,
        outcome=outcome,
        confidence=confidence,
        evidence={
            "change_case_id": case.id,
            "target_type": case.target_type,
            "target_id": case.target_id,
            "change_kind": case.change_kind,
            "current_value": current if current is not None else dict(case.old_value or {}),
            "proposed_value": proposed,
            "expected_version": case.expected_version,
            "current_version": current_version or "",
            "destination": case.destination or "",
            "evidence": list(case.evidence or []),
        },
        reason=reason,
    )


# ------------------------------------------------------------------ the issue


def _owner_label(session: Session, issue: change.GovernanceIssue) -> str:
    """Return the plain name of the queue or the person that has to act."""
    if issue.responsible_queue_id:
        queue = session.execute(
            select(governance.StewardQueue).where(
                governance.StewardQueue.queue_id == issue.responsible_queue_id
            )
        ).scalars().first()
        if queue is not None and queue.label:
            return queue.label
    if issue.assigned_actor_id:
        actor = session.get(governance.Actor, issue.assigned_actor_id)
        if actor is not None and actor.label:
            return actor.label
    return ""


def _dataset_label(session: Session, dataset_key: str) -> str:
    """Return the registered name of a dataset."""
    contract = session.execute(
        select(governance.SourceContract).where(
            governance.SourceContract.dataset_key == dataset_key
        )
    ).scalars().first()
    if contract is not None and contract.label:
        return contract.label
    return dataset_key.replace("_", " ")


def _field_label(attribute_path: str) -> str:
    """Return the readable name of a field of a master record."""
    return attribute_path.replace("_", " ").replace(".", " ")


def _subject_label(session: Session, issue: change.GovernanceIssue) -> str:
    """Return the plain name of the record the issue is about.

    The name is the one a person knows: the name of the master record, the
    readable name of the field and the registered name of the dataset.  The
    internal identifiers stay in the evidence of the recommendation.
    """
    subject = str(issue.subject_id or "")
    if issue.subject_type == "source_dataset":
        return _dataset_label(session, subject)
    if issue.subject_type == "source_record":
        parts = subject.split(":")
        return parts[-1] if parts and parts[-1] else subject
    if issue.subject_type == "canonical_entity":
        entity_id, _, attribute_path = subject.partition(":")
        label = _entity_label(session, entity_id)
        if not attribute_path:
            return label
        return f"{label} ({_field_label(attribute_path)})"
    return subject


def _request_draft(issue: change.GovernanceIssue, subject: str) -> str:
    """Return the draft of the request the steward would send."""
    if issue.issue_type == "late_source_version":
        return (
            f"The accepted version of {subject} stands and the late copy is kept as "
            "history, so this issue can be closed."
        )
    if issue.issue_type == "source_version_payload_conflict":
        return (
            f"{subject} was delivered twice with different content for the same version. "
            "Please confirm which version is correct so the City can continue."
        )
    if issue.issue_type == "unregistered_dataset":
        return (
            f"The dataset {subject} is not registered, so the City holds its records "
            "back. Please register it so the records can be published."
        )
    if issue.issue_type == "unresolved_field_authority":
        return (
            f"The City cannot show the value of {subject} because no source owns the "
            "field. Please name the source that owns it."
        )
    return (
        f"The City needs an answer about {subject} before it changes anything. "
        "Please look at the issue the City recorded."
    )


def _recommend_issue(
    session: Session, task: Task, *, settings: Any = None
) -> Recommendation:
    """Prepare the recommendation of a data issue.

    The issue is classified, the queue or the person that has to act is
    named, and the request the steward would send is drafted.  An issue whose
    facts disagree holds the recommendation for a person.
    """
    issue = session.get(change.GovernanceIssue, task.item_id)
    if issue is None:
        raise NotFoundError(f"no data issue {task.item_id!r} exists")

    classification = ISSUE_CLASSES.get(issue.issue_type)
    owner = _owner_label(session, issue)
    draft = _request_draft(issue, _subject_label(session, issue))

    if issue.issue_type == "source_version_payload_conflict":
        confidence = CONFIDENCE_HELD
        outcome = OUTCOME_AWAITING_SOURCE
        reason = "Two versions of the same record disagree, so a person has to decide."
    elif classification is None:
        confidence = CONFIDENCE_REVIEW
        outcome = OUTCOME_AWAITING_SOURCE
        reason = "The assistant does not know this kind of issue, so a person reads it."
    elif not owner:
        confidence = CONFIDENCE_REVIEW
        outcome = classification[0]
        reason = "No queue owns this issue yet, so a person names one before it moves."
    else:
        confidence = CONFIDENCE_HIGH
        outcome = classification[0]
        reason = classification[1]

    return Recommendation(
        task_kind=task.kind,
        task_id=task.item_id,
        record_version=issue.version,
        outcome=outcome,
        confidence=confidence,
        evidence={
            "issue_id": issue.id,
            "issue_type": issue.issue_type,
            "subject_type": issue.subject_type,
            "subject_id": issue.subject_id,
            "description": issue.description or "",
            "responsible_queue_id": issue.responsible_queue_id or "",
            "assigned_actor_id": issue.assigned_actor_id or "",
            "owner": owner,
            "blocking": issue.blocking,
            "classification": classification[1] if classification is not None else "",
            "request_draft": draft,
        },
        reason=reason,
    )


_BUILDERS = {
    "link": _recommend_link,
    "automatic_link": _recommend_automatic_link,
    "parcel": _recommend_parcel,
    "case": _recommend_case,
    "issue": _recommend_issue,
}

#: The kinds of task the assistant prepares a recommendation for.  They are
#: the kinds the builders above prepare.
TASK_KINDS: tuple[str, ...] = tuple(_BUILDERS)


def recommend(
    session: Session, task: Task, *, settings: Any = None
) -> Recommendation:
    """Prepare the recommendation of one task of the Data Steward's queue.

    The recommendation is deterministic and it decides nothing: it names what
    the assistant proposes, how sure it is, the evidence it read and the words
    the steward reads.

    Args:
        session: The open session.
        task: The task of the queue, with its kind and its identifier.
        settings: The settings of the City, so a recommendation follows the
            line the City applies.

    Returns:
        The recommendation for the task.

    Raises:
        NotFoundError: The record of the task does not exist.
        ValidationError: The assistant prepares no recommendation for this
            kind of task.
    """
    builder = _BUILDERS.get(task.kind)
    if builder is None:
        raise ValidationError(
            f"the assistant prepares no recommendation for a {task.kind!r} task"
        )
    return builder(session, task, settings=settings)


def store_recommendation(
    session: Session,
    recommendation: Recommendation,
    *,
    actor_id: str = STEWARD_ASSIST_ACTOR_ID,
    now: datetime | None = None,
) -> StewardRecommendation:
    """Record one recommendation and clear the one it replaces.

    A task holds one recommendation at a time: a new one replaces the
    earlier one, so the steward never reads two answers to the same task.
    The row is written in the transaction of the caller.

    Args:
        session: The open session.
        recommendation: The recommendation to record.
        actor_id: The actor that made the recommendation.
        now: The moment the recommendation was made.

    Returns:
        The recorded recommendation.
    """
    moment = now or utc_now()
    session.execute(
        update(StewardRecommendation)
        .where(
            StewardRecommendation.task_kind == recommendation.task_kind,
            StewardRecommendation.task_id == recommendation.task_id,
            StewardRecommendation.cleared.is_(False),
        )
        .values(cleared=True, cleared_at=moment)
    )
    row = StewardRecommendation(
        id=new_id("stewrec"),
        task_kind=recommendation.task_kind,
        task_id=recommendation.task_id,
        record_version=recommendation.record_version,
        outcome=recommendation.outcome,
        confidence=recommendation.confidence,
        evidence=dict(recommendation.evidence),
        reason=recommendation.reason,
        made_by_actor_id=actor_id,
        made_at=moment,
        cleared=False,
        cleared_at=None,
    )
    session.add(row)
    session.flush()
    return row


__all__ = [
    "CHECK_WORDS",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_HELD",
    "CONFIDENCE_REVIEW",
    "CONFLICT_CHECKS",
    "ISSUE_CLASSES",
    "OUTCOME_ACCEPT",
    "OUTCOME_APPROVE_PARCEL",
    "OUTCOME_ASK_SOURCE",
    "OUTCOME_AWAITING_SOURCE",
    "OUTCOME_CONFIRM",
    "OUTCOME_KEEP",
    "OUTCOME_NONE_FITS",
    "OUTCOME_REJECT",
    "OUTCOME_RESOLVE",
    "OUTCOME_UNDO",
    "STEWARD_ASSIST_ACTOR_ID",
    "TASK_KINDS",
    "VERSION_TOKEN_CROSSWALK",
    "VERSION_TOKEN_CURRENT_SOURCE",
    "Recommendation",
    "Task",
    "recommend",
    "store_recommendation",
]

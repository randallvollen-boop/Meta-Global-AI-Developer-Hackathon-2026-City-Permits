"""The registry service.

The service owns canonical identities, the source crosswalks, the match
proposals and the steward decisions.  It never writes a source fact: the
permitting, GIS and ERP/Finance sources stay authoritative for the facts they
declared.
"""
# REQUIRES: MDM-01, MDM-02, MDM-03, MDM-04, MDM-05, GOV-05, D01, D02, D04
# Typed canonical identities, one active approved crosswalk per source record,
# evidence-based proposals, steward decisions with recorded actor/time/reason/
# evidence, trusted views and reversible corrections are implemented here.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import (
    NotFoundError,
    ValidationError,
)
from acme_city.core.ids import new_id
from acme_city.core.results import ConflictResult, VersionedResult
from acme_city.registry.candidates import (
    CandidateSet,
    Evidence,
    entity_target_for,
    generate_candidates,
)
from acme_city.registry.provenance import (
    affected_dependents,
    build_trusted_view,
    crosswalk_view,
    current_accepted_snapshot,
)
from acme_city.registry.schemas import (
    CrosswalkView,
    MatchDecisionCommand,
    MatchEvidenceView,
    MatchProposalCommand,
    MatchProposalView,
    TrustedView,
)
from acme_city.persistence.models import change, finance, governance, permit, registry, source

#: The link states a crosswalk may carry.
LINK_STATUSES: tuple[str, ...] = (
    "proposed",
    "approved",
    "rejected",
    "superseded",
    "removed",
    "no_match",
)

#: The permission a steward needs to record a link decision.
DECIDE_ACTION = "registry.crosswalk.decide"

#: The permission a steward needs to propose a link.
PROPOSE_ACTION = "registry.crosswalk.propose"


class RegistryService:
    """Canonical identities, crosswalks, proposals and trusted views."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    # ------------------------------------------------------------------ helpers

    def _contract(
        self, source_system_id: str, dataset_key: str
    ) -> governance.SourceContract | None:
        """Return the registered contract of a dataset."""
        return self._session.execute(
            select(governance.SourceContract).where(
                governance.SourceContract.source_system_id == source_system_id,
                governance.SourceContract.dataset_key == dataset_key,
            )
        ).scalar_one_or_none()

    def _domain_for(self, source_system_id: str, dataset_key: str) -> str | None:
        """Return the domain a dataset belongs to."""
        contract = self._contract(source_system_id, dataset_key)
        return contract.domain_id if contract is not None else None

    def _crosswalk_rows(
        self, source_system_id: str, source_record_id: str
    ) -> list[registry.Crosswalk]:
        """Return every crosswalk of a source record, oldest first."""
        return list(
            self._session.execute(
                select(registry.Crosswalk)
                .where(
                    registry.Crosswalk.source_system_id == source_system_id,
                    registry.Crosswalk.source_record_id == source_record_id,
                )
                .order_by(registry.Crosswalk.created_at, registry.Crosswalk.id)
            ).scalars().all()
        )

    def _ensure_canonical_entity(
        self, entity_id: str, entity_type: str, label: str | None
    ) -> registry.CanonicalEntity:
        """Return the canonical entity of an identifier, creating it when needed."""
        entity = self._session.execute(
            select(registry.CanonicalEntity).where(
                registry.CanonicalEntity.entity_id == entity_id
            )
        ).scalar_one_or_none()
        if entity is not None:
            return entity
        entity = registry.CanonicalEntity(
            id=f"entity_{entity_id}",
            entity_id=entity_id,
            entity_type=entity_type,
            label=label,
            status="active",
        )
        self._session.add(entity)
        self._session.flush()
        return entity

    def _entity_label(self, entity_id: str) -> str | None:
        """Return the label of a canonical entity."""
        party = self._session.get(registry.Party, entity_id)
        if party is not None:
            return party.display_name
        parcel = self._session.get(registry.Parcel, entity_id)
        if parcel is not None:
            return parcel.source_parcel_number
        address = self._session.get(registry.Address, entity_id)
        if address is not None:
            return address.source_string
        return None

    # ----------------------------------------------------------------- proposals

    def propose(
        self, command: MatchProposalCommand, actor: ActorContext
    ) -> MatchProposalView:
        """Propose the candidate links of one source record.

        The proposal is evidence for a steward.  It never approves a link and
        it never writes a source fact.
        """
        domain_id = self._domain_for(command.source_system_id, command.dataset_key)
        self._permissions.authorize(
            actor,
            PROPOSE_ACTION,
            ResourceContext(
                domain_id=domain_id,
                record_type="source_record",
                record_ids=(command.source_record_id,),
            ),
        )
        snapshot = current_accepted_snapshot(
            self._session, command.source_system_id, command.dataset_key, command.source_record_id
        )
        if snapshot is None:
            raise NotFoundError(
                f"no accepted source record {command.source_record_id!r} exists in "
                f"{command.source_system_id}/{command.dataset_key}"
            )
        entity_type = entity_target_for(command.dataset_key, command.entity_type)
        candidate_set = generate_candidates(
            self._session,
            dict(snapshot.raw_payload or {}),
            entity_type,
            snapshot.source_snapshot_id,
        )
        if command.candidate_entity_ids:
            allowed = set(command.candidate_entity_ids)
            candidate_set = CandidateSet(
                entity_type=candidate_set.entity_type,
                candidates=tuple(
                    candidate
                    for candidate in candidate_set.candidates
                    if candidate.entity_id in allowed
                ),
                compared_fields=candidate_set.compared_fields,
            )

        best = candidate_set.best
        proposal = registry.MatchProposal(
            id=new_id("proposal"),
            source_snapshot_id=snapshot.source_snapshot_id,
            correlation_id=new_id("corr"),
            entity_id=best.entity_id if best is not None else None,
            candidate_ids=[candidate.entity_id for candidate in candidate_set.candidates],
            compared_fields=list(candidate_set.compared_fields),
            supporting_evidence=[
                evidence.to_dict() for evidence in _all_supporting(candidate_set)
            ],
            conflicting_evidence=[
                evidence.to_dict() for evidence in _all_conflicting(candidate_set)
            ],
            method=candidate_set.method,
            model_run_id=None,
            proposal_score=best.score if best is not None else None,
            score_is_calibrated=False,
            disposition=candidate_set.disposition,
            created_by_actor_id=actor.actor_id,
            scenario_id=command.scenario_id,
        )
        self._session.add(proposal)
        self._session.flush()

        if best is not None:
            self._record_proposed_crosswalk(
                command=command,
                snapshot=snapshot,
                entity_id=best.entity_id,
                entity_type=entity_type,
            )

        self._audit.append(
            action="registry.crosswalk.propose",
            actor=actor,
            target_type="source_record",
            target_id=command.source_record_id,
            after_version=len(candidate_set.candidates),
            references=[command.source_system_id, command.dataset_key, proposal.id],
            metadata={
                "disposition": candidate_set.disposition,
                "candidate_count": len(candidate_set.candidates),
                "score_is_calibrated": False,
            },
        )
        return self._proposal_view(proposal)

    def _record_proposed_crosswalk(
        self,
        *,
        command: MatchProposalCommand,
        snapshot: source.SourceSnapshot,
        entity_id: str,
        entity_type: str,
    ) -> registry.Crosswalk:
        """Create or refresh the proposed crosswalk of a source record."""
        rows = self._crosswalk_rows(command.source_system_id, command.source_record_id)
        proposed = next((row for row in rows if row.link_status == "proposed"), None)
        if proposed is not None:
            self._ensure_canonical_entity(entity_id, entity_type, self._entity_label(entity_id))
            proposed.entity_id = entity_id
            proposed.entity_type = entity_type
            proposed.source_dataset_key = command.dataset_key
            proposed.version = proposed.version + 1
            self._session.flush()
            return proposed
        approved = next(
            (
                row
                for row in rows
                if row.link_status == "approved" and row.entity_id == entity_id
            ),
            None,
        )
        if approved is not None:
            # The link is already approved for this entity: a replayed proposal
            # does not create a second record.
            return approved
        self._ensure_canonical_entity(entity_id, entity_type, self._entity_label(entity_id))
        crosswalk = registry.Crosswalk(
            id=new_id("crosswalk"),
            entity_id=entity_id,
            entity_type=entity_type,
            source_system_id=command.source_system_id,
            source_dataset_key=command.dataset_key,
            source_record_id=command.source_record_id,
            link_status="proposed",
            decision=None,
            decision_actor_id=None,
            decided_at=None,
            expected_version=None,
            valid_from=None,
            valid_to=None,
            superseded_by_crosswalk_id=None,
            scenario_id=command.scenario_id,
        )
        self._session.add(crosswalk)
        self._session.flush()
        return crosswalk

    # ------------------------------------------------------------------ decisions

    def decide(
        self, command: MatchDecisionCommand, actor: ActorContext
    ) -> VersionedResult[CrosswalkView] | ConflictResult:
        """Record a steward decision on a source-to-canonical link.

        The decision records the acting steward, the time, the reason and the
        evidence the steward relied on.  A correction keeps the earlier
        decision and creates a new version of the link.
        """
        crosswalk = self._resolve_crosswalk(command)
        source_system_id = command.source_system_id or (
            crosswalk.source_system_id if crosswalk is not None else ""
        )
        dataset_key = command.dataset_key or (
            crosswalk.source_dataset_key if crosswalk is not None else ""
        )
        domain_id = self._domain_for(source_system_id, dataset_key or "")
        self._permissions.authorize(
            actor,
            DECIDE_ACTION,
            ResourceContext(
                domain_id=domain_id,
                record_type="source_record",
                record_ids=(crosswalk.source_record_id if crosswalk is not None else "",),
            ),
        )
        if crosswalk is None:
            raise NotFoundError(
                "no source link was found for the stated source record; propose the link first"
            )
        if command.expected_version is not None and crosswalk.version != command.expected_version:
            return ConflictResult(
                code="version_conflict",
                expected_version=command.expected_version,
                current_version=crosswalk.version,
                differences=(
                    {
                        "field": "link_status",
                        "expected": command.expected_version,
                        "current": crosswalk.version,
                    },
                ),
            )
        if command.decision not in {"approve", "reject", "no_match", "correct"}:
            raise ValidationError(
                "a link decision is one of approve, reject, no_match or correct"
            )

        decision_proposal = self._record_decision_proposal(
            command=command, crosswalk=crosswalk, actor=actor
        )

        if command.decision == "correct":
            view = self._apply_correction(command, crosswalk, actor)
        else:
            view = self._apply_decision(command, crosswalk, actor)

        event = self._audit.append(
            action="registry.crosswalk.decide",
            actor=actor,
            target_type="source_record",
            target_id=crosswalk.source_record_id,
            before_version=crosswalk.version - 1,
            after_version=crosswalk.version,
            reason=command.reason,
            references=[view.crosswalk_id, decision_proposal.id, crosswalk.entity_id],
            metadata={"decision": command.decision, "link_status": view.link_status},
        )
        return VersionedResult(value=view, version=view.version, audit_event_id=event.id)

    def _resolve_crosswalk(
        self, command: MatchDecisionCommand
    ) -> registry.Crosswalk | None:
        """Return the crosswalk a decision applies to."""
        if command.crosswalk_id:
            return self._session.get(registry.Crosswalk, command.crosswalk_id)
        if not command.source_system_id or not command.source_record_id:
            return None
        rows = self._crosswalk_rows(command.source_system_id, command.source_record_id)
        proposed = next((row for row in rows if row.link_status == "proposed"), None)
        if proposed is not None:
            return proposed
        approved = [row for row in rows if row.link_status == "approved"]
        return approved[-1] if approved else None

    def _apply_decision(
        self,
        command: MatchDecisionCommand,
        crosswalk: registry.Crosswalk,
        actor: ActorContext,
    ) -> CrosswalkView:
        """Apply an approve, reject or no-match decision."""
        before_version = crosswalk.version
        crosswalk.decision = command.reason
        crosswalk.decision_actor_id = actor.actor_id
        crosswalk.decided_at = self._now
        crosswalk.expected_version = (
            command.expected_version if command.expected_version is not None else before_version
        )
        if command.decision == "approve":
            crosswalk.link_status = "approved"
            crosswalk.valid_from = self._now
            self._supersede_other_approved(crosswalk)
            self._materialize_account_link(crosswalk)
            self._register_revalidation(crosswalk, actor)
        elif command.decision == "reject":
            crosswalk.link_status = "rejected"
        else:
            crosswalk.link_status = "no_match"
        crosswalk.version = before_version + 1
        self._session.flush()
        return crosswalk_view(crosswalk)

    def _apply_correction(
        self,
        command: MatchDecisionCommand,
        crosswalk: registry.Crosswalk,
        actor: ActorContext,
    ) -> CrosswalkView:
        """Correct an approved link without destroying the earlier decision."""
        if not command.entity_id:
            raise ValidationError("a correction states the canonical entity to link to")
        entity_type = command.entity_id and self._entity_type_of(command.entity_id)
        self._ensure_canonical_entity(
            command.entity_id, entity_type or crosswalk.entity_type, self._entity_label(command.entity_id)
        )
        replacement = registry.Crosswalk(
            id=new_id("crosswalk"),
            entity_id=command.entity_id,
            entity_type=entity_type or crosswalk.entity_type,
            source_system_id=crosswalk.source_system_id,
            source_dataset_key=crosswalk.source_dataset_key,
            source_record_id=crosswalk.source_record_id,
            link_status="approved",
            decision=command.reason,
            decision_actor_id=actor.actor_id,
            decided_at=self._now,
            expected_version=command.expected_version,
            valid_from=self._now,
            valid_to=None,
            superseded_by_crosswalk_id=None,
            scenario_id=command.scenario_id or crosswalk.scenario_id,
        )
        self._session.add(replacement)
        self._session.flush()

        before_version = crosswalk.version
        crosswalk.link_status = "superseded"
        crosswalk.superseded_by_crosswalk_id = replacement.id
        crosswalk.version = before_version + 1
        self._session.flush()

        self._supersede_other_approved(replacement)
        self._materialize_account_link(replacement)
        self._register_revalidation(replacement, actor, previous_entity_id=crosswalk.entity_id)
        return crosswalk_view(replacement)

    def _entity_type_of(self, entity_id: str) -> str | None:
        """Return the entity family of a canonical identifier."""
        if self._session.get(registry.Party, entity_id) is not None:
            return "party"
        if self._session.get(registry.Parcel, entity_id) is not None:
            return "parcel"
        if self._session.get(registry.Address, entity_id) is not None:
            return "address"
        entity = self._session.execute(
            select(registry.CanonicalEntity).where(
                registry.CanonicalEntity.entity_id == entity_id
            )
        ).scalar_one_or_none()
        return entity.entity_type if entity is not None else None

    def _supersede_other_approved(self, crosswalk: registry.Crosswalk) -> None:
        """Keep at most one active approved crosswalk per source record."""
        for row in self._crosswalk_rows(crosswalk.source_system_id, crosswalk.source_record_id):
            if row.id == crosswalk.id or row.link_status != "approved":
                continue
            row.link_status = "superseded"
            row.superseded_by_crosswalk_id = crosswalk.id
            row.version = row.version + 1
        self._session.flush()

    def _materialize_account_link(self, crosswalk: registry.Crosswalk) -> None:
        """Record an approved finance account link on the account itself."""
        if crosswalk.source_dataset_key != "finance_accounts":
            return
        account = self._session.execute(
            select(registry.FinanceAccount).where(
                registry.FinanceAccount.source_account_id == crosswalk.source_record_id
            )
        ).scalar_one_or_none()
        if account is None:
            return
        account.party_id = crosswalk.entity_id
        account.link_status = "linked"
        account.link_decision = crosswalk.decision
        account.version = account.version + 1

        active_links = self._session.execute(
            select(finance.FinanceAccountLink).where(
                finance.FinanceAccountLink.account_id == account.id,
                finance.FinanceAccountLink.link_status == "approved",
            )
        ).scalars().all()
        current = None
        for link in active_links:
            if link.party_id == crosswalk.entity_id:
                current = link
                continue
            link.link_status = "superseded"
            link.version = link.version + 1
        if current is None:
            self._session.add(
                finance.FinanceAccountLink(
                    id=new_id("faclink"),
                    account_id=account.id,
                    party_id=crosswalk.entity_id,
                    link_status="approved",
                    decided_by_actor_id=crosswalk.decision_actor_id,
                    decided_at=crosswalk.decided_at,
                    reason=crosswalk.decision,
                    source_version=str(crosswalk.version),
                )
            )
        else:
            current.decided_by_actor_id = crosswalk.decision_actor_id
            current.decided_at = crosswalk.decided_at
            current.reason = crosswalk.decision
            current.source_version = str(crosswalk.version)
        self._session.flush()

    def _register_revalidation(
        self,
        crosswalk: registry.Crosswalk,
        actor: ActorContext,
        *,
        previous_entity_id: str | None = None,
    ) -> None:
        """Register the revalidation work a new or corrected link creates."""
        entity_ids = tuple({crosswalk.entity_id, previous_entity_id or crosswalk.entity_id})
        dependents = affected_dependents(self._session, entity_ids=entity_ids)
        total = sum(len(items) for items in dependents.values())
        if total == 0:
            return
        for consumer_type, consumer_ids in dependents.items():
            for consumer_id in consumer_ids:
                deduplication_key = (
                    f"crosswalk_revalidation:{crosswalk.id}:{consumer_type}:{consumer_id}"
                )
                existing = self._session.execute(
                    select(change.ReviewTask).where(
                        change.ReviewTask.deduplication_key == deduplication_key
                    )
                ).scalars().first()
                if existing is not None:
                    continue
                self._session.add(
                    change.ReviewTask(
                        id=new_id("task"),
                        change_case_id=None,
                        assignee_actor_id=actor.actor_id,
                        task_type="crosswalk_revalidation",
                        target_type=consumer_type,
                        target_id=consumer_id,
                        deduplication_key=deduplication_key,
                        status="open",
                        due_at=None,
                        scenario_id=crosswalk.scenario_id,
                    )
                )
        self._session.add(
            permit.ImpactReview(
                id=new_id("impact"),
                target_type="crosswalk",
                target_id=crosswalk.id,
                reason=(
                    f"the link of {crosswalk.source_record_id!r} changed; the dependent records "
                    "have to be reviewed before their decisions are relied on"
                ),
                assigned_actor_id=actor.actor_id,
                status="open",
                scenario_id=crosswalk.scenario_id,
            )
        )
        self._session.flush()

    def _record_decision_proposal(
        self,
        *,
        command: MatchDecisionCommand,
        crosswalk: registry.Crosswalk,
        actor: ActorContext,
    ) -> registry.MatchProposal:
        """Persist the steward decision with its actor, time, reason and evidence."""
        snapshot = current_accepted_snapshot(
            self._session,
            crosswalk.source_system_id,
            crosswalk.source_dataset_key or "",
            crosswalk.source_record_id,
        )
        if snapshot is None:
            raise ValidationError(
                "the source record of this link has no accepted version, so the decision "
                "cannot be recorded against a snapshot"
            )
        supporting: list[dict[str, Any]] = []
        conflicting: list[dict[str, Any]] = []
        compared_fields: list[str] = []
        for entry in command.evidence:
            field_path = str(entry.get("field", "")).strip()
            if not field_path:
                raise ValidationError("every piece of decision evidence names its field")
            direction = str(entry.get("direction", "supporting")).strip().lower()
            record = {
                "field": field_path,
                "source_snapshot_id": entry.get("source_snapshot_id")
                or (snapshot.source_snapshot_id if snapshot is not None else None),
                "raw_value": entry.get("value"),
                "normalized_value": entry.get("normalized_value", entry.get("value")),
                "direction": direction if direction in {"supporting", "conflicting"} else "supporting",
                "method": str(entry.get("method", "steward_evidence")),
                "detail": str(entry.get("note", "")),
            }
            compared_fields.append(field_path)
            if record["direction"] == "conflicting":
                conflicting.append(record)
            else:
                supporting.append(record)
        proposal = registry.MatchProposal(
            id=new_id("proposal"),
            source_snapshot_id=snapshot.source_snapshot_id,
            correlation_id=new_id("corr"),
            entity_id=command.entity_id or crosswalk.entity_id,
            candidate_ids=[command.entity_id or crosswalk.entity_id],
            compared_fields=sorted(set(compared_fields)),
            supporting_evidence=supporting,
            conflicting_evidence=conflicting,
            method="steward_decision",
            model_run_id=None,
            proposal_score=None,
            score_is_calibrated=False,
            disposition=command.decision,
            created_by_actor_id=actor.actor_id,
            scenario_id=command.scenario_id or crosswalk.scenario_id,
        )
        self._session.add(proposal)
        self._session.flush()
        return proposal

    # -------------------------------------------------------------------- reads

    def current_crosswalk(
        self,
        source_system_id: str,
        source_record_id: str,
        dataset_key: str | None = None,
    ) -> CrosswalkView | None:
        """Return the active crosswalk of a source record."""
        rows = self._crosswalk_rows(source_system_id, source_record_id)
        if dataset_key:
            rows = [row for row in rows if row.source_dataset_key == dataset_key]
        approved = [row for row in rows if row.link_status == "approved"]
        if approved:
            return crosswalk_view(approved[-1])
        proposed = [row for row in rows if row.link_status == "proposed"]
        if proposed:
            return crosswalk_view(proposed[-1])
        return crosswalk_view(rows[-1]) if rows else None

    def crosswalk_history(
        self, source_system_id: str, source_record_id: str
    ) -> list[CrosswalkView]:
        """Return every decision of a source record, oldest first."""
        return [
            crosswalk_view(row)
            for row in self._crosswalk_rows(source_system_id, source_record_id)
        ]

    def trusted_view(self, entity_id: str) -> TrustedView | None:
        """Return the trusted view of a canonical entity."""
        return build_trusted_view(self._session, entity_id, now=self._now)

    def _proposal_view(self, proposal: registry.MatchProposal) -> MatchProposalView:
        """Return the view model of a proposal."""
        snapshot = self._session.get(source.SourceSnapshot, proposal.source_snapshot_id)
        dataset_key = snapshot.source_dataset_id if snapshot is not None else ""
        entity_type = self._entity_type_of(proposal.entity_id) if proposal.entity_id else None
        if entity_type is None:
            crosswalk = self._session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.source_system_id
                    == (snapshot.source_system_id if snapshot is not None else ""),
                    registry.Crosswalk.source_record_id
                    == (snapshot.source_record_id if snapshot is not None else ""),
                )
            ).scalars().first()
            entity_type = (
                crosswalk.entity_type
                if crosswalk is not None
                else entity_target_for(dataset_key)
            )
        return MatchProposalView(
            proposal_id=proposal.id,
            source_snapshot_id=proposal.source_snapshot_id,
            source_system_id=snapshot.source_system_id if snapshot is not None else "",
            source_dataset_key=dataset_key,
            source_record_id=snapshot.source_record_id if snapshot is not None else "",
            entity_id=proposal.entity_id,
            entity_type=entity_type,
            disposition=proposal.disposition,
            method=proposal.method,
            proposal_score=proposal.proposal_score,
            score_is_calibrated=proposal.score_is_calibrated,
            score_label="uncalibrated_heuristic",
            candidate_ids=list(proposal.candidate_ids or []),
            compared_fields=list(proposal.compared_fields or []),
            supporting_evidence=[
                MatchEvidenceView(**item) for item in (proposal.supporting_evidence or [])
            ],
            conflicting_evidence=[
                MatchEvidenceView(**item) for item in (proposal.conflicting_evidence or [])
            ],
            created_by_actor_id=proposal.created_by_actor_id,
            scenario_id=proposal.scenario_id,
            created_at=proposal.created_at,
        )


def _all_supporting(candidate_set: CandidateSet) -> list[Evidence]:
    """Return the supporting evidence of every candidate."""
    items: list[Evidence] = []
    for candidate in candidate_set.candidates:
        items.extend(candidate.supporting)
    return items


def _all_conflicting(candidate_set: CandidateSet) -> list[Evidence]:
    """Return the conflicting evidence of every candidate."""
    items: list[Evidence] = []
    for candidate in candidate_set.candidates:
        items.extend(candidate.conflicting)
    return items


__all__ = ["DECIDE_ACTION", "LINK_STATUSES", "PROPOSE_ACTION", "RegistryService"]

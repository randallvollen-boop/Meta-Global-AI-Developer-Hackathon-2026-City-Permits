"""The parcel link of an application: locate, approve, confirm.

Municipalities identify property by parcel number, not by address, so every
case is matched from the address text an applicant typed to a parcel:

1. the intake agent runs the Address locator: it asks the GIS for candidates
   (``findAddressCandidates``) and asks the parcel layer which parcel the best
   point falls in.  It only *proposes*;
2. the Data Steward approves the parcel link (an identity link);
3. the Permit Reviewer confirms the parcel before deciding.

A case that carries a parcel match cannot be approved until step 2 and step 3
are done.  A case without a match (the seeded demonstration cases) is
unchanged.  Nothing here writes a source fact: a wrong address is flagged to
GIS through the existing source-correction route.
"""
# REQUIRES: GIS-03, GIS-04
# The locator proposes, the steward approves the parcel link, the reviewer
# confirms the parcel, and every step is audited.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import ConflictError, NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.gis.adapter import (
    GisLocator,
    GisServiceError,
    LocatorCandidate,
    ParcelRecord,
    get_locator,
)
from acme_city.permits.guard import require_mutable
from acme_city.persistence.models import gis, permit, registry
from acme_city.persistence.models.gis import (
    MATCH_APPROVED,
    MATCH_NEEDS_CHOICE,
    MATCH_NOT_FOUND,
    MATCH_PROPOSED,
    MATCH_REJECTED,
)

PROPOSE_ACTION = "parcel.match.propose"
APPROVE_ACTION = "registry.crosswalk.decide"
CONFIRM_ACTION = "parcel.confirm"

#: The domain of the parcel master.
PARCEL_DOMAIN = "parcels"
PERMIT_DOMAIN = "permits"

AMBIGUOUS_MESSAGE = "Address needs a person to choose the property"
NOT_FOUND_MESSAGE = "Address not found in the city locator"


def approvable(match: gis.ApplicationParcelMatch) -> bool:
    """Whether the steward may approve this parcel link.

    Only a proposed link that names a parcel of the registry may be approved:
    the point has to fall inside a parcel and the parcel has to exist in the
    registry.  Every caller of that rule reads it here, so the City never
    approves a link under a weaker rule than the one it shows.
    """
    return match.link_state == MATCH_PROPOSED and bool(match.parcel_id)


def strong_candidates(
    candidates: list[dict[str, Any]], threshold: float
) -> list[dict[str, Any]]:
    """Return the candidates that score at or above the line the City applies.

    One strong candidate is a parcel the City proposes; several are a choice
    for a person.
    """
    return [
        item for item in candidates if float(item.get("score") or 0.0) >= threshold
    ]


@dataclass(frozen=True)
class LocateOutcome:
    """What the Address locator found for one application."""

    match: gis.ApplicationParcelMatch
    kind: str  # proposed | needs_choice | not_found | reused
    parcel_conflict: str = ""


def _submitted_text(session: Session, application: permit.Application) -> str:
    facts = dict(application.submitted_facts or {})
    text = str(
        facts.get("submitted_site_text") or facts.get("site_address") or ""
    ).strip()
    if text:
        return text
    site = session.execute(
        select(permit.ApplicationSite).where(
            permit.ApplicationSite.application_id == application.id
        )
    ).scalars().first()
    return (site.submitted_address_text or "").strip() if site else ""


class ParcelMatchService:
    """Locates, proposes, approves and confirms the parcel of an application."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Any = None,
        now: datetime | None = None,
        locator: GisLocator | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._now = now or utc_now()
        self._locator = locator
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    # ----------------------------------------------------------------- helpers

    @property
    def locator(self) -> GisLocator:
        if self._locator is None:
            self._locator = get_locator(self._settings)
        return self._locator

    @property
    def threshold(self) -> int:
        return int(getattr(self._settings, "gis_auto_propose_score", 90) or 90)

    def for_application(self, application_id: str) -> gis.ApplicationParcelMatch | None:
        return self._session.execute(
            select(gis.ApplicationParcelMatch).where(
                gis.ApplicationParcelMatch.application_id == application_id
            )
        ).scalar_one_or_none()

    def _load(self, application_id: str) -> tuple[permit.Application, gis.ApplicationParcelMatch]:
        application = self._session.get(permit.Application, application_id)
        if application is None:
            raise NotFoundError("that application does not exist")
        match = self.for_application(application_id)
        if match is None:
            raise NotFoundError("that application has no parcel match yet")
        return application, match

    def _load_open(self, application_id: str, *, action: str) -> permit.Application:
        """Return the application of a parcel operation, refusing an archived case.

        The guard runs before the parcel match is read, so an archived case
        is refused as an archived case and not as a case without a match.
        """
        application = self._session.get(permit.Application, application_id)
        if application is None:
            raise NotFoundError("that application does not exist")
        require_mutable(application, action=action)
        return application

    def registry_parcel(self, parcel_number: str | None) -> registry.Parcel | None:
        if not parcel_number:
            return None
        return self._session.execute(
            select(registry.Parcel).where(registry.Parcel.source_parcel_number == parcel_number)
        ).scalar_one_or_none()

    def registry_address(self, address_id: str | None) -> registry.Address | None:
        if not address_id:
            return None
        return self._session.execute(
            select(registry.Address).where(registry.Address.address_id == address_id)
        ).scalar_one_or_none()

    def _check_version(self, match: gis.ApplicationParcelMatch, expected: int | None) -> None:
        if expected is not None and expected != match.version:
            raise ConflictError(
                "the parcel link changed since it was read; read it again and retry",
                expected_version=expected,
                current_version=match.version,
            )

    def _enrich(self, candidates: list[LocatorCandidate]) -> list[dict[str, Any]]:
        rows = []
        for candidate in candidates:
            record = candidate.to_dict()
            if not record["parcel_number"]:
                parcel = self.locator.parcel_at(candidate.x, candidate.y)
                record["parcel_number"] = parcel.parcel_number if parcel else ""
            rows.append(record)
        return rows

    # ------------------------------------------------------------------ locate

    def locate(
        self, application: permit.Application, actor: ActorContext | str
    ) -> LocateOutcome:
        """Run the Address locator for an application and record what it found.

        An already approved link is kept: re-running the intake agent never
        throws away a steward decision.
        """
        if isinstance(actor, ActorContext):
            self._permissions.authorize(
                actor, PROPOSE_ACTION, ResourceContext(domain_id=PERMIT_DOMAIN)
            )
        require_mutable(application, action="locating the property")
        actor_id = actor.actor_id if isinstance(actor, ActorContext) else actor
        existing = self.for_application(application.id)
        if existing is not None and existing.link_state == MATCH_APPROVED:
            return LocateOutcome(match=existing, kind="reused")

        text = _submitted_text(self._session, application)
        try:
            candidates = self.locator.find_candidates(text, 5) if text else []
        except GisServiceError as error:
            candidates = []
            note = f"The city locator could not be reached: {error}"
        else:
            note = ""
        enriched = self._enrich(candidates)

        top = candidates[0] if candidates else None
        strong = strong_candidates(enriched, self.threshold)
        parcel: ParcelRecord | None = None
        if top is None:
            state = MATCH_NOT_FOUND
            status = "U"
            note = note or NOT_FOUND_MESSAGE
        elif len(strong) == 1:
            parcel = self.locator.parcel_at(top.x, top.y)
            if parcel is None:
                state = MATCH_NEEDS_CHOICE
                note = "The best address point falls in no parcel of the parcel layer."
            else:
                state = MATCH_PROPOSED
                note = (
                    f"One candidate scored {top.score:g} (threshold {self.threshold}); the "
                    "point falls inside the parcel shown."
                )
            status = top.status
        else:
            state = MATCH_NEEDS_CHOICE
            status = "T" if len(strong) > 1 else top.status
            note = (
                f"{len(strong)} candidates scored at or above {self.threshold}; a person must choose."
                if len(strong) > 1
                else f"The best candidate scored {top.score:g}, below the threshold {self.threshold}; "
                "a person must choose."
            )

        values = {
            "submitted_text": text[:320],
            "matched_address": top.address if (top and state == MATCH_PROPOSED) else None,
            "address_id": None,
            "parcel_id": None,
            "parcel_number": parcel.parcel_number if parcel else None,
            "score": top.score if top else None,
            "locator_status": status,
            "x": top.x if top else None,
            "y": top.y if top else None,
            "candidates": enriched,
            "method": "findAddressCandidates + point-in-parcel query",
            "link_state": state,
            "note": note,
            "proposed_by": actor_id,
            "decided_by": None,
            "decided_at": None,
            "decision_reason": None,
            "confirmed_by": None,
            "confirmed_at": None,
        }
        if state == MATCH_PROPOSED and top is not None:
            registry_address = self.registry_address(top.address_id)
            registry_parcel = self.registry_parcel(parcel.parcel_number if parcel else None)
            values["address_id"] = registry_address.id if registry_address else None
            values["parcel_id"] = registry_parcel.id if registry_parcel else None
        match = existing
        if match is None:
            match = gis.ApplicationParcelMatch(
                id=new_id("pmatch"),
                application_id=application.id,
                correlation_id=application.correlation_id or new_id("corr"),
                version=1,
                **values,
            )
            self._session.add(match)
        else:
            for key, value in values.items():
                setattr(match, key, value)
            match.version += 1
        self._session.flush()

        conflict = ""
        facts = dict(application.submitted_facts or {})
        given = str(facts.get("parcel_number") or facts.get("submitted_parcel") or "").strip()
        if state == MATCH_PROPOSED and parcel is not None and given:
            if given.upper() != parcel.parcel_number.upper():
                conflict = (
                    f"The application states parcel {given}, but the located address "
                    f"falls in parcel {parcel.parcel_number}."
                )
        self._audit.append(
            action="parcel.match.locate",
            actor=actor,
            target_type="application",
            target_id=application.id,
            after_version=match.version,
            reason=note,
            references=[match.id],
            metadata={
                "link_state": state,
                "score": match.score,
                "locator_status": status,
                "parcel_number": match.parcel_number,
                "candidates": len(enriched),
            },
        )
        return LocateOutcome(match=match, kind=state, parcel_conflict=conflict)

    # --------------------------------------------------------- steward decision

    def decide_link(
        self,
        application_id: str,
        *,
        decision: str,
        reason: str,
        expected_version: int | None,
        actor: ActorContext,
    ) -> gis.ApplicationParcelMatch:
        """The Data Steward approves or rejects the proposed parcel link."""
        self._permissions.authorize(
            actor, APPROVE_ACTION, ResourceContext(domain_id=PARCEL_DOMAIN)
        )
        if decision not in {"approve", "reject"}:
            raise ValidationError("the decision must be approve or reject")
        if not reason.strip():
            raise ValidationError("a parcel link decision requires a reason")
        application = self._load_open(application_id, action="deciding the parcel link")
        _application, match = self._load(application_id)
        self._check_version(match, expected_version)
        if decision == "approve":
            if not approvable(match):
                raise ValidationError(
                    "only a proposed parcel link that names a parcel of the registry can be approved"
                )
            match.link_state = MATCH_APPROVED
            self._resolve_site(application, match)
        else:
            if match.link_state not in {MATCH_PROPOSED, MATCH_NEEDS_CHOICE, MATCH_NOT_FOUND}:
                raise ValidationError("only an open parcel link can be rejected")
            match.link_state = MATCH_REJECTED
        match.decided_by = actor.actor_id
        match.decided_at = self._now
        match.decision_reason = reason.strip()
        match.confirmed_by = None
        match.confirmed_at = None
        match.version += 1
        self._session.flush()
        self._audit.append(
            action=f"parcel.link.{decision}",
            actor=actor,
            target_type="application",
            target_id=application_id,
            after_version=match.version,
            reason=reason.strip(),
            references=[match.id, match.parcel_number or ""],
            metadata={"parcel_number": match.parcel_number, "link_state": match.link_state},
        )
        return match

    def _resolve_site(
        self, application: permit.Application, match: gis.ApplicationParcelMatch
    ) -> None:
        """Point the site of the application at the approved parcel and address."""
        site = self._session.execute(
            select(permit.ApplicationSite).where(
                permit.ApplicationSite.application_id == application.id,
                permit.ApplicationSite.is_primary.is_(True),
            )
        ).scalars().first()
        if site is None:
            return
        site.parcel_id = match.parcel_id
        site.address_id = match.address_id or site.address_id
        site.resolution_status = (
            "resolved" if site.parcel_id and site.address_id else "unresolved"
        )
        self._session.flush()

    # ------------------------------------------------------ propose a different

    def choose_candidate(
        self,
        application_id: str,
        *,
        address_id: str,
        reason: str,
        expected_version: int | None,
        actor: ActorContext,
    ) -> gis.ApplicationParcelMatch:
        """Propose another candidate of the locator; the steward must approve it."""
        self._permissions.authorize(
            actor, PROPOSE_ACTION, ResourceContext(domain_id=PERMIT_DOMAIN)
        )
        if not reason.strip():
            raise ValidationError("choosing another candidate requires a reason")
        self._load_open(application_id, action="choosing another parcel candidate")
        _application, match = self._load(application_id)
        self._check_version(match, expected_version)
        chosen = next(
            (item for item in (match.candidates or []) if item.get("address_id") == address_id),
            None,
        )
        if chosen is None:
            raise ValidationError("that address is not one of the locator candidates")
        parcel = self.locator.parcel_at(float(chosen["x"]), float(chosen["y"]))
        if parcel is None:
            raise ValidationError("that candidate falls in no parcel of the parcel layer")
        self._propose(
            match,
            address=chosen["address"],
            address_id=chosen["address_id"],
            parcel=parcel,
            score=float(chosen["score"]),
            status=str(chosen.get("status") or "M"),
            x=float(chosen["x"]),
            y=float(chosen["y"]),
            method=f"candidate chosen by {actor.actor_id}",
            reason=reason,
            actor=actor,
        )
        self._audit_change("parcel.candidate.choose", actor, match, reason)
        return match

    def find_by_number(
        self,
        application_id: str,
        *,
        parcel_number: str,
        reason: str,
        expected_version: int | None,
        actor: ActorContext,
    ) -> gis.ApplicationParcelMatch:
        """Look a parcel up in the parcel layer by its number and propose it."""
        self._permissions.authorize(
            actor, PROPOSE_ACTION, ResourceContext(domain_id=PERMIT_DOMAIN)
        )
        if not parcel_number.strip():
            raise ValidationError("a parcel number is required")
        if not reason.strip():
            raise ValidationError("finding a parcel by number requires a reason")
        self._load_open(application_id, action="looking a parcel up by number")
        _application, match = self._load(application_id)
        self._check_version(match, expected_version)
        parcel = self.locator.parcel_by_number(parcel_number)
        if parcel is None:
            raise ValidationError(
                f"the parcel layer holds no parcel {parcel_number.strip()!r}"
            )
        points = self.locator.addresses_on_parcel(parcel.parcel_number)
        building = next((point for point in points if not point.unit), points[0] if points else None)
        self._propose(
            match,
            address=building.full_address if building else parcel.site_address,
            address_id=building.address_id if building else "",
            parcel=parcel,
            score=100.0,
            status="M",
            x=float(building.x) if building and building.x is not None else None,
            y=float(building.y) if building and building.y is not None else None,
            method=f"parcel found by number {parcel.parcel_number}, chosen by {actor.actor_id}",
            reason=reason,
            actor=actor,
        )
        self._audit_change("parcel.find_by_number", actor, match, reason)
        return match

    def _propose(
        self,
        match: gis.ApplicationParcelMatch,
        *,
        address: str,
        address_id: str,
        parcel: ParcelRecord,
        score: float,
        status: str,
        x: float | None,
        y: float | None,
        method: str,
        reason: str,
        actor: ActorContext,
    ) -> None:
        registry_parcel = self.registry_parcel(parcel.parcel_number)
        registry_address = self.registry_address(address_id)
        match.matched_address = address
        match.address_id = registry_address.id if registry_address else None
        match.parcel_id = registry_parcel.id if registry_parcel else None
        match.parcel_number = parcel.parcel_number
        match.score = score
        match.locator_status = status if status in {"M", "T", "U"} else "M"
        match.x, match.y = x, y
        match.method = method
        match.link_state = MATCH_PROPOSED if registry_parcel else MATCH_NEEDS_CHOICE
        match.note = (
            f"{actor.actor_id} proposed parcel {parcel.parcel_number}: {reason.strip()}"
            if registry_parcel
            else f"Parcel {parcel.parcel_number} is not in the registry yet."
        )
        match.proposed_by = actor.actor_id
        match.decided_by = None
        match.decided_at = None
        match.decision_reason = None
        match.confirmed_by = None
        match.confirmed_at = None
        match.version += 1
        self._session.flush()

    def _audit_change(
        self, action: str, actor: ActorContext, match: gis.ApplicationParcelMatch, reason: str
    ) -> None:
        self._audit.append(
            action=action,
            actor=actor,
            target_type="application",
            target_id=match.application_id,
            after_version=match.version,
            reason=reason.strip(),
            references=[match.id, match.parcel_number or ""],
            metadata={"parcel_number": match.parcel_number, "link_state": match.link_state},
        )

    # ------------------------------------------------------------ confirmation

    def confirm(
        self,
        application_id: str,
        *,
        reason: str,
        expected_version: int | None,
        actor: ActorContext,
    ) -> gis.ApplicationParcelMatch:
        """The Permit Reviewer confirms that this is the right property."""
        self._permissions.authorize(
            actor, CONFIRM_ACTION, ResourceContext(domain_id=PERMIT_DOMAIN)
        )
        application = self._load_open(application_id, action="confirming the parcel")
        _application, match = self._load(application_id)
        self._check_version(match, expected_version)
        if match.link_state != MATCH_APPROVED:
            raise ValidationError(
                "the Data Steward must approve the parcel link before the reviewer confirms the parcel"
            )
        match.confirmed_by = actor.actor_id
        match.confirmed_at = self._now
        match.version += 1
        self._session.flush()
        self._audit_change(
            "parcel.confirm", actor, match, reason.strip() or "confirmed: this is the right property"
        )
        return match

    # ---------------------------------------------------------------- blockers

    def blocker_states(self, application_id: str) -> list[tuple[str, str]]:
        """Return the ``(code, detail)`` pairs that block a decision."""
        match = self.for_application(application_id)
        if match is None:
            return []
        if match.link_state != MATCH_APPROVED:
            return [
                (
                    "parcel_link_unapproved",
                    "the parcel link proposed by the address locator has not been approved "
                    "by the Data Steward",
                )
            ]
        if match.confirmed_at is None:
            return [
                (
                    "parcel_unconfirmed",
                    "the Permit Reviewer has not confirmed that this is the right property",
                )
            ]
        return []

    def confirmed_parcel(self, application_id: str) -> registry.Parcel | None:
        """Return the confirmed parcel, or ``None`` when it is not confirmed."""
        match = self.for_application(application_id)
        if match is None or match.link_state != MATCH_APPROVED or match.confirmed_at is None:
            return None
        return self._session.get(registry.Parcel, match.parcel_id) if match.parcel_id else None

    def approved_parcel(self, application_id: str) -> registry.Parcel | None:
        """Return the parcel the Data Steward approved, or ``None``.

        The approved link is the property the City resolved for the case: the
        Data Steward compared the address the applicant typed with the parcel
        of the locator and approved that link.  The Permit Reviewer confirms
        the parcel afterwards, before the decision; until then the case keeps
        the blocker ``parcel_unconfirmed``.
        """
        match = self.for_application(application_id)
        if match is None or match.link_state != MATCH_APPROVED:
            return None
        return self._session.get(registry.Parcel, match.parcel_id) if match.parcel_id else None

    def parcel_confirmed(self, application_id: str) -> bool:
        """Return whether the Data Steward confirmed the property of the case.

        A case that carries no parcel match has no property follow-up. A case
        with a match may have parcel-dependent rules marked Not checked until
        the Data Steward approves the link; the review still proceeds on the
        checks that ran.
        """
        match = self.for_application(application_id)
        if match is None:
            return True
        return match.link_state == MATCH_APPROVED


__all__ = [
    "AMBIGUOUS_MESSAGE",
    "APPROVE_ACTION",
    "CONFIRM_ACTION",
    "NOT_FOUND_MESSAGE",
    "PROPOSE_ACTION",
    "LocateOutcome",
    "ParcelMatchService",
    "approvable",
    "strong_candidates",
]

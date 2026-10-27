"""The permit application service.

The service owns the application lifecycle: it records an immutable submitted
revision, evaluates a revision against the selected rule versions, and keeps
the submitted facts, the current profile, the evaluation, the decision and
the issued permit apart from one another.

Every evaluation records the rule versions, the inputs, the basis date and the
dependencies it used, so that a later change can be shown to affect exactly
the cases it affects.
"""
# REQUIRES: PER-01, PER-02, PER-03, PER-06, EDIT-05, ING-02, CHG-03
# Submitted facts are separate from shared party and GIS facts, every
# revision is immutable, and an evaluation persists its inputs, versions and
# dependencies so that only the affected cases are invalidated later.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.core.results import ConflictResult
from acme_city.permits.schemas import (
    DEFAULT_DATE_BASIS,
    ApplicationPartyInput,
    ApplicationPartyView,
    ApplicationRevisionView,
    ApplicationSiteView,
    Blocker,
    EvaluationView,
    ReviseApplicationCommand,
    SubmitApplicationCommand,
)
from acme_city.persistence.models import finance, permit, registry
from acme_city.rules.evaluator import evaluate as evaluate_inputs
from acme_city.rules.evaluator import overall_status, worst_status
from acme_city.rules.service import RuleCatalogService

#: The domain every permit action is authorized in.
PERMIT_DOMAIN = "permits"

#: The role a party plays when it is the applicant of record.
APPLICANT_ROLE = "applicant"

#: The role a party plays when it carries out the work.
CONTRACTOR_ROLE = "contractor"

#: The role a party plays when it pays the fee.
PAYER_ROLE = "payer"


class PermitService:
    """Applications, revisions and evaluations."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)
        self._catalog = RuleCatalogService(session, now=self._now)

    # ----------------------------------------------------------------- loading

    def load_application(self, application_id: str) -> permit.Application:
        """Return the stored application or refuse."""
        application = self._session.execute(
            select(permit.Application).where(permit.Application.id == application_id)
        ).scalar_one_or_none()
        if application is None:
            raise NotFoundError("that application does not exist")
        return application

    def current_revision(self, application_id: str) -> permit.ApplicationRevision:
        """Return the latest submitted revision of an application."""
        revision = self._session.execute(
            select(permit.ApplicationRevision)
            .where(permit.ApplicationRevision.application_id == application_id)
            .order_by(permit.ApplicationRevision.revision_number.desc())
            .limit(1)
        ).scalar_one_or_none()
        if revision is None:
            raise NotFoundError("that application has no submitted revision")
        return revision

    def current_evaluation(self, application_id: str) -> permit.Evaluation | None:
        """Return the current evaluation of an application, if there is one."""
        return self._session.execute(
            select(permit.Evaluation)
            .where(
                permit.Evaluation.application_id == application_id,
                permit.Evaluation.status == "current",
            )
            .order_by(permit.Evaluation.version.desc())
            .limit(1)
        ).scalar_one_or_none()

    def current_decision(self, application_id: str) -> permit.Decision | None:
        """Return the current decision of an application, if there is one."""
        return self._session.execute(
            select(permit.Decision)
            .where(
                permit.Decision.application_id == application_id,
                permit.Decision.status == "current",
            )
            .order_by(permit.Decision.version.desc())
            .limit(1)
        ).scalar_one_or_none()

    def permit_type(self, application: permit.Application) -> permit.PermitType:
        """Return the permit type configuration of an application."""
        row = self._session.execute(
            select(permit.PermitType).where(permit.PermitType.id == application.permit_type_id)
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("that permit type is not configured")
        return row

    def parties(self, application_id: str) -> list[permit.ApplicationParty]:
        """Return the parties of an application."""
        return list(
            self._session.execute(
                select(permit.ApplicationParty)
                .where(permit.ApplicationParty.application_id == application_id)
                .order_by(permit.ApplicationParty.id)
            )
            .scalars()
            .all()
        )

    def site(self, application_id: str) -> permit.ApplicationSite | None:
        """Return the primary site of an application."""
        return self._session.execute(
            select(permit.ApplicationSite)
            .where(
                permit.ApplicationSite.application_id == application_id,
                permit.ApplicationSite.is_primary.is_(True),
            )
            .limit(1)
        ).scalar_one_or_none()

    # ---------------------------------------------------------------- commands

    def submit(
        self, command: SubmitApplicationCommand, actor: ActorContext
    ) -> ApplicationRevisionView:
        """Submit an application and record its first immutable revision."""
        self._permissions.authorize(
            actor,
            "application.submit",
            ResourceContext(
                domain_id=PERMIT_DOMAIN,
                record_ids=tuple(
                    part
                    for part in (command.applicant_party_id, command.source_application_number)
                    if part
                ),
            ),
        )
        permit_type = self._session.execute(
            select(permit.PermitType).where(permit.PermitType.key == command.permit_type_key)
        ).scalar_one_or_none()
        if permit_type is None:
            raise ValidationError("that permit type is not configured")

        facts = dict(command.facts)
        number = command.source_application_number or self._next_application_number()
        application = permit.Application(
            id=new_id("app"),
            source_application_number=number,
            permit_type_id=permit_type.id,
            initial_submitted_at=self._now,
            revision_submitted_at=self._now,
            status="submitted",
            revision=1,
            description=str(facts.get("project_description") or "") or None,
            submitted_facts=facts,
            applicant_party_id=command.applicant_party_id,
            correlation_id=new_id("corr"),
        )
        self._session.add(application)
        self._session.flush()

        revision = permit.ApplicationRevision(
            id=new_id("rev"),
            application_id=application.id,
            revision_number=1,
            submitted_at=self._now,
            submitted_by_actor_id=actor.actor_id,
            snapshot=facts,
            date_basis=DEFAULT_DATE_BASIS,
        )
        self._session.add(revision)
        self._session.flush()

        self._store_parties(application.id, command.parties, command.applicant_party_id)
        self._store_site(application.id, facts, command.site)
        self._session.flush()

        self._audit.append(
            action="application.submit",
            actor=actor,
            target_type="application",
            target_id=application.id,
            after_version=application.version,
            reason=command.reason or None,
            references=[number],
            correlation_id=application.correlation_id,
        )
        self._session.flush()
        return self.application_view(application)

    def revise(
        self, command: ReviseApplicationCommand, actor: ActorContext
    ) -> ApplicationRevisionView | ConflictResult:
        """Create a new submitted revision of an application.

        The initial submission date never changes, and the previous revision
        keeps the facts it was submitted with.
        """
        application = self.load_application(command.application_id)
        self._permissions.authorize(
            actor,
            "application.revision.submit",
            ResourceContext(
                domain_id=PERMIT_DOMAIN,
                record_ids=(
                    application.source_application_number,
                    application.applicant_party_id or "",
                ),
            ),
        )
        if (
            command.expected_version is not None
            and application.version != command.expected_version
        ):
            return ConflictResult(
                code="version_conflict",
                expected_version=command.expected_version,
                current_version=application.version,
                differences=(
                    {
                        "field": "application_version",
                        "expected": command.expected_version,
                        "current": application.version,
                    },
                ),
            )

        previous = self.current_revision(application.id)
        snapshot = dict(previous.snapshot or {})
        snapshot.update(command.facts)

        revision = permit.ApplicationRevision(
            id=new_id("rev"),
            application_id=application.id,
            revision_number=previous.revision_number + 1,
            submitted_at=self._now,
            submitted_by_actor_id=actor.actor_id,
            snapshot=snapshot,
            date_basis=DEFAULT_DATE_BASIS,
        )
        self._session.add(revision)

        application.revision = revision.revision_number
        application.revision_submitted_at = self._now
        application.submitted_facts = snapshot
        application.status = "submitted"
        application.version += 1
        if command.parties is not None:
            self._replace_parties(application.id, command.parties)
        if command.site is not None:
            self._replace_site(application.id, snapshot, command.site)
        self._session.flush()

        self._invalidate_dependent_work(
            application,
            reason="a new revision was submitted",
        )
        self._audit.append(
            action="application.revision.submit",
            actor=actor,
            target_type="application",
            target_id=application.id,
            before_version=application.version - 1,
            after_version=application.version,
            reason=command.reason or None,
            references=[revision.id],
            correlation_id=application.correlation_id,
        )
        self._session.flush()
        return self.application_view(application)

    def evaluate(self, application_id: str, actor: ActorContext) -> EvaluationView:
        """Evaluate the current revision against the selected rule versions."""
        application = self.load_application(application_id)
        self._permissions.authorize(
            actor,
            "application.evaluate",
            ResourceContext(
                domain_id=PERMIT_DOMAIN,
                record_ids=(
                    application.source_application_number,
                    application.applicant_party_id or "",
                ),
            ),
        )
        revision = self.current_revision(application.id)
        permit_type = self.permit_type(application)
        basis_at = application.initial_submitted_at or revision.submitted_at
        rule_set = self._catalog.resolve(
            "executable", permit_type.key, basis_at, basis_label=DEFAULT_DATE_BASIS
        )
        inputs = build_inputs(revision.snapshot or {})
        results = evaluate_inputs(inputs, rule_set)
        blockers = self.evaluation_blockers(application, inputs, permit_type)
        dependencies, dependency_versions = self.dependency_state(
            application, revision, rule_set
        )

        previous = self.current_evaluation(application.id)
        if previous is not None:
            previous.status = "superseded"
            previous.stale = True

        evaluation = permit.Evaluation(
            id=new_id("eval"),
            application_id=application.id,
            revision_id=revision.id,
            source_versions={
                "inputs": inputs,
                "dependencies": dependencies,
                "dependency_versions": dependency_versions,
                "blockers": [blocker.model_dump(mode="json") for blocker in blockers],
                "application_revision": {
                    "revision_id": revision.id,
                    "revision_number": revision.revision_number,
                    "submitted_at": revision.submitted_at.isoformat(),
                },
            },
            registry_versions=self.registry_versions(application),
            rule_versions=rule_set.version_labels(),
            date_basis=f"{DEFAULT_DATE_BASIS}@{basis_at.isoformat()}",
            results=[result.model_dump(mode="json") for result in results],
            performed_at=self._now,
            performed_by_actor_id=actor.actor_id,
            status="current",
            stale=False,
            correlation_id=application.correlation_id,
        )
        self._session.add(evaluation)
        if application.status != "issued":
            # An issued case keeps its state; the evaluation is recorded
            # without reopening the workflow.
            application.status = "ready_for_review"
        application.version += 1
        self._session.flush()

        self._mark_stale_decision_if_changed(application, dependency_versions)
        self._audit.append(
            action="application.evaluate",
            actor=actor,
            target_type="evaluation",
            target_id=evaluation.id,
            after_version=evaluation.version,
            references=[revision.id],
            correlation_id=application.correlation_id,
            metadata={"outcome": overall_status(results)},
        )
        self._session.flush()
        return self.evaluation_view(evaluation)

    # ------------------------------------------------------- delegated actions

    def decide(self, command, actor: ActorContext):
        """Record an actual reviewer decision."""
        from acme_city.permits.decisions import PermitDecisionService

        return PermitDecisionService(self._session, now=self._now).decide(command, actor)

    def reconfirm(self, command, actor: ActorContext):
        """Record a reviewer reconfirmation of a stale decision."""
        from acme_city.permits.decisions import PermitDecisionService

        return PermitDecisionService(self._session, now=self._now).reconfirm(command, actor)

    def issue(self, command, actor: ActorContext):
        """Issue a simulated permit from a current approved decision."""
        from acme_city.permits.issuance import PermitIssuanceService

        return PermitIssuanceService(self._session, now=self._now).issue(command, actor)

    # ------------------------------------------------------------------ views

    def application_view(self, application: permit.Application) -> ApplicationRevisionView:
        """Return the view of an application and its latest revision."""
        revision = self.current_revision(application.id)
        permit_type = self.permit_type(application)
        site = self.site(application.id)
        return ApplicationRevisionView(
            application_id=application.id,
            source_application_number=application.source_application_number,
            permit_type_key=permit_type.key,
            revision_id=revision.id,
            revision_number=revision.revision_number,
            submitted_at=revision.submitted_at,
            submitted_by_actor_id=revision.submitted_by_actor_id,
            initial_submitted_at=application.initial_submitted_at,
            revision_submitted_at=application.revision_submitted_at,
            date_basis=revision.date_basis or DEFAULT_DATE_BASIS,
            status=application.status,
            application_version=application.version,
            snapshot=dict(revision.snapshot or {}),
            parties=[
                ApplicationPartyView(
                    party_id=party.party_id,
                    party_role=party.party_role,
                    is_primary=party.is_primary,
                    authority_evidence_ref=party.authority_evidence_ref,
                )
                for party in self.parties(application.id)
            ],
            site=ApplicationSiteView(
                parcel_id=None if site is None else site.parcel_id,
                address_id=None if site is None else site.address_id,
                resolution_status="unresolved" if site is None else site.resolution_status,
                submitted_address_text=None if site is None else site.submitted_address_text,
            ),
        )

    def evaluation_view(self, evaluation: permit.Evaluation) -> EvaluationView:
        """Return the view of a stored evaluation."""
        source_versions = dict(evaluation.source_versions or {})
        results = [dict(item) for item in (evaluation.results or [])]
        return EvaluationView(
            evaluation_id=evaluation.id,
            application_id=evaluation.application_id,
            revision_id=evaluation.revision_id,
            version=evaluation.version,
            performed_at=evaluation.performed_at,
            performed_by_actor_id=evaluation.performed_by_actor_id,
            date_basis=evaluation.date_basis or DEFAULT_DATE_BASIS,
            rule_versions=dict(evaluation.rule_versions or {}),
            citations=sorted({str(item.get("citation")) for item in results if item.get("citation")}),
            inputs=dict(source_versions.get("inputs") or {}),
            results=results,
            outcome=worst_status(str(item.get("status", "review")) for item in results),
            blockers=[Blocker(**blocker) for blocker in (source_versions.get("blockers") or [])],
            dependencies=list(source_versions.get("dependencies") or []),
            dependency_versions=dict(source_versions.get("dependency_versions") or {}),
            status=evaluation.status,
            stale=evaluation.stale,
        )

    # ------------------------------------------------------------- internals

    def _next_application_number(self) -> str:
        """Return the next fictional application number."""
        count = self._session.execute(
            select(func.count()).select_from(permit.Application)
        ).scalar_one()
        return f"SYN-APP-{int(count) + 1:03d}"

    def _store_parties(
        self,
        application_id: str,
        parties: list[ApplicationPartyInput],
        applicant_party_id: str | None,
    ) -> None:
        """Record the parties of an application."""
        entries = list(parties)
        if not entries and applicant_party_id:
            entries = [
                ApplicationPartyInput(
                    party_id=applicant_party_id, party_role=APPLICANT_ROLE, is_primary=True
                )
            ]
        for entry in entries:
            self._session.add(
                permit.ApplicationParty(
                    id=new_id("appparty"),
                    application_id=application_id,
                    party_id=entry.party_id,
                    party_role=entry.party_role,
                    is_primary=entry.is_primary,
                    authority_evidence_ref=entry.authority_evidence_ref,
                )
            )

    def _replace_parties(
        self, application_id: str, parties: list[ApplicationPartyInput]
    ) -> None:
        """Replace the parties of an application."""
        for existing in self.parties(application_id):
            self._session.delete(existing)
        self._session.flush()
        self._store_parties(application_id, parties, None)

    def _store_site(
        self,
        application_id: str,
        facts: dict[str, Any],
        site,
    ) -> None:
        """Record the site of an application."""
        parcel_number = None if site is None else site.parcel_number
        address_text = None if site is None else site.address_text
        if site is None:
            parcel_number = facts.get("submitted_parcel")
            address_text = facts.get("submitted_site_text")
        parcel_id = None if site is None else site.parcel_id
        address_id = None if site is None else site.address_id
        if parcel_id is None and parcel_number:
            parcel = self._session.execute(
                select(registry.Parcel).where(
                    registry.Parcel.source_parcel_number == str(parcel_number)
                )
            ).scalar_one_or_none()
            parcel_id = None if parcel is None else parcel.parcel_id
        if address_id is None and address_text:
            address = self._resolve_address(str(address_text))
            address_id = None if address is None else address.address_id
        resolution = "resolved" if parcel_id and address_id else "unresolved"
        self._session.add(
            permit.ApplicationSite(
                id=new_id("site"),
                application_id=application_id,
                parcel_id=parcel_id,
                address_id=address_id,
                is_primary=True,
                resolution_status=resolution,
                submitted_address_text=address_text,
            )
        )

    def _replace_site(
        self, application_id: str, facts: dict[str, Any], site
    ) -> None:
        """Replace the site of an application."""
        existing = self.site(application_id)
        if existing is not None:
            self._session.delete(existing)
        self._session.flush()
        self._store_site(application_id, facts, site)

    def _resolve_address(self, text: str) -> registry.Address | None:
        """Return the official address a submitted address text refers to.

        The submitted text is written by an applicant, so it may name the
        unit as a suite and may carry the municipality.  The official record
        is matched on the street number, the street name and the unit, and
        nothing is invented when the text does not resolve.
        """
        number, street, unit = parse_address_text(text)
        if not number or not street:
            return None
        rows = self._session.execute(select(registry.Address)).scalars().all()
        for row in rows:
            if (row.street_number or "").strip() != number:
                continue
            if (row.street_name or "").strip().lower() != street.strip().lower():
                continue
            if unit:
                if (row.unit_number or "").strip() != unit:
                    continue
            elif (row.unit_number or "").strip():
                continue
            return row
        return None

    def evaluation_blockers(
        self,
        application: permit.Application,
        inputs: dict[str, Any],
        permit_type: permit.PermitType,
    ) -> list[Blocker]:
        """Return the conditions that block a dependent action.

        A missing required field, an unresolved site and an invalid required
        credential are all reported.  A rule outcome is reported by the
        evaluation results, not here.
        """
        blockers: list[Blocker] = []
        for field in permit_type.required_fields or []:
            value = inputs.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                blockers.append(
                    Blocker(
                        code="missing_required_field",
                        detail=f"the required input {field!r} was not supplied",
                        subject_type="permit_type",
                        subject_id=permit_type.permit_type_id,
                    )
                )
        blockers.extend(self.site_blockers(application))
        blockers.extend(self.credential_blockers(application, inputs, self._now))
        return blockers

    def site_blockers(self, application: permit.Application) -> list[Blocker]:
        """Return the site conditions that block a dependent action."""
        site = self.site(application.id)
        if site is None:
            return [
                Blocker(
                    code="site_missing",
                    detail="the application has no recorded site",
                    subject_type="application",
                    subject_id=application.id,
                )
            ]
        if site.resolution_status != "resolved" or not site.parcel_id or not site.address_id:
            return [
                Blocker(
                    code="site_unresolved",
                    detail=(
                        "the site does not resolve against the official parcel and "
                        "address records"
                    ),
                    subject_type="application_site",
                    subject_id=site.id,
                )
            ]
        return []

    def credential_blockers(
        self,
        application: permit.Application,
        inputs: dict[str, Any],
        at: datetime,
    ) -> list[Blocker]:
        """Return the credential conditions that block a dependent action.

        The contractor registration is checked against the number the
        applicant submitted, and a business licence is required only when the
        applicant is a business.
        """
        blockers: list[Blocker] = []
        parties = self.parties(application.id)
        license_number = inputs.get("contractor_license")
        if license_number:
            rows = self._session.execute(
                select(registry.Credential).where(
                    registry.Credential.number == str(license_number),
                    registry.Credential.credential_type == "contractor_registration",
                )
            ).scalars().all()
            if not rows:
                blockers.append(
                    Blocker(
                        code="credential_missing",
                        detail=(
                            f"no contractor registration is recorded for {license_number!r}"
                        ),
                        subject_type="application",
                        subject_id=application.id,
                    )
                )
            else:
                credential = rows[0]
                blockers.extend(self._credential_validity(credential, at))
                contractors = [p for p in parties if p.party_role == CONTRACTOR_ROLE]
                if contractors and credential.holder_party_id not in {
                    party.party_id for party in contractors
                }:
                    blockers.append(
                        Blocker(
                            code="credential_holder_mismatch",
                            detail=(
                                f"the contractor registration {license_number!r} is held by "
                                "another party"
                            ),
                            subject_type="credential",
                            subject_id=credential.credential_id,
                        )
                    )
        if str(inputs.get("applicant_role") or "").lower() == "business":
            applicants = [p for p in parties if p.party_role == APPLICANT_ROLE]
            for applicant in applicants:
                rows = self._session.execute(
                    select(registry.Credential).where(
                        registry.Credential.holder_party_id == applicant.party_id,
                        registry.Credential.credential_type == "business_license",
                    )
                ).scalars().all()
                if not rows:
                    blockers.append(
                        Blocker(
                            code="credential_missing",
                            detail="the applicant has no business licence on record",
                            subject_type="party",
                            subject_id=applicant.party_id,
                        )
                    )
                else:
                    blockers.extend(self._credential_validity(rows[0], at))
        return blockers

    def _credential_validity(
        self, credential: registry.Credential, at: datetime
    ) -> list[Blocker]:
        """Return the validity blockers of one credential."""
        if credential.valid_to is not None and credential.valid_to < at:
            return [
                Blocker(
                    code="credential_expired",
                    detail=(
                        f"the {credential.credential_type} {credential.number!r} expired on "
                        f"{credential.valid_to.date().isoformat()}"
                    ),
                    subject_type="credential",
                    subject_id=credential.credential_id,
                )
            ]
        if credential.status != "active":
            return [
                Blocker(
                    code="credential_inactive",
                    detail=(
                        f"the {credential.credential_type} {credential.number!r} is "
                        f"{credential.status}"
                    ),
                    subject_type="credential",
                    subject_id=credential.credential_id,
                )
            ]
        if credential.valid_from is not None and credential.valid_from > at:
            return [
                Blocker(
                    code="credential_not_yet_valid",
                    detail=(
                        f"the {credential.credential_type} {credential.number!r} is not valid "
                        f"until {credential.valid_from.date().isoformat()}"
                    ),
                    subject_type="credential",
                    subject_id=credential.credential_id,
                )
            ]
        return []

    def identity_link_blockers(self, application: permit.Application) -> list[Blocker]:
        """Return the identity links that a dependent action requires.

        The applicant, the contractor and the payer need an approved canonical
        link before a decision may be recorded.  A party that is only
        referenced, such as the property owner of the site, does not.
        """
        parties = self.parties(application.id)
        required = [
            party
            for party in parties
            if party.party_role in {APPLICANT_ROLE, CONTRACTOR_ROLE, PAYER_ROLE}
        ]
        blockers: list[Blocker] = []
        for party in required:
            approved = self._session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.entity_id == party.party_id,
                    registry.Crosswalk.link_status == "approved",
                )
            ).scalars().all()
            if not approved:
                blockers.append(
                    Blocker(
                        code="identity_link_unapproved",
                        detail=(
                            f"the canonical link for {party.party_id!r} has not been approved"
                        ),
                        subject_type="party",
                        subject_id=party.party_id,
                    )
                )
        return blockers

    def finance_link_blockers(self, application: permit.Application) -> list[Blocker]:
        """Return the payer link conditions that block a dependent action.

        A payer is resolved through an approved finance account link.  The
        account identifier in the authority evidence names the source account
        of the ERP/Finance system.
        """
        blockers: list[Blocker] = []
        for party in self.parties(application.id):
            if party.party_role != PAYER_ROLE:
                continue
            reference = party.authority_evidence_ref or ""
            if not reference.startswith("erp_finance:"):
                continue
            source_account_id = reference.split(":", 1)[1]
            account = self._session.execute(
                select(registry.FinanceAccount).where(
                    registry.FinanceAccount.source_account_id == source_account_id
                )
            ).scalar_one_or_none()
            if account is None:
                blockers.append(
                    Blocker(
                        code="finance_account_unknown",
                        detail=f"no finance account {source_account_id!r} is on record",
                        subject_type="party",
                        subject_id=party.party_id,
                    )
                )
                continue
            if not self.account_is_linked(account, party.party_id):
                blockers.append(
                    Blocker(
                        code="finance_account_link_unapproved",
                        detail=(
                            f"the finance account {source_account_id!r} is not approved for "
                            f"{party.party_id!r}"
                        ),
                        subject_type="finance_account",
                        subject_id=account.account_id,
                    )
                )
        return blockers

    def account_is_linked(self, account: registry.FinanceAccount, party_id: str) -> bool:
        """Return whether a finance account has an approved link to a party.

        Both an approved link record and an approved account row are
        accepted, so the registry and the finance service may record the
        decision in the way that fits their own boundary.
        """
        if account.party_id == party_id and account.link_status == "approved":
            return True
        link = self._session.execute(
            select(finance.FinanceAccountLink).where(
                finance.FinanceAccountLink.account_id == account.account_id,
                finance.FinanceAccountLink.party_id == party_id,
                finance.FinanceAccountLink.link_status == "approved",
            )
        ).scalar_one_or_none()
        return link is not None

    def dependency_state(
        self,
        application: permit.Application,
        revision: permit.ApplicationRevision,
        rule_set,
    ) -> tuple[list[str], dict[str, str]]:
        """Return the dependencies an evaluation consumed and their versions."""
        dependencies: dict[str, str] = {}
        for rule in rule_set.rules:
            dependencies[f"rule:{rule.rule_id}"] = rule.version_label
        inputs = build_inputs(revision.snapshot or {})
        for credential in self._credential_rows(application, inputs):
            dependencies[f"credential:{credential.credential_id}"] = (
                f"{credential.status}@{credential.valid_to.isoformat() if credential.valid_to else 'open'}"
            )
        for party in self.parties(application.id):
            row = self._session.execute(
                select(registry.Party).where(registry.Party.id == party.party_id)
            ).scalar_one_or_none()
            dependencies[f"party:{party.party_id}"] = (
                str(row.version) if row is not None else "unknown"
            )
            account = self._payer_account(party)
            if account is not None:
                dependencies[f"finance_account:{account.account_id}"] = account.link_status
        site = self.site(application.id)
        if site is not None and site.parcel_id:
            dependencies[f"site:{site.parcel_id}"] = site.resolution_status
        dependencies[f"application_revision:{revision.id}"] = str(revision.revision_number)
        return sorted(dependencies), dependencies

    def _credential_rows(
        self, application: permit.Application, inputs: dict[str, Any]
    ) -> list[registry.Credential]:
        """Return the credential records an evaluation depends on."""
        rows: list[registry.Credential] = []
        license_number = inputs.get("contractor_license")
        if license_number:
            rows.extend(
                self._session.execute(
                    select(registry.Credential).where(
                        registry.Credential.number == str(license_number)
                    )
                )
                .scalars()
                .all()
            )
        for party in self.parties(application.id):
            if party.party_role != APPLICANT_ROLE:
                continue
            rows.extend(
                self._session.execute(
                    select(registry.Credential).where(
                        registry.Credential.holder_party_id == party.party_id
                    )
                )
                .scalars()
                .all()
            )
        unique: dict[str, registry.Credential] = {}
        for row in rows:
            unique.setdefault(row.credential_id, row)
        return list(unique.values())

    def registry_versions(self, application: permit.Application) -> dict[str, Any]:
        """Return the canonical link versions an evaluation relied on."""
        links: dict[str, Any] = {}
        accounts: dict[str, Any] = {}
        for party in self.parties(application.id):
            rows = self._session.execute(
                select(registry.Crosswalk).where(
                    registry.Crosswalk.entity_id == party.party_id,
                    registry.Crosswalk.link_status == "approved",
                )
            ).scalars().all()
            if rows:
                links[party.party_id] = max(row.version for row in rows)
            account = self._payer_account(party)
            if account is not None:
                accounts[account.account_id] = {
                    "link_status": account.link_status,
                    "party_id": account.party_id,
                }
        return {"crosswalks": links, "finance_accounts": accounts}

    def _payer_account(
        self, party: permit.ApplicationParty
    ) -> registry.FinanceAccount | None:
        """Return the finance account of a payer party."""
        if party.party_role != PAYER_ROLE:
            return None
        reference = party.authority_evidence_ref or ""
        if not reference.startswith("erp_finance:"):
            return None
        source_account_id = reference.split(":", 1)[1]
        return self._session.execute(
            select(registry.FinanceAccount).where(
                registry.FinanceAccount.source_account_id == source_account_id
            )
        ).scalar_one_or_none()

    def _mark_stale_decision_if_changed(
        self, application: permit.Application, dependency_versions: dict[str, str]
    ) -> None:
        """Mark the current decision stale when a dependency changed.

        Revalidation alone never restores an approval: the decision stays
        stale until an authorized reviewer reconfirms it.
        """
        decision = self.current_decision(application.id)
        if decision is None:
            return
        recorded = dict((decision.input_versions or {}).get("dependency_versions") or {})
        if recorded == dependency_versions:
            return
        decision.stale = True
        self._session.flush()

    def _invalidate_dependent_work(
        self,
        application: permit.Application,
        *,
        reason: str,
    ) -> None:
        """Mark the evaluation and the decision of an application stale."""
        evaluation = self.current_evaluation(application.id)
        if evaluation is not None:
            evaluation.stale = True
            evaluation.status = "superseded"
        decision = self.current_decision(application.id)
        if decision is not None:
            decision.stale = True
        self._session.flush()


#: The words an applicant may use for a unit.
UNIT_KEYWORDS: tuple[str, ...] = ("suite", "unit", "apt", "apartment", "floor", "fl")


def parse_address_text(text: str) -> tuple[str | None, str | None, str | None]:
    """Return the street number, the street name and the unit of an address.

    The applicant writes the address as they know it, so a suite is a unit
    and the municipality may be carried along.  Nothing is guessed: a part
    that is neither a street nor a unit is ignored.
    """
    number: str | None = None
    street: str | None = None
    unit: str | None = None
    for part in (piece.strip() for piece in str(text).split(",")):
        if not part:
            continue
        head, unit_part = _split_unit(part)
        if unit is None and unit_part:
            digits = "".join(character for character in unit_part if character.isdigit())
            unit = digits or None
        if number is None and head and head[0].isdigit():
            tokens = head.split()
            number = tokens[0]
            street = " ".join(tokens[1:]) or None
    return number, street, unit


def _split_unit(part: str) -> tuple[str, str | None]:
    """Split a unit expression off one part of an address."""
    lowered = part.lower()
    if "#" in part:
        index = part.index("#")
        return part[:index].strip(), part[index:].strip()
    for keyword in UNIT_KEYWORDS:
        for separator in (f" {keyword} ", f" {keyword}"):
            index = lowered.find(separator)
            if index > 0:
                return part[:index].strip(), part[index:].strip()
    return part, None


def build_inputs(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the evaluated inputs of a submitted revision.

    The submitted facts are the inputs.  The parcel reference is presented
    under the name the catalogue uses, and the declared valuation is kept in
    cents beside its decimal form.
    """
    inputs = dict(snapshot)
    if "parcel_number" not in inputs:
        parcel = inputs.get("submitted_parcel")
        if parcel:
            inputs["parcel_number"] = parcel
    if "valuation_cents" not in inputs and inputs.get("valuation") is not None:
        from acme_city.finance.calculator import to_cents

        inputs["valuation_cents"] = to_cents(inputs["valuation"])
    return inputs


def rule_result_statuses(evaluation: permit.Evaluation) -> list[str]:
    """Return the statuses of the rule results of an evaluation."""
    return [str(item.get("status", "review")) for item in (evaluation.results or [])]


__all__ = [
    "APPLICANT_ROLE",
    "CONTRACTOR_ROLE",
    "PAYER_ROLE",
    "PERMIT_DOMAIN",
    "UNIT_KEYWORDS",
    "PermitService",
    "build_inputs",
    "parse_address_text",
    "rule_result_statuses",
]

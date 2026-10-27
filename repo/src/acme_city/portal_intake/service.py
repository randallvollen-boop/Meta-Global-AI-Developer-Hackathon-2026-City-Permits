"""Simulated outside intake: portal records become Permitting applications.

The flow never writes tables directly:

1. the raw record is staged through the registered ``intake_portal`` /
   ``submitted_applications`` contract (:class:`IngestionService`);
2. a Permitting application, its first immutable revision and its site are
   created through :class:`PermitService`;
3. each typed document is stored through :class:`DocumentService`;
4. nothing else happens: the case waits as "Awaiting intake agent" until a
   person wakes the intake agent and runs it.

A repeated portal reference is idempotent: the already-created application
is reported as a duplicate and nothing is created twice.
"""
# REQUIRES: ING-01, ING-02, PER-01
# Raw staging precedes any application, duplicates are idempotent on the
# portal reference, and every business record is written by its own service.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.core.clock import utc_now
from acme_city.core.errors import ValidationError
from acme_city.documents.service import DocumentService, StoreDocumentCommand
from acme_city.ingestion.schemas import IngestCommand, SourceRecordCommand
from acme_city.ingestion.service import IngestionService
from acme_city.portal_intake.scenarios import build_scenario
from acme_city.portal_intake.schemas import IntakeRecordCommand, IntakeSubmitResult
from acme_city.permits.schemas import (
    ApplicationPartyInput,
    ApplicationSiteInput,
    SubmitApplicationCommand,
)
from acme_city.permits.service import PermitService
from acme_city.persistence.models import permit, source
from acme_city.triage.service import service_actor

#: The service identity that stages an incoming record.
INTAKE_AGENT_ID = "service_agent_intake"

#: The simulated outside source system and its only dataset.
SOURCE_SYSTEM_ID = "intake_portal"
DATASET_KEY = "submitted_applications"

#: Channels the outside application gathers through.
CHANNELS: tuple[str, ...] = ("portal", "counter_scan", "email", "mail", "fax")


class IntakeService:
    """Turns outside intake records into applications, then triages them."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Any = None,
        now: datetime | None = None,
        live_muse: bool = False,
        document_root: Any = None,
        muse_client: Any = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._now = now or utc_now()
        self._live_muse = live_muse
        self._document_root = document_root
        self._muse_client = muse_client
        self._audit = AuditService(session, now=self._now)

    # ------------------------------------------------------------------ public

    def submit_record(
        self, record: IntakeRecordCommand, actor: ActorContext
    ) -> IntakeSubmitResult:
        """Ingest one record and create its application.

        ``actor`` is who submitted the record (the portal custodian for an
        API post, the administrator for a governed simulation).  Staging is
        authorized against that actor; every later write runs as the seeded
        intake service identity.  The case waits as "Awaiting intake agent":
        the intake agent only runs when a person runs it.
        """
        duplicate = self._existing_application(record.portal_reference)
        if duplicate is not None:
            return IntakeSubmitResult(
                portal_reference=record.portal_reference,
                status="duplicate",
                application_id=duplicate.id,
                source_application_number=duplicate.source_application_number,
            )

        payload = self._payload(record)
        # The submitting actor authorized the intake (API session or the
        # administrator's governed simulate action).  Raw staging itself is
        # the intake service identity's governed act, as in every other
        # service step; no table is written directly.
        agent = service_actor(self._session, INTAKE_AGENT_ID)
        ingestion = IngestionService(self._session, now=self._now).ingest(
            IngestCommand(
                source_system_id=SOURCE_SYSTEM_ID,
                dataset_key=DATASET_KEY,
                records=[
                    SourceRecordCommand(
                        source_record_id=record.portal_reference,
                        source_record_version="1",
                        payload=payload,
                        source_updated_at=record.received_at,
                    )
                ],
                received_at=record.received_at,
            ),
            agent,
        )
        outcome = ingestion.records[0] if ingestion.records else None
        if outcome is None or outcome.status not in {"accepted", "unchanged"}:
            raise ValidationError(
                "the intake record was not accepted by its registered contract: "
                + "; ".join(
                    f"{error.field_path}: {error.message}"
                    for error in (outcome.field_errors if outcome else [])
                )
            )

        facts = self._facts(record)
        applicant_party = self._match_party(record.applicant.name)
        parties = []
        applicant_party_id = None
        if applicant_party is not None:
            applicant_party_id = applicant_party.id
            parties.append(
                ApplicationPartyInput(
                    party_id=applicant_party.id, party_role="applicant", is_primary=True
                )
            )
        view = PermitService(self._session, now=self._now).submit(
            SubmitApplicationCommand(
                permit_type_key=record.permit_type_key,
                facts=facts,
                applicant_party_id=applicant_party_id,
                parties=parties,
                site=ApplicationSiteInput(
                    parcel_number=record.parcel_text or None,
                    address_text=record.site_address or None,
                ),
                reason=f"submitted through the {record.channel} channel of the "
                "ACME ePermit Portal (simulated)",
            ),
            agent,
        )
        application_id = view.application_id

        # The permit-type requirements that are in force right now are
        # recorded on the case, so a later configuration change takes effect
        # for new intake only and never rewrites what this case was measured
        # against.
        application_row = self._session.get(permit.Application, application_id)
        if application_row is not None:
            permit_type = self._session.get(
                permit.PermitType, application_row.permit_type_id
            )
            if permit_type is not None:
                application_row.requirements_snapshot = {
                    "permit_type_key": permit_type.key,
                    "permit_type_label": permit_type.label,
                    "required_fields": list(permit_type.required_fields or []),
                    "required_documents": list(permit_type.required_documents or []),
                    "review_area": permit_type.review_area,
                    "process_category": permit_type.process_category,
                }
                self._session.flush()

        # Link the staged raw record to the application it created, so the
        # identity agent (and any later reader) can find its source.
        snapshot = self._session.execute(
            select(source.SourceSnapshot).where(
                source.SourceSnapshot.source_snapshot_id == outcome.source_snapshot_id
            )
        ).scalar_one_or_none()
        if snapshot is not None:
            snapshot.raw_payload = {
                **dict(snapshot.raw_payload or {}),
                "application_id": application_id,
            }
            self._session.flush()

        documents = DocumentService(self._session, root=self._document_root)
        for document in self._documents(record):
            text = document["text"]
            if not text.strip():
                continue
            documents.store_version(
                StoreDocumentCommand(
                    application_id=application_id,
                    document_type=document["document_type"],
                    filename=f"{record.portal_reference}-{document['document_type']}.txt",
                    media_type="text/plain",
                    content=text.encode("utf-8"),
                    quality=list(document.get("quality") or []),
                ),
                agent,
            )

        self._audit.append(
            action="intake.record.submit",
            actor=actor,
            target_type="application",
            target_id=application_id,
            reason=f"intake via {record.channel} as {record.portal_reference}",
            references=[record.portal_reference, outcome.source_snapshot_id or ""],
            metadata={"channel": record.channel, "awaiting": "intake_agent"},
        )
        return IntakeSubmitResult(
            portal_reference=record.portal_reference,
            status="created",
            application_id=application_id,
            source_application_number=view.source_application_number,
            snapshot_id=outcome.source_snapshot_id,
            triage_outcome="awaiting_intake_agent",
        )

    def simulate(
        self, scenario: str, *, count: int | None, actor: ActorContext
    ) -> list[IntakeSubmitResult]:
        """Submit one deterministic scenario through the same governed path."""
        base = build_scenario(scenario, count=count)
        records = list(base)
        if count is not None and scenario != "random" and count > len(records):
            # Extra records repeat the scenario with fresh portal references;
            # an exact repeat would (correctly) be an idempotent duplicate.
            index = len(records)
            while len(records) < count:
                for record in base:
                    if len(records) >= count:
                        break
                    records.append(
                        record.model_copy(
                            update={
                                "portal_reference": (
                                    f"{record.portal_reference}-R{index}"
                                )
                            }
                        )
                    )
                    index += 1
        elif count is not None and scenario != "random":
            records = records[:count]
        results = [self.submit_record(record, actor) for record in records]
        self._audit.append(
            action="intake.simulate",
            actor=actor,
            target_type="source_dataset",
            target_id=DATASET_KEY,
            reason=f"simulated scenario {scenario!r} ({len(results)} record(s))",
            references=[result.portal_reference for result in results],
            metadata={"scenario": scenario, "count": len(results)},
        )
        return results

    # ----------------------------------------------------------------- helpers

    def _existing_application(self, portal_reference: str) -> permit.Application | None:
        rows = self._session.execute(
            select(source.SourceSnapshot).where(
                source.SourceSnapshot.source_system_id == SOURCE_SYSTEM_ID,
                source.SourceSnapshot.source_dataset_id == DATASET_KEY,
                source.SourceSnapshot.source_record_id == portal_reference,
            )
        ).scalars().all()
        for row in rows:
            payload = dict(row.raw_payload or {})
            application_id = payload.get("application_id")
            if application_id:
                application = self._session.get(permit.Application, str(application_id))
                if application is not None:
                    return application
        return None

    def _match_party(self, name: str):
        """Return the canonical party whose name/alias matches, if any.

        This only attaches the party the applicant named to the application;
        the registry link itself is still proposed by triage and approved by
        the Data Steward.
        """
        from acme_city.ingestion.normalization import normalize_name
        from acme_city.persistence.models import registry

        if not name.strip():
            return None
        wanted = normalize_name(name).core_tokens
        if not wanted:
            return None
        parties = self._session.execute(select(registry.Party)).scalars().all()
        for party in parties:
            for candidate in (party.display_name, party.legal_name or ""):
                if candidate and normalize_name(candidate).core_tokens == wanted:
                    return party
        aliases = self._session.execute(select(registry.PartyAlias)).scalars().all()
        for alias in aliases:
            if normalize_name(alias.alias_value).core_tokens == wanted:
                return self._session.get(registry.Party, alias.party_id)
        return None

    def _payload(self, record: IntakeRecordCommand) -> dict[str, Any]:
        """Return the raw payload of one intake record.

        The payload carries the applicant's name, the parcel reference and the
        site address as well as the nested record, so that the deterministic
        matcher can compare them with the canonical records.
        """
        facts = dict(record.submitted_facts)
        payload = {
            "portal_reference": record.portal_reference,
            "channel": record.channel,
            "received_at": record.received_at.isoformat() if record.received_at else None,
            "applicant": record.applicant.model_dump(mode="json"),
            "display_name": record.applicant.name,
            "site_address": record.site_address,
            "submitted_site_text": record.site_address,
            "parcel_text": record.parcel_text,
            "parcel_number": record.parcel_text or facts.get("parcel_number", ""),
            "submitted_parcel": record.parcel_text or facts.get("parcel_number", ""),
            "permit_type_key": record.permit_type_key,
            "submitted_facts": dict(record.submitted_facts),
            "documents": [doc.model_dump(mode="json") for doc in record.documents],
            "document_text": record.document_text,
        }
        contractor = str(facts.get("contractor_license") or "")
        if contractor:
            payload["license_number"] = contractor
        return payload

    def _facts(self, record: IntakeRecordCommand) -> dict[str, Any]:
        facts = dict(record.submitted_facts)
        facts.setdefault("parcel_number", record.parcel_text)
        facts.setdefault("submitted_parcel", record.parcel_text)
        facts.setdefault("submitted_site_text", record.site_address)
        facts["applicant_name"] = record.applicant.name
        facts["applicant_email"] = record.applicant.email
        facts["portal_reference"] = record.portal_reference
        facts["channel"] = record.channel
        facts["permit_type_key"] = record.permit_type_key
        return facts

    def _documents(self, record: IntakeRecordCommand) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = [
            {
                "document_type": doc.document_type,
                "text": doc.text,
                "quality": list(doc.quality or []),
            }
            for doc in record.documents
        ]
        if not documents and record.document_text.strip():
            documents.append(
                {
                    "document_type": "supporting_document",
                    "text": record.document_text,
                    "quality": [],
                }
            )
        return documents


__all__ = ["CHANNELS", "DATASET_KEY", "SOURCE_SYSTEM_ID", "IntakeService"]

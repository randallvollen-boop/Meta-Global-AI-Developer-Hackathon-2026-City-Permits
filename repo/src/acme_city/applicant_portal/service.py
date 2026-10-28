"""The applicant portal service: drafts, uploads, completeness and submission.

Every write runs under the acting persona's own ``application.submit`` grant
and is audited.  The server decides whether an application is complete; the
browser script only mirrors that answer while the applicant types.
"""
# REQUIRES: PORTAL-01, PORTAL-02, PORTAL-03
# Submission is refused server-side unless the application is complete and
# accompanied by the certification; a draft keeps the applicant's work; uploads are limited by size
# and type and stored as real files.

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.applicant_portal import forms
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.documents.service import DOCUMENT_ROOT, DocumentService, StoreDocumentCommand
from acme_city.permits.guard import require_mutable
from acme_city.persistence.models import gis, permit

SUBMIT_ACTION = "application.submit"
PERMIT_DOMAIN = "permits"

#: Upload limits: the type of file and its size.
UPLOAD_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".txt": "text/plain",
}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

#: The plain status words the applicant sees.
STATUS_WORDS: dict[str, str] = {
    "draft": "Draft",
    "submitted": "Awaiting intake agent",
    "needs_information": "The City needs more information",
    "revisions_requested": "The City has asked for revisions",
    "ready_for_review": "Ready for review",
    "under_review": "Under review",
    "approved": "Approved",
    "denied": "Denied",
    "withdrawn": "Withdrawn",
    "issued": "Permit issued",
    "returned": "Returned to the applicant",
    "archived": "Archived by the City",
}

#: The statuses an applicant may answer in.
RESPONDABLE_STATUSES: frozenset[str] = frozenset(
    {"needs_information", "revisions_requested"}
)

_SAFE = re.compile(r"[^A-Za-z0-9]+")


def applicant_party(actor: ActorContext) -> str | None:
    """Return the canonical party of an applicant persona, if its scope names one."""
    return next((item for item in actor.record_scope if item.startswith("party_")), None)


#: Fact recording the document types the applicant declared "sent to the City
#: separately". It is the applicant's statement, not a received document.
DECLARED_SEPARATELY_FACT = "documents_sent_separately"


def declared_separately(application: permit.Application) -> list[str]:
    """Return the document types the applicant declared sent separately."""
    facts = application.submitted_facts or {}
    value = facts.get(DECLARED_SEPARATELY_FACT) or []
    return [str(item) for item in value] if isinstance(value, list) else []


class PortalService:
    """Reads the forms and writes drafts, uploads and submissions."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Any = None,
        now: datetime | None = None,
        document_root: Path | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._now = now or utc_now()
        self._root = Path(document_root) if document_root is not None else DOCUMENT_ROOT
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    # ----------------------------------------------------------------- reading

    def _type_row(self, type_key: str) -> permit.PermitType:
        row = self._session.execute(
            select(permit.PermitType).where(
                permit.PermitType.key == type_key, permit.PermitType.active.is_(True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("that permit type is not available in the portal")
        return row

    def form(self, type_key: str) -> forms.FormSpec:
        row = self._type_row(type_key)
        return forms.form_for(
            row.key,
            label=row.label,
            description=row.description or "",
            process_category=row.process_category,
            required_fields=list(row.required_fields or []),
            required_documents=list(row.required_documents or []),
            discretionary=row.discretionary,
        )

    def chooser(self) -> list[dict[str, Any]]:
        """Return the guided chooser: groups of type cards."""
        from acme_city.ui.view_models import icon_for_permit_type

        rows = {
            row.key: row
            for row in self._session.execute(
                select(permit.PermitType).where(permit.PermitType.active.is_(True))
            ).scalars().all()
        }
        used: set[str] = set()
        groups: list[dict[str, Any]] = []

        def card(row: permit.PermitType) -> dict[str, Any]:
            category = row.process_category or "simple"
            pill, pill_text = forms.PROCESS_PILLS.get(category, forms.PROCESS_PILLS["simple"])
            icon = icon_for_permit_type(self._session, row)
            return {
                "type_key": row.key,
                "label": row.label,
                "description": row.description or "",
                "pill": pill,
                "pill_text": pill_text,
                "category": category,
                "icon_url": icon["url"] if icon else "",
                "href": f"/apply/{row.key}",
            }

        for group_key, label, keys in forms.GROUPS:
            cards = [card(rows[key]) for key in keys if key in rows]
            used.update(keys)
            groups.append({"key": group_key, "label": label, "cards": cards})
        other = [card(row) for key, row in sorted(rows.items()) if key not in used]
        if other:
            groups.append({"key": "other", "label": "Other permits", "cards": other})
        return groups

    # ------------------------------------------------------------ completeness

    @staticmethod
    def _present(value: Any) -> bool:
        return value is not None and str(value).strip() != ""

    def completeness(
        self,
        spec: forms.FormSpec,
        values: dict[str, str],
        uploaded_types: set[str],
        *,
        certification_accepted: bool = False,
        sent_separately: set[str] | frozenset[str] | None = None,
    ) -> dict[str, Any]:
        """Return what is still needed, by plain label.

        A document the applicant declared "sent to the City separately" counts
        as provided here, so the form can be submitted without a file; it is
        never treated as received (see ``DECLARED_SEPARATELY_FACT``).

        ``missing`` lists the fields and documents still needed (labels only,
        unchanged). ``items`` carries the same entries with the anchor id of the
        control to jump to. ``blocking`` is ``items`` plus the certification when
        it is unchecked: everything that keeps Submit disabled.
        """
        items: list[dict[str, str]] = []
        declared = set(sent_separately or ())

        def need(label: str, anchor: str, key: str) -> None:
            items.append({"key": key, "label": label, "anchor": anchor})

        if not self._present(values.get("applicant_name")):
            need("Applicant name", "f-applicant_name", "applicant_name")
        if not self._present(values.get("applicant_email")):
            need("Applicant email", "f-applicant_email", "applicant_email")
        elif "@" not in values["applicant_email"]:
            need("Applicant email (enter a valid address)", "f-applicant_email", "applicant_email")
        if spec.needs_business and not self._present(values.get("business_name")):
            need("Business name", "f-business_name", "business_name")
        if not self._present(values.get("address_text")):
            need("Property address", "f-address_text", "address_text")
        for field in spec.fields:
            raw = values.get(field.key)
            anchor = f"f-{field.key}"
            if field.kind == "checkbox":
                if field.required and str(raw or "").lower() not in {"on", "true", "1", "yes"}:
                    need(field.label, anchor, field.key)
                continue
            if not self._present(raw):
                if field.required:
                    need(field.label, anchor, field.key)
                continue
            if field.kind == "number":
                try:
                    if float(str(raw).replace(",", "")) < 0:
                        raise ValueError
                except ValueError:
                    need(f"{field.label} (enter a number)", anchor, field.key)
        for doc_type, label in spec.documents:
            if doc_type not in uploaded_types and doc_type not in declared:
                need(label, f"file-{doc_type}", f"file__{doc_type}")
        missing = [item["label"] for item in items]
        blocking = list(items)
        if not certification_accepted:
            blocking.append(
                {
                    "key": "certification_accepted",
                    "label": "Check the certification",
                    "anchor": "f-certification_accepted",
                }
            )
        complete = not missing
        if not complete:
            banner = "Still needed: " + ", ".join(missing) + "."
        elif certification_accepted:
            banner = "Ready to submit. All required fields and documents are provided."
        else:
            banner = "All fields and documents are provided. Check the certification to submit."
        return {
            "complete": complete,
            "missing": missing,
            "items": items,
            "blocking": blocking,
            "certification_accepted": certification_accepted,
            "sent_separately": sorted(
                doc for doc, _label in spec.documents if doc in declared and doc not in uploaded_types
            ),
            "can_submit": complete and certification_accepted,
            "banner": banner,
        }

    # ----------------------------------------------------------------- locator

    def locate(self, text: str) -> dict[str, Any]:
        """Return the "Did you mean" answer of the locator for typed text."""
        from acme_city.gis.adapter import GisServiceError, get_locator

        text = text.strip()
        if not text:
            return {"found": False, "message": "", "alternatives": []}
        try:
            locator = get_locator(self._settings)
            candidates = locator.find_candidates(text, 5)
        except GisServiceError:
            return {
                "found": False,
                "message": "The address service is not available. You can still submit; the City will find the property.",
                "alternatives": [],
            }
        if not candidates:
            return {
                "found": False,
                "message": "We could not find that address in the city locator. Check the spelling, or submit it and the City will find the property.",
                "alternatives": [],
            }
        top = candidates[0]
        parcel = locator.parcel_at(top.x, top.y)
        alternatives = [
            {"address": item.address, "score": item.score} for item in candidates[1:4]
        ]
        strong = [item for item in candidates if item.score >= 90]
        return {
            "found": True,
            "address": top.address,
            "score": top.score,
            "status": top.status,
            "parcel_number": parcel.parcel_number if parcel else "",
            "exact": top.address.lower().startswith(text.lower().split(",")[0].strip()),
            "ambiguous": len(strong) != 1,
            "alternatives": alternatives,
            "message": (
                f"Did you mean {top.address}? Parcel {parcel.parcel_number}."
                if parcel
                else f"Did you mean {top.address}?"
            ),
        }

    # ------------------------------------------------------------------ drafts

    def draft(self, reference: str, actor: ActorContext) -> gis.ApplicationDraft | None:
        row = self._session.execute(
            select(gis.ApplicationDraft).where(gis.ApplicationDraft.reference == reference)
        ).scalar_one_or_none()
        if row is None or row.owner_actor_id != actor.actor_id:
            return None
        return row

    def draft_documents(self, draft: gis.ApplicationDraft | None) -> dict[str, gis.DraftDocument]:
        if draft is None:
            return {}
        rows = self._session.execute(
            select(gis.DraftDocument)
            .where(gis.DraftDocument.draft_id == draft.id)
            .order_by(gis.DraftDocument.created_at, gis.DraftDocument.id)
        ).scalars().all()
        return {row.document_type: row for row in rows}

    def my_drafts(self, actor: ActorContext) -> list[gis.ApplicationDraft]:
        return list(
            self._session.execute(
                select(gis.ApplicationDraft)
                .where(
                    gis.ApplicationDraft.owner_actor_id == actor.actor_id,
                    gis.ApplicationDraft.status == "open",
                )
                .order_by(gis.ApplicationDraft.created_at)
            ).scalars()
        )

    def _authorize(self, actor: ActorContext) -> None:
        party = applicant_party(actor)
        self._permissions.authorize(
            actor,
            SUBMIT_ACTION,
            ResourceContext(domain_id=PERMIT_DOMAIN, record_ids=(party,) if party else ()),
        )

    def save_draft(
        self,
        spec: forms.FormSpec,
        values: dict[str, str],
        certification_accepted: bool,
        actor: ActorContext,
        *,
        reference: str = "",
        sent_separately: set[str] | frozenset[str] | None = None,
    ) -> gis.ApplicationDraft:
        """Keep the applicant's work as a draft (a draft is not an application)."""
        self._authorize(actor)
        data = {
            "values": dict(values),
            "certification_accepted": bool(certification_accepted),
            "sent_separately": sorted(sent_separately or ()),
        }
        draft = self.draft(reference, actor) if reference else None
        if draft is not None and draft.status != "open":
            raise ValidationError("that draft was already submitted")
        if draft is None:
            draft = gis.ApplicationDraft(
                id=new_id("draft"),
                reference=f"DRAFT-{new_id('d').split('_')[-1][:10].upper()}",
                permit_type_key=spec.type_key,
                owner_actor_id=actor.actor_id,
                data=data,
                status="open",
                correlation_id=new_id("corr"),
                version=1,
                updated_at=self._now,
            )
            self._session.add(draft)
        else:
            draft.data = data
            draft.version += 1
            draft.updated_at = self._now
        self._session.flush()
        self._audit.append(
            action="portal.draft.save",
            actor=actor,
            target_type="application_draft",
            target_id=draft.id,
            after_version=draft.version,
            reason=f"saved a draft of a {spec.label} application",
        )
        return draft

    def store_upload(
        self,
        draft: gis.ApplicationDraft,
        document_type: str,
        filename: str,
        content: bytes,
        actor: ActorContext,
    ) -> gis.DraftDocument:
        """Store one uploaded file on a draft (the latest per document type wins)."""
        self._authorize(actor)
        extension = Path(filename or "").suffix.lower()
        media_type = UPLOAD_EXTENSIONS.get(extension)
        if media_type is None:
            raise ValidationError(
                "that file type is not accepted; add a PDF, PNG, JPG or plain text file"
            )
        if not content:
            raise ValidationError("the file is empty")
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValidationError("the file is larger than 5 MB")
        magic = {
            "application/pdf": content.startswith(b"%PDF"),
            "image/png": content.startswith(b"\x89PNG"),
            "image/jpeg": content.startswith(b"\xff\xd8"),
            "text/plain": True,
        }[media_type]
        if media_type == "text/plain":
            try:
                content.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValidationError("a text file must be UTF-8 text") from error
        if not magic:
            raise ValidationError("the file content does not match its file type")
        digest = hashlib.sha256(content).hexdigest()
        directory = self._root / "drafts" / draft.id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{document_type}-{digest[:16]}{extension}"
        target.write_bytes(content)
        for old in self._session.execute(
            select(gis.DraftDocument).where(
                gis.DraftDocument.draft_id == draft.id,
                gis.DraftDocument.document_type == document_type,
            )
        ).scalars():
            self._session.delete(old)
        safe = _SAFE.sub("-", Path(filename).stem).strip("-")[:40] or "file"
        row = gis.DraftDocument(
            id=new_id("ddoc"),
            draft_id=draft.id,
            document_type=document_type,
            filename=f"{safe}{extension}",
            media_type=media_type,
            file_ref=str(target),
            content_hash=digest,
            byte_length=len(content),
        )
        self._session.add(row)
        self._session.flush()
        self._audit.append(
            action="portal.draft.upload",
            actor=actor,
            target_type="application_draft",
            target_id=draft.id,
            reason=f"added {document_type} ({len(content)} bytes)",
            references=[row.id, digest],
        )
        return row

    # ------------------------------------------------------------------ submit

    def submit(
        self,
        spec: forms.FormSpec,
        values: dict[str, str],
        certification_accepted: bool,
        draft: gis.ApplicationDraft,
        actor: ActorContext,
        *,
        sent_separately: set[str] | frozenset[str] | None = None,
    ) -> permit.Application:
        """Submit a complete application with its certification accepted through the existing path."""
        from acme_city.portal_intake.schemas import IntakeRecordCommand
        from acme_city.portal_intake.service import IntakeService

        self._authorize(actor)
        documents = self.draft_documents(draft)
        state = self.completeness(
            spec,
            values,
            set(documents),
            certification_accepted=certification_accepted,
            sent_separately=sent_separately,
        )
        if not state["complete"]:
            raise ValidationError(state["banner"])
        if not certification_accepted:
            raise ValidationError("the certification must be accepted before you submit")
        if draft.status != "open":
            raise ValidationError("that application was already submitted")

        located = self.locate(values.get("address_text", ""))
        parcel_number = located.get("parcel_number", "") if located.get("found") else ""
        facts: dict[str, Any] = {}
        for field in spec.fields:
            raw = values.get(field.key, "")
            if field.kind == "number" and str(raw).strip():
                number = float(str(raw).replace(",", ""))
                facts[field.key] = int(number) if number.is_integer() else number
            elif field.kind == "checkbox":
                facts[field.key] = str(raw or "").lower() in {"on", "true", "1", "yes"}
            else:
                facts[field.key] = str(raw).strip()
        facts.update(spec.constant_facts)
        facts["submitted_site_text"] = values["address_text"].strip()
        if parcel_number:
            facts["parcel_number"] = parcel_number
            facts["submitted_parcel"] = parcel_number
        if "property_address" in (
            self._type_row(spec.type_key).required_fields or []
        ):
            facts["property_address"] = values["address_text"].strip()
        if values.get("business_name", "").strip():
            facts["business_name"] = values["business_name"].strip()
        facts["certification_accepted"] = True
        if state["sent_separately"]:
            # A declaration only: no document row, file or audit event says it arrived.
            facts[DECLARED_SEPARATELY_FACT] = list(state["sent_separately"])
        facts["applicant_phone"] = values.get("applicant_phone", "").strip()

        record = IntakeRecordCommand(
            channel="portal",
            received_at=self._now,
            portal_reference=f"PORTAL-{draft.reference}",
            applicant={
                "name": values["applicant_name"].strip(),
                "email": values["applicant_email"].strip(),
                "phone": values.get("applicant_phone", "").strip(),
            },
            site_address=values["address_text"].strip(),
            parcel_text=parcel_number,
            permit_type_key=spec.type_key,
            submitted_facts=facts,
            documents=[],
        )
        result = IntakeService(self._session, settings=self._settings).submit_record(record, actor)
        if result.status != "created" or not result.application_id:
            raise ValidationError("that application was already submitted")
        application = self._session.get(permit.Application, result.application_id)
        party = applicant_party(actor)
        if application is not None and party and application.applicant_party_id != party:
            # An applicant persona always owns what it submits.
            application.applicant_party_id = party
            self._session.flush()
        store = DocumentService(self._session, root=self._root)
        for doc_type, row in documents.items():
            if doc_type not in dict(spec.documents):
                continue
            store.store_version(
                StoreDocumentCommand(
                    application_id=result.application_id,
                    document_type=doc_type,
                    filename=f"{result.source_application_number}-{doc_type}{Path(row.filename).suffix}",
                    media_type=row.media_type,
                    content=Path(row.file_ref).read_bytes(),
                ),
                actor,
            )
        draft.status = "submitted"
        draft.application_id = result.application_id
        draft.version += 1
        draft.updated_at = self._now
        self._session.flush()
        self._audit.append(
            action="portal.application.submit",
            actor=actor,
            target_type="application",
            target_id=result.application_id,
            reason=f"submitted a {spec.label} application through the applicant portal",
            references=[draft.reference, result.source_application_number or ""],
        )
        assert application is not None
        return application

    # ------------------------------------------------------------------- track

    def track(self, reference: str, actor: ActorContext) -> dict[str, Any] | None:
        """Return the tracking view of an application the actor may see."""
        from acme_city.permits.comments import comments_for
        from acme_city.ui.view_models import _application_in_scope

        reference = reference.strip()
        if not reference:
            return None
        application = self._session.execute(
            select(permit.Application).where(
                permit.Application.source_application_number == reference
            )
        ).scalar_one_or_none()
        if application is None:
            draft = self._session.execute(
                select(gis.ApplicationDraft).where(gis.ApplicationDraft.reference == reference)
            ).scalar_one_or_none()
            if draft is not None and draft.application_id:
                application = self._session.get(permit.Application, draft.application_id)
        if application is None or not _application_in_scope(actor, application):
            return None
        permit_type = self._session.get(permit.PermitType, application.permit_type_id)
        # "Messages from the City" are the comments the City wrote for the
        # applicant.  An internal note is never one of them.
        messages = [
            {
                "message": row.body,
                "applicant_must": "",
                "severity": "review",
            }
            for row in comments_for(self._session, application.id, actor)
        ]
        decision = self._session.execute(
            select(permit.Decision)
            .where(permit.Decision.application_id == application.id)
            .order_by(permit.Decision.created_at.desc())
        ).scalars().first()
        spec = self.form(permit_type.key) if permit_type else None
        have = {
            doc.document_type
            for doc in DocumentService(self._session, root=self._root).list_versions(
                application.id
            )
        }
        declared = declared_separately(application)
        return {
            "application_id": application.id,
            "reference": application.source_application_number,
            "type_label": permit_type.label if permit_type else "",
            "status": application.status,
            "status_word": STATUS_WORDS.get(application.status, application.status),
            "messages": messages,
            "decision_reason": decision.reason if decision is not None and decision.reason else "",
            # The conditions of approval are the applicant's instructions, so
            # they are shown on the tracker next to the decision note.
            "decision_conditions": list(decision.conditions or [])
            if decision is not None
            else [],
            "revisions_requested": application.status in RESPONDABLE_STATUSES,
            "application_version": application.version,
            "documents": [
                {
                    "type": key,
                    "label": label,
                    "have": key in have,
                    "declared_separately": key not in have and key in declared,
                }
                for key, label in (spec.documents if spec else [])
            ],
            "workspace_href": f"/permits/{application.id}",
        }

    def revise_documents(
        self,
        application_id: str,
        uploads: list[tuple[str, str, bytes]],
        actor: ActorContext,
    ) -> int:
        """Store revised documents as new versions of an application the actor owns."""
        from acme_city.ui.view_models import _application_in_scope

        self._authorize(actor)
        application = self._session.get(permit.Application, application_id)
        if application is None or not _application_in_scope(actor, application):
            raise NotFoundError("that application is not available to you")
        # An archived case is closed: it takes no revised document.
        require_mutable(application, action="uploading a revised document")
        if application.status not in RESPONDABLE_STATUSES:
            raise ValidationError("the City has not asked for revised documents")
        store = DocumentService(self._session, root=self._root)
        count = 0
        for document_type, filename, content in uploads:
            extension = Path(filename or "").suffix.lower()
            media_type = UPLOAD_EXTENSIONS.get(extension)
            if media_type is None or not content or len(content) > MAX_UPLOAD_BYTES:
                raise ValidationError(
                    "a revised file must be a PDF, PNG, JPG or text file of at most 5 MB"
                )
            store.store_version(
                StoreDocumentCommand(
                    application_id=application.id,
                    document_type=document_type,
                    filename=f"{application.source_application_number}-{document_type}-rev{extension}",
                    media_type=media_type,
                    content=content,
                ),
                actor,
            )
            count += 1
        self._audit.append(
            action="portal.documents.revise",
            actor=actor,
            target_type="application",
            target_id=application.id,
            reason=f"submitted {count} revised document(s) through the applicant portal",
        )
        return count

    def resubmit(
        self,
        application_id: str,
        actor: ActorContext,
        *,
        uploads: list[tuple[str, str, bytes]] | None = None,
        answers: dict[str, Any] | None = None,
        expected_version: int | None,
    ) -> permit.Application:
        """Answer the City and send the case back to intake.

        The resubmission is atomic: the revised documents, the new submitted
        revision and the state of the case move together.  The case returns
        to intake, the work that was done against the earlier revision
        becomes stale, and the date the applicant first submitted is kept.
        """
        from acme_city.permits.schemas import ReviseApplicationCommand
        from acme_city.permits.service import PermitService
        from acme_city.ui.view_models import _application_in_scope

        self._authorize(actor)
        application = self._session.get(permit.Application, application_id)
        if application is None or not _application_in_scope(actor, application):
            raise NotFoundError("that application is not available to you")
        # An archived case is closed: it takes no answer.
        require_mutable(application, action="resubmitting the application")
        if application.status not in RESPONDABLE_STATUSES:
            raise ValidationError("the City has not asked for a response")
        if expected_version is None:
            raise ValidationError("an expected version is required to resubmit")
        if application.version != expected_version:
            raise ValidationError(
                "the application changed since it was read; read it again and retry"
            )
        if uploads:
            self.revise_documents(application.id, list(uploads), actor)
        permits = PermitService(self._session)
        permits.revise(
            ReviseApplicationCommand(
                application_id=application.id,
                facts=dict(answers or {}),
                reason="the applicant answered the City and sent the case back",
                expected_version=application.version,
            ),
            actor,
        )
        self._audit.append(
            action="portal.application.resubmit",
            actor=actor,
            target_type="application",
            target_id=application.id,
            after_version=application.version,
            reason=(
                "answered the City and sent the case back to intake; "
                f"{len(uploads or [])} revised document(s)"
            ),
        )
        self._session.flush()
        return application


__all__ = [
    "MAX_UPLOAD_BYTES",
    "STATUS_WORDS",
    "UPLOAD_EXTENSIONS",
    "PortalService",
    "applicant_party",
]

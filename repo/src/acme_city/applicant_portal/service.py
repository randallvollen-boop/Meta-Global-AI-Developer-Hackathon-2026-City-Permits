"""The applicant portal service: drafts, uploads, completeness and submission.

Every write runs under the acting persona's own ``application.submit`` grant
and is audited.  The server decides whether an application is complete; the
browser script only mirrors that answer while the applicant types.
"""
# REQUIRES: PORTAL-01, PORTAL-02, PORTAL-03
# Submission is refused server-side unless the application is complete and
# certified; a draft keeps the applicant's work; uploads are limited by size
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
    "ready_for_review": "Ready for review",
    "under_review": "Under review",
    "approved": "Approved",
    "denied": "Denied",
    "withdrawn": "Withdrawn",
    "issued": "Permit issued",
}

_SAFE = re.compile(r"[^A-Za-z0-9]+")


def applicant_party(actor: ActorContext) -> str | None:
    """Return the canonical party of an applicant persona, if its scope names one."""
    return next((item for item in actor.record_scope if item.startswith("party_")), None)


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
        certified: bool = False,
    ) -> dict[str, Any]:
        """Return what is still needed, by plain label."""
        missing: list[str] = []
        if not self._present(values.get("applicant_name")):
            missing.append("Applicant name")
        if not self._present(values.get("applicant_email")):
            missing.append("Applicant email")
        elif "@" not in values["applicant_email"]:
            missing.append("Applicant email (enter a valid address)")
        if spec.needs_business and not self._present(values.get("business_name")):
            missing.append("Business name")
        if not self._present(values.get("address_text")):
            missing.append("Property address")
        for field in spec.fields:
            raw = values.get(field.key)
            if field.kind == "checkbox":
                if field.required and str(raw or "").lower() not in {"on", "true", "1", "yes"}:
                    missing.append(field.label)
                continue
            if not self._present(raw):
                if field.required:
                    missing.append(field.label)
                continue
            if field.kind == "number":
                try:
                    if float(str(raw).replace(",", "")) < 0:
                        raise ValueError
                except ValueError:
                    missing.append(f"{field.label} (enter a number)")
        for doc_type, label in spec.documents:
            if doc_type not in uploaded_types:
                missing.append(label)
        complete = not missing
        return {
            "complete": complete,
            "missing": missing,
            "certified": certified,
            "can_submit": complete and certified,
            "banner": (
                "Ready to submit. All required fields and documents are provided."
                if complete
                else "Still needed: " + ", ".join(missing) + "."
            ),
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
        certified: bool,
        actor: ActorContext,
        *,
        reference: str = "",
    ) -> gis.ApplicationDraft:
        """Keep the applicant's work as a draft (a draft is not an application)."""
        self._authorize(actor)
        data = {"values": dict(values), "certified": bool(certified)}
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
        certified: bool,
        draft: gis.ApplicationDraft,
        actor: ActorContext,
    ) -> permit.Application:
        """Submit a complete, certified application through the existing path."""
        from acme_city.portal_intake.schemas import IntakeRecordCommand
        from acme_city.portal_intake.service import IntakeService

        self._authorize(actor)
        documents = self.draft_documents(draft)
        state = self.completeness(spec, values, set(documents), certified=certified)
        if not state["complete"]:
            raise ValidationError(state["banner"])
        if not certified:
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
        facts["certified"] = True
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
        findings = self._session.execute(
            select(permit.ApplicationFinding)
            .where(permit.ApplicationFinding.application_id == application.id)
            .order_by(permit.ApplicationFinding.created_at, permit.ApplicationFinding.id)
        ).scalars().all()
        messages = [
            {
                "message": row.message,
                "applicant_must": row.applicant_must or "",
                "severity": row.severity,
            }
            for row in findings
            if row.applicant_must
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
        return {
            "application_id": application.id,
            "reference": application.source_application_number,
            "type_label": permit_type.label if permit_type else "",
            "status": application.status,
            "status_word": STATUS_WORDS.get(application.status, application.status),
            "messages": messages,
            "decision_reason": decision.reason if decision is not None and decision.reason else "",
            "revisions_requested": application.status == "needs_information",
            "documents": [
                {"type": key, "label": label, "have": key in have}
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
        if application.status != "needs_information":
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


__all__ = [
    "MAX_UPLOAD_BYTES",
    "STATUS_WORDS",
    "UPLOAD_EXTENSIONS",
    "PortalService",
    "applicant_party",
]

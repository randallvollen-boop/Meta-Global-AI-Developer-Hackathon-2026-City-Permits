"""Storage of fictional document versions.

A document version is the bytes that were actually received together with
their hash and their path.  A label alone never demonstrates that a document
was read, so a version without bytes is refused.  The bytes live outside the
templates, under the ignored ``var`` directory, and the database keeps only
the hash, the relative path and the metadata.
"""
# REQUIRES: PER-01, SEC-04, AI-05
# A stored document version keeps its bytes, its hash and its path, and the
# document store never accepts a filename or a media type outside the
# allowlist.

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.permits.schemas import DocumentVersionView
from acme_city.persistence.models import permit

#: Where the document bytes are stored.  The directory is ignored by git.
DOCUMENT_ROOT = Path("var/documents")

#: The media types a stored document may use, with the extension each one
#: must carry.
ALLOWED_MEDIA_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "text/plain": ".txt",
}

#: The document types the permit configurations ask for.
ALLOWED_DOCUMENT_TYPES: frozenset[str] = frozenset(
    {
        "construction_plans",
        "site_plan",
        "energy_compliance_form",
        "material_spec",
        "floor_plan",
        "fire_suppression_plan",
        "business_license_copy",
        "sign_drawing",
        "owner_authorization",
        "traffic_control_plan",
        "insurance_certificate",
        "supporting_document",
    }
)

#: The largest document the demonstration accepts.
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024

#: A safe document file name.
_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


class StoreDocumentCommand(BaseModel):
    """One document version that was received.

    The command carries the bytes.  A command that only names a document is
    refused: the store never records a document that was not received.
    """

    model_config = ConfigDict(extra="forbid")

    application_id: str
    document_type: str
    filename: str
    media_type: str
    content: bytes


class DocumentService:
    """Stores and reads fictional document versions."""

    def __init__(
        self,
        session: Session,
        *,
        root: Path | None = None,
        now: datetime | None = None,
    ) -> None:
        self._session = session
        self._root = Path(root) if root is not None else DOCUMENT_ROOT
        self._now = now or utc_now()
        self._permissions = PermissionResolver(session, now=self._now)

    def store_version(
        self, command: StoreDocumentCommand, actor: ActorContext
    ) -> DocumentVersionView:
        """Store one document version and record its hash and path.

        The command carries the bytes.  A command that only names a document
        is refused: the store never records a document that was not received.
        """
        document_type = str(command.document_type or "").strip()
        if document_type not in ALLOWED_DOCUMENT_TYPES:
            raise ValidationError(f"unsupported document type: {document_type!r}")

        media_type = str(command.media_type or "").strip().lower()
        extension = ALLOWED_MEDIA_TYPES.get(media_type)
        if extension is None:
            raise ValidationError(f"unsupported media type: {command.media_type!r}")

        filename = str(command.filename or "").strip()
        if not _FILENAME.match(filename):
            raise ValidationError("the file name is not an acceptable document name")
        if Path(filename).suffix.lower() != extension:
            raise ValidationError(
                f"the file name must carry the {extension} extension of {media_type!r}"
            )

        content = command.content
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise ValidationError("a document version must carry the bytes that were received")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise ValidationError("the document is larger than the demonstration accepts")

        application = self._session.execute(
            select(permit.Application).where(permit.Application.id == command.application_id)
        ).scalar_one_or_none()
        if application is None:
            raise NotFoundError("that application does not exist")
        self._permissions.authorize(
            actor,
            "application.submit",
            ResourceContext(
                domain_id="permits",
                record_ids=(
                    application.source_application_number,
                    application.applicant_party_id or "",
                ),
            ),
        )

        version = self._next_version(application.id, document_type)
        document_id = new_id("doc")
        directory = self._root / application.id / document_id
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"v{version}{extension}"
        target.write_bytes(bytes(content))

        digest = hashlib.sha256(bytes(content)).hexdigest()
        row = permit.Document(
            id=document_id,
            application_id=application.id,
            document_type=document_type,
            version=version,
            file_ref=str(target),
            content_hash=digest,
            received_at=self._now,
            uploaded_by_actor_id=actor.actor_id,
            fictional_demo=True,
        )
        self._session.add(row)
        self._session.flush()
        return self.view(row, media_type=media_type, byte_length=len(content))

    def list_versions(self, application_id: str) -> list[DocumentVersionView]:
        """Return the document versions of an application."""
        rows = self._session.execute(
            select(permit.Document)
            .where(permit.Document.application_id == application_id)
            .order_by(permit.Document.document_type, permit.Document.version)
        ).scalars().all()
        return [
            self.view(
                row,
                media_type=self._media_type_of(row),
                byte_length=self._byte_length(row),
            )
            for row in rows
        ]

    def read_bytes(self, document_id: str) -> bytes:
        """Return the bytes of one stored document version."""
        row = self._session.execute(
            select(permit.Document).where(permit.Document.id == document_id)
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("that document version does not exist")
        path = Path(row.file_ref)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise NotFoundError("the stored document is no longer available")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != row.content_hash:
            raise ValidationError("the stored document no longer matches its recorded hash")
        return content

    def view(
        self, row: permit.Document, *, media_type: str, byte_length: int
    ) -> DocumentVersionView:
        """Return the view of one stored document version."""
        return DocumentVersionView(
            document_id=row.id,
            application_id=row.application_id,
            document_type=row.document_type,
            version=row.version,
            file_ref=row.file_ref,
            content_hash=row.content_hash,
            byte_length=byte_length,
            media_type=media_type,
            received_at=row.received_at,
            uploaded_by_actor_id=row.uploaded_by_actor_id,
            fictional_demo=row.fictional_demo,
        )

    def _next_version(self, application_id: str, document_type: str) -> int:
        """Return the next version number of one document type."""
        highest = self._session.execute(
            select(func.max(permit.Document.version)).where(
                permit.Document.application_id == application_id,
                permit.Document.document_type == document_type,
            )
        ).scalar_one()
        return 1 if highest is None else int(highest) + 1

    def _media_type_of(self, row: permit.Document) -> str:
        """Return the media type implied by the stored file name."""
        suffix = Path(row.file_ref).suffix.lower()
        for media_type, extension in ALLOWED_MEDIA_TYPES.items():
            if extension == suffix:
                return media_type
        return "application/octet-stream"

    def _byte_length(self, row: permit.Document) -> int:
        """Return the number of bytes of one stored document version."""
        path = Path(row.file_ref)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            return 0
        return path.stat().st_size


__all__ = [
    "ALLOWED_DOCUMENT_TYPES",
    "ALLOWED_MEDIA_TYPES",
    "DOCUMENT_ROOT",
    "MAX_DOCUMENT_BYTES",
    "DocumentService",
    "StoreDocumentCommand",
]

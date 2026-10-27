"""Permit type icons: seeded assets, Muse Image generations and saves.

The map below is configuration data, not template logic: it names the
bundled WebP asset that seeds each of three permit types.  The other two
types start with no icon and fall back to a line-icon tile until an
administrator generates and saves one.

Every generation attempt — capped, refused, failed or succeeded — is
recorded as an audit event carrying the prompt, the status, the cost
estimate and the delivered response size.  A generated image stays
pending until an administrator saves it; saving is what makes it the
type's current icon.  Seeding happens only when the rules-fees screen's
view model first needs the icons, and only inside the caller's
transaction: this module never commits.
"""
# REQUIRES: AI-01, AI-03, SEC-01, SEC-04, UX-01
# An icon generation is a governed, capped, audited administrator action;
# Muse proposes an image and only an explicit save makes it current.

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.core.clock import utc_now
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError, ValidationError
from acme_city.core.ids import new_id
from acme_city.muse.image_client import (
    IMAGE_COST_ESTIMATE_USD,
    MuseImageClient,
    describe_image,
    wrap_icon_prompt,
)
from acme_city.persistence.models import audit, permit
from acme_city.ui.view_models import allows

#: Permit type id -> bundled seed asset in ``static/permit-type-icons/``.
PERMIT_TYPE_SEED_ICONS: Final[dict[str, str]] = {
    "permit_type_com_ti": "commercial-alteration",
    "permit_type_res_building": "new-building",
    "permit_type_sign": "sign",
}

#: The permission an icon generation or save requires, and its action ids.
ICON_PERMISSION: Final = "permit.icon.generate"
GENERATE_ACTION: Final = "permit.icon.generate"
SAVE_ACTION: Final = "permit.icon.save"

#: The hard per-type daily cap of generation attempts.
PER_TYPE_DAILY_CAP: Final = 3

#: The icon assets bundled with the application.
STATIC_ICON_DIR: Final = (
    Path(__file__).resolve().parents[1] / "static" / "permit-type-icons"
)

#: The audit action of one generation attempt.
ATTEMPT_ACTION: Final = "ui.permit.icon.generate"


def _permit_type(session: Session, permit_type_id: str) -> permit.PermitType:
    row = session.execute(
        select(permit.PermitType).where(permit.PermitType.id == permit_type_id)
    ).scalar_one_or_none()
    if row is None:
        raise ValidationError(
            f"unknown permit type {permit_type_id!r}", code="unknown_permit_type"
        )
    return row


def ensure_seeded(session: Session) -> None:
    """Insert the bundled seed icons that are missing.  Never commits.

    A type whose current icon was changed keeps it: seeding only fills a
    type that has no icon rows at all.  A missing asset file is skipped,
    so the type simply keeps its line-icon fallback.
    """
    for type_row in session.execute(select(permit.PermitType)).scalars().all():
        existing = session.execute(
            select(permit.PermitTypeIcon).where(
                permit.PermitTypeIcon.permit_type_id == type_row.id
            )
        ).scalars().first()
        if existing is not None:
            continue
        slug = PERMIT_TYPE_SEED_ICONS.get(type_row.permit_type_id)
        if slug is None:
            continue
        asset = STATIC_ICON_DIR / f"{slug}.webp"
        try:
            data = asset.read_bytes()
        except OSError:
            continue
        described = describe_image(data)
        if described is None:
            continue
        # A fixed id keeps two resets of the same fixture version identical.
        icon = permit.PermitTypeIcon(
            id=f"icon_seed_{type_row.key}",
            permit_type_id=type_row.id,
            image_data=data,
            media_type=described[0],
            prompt=f"Bundled seed icon asset {slug}.webp",
            created_by=None,
            source="seed",
            is_current=True,
        )
        session.add(icon)
        session.flush()
        type_row.icon_id = icon.id
    session.flush()


def icon_attempt_counts(
    session: Session, *, today: datetime | None = None
) -> tuple[dict[str, int], int]:
    """Return today's generation attempts per permit type and in total."""
    moment = today or utc_now()
    start = datetime.combine(moment.date(), time.min, tzinfo=moment.tzinfo)
    rows = session.execute(
        select(audit.AuditEvent).where(
            audit.AuditEvent.action == ATTEMPT_ACTION,
            audit.AuditEvent.occurred_at >= start,
        )
    ).scalars().all()
    per_type: dict[str, int] = {}
    for row in rows:
        if row.target_id:
            per_type[row.target_id] = per_type.get(row.target_id, 0) + 1
    return per_type, len(rows)


def _record_attempt(
    session: Session,
    actor: ActorContext,
    *,
    permit_type_id: str,
    prompt: str,
    status: str,
    response_size: int = 0,
    icon_id: str | None = None,
    detail: str = "",
) -> None:
    AuditService(session).append(
        action=ATTEMPT_ACTION,
        actor=actor,
        target_type="permit_type",
        target_id=permit_type_id,
        reason=f"icon generation {status} for {permit_type_id}",
        outcome="accepted",
        metadata={
            "prompt": prompt,
            "status": status,
            "cost_estimate_usd": IMAGE_COST_ESTIMATE_USD,
            "response_size": response_size,
            "icon_id": icon_id or "",
            "detail": detail,
        },
    )


def record_denied_attempt(
    session: Session,
    *,
    actor_id: str,
    permit_type_id: str,
    prompt: str,
    detail: str,
) -> None:
    """Append the attempt record of a refused generation in its own commit.

    The governed-action dispatcher rolls its transaction back when a
    handler raises, so a refusal that must stay recorded — a cap refusal —
    is written by this helper, which first abandons any pending work of
    the request transaction and then commits only the attempt record.
    """
    try:
        session.rollback()
    except Exception:
        pass
    AuditService(session).append(
        action=ATTEMPT_ACTION,
        actor=actor_id,
        target_type="permit_type",
        target_id=permit_type_id or None,
        reason=f"icon generation refused for {permit_type_id}",
        outcome="denied",
        denial_reason="daily generation cap reached",
        metadata={
            "prompt": prompt,
            "status": "refused_cap",
            "cost_estimate_usd": IMAGE_COST_ESTIMATE_USD,
            "response_size": 0,
            "icon_id": "",
            "detail": detail,
        },
    )
    session.commit()


def generate_icon(
    ctx: Any,
    *,
    client: MuseImageClient | None = None,
    now: datetime | None = None,
) -> Any:
    """Generate one pending icon candidate for a permit type.

    Raises PermissionDeniedError for a persona without the grant and
    ValidationError for a missing type or description.  A cap refusal is
    recorded before it is raised.  The caller (the UI dispatcher) commits
    an accepted outcome and rolls a raised one back after recording the
    refusal, so the attempt and its candidate commit together.
    """
    from acme_city.ui.router import Outcome

    session: Session = ctx.session
    actor: ActorContext = ctx.actor
    settings: Settings = ctx.settings
    permit_type_id = ctx.text("permit_type_id")
    sentence = ctx.text("prompt")
    if not allows(session, actor, ICON_PERMISSION):
        raise PermissionDeniedError(
            "icon generation is limited to the City Administrator: your persona "
            f"does not hold the {ICON_PERMISSION!r} grant",
            actor_id=actor.actor_id,
            action="ui.permit.icon.generate",
        )
    if not permit_type_id:
        raise ValidationError("permit_type_id is required", code="missing_permit_type")
    type_row = _permit_type(session, permit_type_id)
    if not sentence:
        raise ValidationError(
            "describe the icon in a sentence before generating",
            code="missing_icon_description",
        )
    ensure_seeded(session)
    per_type, total = icon_attempt_counts(session, today=now)
    type_count = per_type.get(type_row.id, 0)
    if type_count >= PER_TYPE_DAILY_CAP:
        detail = (
            f"this permit type already used its {PER_TYPE_DAILY_CAP} icon "
            "generations for today; try again tomorrow"
        )
        record_denied_attempt(
            session,
            actor_id=actor.actor_id,
            permit_type_id=type_row.id,
            prompt=sentence,
            detail=detail,
        )
        raise ValidationError(detail, code="icon_generation_cap")
    if total >= settings.muse_image_daily_cap:
        detail = (
            f"the daily icon generation cap of {settings.muse_image_daily_cap} "
            "was reached for today; try again tomorrow"
        )
        record_denied_attempt(
            session,
            actor_id=actor.actor_id,
            permit_type_id=type_row.id,
            prompt=sentence,
            detail=detail,
        )
        raise ValidationError(detail, code="icon_generation_cap")
    wrapped = wrap_icon_prompt(sentence)
    image_client = client or MuseImageClient(settings)
    result = image_client.generate(wrapped)
    if not result.ok:
        _record_attempt(
            session,
            actor,
            permit_type_id=type_row.id,
            prompt=sentence,
            status="failed",
            response_size=result.response_size,
            detail=result.error or "the provider request failed",
        )
        return Outcome(
            message=(
                "Icon generation failed: "
                + (result.error or "the provider request failed")
            ),
            destination="Muse Image generation",
            state="failed",
            target_type="permit_type",
            target_id=type_row.id,
        )
    icon = permit.PermitTypeIcon(
        id=new_id("icon"),
        permit_type_id=type_row.id,
        image_data=result.image_data,
        media_type=result.media_type,
        prompt=sentence,
        created_by=actor.actor_id,
        source="generated",
        is_current=False,
    )
    session.add(icon)
    session.flush()
    _record_attempt(
        session,
        actor,
        permit_type_id=type_row.id,
        prompt=sentence,
        status="succeeded",
        response_size=result.response_size,
        icon_id=icon.id,
    )
    return Outcome(
        message=(
            "Generated a new icon candidate. It stays pending until you save it; "
            "nothing on the permit types changed yet."
        ),
        destination="Muse Image generation",
        state="pending",
        target_type="permit_type",
        target_id=type_row.id,
        extra={"icon_id": icon.id},
    )


def save_icon(ctx: Any) -> Any:
    """Make one stored icon the current icon of its permit type."""
    from acme_city.ui.router import Outcome

    session: Session = ctx.session
    actor: ActorContext = ctx.actor
    if not allows(session, actor, ICON_PERMISSION):
        raise PermissionDeniedError(
            "saving a permit type icon is limited to the City Administrator: "
            f"your persona does not hold the {ICON_PERMISSION!r} grant",
            actor_id=actor.actor_id,
            action="ui.permit.icon.save",
        )
    permit_type_id = ctx.text("permit_type_id")
    icon_id = ctx.text("icon_id")
    if not permit_type_id:
        raise ValidationError("permit_type_id is required", code="missing_permit_type")
    if not icon_id:
        raise ValidationError(
            "choose an icon from the history before saving", code="missing_icon_choice"
        )
    type_row = _permit_type(session, permit_type_id)
    expected = ctx.integer("expected_version")
    if expected is not None and expected != type_row.version:
        raise ValidationError(
            "the permit type changed since it was read; read it again and retry",
            code="version_conflict",
        )
    icon = session.execute(
        select(permit.PermitTypeIcon).where(permit.PermitTypeIcon.id == icon_id)
    ).scalar_one_or_none()
    if icon is None or icon.permit_type_id != type_row.id:
        raise ValidationError(
            "the chosen icon does not belong to this permit type",
            code="icon_type_mismatch",
        )
    before_version = type_row.version
    for other in session.execute(
        select(permit.PermitTypeIcon).where(
            permit.PermitTypeIcon.permit_type_id == type_row.id
        )
    ).scalars().all():
        other.is_current = other.id == icon.id
    type_row.icon_id = icon.id
    type_row.version = before_version + 1
    session.flush()
    return Outcome(
        message=f"Saved the icon for {type_row.label}. It is now the current icon.",
        destination="Permit type icons",
        state="saved",
        target_type="permit_type",
        target_id=type_row.id,
        before_version=before_version,
        after_version=type_row.version,
        extra={"icon_id": icon.id},
    )


__all__ = [
    "ATTEMPT_ACTION",
    "GENERATE_ACTION",
    "ICON_PERMISSION",
    "PERMIT_TYPE_SEED_ICONS",
    "PER_TYPE_DAILY_CAP",
    "SAVE_ACTION",
    "STATIC_ICON_DIR",
    "ensure_seeded",
    "generate_icon",
    "icon_attempt_counts",
    "record_denied_attempt",
    "save_icon",
]

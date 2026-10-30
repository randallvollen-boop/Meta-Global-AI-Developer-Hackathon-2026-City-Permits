"""Configuration changes of the City.

A permit type, a reason code and a user are configuration.  Every change is
a governed, audited action, and every change shows up in the configuration
log.  A configuration change takes effect for new intake: it never rewrites
what an already-submitted case was measured against.
"""
# REQUIRES: GOV-04, SEC-02, PER-01
# A configuration change is authorized, versioned and audited, and a new
# permit type starts without rules so the adjudication agent holds it.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.agents.bundle import AGENT_OPERATIONS
from acme_city.agents.policy import MODE_AUTOMATIC, MODE_MANUAL
from acme_city.agents.runtime import DEFAULT_MAX_BATCH_SIZE
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.configuration.reasons import REASON_CODE_TYPES, reason_code_view
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.documents.service import ALLOWED_DOCUMENT_TYPES
from acme_city.persistence.models import governance, permit
from acme_city.persistence.models import agent_ops

#: The grant that changes the configuration.
PERMISSION_MANAGE = "config.manage"

#: The grant that adds a user.
PERMISSION_MANAGE_USERS = "admin.actor.manage"

#: The bounds of the hourly limit the City may set.
MIN_RUNS_PER_HOUR = 1
MAX_RUNS_PER_HOUR = 120

PERMISSION_MANAGE_AGENT_ROLES = "admin.actor.manage"
MANAGED_AGENT_ROLE_IDS: tuple[str, ...] = (
    "agent_operator",
    "permit_reviewer",
    "intake_clerk",
    "domain_steward",
    "domain_mdm_steward",
)

#: The persona roles a user may be given.
PERSONA_ROLES: dict[str, str] = {
    "Applicant": "persona_applicant",
    "Data Steward": "persona_data_steward",
    "Permit Reviewer": "persona_permit_reviewer",
    "City Administrator": "persona_city_administrator",
    "Agent Operator": "persona_agent_operator",
}

#: The process categories a permit type may declare.
PROCESS_CATEGORIES: tuple[str, ...] = ("simple", "with_plans", "formal_review")


class ConfigurationService:
    """Changes the permit types, the reason codes and the users."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    # ------------------------------------------------------------ permit types

    def set_required_document(
        self,
        *,
        permit_type_id: str,
        document_type: str,
        required: bool,
        actor: ActorContext,
        expected_version: int | None = None,
    ) -> permit.PermitType:
        """Require a document of a permit type, or stop requiring it."""
        self._permissions.authorize(
            actor,
            PERMISSION_MANAGE,
            ResourceContext(domain_id=None, record_ids=()),
        )
        row = self._session.get(permit.PermitType, permit_type_id)
        if row is None:
            raise NotFoundError("that permit type does not exist")
        if document_type not in ALLOWED_DOCUMENT_TYPES:
            raise ValidationError(f"unknown document type: {document_type!r}")
        if expected_version is not None and row.version != expected_version:
            raise ValidationError(
                "the permit type changed since it was read; read it again and retry"
            )
        documents = list(row.required_documents or [])
        before = list(documents)
        if required and document_type not in documents:
            documents.append(document_type)
            documents.sort()
        elif not required and document_type in documents:
            documents.remove(document_type)
        row.required_documents = documents
        row.version += 1
        self._session.flush()
        self._audit.append(
            action="config.permit_type.document",
            actor=actor,
            target_type="permit_type",
            target_id=row.id,
            before_version=row.version - 1,
            after_version=row.version,
            reason=(
                f"{'Require' if required else 'Stop requiring'} {document_type} for "
                f"{row.label}"
            ),
            metadata={
                "before": ", ".join(before) or "none",
                "after": ", ".join(documents) or "none",
                "document_type": document_type,
                "required": required,
            },
        )
        return row

    def create_permit_type(
        self,
        *,
        key: str,
        label: str,
        description: str,
        review_area: str,
        process_category: str,
        discretionary: bool,
        required_fields: list[str],
        required_documents: list[str],
        fee_schedule_key: str,
        actor: ActorContext,
    ) -> permit.PermitType:
        """Create one new permit type.

        A new type has no published rule, so the adjudication agent holds it
        for a person.  That is expected and is stated on the form.
        """
        self._permissions.authorize(
            actor,
            PERMISSION_MANAGE,
            ResourceContext(domain_id=None, record_ids=()),
        )
        clean_key = str(key or "").strip().lower().replace(" ", "_")
        if not clean_key:
            raise ValidationError("a permit type needs a key")
        if not str(label or "").strip():
            raise ValidationError("a permit type needs a label")
        if process_category not in PROCESS_CATEGORIES:
            raise ValidationError(
                "a permit type needs a process category: "
                + ", ".join(PROCESS_CATEGORIES)
            )
        unknown_documents = set(required_documents) - ALLOWED_DOCUMENT_TYPES
        if unknown_documents:
            raise ValidationError(
                "unknown document type(s): " + ", ".join(sorted(unknown_documents))
            )
        existing = self._session.execute(
            select(permit.PermitType).where(permit.PermitType.key == clean_key)
        ).scalar_one_or_none()
        if existing is not None:
            raise ValidationError(f"a permit type with the key {clean_key!r} already exists")
        row = permit.PermitType(
            id=new_id("permit_type"),
            permit_type_id=new_id("permit_type"),
            key=clean_key,
            label=str(label).strip(),
            review_route=str(review_area or label).strip(),
            required_fields=sorted({str(field).strip() for field in required_fields if field}),
            required_documents=sorted(
                {str(document).strip() for document in required_documents if document}
            ),
            active=True,
            review_area=str(review_area or "").strip() or None,
            process_category=process_category,
            discretionary=bool(discretionary),
            description=str(description or "").strip() or None,
            fee_schedule_key=str(fee_schedule_key or "").strip() or None,
        )
        self._session.add(row)
        self._session.flush()
        self._audit.append(
            action="config.permit_type.create",
            actor=actor,
            target_type="permit_type",
            target_id=row.id,
            after_version=row.version,
            reason=f"Created the permit type {row.label} ({row.key})",
            metadata={
                "before": "none",
                "after": f"{row.label} ({row.key})",
                "process_category": process_category,
                "discretionary": bool(discretionary),
                "review_area": row.review_area,
            },
        )
        return row

    # ------------------------------------------------------------ reason codes

    def add_reason_code(
        self,
        *,
        code: str,
        label: str,
        description: str,
        code_type: str,
        actor: ActorContext,
    ) -> permit.ReasonCode:
        """Add one reason code.

        The code carries the type of use it may serve.  A code that was
        retired is never overwritten: its row, its label and its history stay,
        and its code cannot be taken again.
        """
        self._permissions.authorize(
            actor,
            PERMISSION_MANAGE,
            ResourceContext(domain_id=None, record_ids=()),
        )
        clean_code = str(code or "").strip().upper()
        if not clean_code:
            raise ValidationError("a reason code needs a code")
        if not str(label or "").strip():
            raise ValidationError("a reason code needs a label")
        clean_type = str(code_type or "").strip().lower()
        if clean_type not in REASON_CODE_TYPES:
            raise ValidationError(
                "a reason code needs a type: " + ", ".join(REASON_CODE_TYPES)
            )
        existing = self._session.execute(
            select(permit.ReasonCode).where(permit.ReasonCode.code == clean_code)
        ).scalar_one_or_none()
        if existing is not None:
            if not existing.active:
                raise ValidationError(
                    f"the reason code {clean_code!r} was retired; its history is kept and "
                    "the code cannot be taken again"
                )
            raise ValidationError(f"the reason code {clean_code!r} already exists")
        row = permit.ReasonCode(
            id=new_id("reasoncode"),
            correlation_id=new_id("corr"),
            code=clean_code,
            label=str(label).strip(),
            description=str(description or "").strip() or None,
            code_type=clean_type,
            active=True,
            version=1,
            changed_by=actor.actor_id,
            changed_at=self._now,
        )
        self._session.add(row)
        self._session.flush()
        self._audit.append(
            action="config.reason_code.add",
            actor=actor,
            target_type="reason_code",
            target_id=row.id,
            after_version=row.version,
            reason=f"Added the reason code {row.code}",
            metadata={
                "before": "none",
                "after": f"{row.code} · {row.label}",
                "code_type": clean_type,
            },
        )
        return row

    def reason_codes(self, *, code_type: str | None = None) -> list[permit.ReasonCode]:
        """Return the reason codes, optionally of one type only."""
        statement = select(permit.ReasonCode)
        if code_type is not None:
            statement = statement.where(permit.ReasonCode.code_type == code_type)
        return list(
            self._session.execute(statement.order_by(permit.ReasonCode.code)).scalars().all()
        )

    def retire_reason_code(
        self, *, code: str, actor: ActorContext
    ) -> permit.ReasonCode:
        """Retire one reason code."""
        self._permissions.authorize(
            actor,
            PERMISSION_MANAGE,
            ResourceContext(domain_id=None, record_ids=()),
        )
        row = self._session.execute(
            select(permit.ReasonCode).where(permit.ReasonCode.code == str(code).strip().upper())
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("that reason code does not exist")
        if not row.active:
            return row
        row.active = False
        row.version += 1
        row.changed_by = actor.actor_id
        row.changed_at = self._now
        self._session.flush()
        self._audit.append(
            action="config.reason_code.retire",
            actor=actor,
            target_type="reason_code",
            target_id=row.id,
            before_version=row.version - 1,
            after_version=row.version,
            reason=f"Retired the reason code {row.code}",
            metadata={"before": "active", "after": "retired"},
        )
        return row

    # ------------------------------------------------------- processing policy

    def set_processing_policy(
        self,
        *,
        automatic: bool,
        runs_per_hour: int,
        reason: str,
        actor: ActorContext,
        expected_version: int | None = None,
    ) -> agent_ops.AgentProcessingPolicy:
        """Save the processing policy of the City.

        The policy says when the agents work: manually, when a person asks,
        or automatically as the work arrives.  It is a governed change: it
        needs the configuration grant, it names a reason and it is audited.  A
        save that was made against an older version of the policy is refused,
        so two administrators never overwrite each other in silence.

        The policy never decides anything about a case: it says when the
        agents may work, not what they decide.
        """
        self._permissions.authorize(
            actor,
            PERMISSION_MANAGE,
            ResourceContext(domain_id=None, record_ids=()),
        )
        if not str(reason or "").strip():
            raise ValidationError(
                "a reason is required when changing the processing settings"
            )
        limit = int(runs_per_hour)
        if not MIN_RUNS_PER_HOUR <= limit <= MAX_RUNS_PER_HOUR:
            raise ValidationError(
                f"the hourly limit must be between {MIN_RUNS_PER_HOUR} and "
                f"{MAX_RUNS_PER_HOUR} run(s)"
            )
        mode = MODE_AUTOMATIC if automatic else MODE_MANUAL
        row = self._session.execute(
            select(agent_ops.AgentProcessingPolicy).order_by(
                agent_ops.AgentProcessingPolicy.created_at
            )
        ).scalars().first()
        if row is None:
            row = agent_ops.AgentProcessingPolicy(
                id=new_id("agentpolicy"),
                correlation_id=new_id("corr"),
                mode=mode,
                runs_per_hour=limit,
                max_batch_size=DEFAULT_MAX_BATCH_SIZE,
                version=1,
            )
            self._session.add(row)
            before_mode = MODE_MANUAL
        else:
            if expected_version is not None and row.version != expected_version:
                raise ValidationError(
                    "the processing settings changed since they were read; read them "
                    "again and retry"
                )
            before_mode = row.mode
            row.mode = mode
            row.runs_per_hour = limit
            row.version += 1
        self._session.flush()
        self._audit.append(
            action="admin.agent.processing",
            actor=actor,
            target_type="agent_processing_policy",
            target_id=row.id,
            before_version=row.version - 1 if row.version > 1 else None,
            after_version=row.version,
            reason=str(reason).strip(),
            metadata={
                "before": before_mode,
                "after": mode,
                "runs_per_hour": limit,
            },
        )
        return row

    # ------------------------------------------------------------------- users

    def set_agent_role_entitlement(
        self,
        *,
        role_id: str,
        can_run_agents: bool,
        reason: str,
        actor: ActorContext,
    ) -> agent_ops.AgentRoleEntitlement:
        """Set one managed agent-operation bundle for a staff role.

        The existing administrator-management grant is the explicit boundary
        for this Users and roles control.  The role id is server validated and
        never accepted as authority from a browser.
        """
        self._permissions.authorize(
            actor,
            PERMISSION_MANAGE_AGENT_ROLES,
            ResourceContext(domain_id=None, record_ids=()),
        )
        if role_id not in MANAGED_AGENT_ROLE_IDS:
            raise ValidationError("that role cannot receive the agent operations bundle")
        if not str(reason or "").strip():
            raise ValidationError("a reason is required when changing role permissions")
        row = self._session.execute(
            select(agent_ops.AgentRoleEntitlement).where(
                agent_ops.AgentRoleEntitlement.role_id == role_id
            )
        ).scalar_one_or_none()
        if row is None:
            row = agent_ops.AgentRoleEntitlement(
                id=new_id("agentrole"),
                correlation_id=new_id("corr"),
                role_id=role_id,
                can_run_agents=bool(can_run_agents),
                version=1,
                changed_by=actor.actor_id,
                changed_at=self._now,
            )
            self._session.add(row)
            before = False
        else:
            before = bool(row.can_run_agents)
            row.can_run_agents = bool(can_run_agents)
            row.version += 1
            row.changed_by = actor.actor_id
            row.changed_at = self._now
        self._session.flush()
        self._audit.append(
            action="admin.role.permissions",
            actor=actor,
            target_type="agent_role_entitlement",
            target_id=row.id,
            before_version=row.version - 1 if row.version > 1 else None,
            after_version=row.version,
            reason=str(reason).strip(),
            metadata={
                "role_id": role_id,
                "before": before,
                "after": bool(can_run_agents),
                "bundle": list(AGENT_OPERATIONS),
            },
        )
        return row

    def add_user(
        self,
        *,
        name: str,
        department: str,
        persona_role: str,
        actor: ActorContext,
    ) -> governance.Actor:
        """Add one user and copy the grant template of the persona role.

        The new user is not selectable: the persona switcher still holds
        exactly the five personas of the demonstration.
        """
        self._permissions.authorize(
            actor,
            PERMISSION_MANAGE_USERS,
            ResourceContext(domain_id=None, record_ids=()),
        )
        if persona_role not in PERSONA_ROLES:
            raise ValidationError(
                "a user needs one of the five persona roles: "
                + ", ".join(sorted(PERSONA_ROLES))
            )
        if not str(name or "").strip():
            raise ValidationError("a user needs a name")
        template_id = PERSONA_ROLES[persona_role]
        template = self._session.execute(
            select(governance.Actor).where(governance.Actor.actor_id == template_id)
        ).scalar_one_or_none()
        if template is None:
            raise NotFoundError("the persona role template does not exist")
        actor_id = new_id("user")
        row = governance.Actor(
            id=actor_id,
            actor_id=actor_id,
            label=str(name).strip(),
            active=True,
            fictional=True,
            selectable=False,
            department=str(department or "").strip() or None,
            persona_role=persona_role,
        )
        self._session.add(row)
        self._session.flush()
        self._copy_grants(template_id, actor_id)
        self._audit.append(
            action="config.user.add",
            actor=actor,
            target_type="actor",
            target_id=actor_id,
            after_version=1,
            reason=f"Added the user {row.label} as {persona_role}",
            metadata={
                "before": "none",
                "after": f"{row.label} · {persona_role} · {row.department or 'no department'}",
            },
        )
        return row

    def _copy_grants(self, template_id: str, actor_id: str) -> None:
        """Copy the grants and the roles of one actor onto another."""
        for grant in self._session.execute(
            select(governance.ActorGrant).where(
                governance.ActorGrant.actor_id == template_id
            )
        ).scalars().all():
            self._session.add(
                governance.ActorGrant(
                    id=new_id("grant"),
                    actor_id=actor_id,
                    permission_id=grant.permission_id,
                    domain_id=grant.domain_id,
                    record_scope=list(grant.record_scope or []),
                    effective_from=grant.effective_from,
                    effective_to=grant.effective_to,
                    source="copied_from_persona_template",
                )
            )
        for role in self._session.execute(
            select(governance.ActorRole).where(
                governance.ActorRole.actor_id == template_id
            )
        ).scalars().all():
            self._session.add(
                governance.ActorRole(
                    id=new_id("actorrole"),
                    actor_id=actor_id,
                    role_id=role.role_id,
                )
            )
        self._session.flush()


def permit_type_view(row: permit.PermitType) -> dict[str, Any]:
    """Return the view of one permit type."""
    return {
        "permit_type_id": row.id,
        "permit_type_key": row.key,
        "label": row.label,
        "description": row.description or "",
        "review_area": row.review_area or row.review_route,
        "process_category": row.process_category or "",
        "discretionary": bool(row.discretionary),
        "required_fields": list(row.required_fields or []),
        "required_documents": list(row.required_documents or []),
        "fee_schedule_key": row.fee_schedule_key or "",
        "version": row.version,
    }


__all__ = [
    "MANAGED_AGENT_ROLE_IDS",
    "MAX_RUNS_PER_HOUR",
    "MIN_RUNS_PER_HOUR",
    "MODE_AUTOMATIC",
    "MODE_MANUAL",
    "PERMISSION_MANAGE_AGENT_ROLES",
    "PERMISSION_MANAGE",
    "PERMISSION_MANAGE_USERS",
    "PERSONA_ROLES",
    "PROCESS_CATEGORIES",
    "REASON_CODE_TYPES",
    "ConfigurationService",
    "permit_type_view",
    "reason_code_view",
]

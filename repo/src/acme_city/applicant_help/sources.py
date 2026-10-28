"""The source bundle of the applicant help assistant.

The assistant answers from a bundle the server builds.  The bundle holds:

* the **published rule versions** of the City that are in force at the basis
  date — never a draft, never a rule of another City.  The City's rules are
  public, so the bundle holds the rules of every active permit type; the
  rules of the applicant's own type are the ones in force when the applicant
  filed the case.  Each rule is rendered with its applicability, its operator,
  its threshold and its conditions, so a reader can see that a limit is a
  limit and not an exemption;
* the **permit-type configuration** the City stores: the review area, the
  process category, the discretionary flag, the fields and the documents the
  type asks for;
* the **service target** of the type, with its definition, so it is read as a
  target and never as a promise;
* the fixed **lifecycle and process passages** of the configuration;
* the **applicant's own case**, and only that case: its status, the current
  findings with their "applicant must" line, the comments written for the
  applicant and the next step open to them.  An internal note is never in the
  bundle, and the bundle of one applicant never carries another applicant's
  record.

The basis date is the application's first submission time for a case and the
server's own time for general guidance, so the rules quoted for a case are
the rules that were in force when it was filed.

The bundle is checked against the same truth guard the model payloads use
before it is used: it may not carry an expected outcome or a decision.
"""
# REQUIRES: REF-01, REF-02, PER-04, SEC-02, SEC-03
# The bundle is built from published rule versions and the stored permit-type
# configuration, never from a draft; it carries the applicant's own case only,
# never an internal note, and it is refused when it would carry a truth.

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.applicant_portal.forms import DOCUMENT_LABELS, FIELD_LABELS, PROCESS_PILLS
from acme_city.auth.context import ActorContext
from acme_city.core.clock import utc_now
from acme_city.muse.payloads import _application_is_visible, assert_no_truth_in_payload
from acme_city.persistence.models import finance, permit
from acme_city.rules import catalog

#: The plain words of the finding types the applicant may read.
FINDING_LABELS: dict[str, str] = {
    "missing_field": "an item the application is missing",
    "missing_document": "a document the application is missing",
    "unreadable": "a document the City could not read",
    "wrong_type": "a permit type that needs confirming",
    "duplicate": "a possible duplicate of another application",
    "conflict": "a conflict a person must settle",
    "fee": "a fee a person must settle",
    "low_confidence_extraction": "a value a person must confirm",
    "judgment": "a point a person must judge",
}

#: The ways a rule may be checked, in the words an applicant reads.
OPERATOR_WORDS: dict[str, str] = {
    "max": "must not be more than",
    "min": "must not be less than",
    "required": "must be provided",
    "equals": "must be",
}

#: The plain status words of a case.
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


@dataclass(frozen=True)
class Source:
    """One passage the assistant may quote."""

    source_id: str
    kind: str
    title: str
    version: str
    text: str
    sha256: str
    citation: str = ""
    keywords: tuple[str, ...] = ()
    facts: Mapping[str, Any] = field(default_factory=dict, compare=False)
    #: Whether the passage states a **computed** fact of the City or of the
    #: applicant's own case: an evaluated rule result, the configured service
    #: target or a fee calculation.  A claim about a fee, a duration or a
    #: dimension may only be made when the answer cites such a passage.
    server_fact: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the source as a plain mapping."""
        return {
            "source_id": self.source_id,
            "kind": self.kind,
            "title": self.title,
            "version": self.version,
            "citation": self.citation,
            "text": self.text,
            "sha256": self.sha256,
            "keywords": list(self.keywords),
            "facts": dict(self.facts),
            "server_fact": self.server_fact,
        }


@dataclass(frozen=True)
class SourceBundle:
    """The passages one question may be answered from."""

    passages: tuple[Source, ...]
    bundle_hash: str
    basis_at: datetime
    permit_type_key: str = ""
    application_reference: str = ""
    #: The hash of the **content** of the bundle.
    #:
    #: The bundle hash covers the identifiers of every passage, and some of
    #: them are generated: the identifier of a finding, for instance, changes
    #: with every reset of the demonstration.  The content hash covers only
    #: what a reader of the answer actually reads — the kind, the version, the
    #: citation and the text of every passage — so the same published text
    #: always carries the same content hash.  A recorded answer is replayed
    #: only against the content hash it was written for.
    content_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        """Return the bundle as the mapping the truth guard reads."""
        return {
            "purpose": "applicant_help",
            "basis_at": self.basis_at.isoformat(),
            "permit_type_key": self.permit_type_key,
            "application_reference": self.application_reference,
            "passages": [source.to_dict() for source in self.passages],
        }

    def source(self, source_id: str) -> Source | None:
        """Return one passage by its identifier."""
        for passage in self.passages:
            if passage.source_id == source_id:
                return passage
        return None


def _hash(text: str) -> str:
    """Return the SHA-256 hash of a text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    """Return the canonical JSON text of a mapping."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _content_hash(passages: Sequence[Source]) -> str:
    """Return the hash of the readable content of a bundle.

    The hash covers what a reader of an answer reads: the kind, the version,
    the citation and the text of every passage.  It deliberately leaves out the
    identifier of a passage, because some identifiers are generated and change
    with every reset of the demonstration while the published text they
    carry does not.
    """
    material = [
        [source.kind, source.version, source.citation, source.text]
        for source in sorted(
            passages, key=lambda item: (item.kind, item.version, item.citation, item.text)
        )
    ]
    return _hash(_canonical(material))


def _field_label(field_path: str | None) -> str:
    """Return the plain label of a field."""
    if not field_path:
        return ""
    return FIELD_LABELS.get(field_path, field_path.replace("_", " ").capitalize())


def _document_label(document_type: str) -> str:
    """Return the plain label of a document type."""
    return DOCUMENT_LABELS.get(document_type, document_type.replace("_", " ").capitalize())


def _condition_text(condition: Mapping[str, Any] | None) -> str:
    """Return the plain text of the applicability condition of a rule."""
    if not condition:
        return "always"
    parts: list[str] = []
    for key in sorted(condition):
        value = condition[key]
        if isinstance(value, Mapping):
            inner = ", ".join(f"{name} = {item}" for name, item in sorted(value.items()))
            parts.append(f"{key} ({inner})")
        else:
            parts.append(f"{key} = {value}")
    return "; ".join(parts)


def _rule_source(
    row: finance.RuleVersion, type_row: permit.PermitType | None
) -> Source:
    """Return the passage of one published rule version."""
    version = catalog.version_label(row)
    operator = (row.operator or "").strip().lower()
    operator_words = OPERATOR_WORDS.get(operator, f"is checked with the operator {operator}")
    mapping = dict(row.source_mapping or {})
    unit = str(mapping.get("unit") or "").strip()
    threshold = str(row.limit_value or "").strip()
    lines = [
        f"{row.citation}: {row.title}",
        f"Published rule {row.rule_id}, version {version}.",
    ]
    if type_row is not None:
        lines.append(f"Applies to: {type_row.label} ({type_row.key}).")
    lines.append(f"Applies when: {_condition_text(row.condition)}.")
    if row.field_path:
        lines.append(f"Checks: {_field_label(row.field_path)}.")
    lines.append(f"Operator: {operator_words}.")
    if threshold:
        lines.append(f"Threshold: {threshold}{' ' + unit if unit else ''}.")
    if (row.on_violate or "").strip().lower() == "judgment":
        lines.append("When the rule is not met, a person must look at the case.")
    if row.message:
        lines.append(f"If the rule is not met: {row.message}")
    if row.condition_note:
        lines.append(f"Note: {row.condition_note}")
    text = "\n".join(lines)
    keywords = [row.rule_id.lower(), row.citation]
    if row.field_path:
        keywords.extend([row.field_path, row.field_path.replace("_", " "), _field_label(row.field_path)])
    if type_row is not None:
        keywords.extend([type_row.key, type_row.label])
    if row.condition:
        keywords.extend(str(value) for value in row.condition.values() if not isinstance(value, Mapping))
    return Source(
        source_id=f"rule.{row.rule_id}.{version}",
        kind="rule",
        title=f"{row.citation}: {row.title}",
        version=version,
        text=text,
        sha256=_hash(text),
        citation=row.citation,
        keywords=tuple(keywords),
        facts=MappingProxyType(
            {
                "rule_id": row.rule_id,
                "citation": row.citation,
                "field_path": row.field_path or "",
                "operator": operator,
                "threshold": threshold,
                "applicability": _condition_text(row.condition),
                "conditions": dict(row.condition) if row.condition else {},
                "on_violate": row.on_violate or "",
                "permit_type_key": type_row.key if type_row is not None else "",
            }
        ),
        # The passage is rendered by the server from the structured fields of
        # a published, effective rule version: its applicability, operator and
        # threshold. That makes it the fact a dimension claim may cite.  It is
        # a limit and never an exemption.
        server_fact=True,
    )


def _type_source(type_row: permit.PermitType) -> Source:
    """Return the passage of the stored configuration of one permit type."""
    category = type_row.process_category or "simple"
    pill, pill_text = PROCESS_PILLS.get(category, PROCESS_PILLS["simple"])
    fields = list(type_row.required_fields or [])
    documents = list(type_row.required_documents or [])
    lines = [
        f"{type_row.label} ({type_row.key})",
        f"Review area: {type_row.review_area or 'not routed'}.",
        f"Process: {pill}: {pill_text}",
    ]
    if type_row.discretionary:
        lines.append("A discretionary type is always held for a person or a board.")
    if type_row.description:
        lines.append(str(type_row.description))
    lines.append(
        "Required fields: "
        + ("; ".join(_field_label(item) for item in fields) if fields else "none")
        + "."
    )
    lines.append(
        "Required documents: "
        + ("; ".join(_document_label(item) for item in documents) if documents else "none")
        + "."
    )
    text = "\n".join(lines)
    keywords = [type_row.key, type_row.label, type_row.description or ""]
    keywords.extend(_field_label(item) for item in fields)
    keywords.extend(_document_label(item) for item in documents)
    return Source(
        source_id=f"permit_type.{type_row.key}",
        kind="permit_type",
        title=f"{type_row.label} ({type_row.key})",
        version=f"{type_row.key}@{type_row.version}",
        text=text,
        sha256=_hash(text),
        citation="",
        keywords=tuple(keywords),
        facts=MappingProxyType(
            {
                "permit_type_key": type_row.key,
                "review_area": type_row.review_area or "",
                "process_category": category,
                "discretionary": bool(type_row.discretionary),
                "required_fields": fields,
                "required_documents": documents,
            }
        ),
    )


def _target_source(type_row: permit.PermitType) -> Source:
    """Return the passage of the configured service target of a type."""
    days = int(type_row.service_target_days or 0)
    text = (
        f"Service target for {type_row.label} ({type_row.key}): {days} days.\n"
        "This is the fictional number of days the City aims to review a case of this "
        "type in. It is a target the City works to. It makes no promise about your "
        "application and gives no completion date."
    )
    return Source(
        source_id=f"service_target.{type_row.key}",
        kind="service_target",
        title=f"Service target for {type_row.label}",
        version=f"{type_row.key}@{type_row.version}",
        text=text,
        sha256=_hash(text),
        citation="",
        keywords=(type_row.key, type_row.label, "target", "days", "long", "take", "time"),
        facts=MappingProxyType(
            {
                "permit_type_key": type_row.key,
                "service_target_days": days,
                "review_area": type_row.review_area or "",
            }
        ),
        server_fact=True,
    )


def _config_source(
    passage_id: str,
    title: str,
    text: str,
    keywords: Sequence[str],
    *,
    kind: str,
    version: str = "config@1",
    status: str = "",
) -> Source:
    """Return the passage of one fixed configuration passage."""
    return Source(
        source_id=passage_id,
        kind=kind,
        title=title,
        version=version,
        text=text,
        sha256=_hash(text),
        citation="",
        keywords=tuple(keywords),
        facts=MappingProxyType({"status": status} if status else {}),
    )


def _fee_schedule_source(row: finance.FeeScheduleVersion) -> Source:
    """Return the passage of the published fee schedule in force.

    The schedule is the City's own published fee, versioned and effective.
    The passage names the fixed charge and the multiplier and nothing else:
    it never names an assessed amount, because an assessed amount belongs to
    one application and is computed from it.
    """
    definition = dict(row.definition or {})
    currency = row.currency or "USD"
    fixed_cents = int(definition.get("fixed_review_charge_cents") or 0)
    multiplier = str(definition.get("valuation_multiplier") or "")
    formula = str(definition.get("formula") or "")
    lines = [
        f"Published fee schedule {row.fee_schedule_id}, version {row.version_label}.",
        f"Currency: {currency}.",
    ]
    if fixed_cents:
        lines.append(f"Fixed review charge: {fixed_cents / 100:.2f} {currency}.")
    if multiplier:
        lines.append(f"Variable component: {multiplier} of the declared valuation.")
    if formula:
        lines.append(f"The schedule says: {formula}")
    lines.append(
        "The fee of an application is computed from this schedule and the declared "
        "valuation of that application. The City assesses it and tells the applicant "
        "the amount before any payment."
    )
    text = "\n".join(lines)
    return Source(
        source_id=f"fee_schedule.{row.fee_schedule_id}.{row.version_label}",
        kind="fee_schedule",
        title=f"Published fee schedule {row.fee_schedule_id} ({row.version_label})",
        version=row.version_label,
        text=text,
        sha256=_hash(text),
        citation="",
        keywords=("fee", "fees", "cost", "price", "charge", "payment", "pay", "schedule"),
        facts=MappingProxyType(
            {
                "fee_schedule_id": row.fee_schedule_id,
                "version_label": row.version_label,
                "currency": currency,
                "fixed_review_charge_cents": fixed_cents,
                "valuation_multiplier": multiplier,
            }
        ),
        server_fact=True,
    )


#: The plain words of the outcome of an evaluated rule.
_RULE_RESULT_WORDS: dict[str, str] = {
    "pass": "the rule is met",
    "condition": "the rule is met with a condition",
    "fail": "the rule is not met",
    "review": "a person at the City has to look at this rule",
}


def _case_rule_sources(
    session: Session, application: permit.Application
) -> list[Source]:
    """Return the passages of the evaluated rules of the applicant's case.

    The evaluation is the City's own computation against the published rule
    versions: the recorded value, the limit of the rule and the result.  The
    violation message of the rule appears only under the words of a rule that
    is not met, because a message states what happens when a rule is not met,
    not a fact about the applicant.
    """
    evaluation = session.execute(
        select(permit.Evaluation)
        .where(
            permit.Evaluation.application_id == application.id,
            permit.Evaluation.status == "current",
            permit.Evaluation.stale.is_(False),
        )
        .order_by(permit.Evaluation.performed_at.desc(), permit.Evaluation.id)
    ).scalars().first()
    if evaluation is None:
        return []
    reference = application.source_application_number
    sources: list[Source] = []
    for result in evaluation.results or []:
        if not isinstance(result, MappingABC):
            continue
        rule_id = str(result.get("rule_id") or "")
        if not rule_id:
            continue
        citation = str(result.get("citation") or "")
        version_label = str(result.get("version_label") or "")
        status = str(result.get("status") or "")
        unit = str(result.get("unit") or "").strip()
        observed = result.get("observed_value")
        limit = result.get("limit_value")
        lines = [
            f"The City evaluated {citation} ({version_label}) against your application.",
        ]
        if not bool(result.get("applicable", True)):
            lines.append("This rule does not apply to your application.")
        else:
            field_path = str(result.get("field_path") or "")
            if field_path:
                lines.append(f"The fact this rule checks: {_field_label(field_path)}.")
            if observed not in (None, ""):
                value = f"{observed}{' ' + unit if unit else ''}"
                lines.append(f"The recorded value is {value}.")
            if limit not in (None, ""):
                value = f"{limit}{' ' + unit if unit else ''}"
                lines.append(f"The limit of this rule is {value}.")
            lines.append(
                "The result on your application: "
                + _RULE_RESULT_WORDS.get(status, "a person at the City has to look at it")
                + "."
            )
        message = str(result.get("message") or "").strip()
        if message:
            lines.append(f"If the rule is not met: {message}")
        note = str(result.get("condition_note") or "").strip()
        if note:
            lines.append(f"Note: {note}")
        text = "\n".join(lines)
        sources.append(
            Source(
                source_id=f"case.{reference}.rule.{rule_id}",
                kind="case_rule",
                title=f"What the City evaluated: {citation}",
                version=f"evaluation@{evaluation.version}",
                text=text,
                sha256=_hash(text),
                citation=citation,
                keywords=(reference, rule_id, citation, "evaluated", "result", "limit"),
                facts=MappingProxyType(
                    {
                        "rule_id": rule_id,
                        "version_label": version_label,
                        "citation": citation,
                        "status": status,
                        "observed_value": observed,
                        "limit_value": limit,
                        "unit": unit,
                    }
                ),
                server_fact=True,
            )
        )
    return sources


def _case_fee_source(
    session: Session, application: permit.Application
) -> list[Source]:
    """Return the passage of the assessed fee of the applicant's case.

    The assessment is the City's own computation from the published fee
    schedule.  It is a fact of the applicant's own case and it is never
    another applicant's.
    """
    assessment = session.execute(
        select(finance.Assessment)
        .where(
            finance.Assessment.application_id == application.id,
            finance.Assessment.status == "current",
        )
        .order_by(finance.Assessment.id)
    ).scalars().first()
    if assessment is None:
        return []
    reference = application.source_application_number
    amount = int(assessment.assessed_total_cents or 0)
    currency = assessment.currency or "USD"
    text = (
        f"The City assessed {amount / 100:.2f} {currency} for your application.\n"
        "This amount is the assessment the City computed for this application from the "
        "published fee schedule. It records the assessment only, with no payment, and it "
        "changes when the City reassesses the application."
    )
    return [
        Source(
            source_id=f"case.{reference}.fee",
            kind="case_fee",
            title="The assessed fee of your application",
            version=f"assessment@{assessment.version}",
            text=text,
            sha256=_hash(text),
            citation="",
            keywords=(reference, "fee", "fees", "cost", "price", "assessed", "payment"),
            facts=MappingProxyType(
                {
                    "assessment_id": assessment.id,
                    "assessed_total_cents": amount,
                    "currency": currency,
                }
            ),
            server_fact=True,
        )
    ]


def applicant_next_steps(
    session: Session, actor: ActorContext, application: permit.Application | None
) -> list[str]:
    """Return the steps that are open to this applicant right now.

    The steps come from the grants the server holds for the actor, never from
    the text of an answer.
    """
    from acme_city.auth.permissions import PermissionResolver

    held = PermissionResolver(session).permissions_for(actor.actor_id)
    steps: list[str] = []
    if application is not None:
        status = application.status
        if status in ("needs_information", "revisions_requested"):
            if "application.revision.submit" in held:
                steps.append(
                    "Upload the documents the City asked for and send your answer "
                    "from your application page."
                )
        if status in ("returned", "denied") and "application.submit" in held:
            steps.append("Start a new application for the change you want to make.")
    if not steps:
        steps.append("Nothing is needed from you right now.")
    return steps


def _case_sources(
    session: Session, actor: ActorContext, application: permit.Application
) -> list[Source]:
    """Return the passages of the applicant's own case.

    Only the case the actor may see is read, and only the comments that were
    written for the applicant.  The internal message of a finding is not
    carried: the applicant reads the line that says what they must do.
    """
    from acme_city.agents.findings import current_findings
    from acme_city.permits.comments import comments_for

    sources: list[Source] = []
    reference = application.source_application_number
    status_word = STATUS_WORDS.get(application.status, application.status)
    status_text = f"Your application {reference} is in the state: {status_word}."
    sources.append(
        Source(
            source_id=f"case.{reference}.status",
            kind="case",
            title="The state of your application",
            version=f"application@{application.version}",
            text=status_text,
            sha256=_hash(status_text),
            citation="",
            keywords=(reference, status_word, "status", "state", "application"),
            facts=MappingProxyType(
                {"status": application.status, "status_word": status_word}
            ),
        )
    )
    for finding in current_findings(session, application.id):
        label = FINDING_LABELS.get(finding.finding_type, "an item a person must settle")
        must = str(finding.applicant_must or "").strip()
        body = f"Your application has {label}."
        if must:
            body = f"{body} What you must do: {must}"
        sources.append(
            Source(
                source_id=f"case.{reference}.finding.{finding.id}",
                kind="case",
                title="What the City recorded about your application",
                version=f"finding@{finding.version}",
                text=body,
                sha256=_hash(body),
                citation=finding.rule or "",
                keywords=(reference, finding.finding_type, label, "must", "finding"),
                facts=MappingProxyType(
                    {
                        "finding_type": finding.finding_type,
                        "applicant_must": must,
                        "severity": finding.severity,
                    }
                ),
            )
        )
    for comment in comments_for(session, application.id, actor):
        if comment.visibility != "applicant":
            continue
        body = f"A message from the City: {comment.body}"
        sources.append(
            Source(
                source_id=f"case.{reference}.comment.{comment.id}",
                kind="case",
                title="A message from the City",
                version=f"comment@{comment.version}",
                text=body,
                sha256=_hash(body),
                citation="",
                keywords=(reference, "message", "city", "comment"),
                facts=MappingProxyType({"comment_id": comment.id}),
            )
        )
    steps = applicant_next_steps(session, actor, application)
    step_text = "The next step open to you: " + " ".join(steps)
    sources.append(
        Source(
            source_id=f"case.{reference}.next_step",
            kind="case",
            title="What you can do now",
            version=f"application@{application.version}",
            text=step_text,
            sha256=_hash(step_text),
            citation="",
            keywords=(reference, "next", "step", "action", "now"),
            facts=MappingProxyType({"next_steps": list(steps)}),
        )
    )
    return sources


def build_bundle(
    session: Session,
    actor: ActorContext,
    *,
    config: Any,
    permit_type_key: str = "",
    application_id: str = "",
    now: datetime | None = None,
) -> SourceBundle:
    """Return the source bundle of one question.

    Args:
        session: The open session.
        actor: The acting applicant.
        config: The applicant-help configuration.
        permit_type_key: The permit type the applicant is looking at, when the
            portal knows one.
        application_id: The application the applicant is asking about, when
            the portal knows one.
        now: The server time, used as the basis date of general guidance.

    Returns:
        The bundle of passages the answer may be drawn from.

    Raises:
        PermissionDeniedError: when the actor may not see the application the
            question is about.
    """
    moment = now or utc_now()
    passages: list[Source] = []
    application: permit.Application | None = None
    reference = ""
    basis_at = moment
    case_type_key = ""

    if application_id:
        application = session.get(permit.Application, application_id)
        if application is None:
            from acme_city.core.errors import NotFoundError

            raise NotFoundError("that application is not available to you")
        if not _application_is_visible(actor, application):
            from acme_city.core.errors import PermissionDeniedError

            raise PermissionDeniedError(
                "the application is not available to this applicant",
                actor_id=actor.actor_id,
                action="applicant.help.ask",
                domain_id="permits",
            )
        reference = application.source_application_number
        type_row = session.get(permit.PermitType, application.permit_type_id)
        # The rules of the case are the rules that were in force when the
        # applicant filed it.  The rules of every other type are the ones in
        # force now: they are general guidance.
        basis_at = (
            application.initial_submitted_at or application.revision_submitted_at or moment
        )
        case_type_key = type_row.key if type_row is not None else ""
        permit_type_key = case_type_key or permit_type_key

    # The City's published rules are public, so the bundle holds the rules of
    # every active permit type.  The type the applicant is looking at is the
    # one the case, the form or the question is about.
    type_rows = list(
        session.execute(
            select(permit.PermitType)
            .where(permit.PermitType.active.is_(True))
            .order_by(permit.PermitType.key)
        ).scalars()
    )

    for type_row in type_rows:
        passages.append(_type_source(type_row))
        passages.append(_target_source(type_row))
        type_basis = basis_at if type_row.key == case_type_key else moment
        for row in catalog.select_rule_versions(session, type_row.id, type_basis):
            passages.append(_rule_source(row, type_row))

    for passage in config.lifecycle_passages:
        passages.append(
            _config_source(
                passage.source_id,
                passage.title,
                passage.text,
                passage.keywords,
                kind="lifecycle",
                status=passage.status,
            )
        )
    for passage in config.steps_passages:
        passages.append(
            _config_source(
                passage.source_id,
                passage.title,
                passage.text,
                passage.keywords,
                kind="steps",
            )
        )

    # The published fee schedule in force at the basis date: the City's own
    # fee, versioned and effective.  It is the fact a fee answer may cite.
    schedule = catalog.select_fee_schedule(session, basis_at)
    if schedule is not None:
        passages.append(_fee_schedule_source(schedule))

    if application is not None:
        passages.extend(_case_sources(session, actor, application))
        passages.extend(_case_rule_sources(session, application))
        passages.extend(_case_fee_source(session, application))

    ordered = tuple(sorted(passages, key=lambda item: item.source_id))
    bundle = SourceBundle(
        passages=ordered,
        bundle_hash=_hash(_canonical([source.to_dict() for source in ordered])),
        basis_at=basis_at,
        permit_type_key=permit_type_key,
        application_reference=reference,
        content_hash=_content_hash(ordered),
    )
    # The bundle carries no truth: it holds published text and the
    # applicant's own case, never an expected outcome.
    assert_no_truth_in_payload(bundle.to_payload())
    return bundle


__all__ = [
    "FINDING_LABELS",
    "OPERATOR_WORDS",
    "STATUS_WORDS",
    "Source",
    "SourceBundle",
    "applicant_next_steps",
    "build_bundle",
]

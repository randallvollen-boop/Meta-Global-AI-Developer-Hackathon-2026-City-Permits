"""Command and view models for the rule and fee catalogue.

The catalogue is the single source of truth for a rule version: the same
selected version supplies the retrieval answer, the deterministic execution and
the citation that is displayed.  Nothing here decides anything; a decision
belongs to an authorized reviewer.
"""
# REQUIRES: REF-01, REF-02, PER-02, PER-06
# One approved catalogue supplies retrieval, execution, explanations and
# citations, and a rule version carries its applicability, parameters, dates
# and approval state.

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: The lifecycle of a rule or fee-schedule version.
RULE_STATUSES: tuple[str, ...] = ("draft", "in_review", "approved", "published", "retired")

#: The outcome vocabulary of one evaluated rule.
RULE_RESULT_STATUSES: tuple[str, ...] = ("pass", "condition", "fail", "review")

#: The kinds of catalogue entry.
RULE_KINDS: tuple[str, ...] = ("executable", "fee_schedule")

#: The operators an executable rule may declare.
RULE_OPERATORS: tuple[str, ...] = ("min", "max", "equals")


class RuleModel(BaseModel):
    """A model that ignores unknown request fields.

    A client-supplied role, actor or permission field is ignored rather than
    honoured: the server resolves the actor and the scope itself.
    """

    model_config = ConfigDict(extra="ignore")


class RuleVersionView(RuleModel):
    """One stored rule version."""

    rule_id: str
    version_label: str
    row_id: str
    version: int = 1
    permit_type_key: str | None = None
    kind: str = "executable"
    title: str
    citation: str
    field_path: str | None = None
    operator: str | None = None
    limit_value: str | None = None
    on_violate: str | None = None
    condition: dict[str, Any] | None = None
    message: str | None = None
    condition_note: str | None = None
    effective_from: datetime
    effective_to: datetime | None = None
    status: str = "draft"
    author_actor_id: str | None = None
    approver_actor_id: str | None = None
    source_mapping: dict[str, Any] | None = None
    precedence: str | None = None


class RuleSetView(RuleVersionView):
    """The published view of one catalogue version.

    ``publish`` returns this view so that the caller sees the version that
    became authoritative, with the citation and effective dates it carries.
    """


class FeeScheduleView(RuleModel):
    """One stored fee schedule version."""

    row_id: str
    fee_schedule_id: str
    version_label: str
    version: int = 1
    effective_from: datetime
    effective_to: datetime | None = None
    currency: str = "USD"
    definition: dict[str, Any] | None = None
    status: str = "draft"
    author_actor_id: str | None = None
    approver_actor_id: str | None = None
    source_mapping: dict[str, Any] | None = None


class RuleSetVersion(RuleModel):
    """The versions selected for one retrieval, execution or citation.

    The basis date is the recorded reason the selection was made, so an
    evaluation, an assessment and an explanation can all name the same
    versions.
    """

    rule_set_id: str
    kind: str = "executable"
    permit_type_key: str | None = None
    basis_at: datetime
    basis_label: str = ""
    rules: list[RuleVersionView] = Field(default_factory=list)
    fee_schedule: FeeScheduleView | None = None
    citations: list[str] = Field(default_factory=list)

    def rule_by_id(self, rule_id: str) -> RuleVersionView | None:
        """Return the selected version of ``rule_id``, if the set contains one."""
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    def version_labels(self) -> dict[str, str]:
        """Return the selected version label of every rule in the set."""
        return {rule.rule_id: rule.version_label for rule in self.rules}


class RuleResult(RuleModel):
    """The outcome of one rule against one set of inputs.

    ``status`` is one of ``pass``, ``condition``, ``fail`` or ``review``.  A
    rule whose applicability cannot be decided is ``review``; it is never an
    implicit pass.
    """

    rule_id: str
    version_label: str
    citation: str
    status: str
    applicable: bool = True
    field_path: str | None = None
    observed_value: str | None = None
    limit_value: str | None = None
    operator: str | None = None
    message: str | None = None
    condition_note: str | None = None
    reason: str | None = None
    detail: str | None = None


class DraftRuleCommand(RuleModel):
    """Create a new draft rule version."""

    rule_id: str
    permit_type_key: str
    title: str
    citation: str
    field_path: str | None = None
    operator: str | None = None
    limit_value: str | None = None
    on_violate: str | None = None
    condition: dict[str, Any] | None = None
    message: str | None = None
    condition_note: str | None = None
    effective_from: datetime
    reason: str = ""


class RuleLifecycleCommand(RuleModel):
    """Move one rule version through the catalogue lifecycle."""

    rule_version_id: str
    expected_version: int
    reason: str = ""


class PublishRuleCommand(RuleLifecycleCommand):
    """Publish one approved rule version.

    ``precedence`` names the explicit precedence policy that resolves an
    otherwise overlapping published version.  Without it, an overlap is
    refused.
    """

    precedence: str | None = None


class RetireRuleCommand(RuleLifecycleCommand):
    """Retire one published rule version."""

    effective_to: datetime | None = None


class DraftFeeScheduleCommand(RuleModel):
    """Create a new draft fee schedule version."""

    fee_schedule_id: str
    version_label: str
    effective_from: datetime
    currency: str = "USD"
    definition: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class FeeScheduleLifecycleCommand(RuleModel):
    """Move one fee schedule version through the catalogue lifecycle."""

    fee_schedule_version_id: str
    expected_version: int
    reason: str = ""
    precedence: str | None = None
    effective_to: datetime | None = None


__all__ = [
    "RULE_KINDS",
    "RULE_OPERATORS",
    "RULE_RESULT_STATUSES",
    "RULE_STATUSES",
    "DraftFeeScheduleCommand",
    "DraftRuleCommand",
    "FeeScheduleLifecycleCommand",
    "FeeScheduleView",
    "PublishRuleCommand",
    "RetireRuleCommand",
    "RuleLifecycleCommand",
    "RuleModel",
    "RuleResult",
    "RuleSetVersion",
    "RuleSetView",
    "RuleVersionView",
]

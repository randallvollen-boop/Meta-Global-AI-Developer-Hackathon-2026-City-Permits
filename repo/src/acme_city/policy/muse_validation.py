"""The claim-by-claim validation of what the what-if agent writes.

The agent explains figures the permit engine counted and proposes changes for
a person to review.  The validation stands between a model output and the
person who reads it, and it refuses the **whole** response when any part of it
fails: a sentence is never dropped to make a response acceptable.

For a briefing or an explanation the rules are:

* the output must match the strict policy-brief schema, and carry the
  sections the purpose needs;
* every sentence that states a figure must cite the typed fact it rests on.
  A claim repeats the fact's value, unit, direction, population and the
  identities of the baseline and the scenario, and the server compares each
  with the fact it holds;
* every figure of a sentence must equal one of its claims or one of its rule
  sources, so a number the engine did not count is refused;
* the direction of a sentence must match the direction of its facts, so
  "12 fewer" can never be written for a +12;
* an ACME Code section, a rule id or a threshold may only be named through a
  versioned rule source of the run (baseline or scenario) and must match it;
* no sentence may claim staff time, throughput or revenue, may use the word
  "revenue", may say that no permit is required, may recommend enacting the
  change, may promise an outcome or give legal advice;
* the briefing of a synthetic population says that it is synthetic.

For a proposal the strict schema carries typed changes only.  Each change is
rebuilt into a change request, read by ``parse_change`` and applied on its own
to a copy of the baseline by ``apply_scenario``; a kind the release does not
support is refused by name.

A failed validation writes nothing.  The reader receives the deterministic
briefing instead.
"""
# REQUIRES: AI-02, AI-04, PER-04, SEC-03
# A what-if briefing, explanation or proposal is validated claim by claim against the
# typed facts and the versioned rules of the run before anyone sees it.

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from pydantic import ValidationError as PydanticValidationError

from acme_city.muse.schemas import PolicyBriefOutput, PolicyProposeOutput
from acme_city.muse.validation import ValidationIssue, ValidationOutcome
from acme_city.policy import changes as change_module
from acme_city.policy.briefing import Fact
from acme_city.policy.config import PolicyConfig

#: The sections of a briefing, in reading order.
SECTION_KEYS: Final = ("summary", "key_effects", "risks", "protected", "question")

#: The sections each purpose must carry.
REQUIRED_SECTIONS: Final = {
    "brief": ("summary", "key_effects", "risks", "protected"),
    "explain": ("summary", "key_effects"),
}

#: The reasons the agent may give when it cannot write a briefing.
BRIEF_REFUSAL_REASONS: Final = ("no_facts", "needs_a_person")

#: The reasons the agent may give when it cannot propose a what-if.
PROPOSE_REFUSAL_REASONS: Final = (
    "unsupported_change",
    "not_a_policy_question",
    "needs_a_person",
)

#: The most changes one proposal may hold.
MAX_PROPOSED_CHANGES: Final = 5

#: The tolerance of the comparison of two figures.
FIGURE_TOLERANCE: Final = 0.005

_FIGURE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_SECTION_NUMBER = re.compile(r"§\s*(\d+(?:[-–]\d+)*)")
_RULE_ID = re.compile(r"\b[A-Z]{1,4}-\d{1,3}\b")
_CODE_WORDS = re.compile(r"\bACME Code\b", re.IGNORECASE)
_SENTENCE_NUMBER_WORDS: Final = {
    "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0, "six": 6.0, "seven": 7.0,
    "eight": 8.0, "nine": 9.0, "ten": 10.0, "eleven": 11.0, "twelve": 12.0,
    "thirteen": 13.0, "fourteen": 14.0, "fifteen": 15.0, "sixteen": 16.0,
    "seventeen": 17.0, "eighteen": 18.0, "nineteen": 19.0, "twenty": 20.0,
    "hundred": 100.0, "thousand": 1000.0, "dozen": 12.0,
}
_NUMBER_WORD = re.compile(r"\b(" + "|".join(_SENTENCE_NUMBER_WORDS) + r")\b", re.IGNORECASE)

# --------------------------------------------------------------------- claims

#: Claims the agent may never make.  Each pattern names its family.
_FORBIDDEN: Final = tuple(
    (family, re.compile(pattern, re.IGNORECASE))
    for family, pattern in (
        ("revenue", r"\brevenues?\b"),
        ("revenue", r"\b(?:income|profit|money (?:saved|earned)|savings?|cost[- ]saving|(?:would|will|could) collect)\b"),
        ("staff_time", r"\bstaff[- ]?(?:time|hours?|days?|workload|capacity|costs?|savings?)\b"),
        ("staff_time", r"\b(?:time[- ]sav\w*|saves? (?:staff )?time|person[- ]?hours?|man[- ]?hours?)\b"),
        ("staff_time", r"\b(?:processing|review|turnaround|wait(?:ing)?) times?\b"),
        ("throughput", r"\b(?:throughput|faster|quicker|speeds? up|sped up|speed-up|workload)\b"),
        ("no_permit", r"\bno permit(?:s)? (?:is|are|would be|will be) (?:needed|required|necessary)\b"),
        ("no_permit", r"\bno permit(?:s)? (?:required|needed|necessary)\b"),
        ("no_permit", r"\bpermit(?:s)? (?:is|are|would be|will be) (?:not|no longer) (?:needed|required|necessary)\b"),
        ("no_permit", r"\b(?:no longer|not) (?:need|needs|require|requires) a permit\b"),
        ("no_permit", r"\bwithout (?:a|any) permit\b"),
        ("no_permit", r"\b(?:is|are) exempt\b|\bexempt from\b|\bexemption\b"),
        (
            "enact",
            r"\b(?:we|i|council|legislators?|the city|elected officials)\s+(?:should|must|ought to)\b",
        ),
        ("enact", r"\bshould (?:be )?(?:adopt|enact|approv|pass|implement|proceed)\w*"),
        ("enact", r"\b(?:we|i|muse)\s+(?:recommend|urge|advise|suggest)\b"),
        ("enact", r"\brecommend(?:s|ed)?\s+(?:that|adopting|enacting|approving|passing|to (?:adopt|enact|approve|pass))\b"),
        ("enact", r"\b(?:urge|urges|urged|advise|advises|advised)\b"),
        ("enact", r"\bworth (?:adopting|enacting|passing)\b|\bgo ahead with\b|\bvote (?:for|yes)\b"),
        ("outcome", r"\bwill be (?:approved|denied|issued|granted|rejected|refused)\b"),
        ("outcome", r"\b(?:is|are) (?:automatically )?approved\b|\bguarantee(?:d|s)?\b|\bwill succeed\b"),
        ("risk_free", r"\b(?:no|zero|without any) risks?\b|\brisk[- ]free\b|\bcompletely safe\b"),
        ("legal", r"\blegal advice\b|\b(?:attorney|lawyer)\b|\blegally (?:entitled|required|liable)\b|\bliab(?:le|ility)\b"),
    )
)

_DECREASE: Final = re.compile(
    r"\b(?:fewer|decreas\w*|declin\w*|drop(?:s|ped|ping)?|reduc\w*|fall(?:s|ing)?|fell|lower (?:number|count|total))\b",
    re.IGNORECASE,
)
_INCREASE: Final = re.compile(
    r"\b(?:increas\w*|ris(?:e|es|ing)|rose|risen|grow(?:s|ing)?|grew|additional|higher|"
    r"more (?:cases?|holds?|applications?|permits?|than))\b",
    re.IGNORECASE,
)
_UNCHANGED: Final = re.compile(
    r"\b(?:unchanged|no change|same as|stay(?:s|ed)? the same|remain(?:s|ed)? the same)\b",
    re.IGNORECASE,
)

#: What the agent may say of a result is cited, not recommended.
_DIRECTION_CUES: Final = (
    ("decrease", _DECREASE),
    ("increase", _INCREASE),
    ("unchanged", _UNCHANGED),
)


def forbidden_family(text: str) -> str | None:
    """Return the family of the first forbidden claim a text carries."""
    for family, pattern in _FORBIDDEN:
        if pattern.search(text) is not None:
            return family
    return None


def figures_of(text: str) -> tuple[float, ...]:
    """Return the figures a text names, digits and spelled numbers alike."""
    found: list[float] = []
    for token in _FIGURE.findall(str(text or "")):
        try:
            found.append(float(token.replace(",", "")))
        except ValueError:  # pragma: no cover - the pattern only matches numbers
            continue
    for word in _NUMBER_WORD.findall(str(text or "")):
        found.append(_SENTENCE_NUMBER_WORDS[word.lower()])
    return tuple(found)


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= FIGURE_TOLERANCE


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _issue(code: str, message: str, path: str) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, path=path)


def direction_cues(text: str) -> frozenset[str]:
    """Return the directions a sentence puts into words."""
    return frozenset(name for name, pattern in _DIRECTION_CUES if pattern.search(text))


# ---------------------------------------------------------------- rule sources


@dataclass(frozen=True)
class RuleSource:
    """One versioned rule, as the baseline or the scenario holds it."""

    configuration: str
    rule_id: str
    version: str
    citation: str
    limit_value: str
    unit: str
    operator: str
    title: str


def rule_sources_of(
    baseline_config: Mapping[str, Any], proposed_config: Mapping[str, Any]
) -> dict[tuple[str, str, str], RuleSource]:
    """Return every versioned rule of a run, keyed by configuration, id and version.

    The sources come from the frozen configurations a run stores, so a
    threshold is always the one the engine scored.
    """
    sources: dict[tuple[str, str, str], RuleSource] = {}
    for name, config in (("baseline", baseline_config), ("scenario", proposed_config)):
        for rule in config.get("rules", ()):
            key = (name, str(rule.get("rule_id") or ""), str(rule.get("version_label") or ""))
            sources[key] = RuleSource(
                configuration=name,
                rule_id=key[1],
                version=key[2],
                citation=str(rule.get("citation") or ""),
                limit_value=str(rule.get("limit_value") or ""),
                unit=str(rule.get("unit") or ""),
                operator=str(rule.get("operator") or ""),
                title=str(rule.get("title") or ""),
            )
    return sources


def _section_numbers(text: str) -> set[str]:
    return {m.replace("–", "-") for m in _SECTION_NUMBER.findall(text)}


def _strip_rule_numbers(text: str) -> str:
    """Return the text without ACME Code section numbers and rule ids."""
    stripped = _SECTION_NUMBER.sub(" ", text)
    stripped = _RULE_ID.sub(" ", stripped)
    return _CODE_WORDS.sub(" ", stripped)


# ----------------------------------------------------------------------- brief


@dataclass(frozen=True)
class BriefCheck:
    """The outcome of the validation of a briefing, with what was cited."""

    outcome: ValidationOutcome
    declined: bool = False
    reason: str = ""
    cited_facts: tuple[str, ...] = ()
    cited_rules: tuple[str, ...] = ()


def validate_brief(
    data: Mapping[str, Any],
    *,
    facts: Sequence[Fact],
    sources: Mapping[tuple[str, str, str], RuleSource],
    purpose: str = "brief",
    synthetic: bool = False,
) -> BriefCheck:
    """Return the validation of one briefing or explanation.

    Args:
        data: The parsed output of the run.
        facts: The typed facts of the run, the only figures the text may rest on.
        sources: The versioned rule sources of the run.
        purpose: ``brief`` or ``explain``.
        synthetic: Whether the population is synthetic.

    Returns:
        The check.  A failed outcome carries every issue found, and the whole
        response is refused: a sentence is never dropped.
    """
    try:
        model = PolicyBriefOutput.model_validate(dict(data))
    except PydanticValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ()))
        return BriefCheck(
            ValidationOutcome(
                state="failed",
                issues=(
                    _issue(
                        "schema_invalid",
                        "the output does not match the policy-brief schema: "
                        f"{first.get('msg', 'invalid')}",
                        location,
                    ),
                ),
            )
        )
    checked = ("schema", "sections", "claims", "figures", "direction", "rules", "forbidden")
    issues: list[ValidationIssue] = []
    by_id = {fact.fact_id: fact for fact in facts}

    if model.cannot_brief:
        if model.sections:
            issues.append(_issue("answer_with_refusal", "the output refuses and carries sections", "sections"))
        if model.reason not in BRIEF_REFUSAL_REASONS:
            issues.append(_issue("invalid_refusal_reason", "the refusal reason is not one the City allows", "reason"))
        if issues:
            return BriefCheck(ValidationOutcome("failed", tuple(issues), checked))
        return BriefCheck(ValidationOutcome("passed", (), checked), declined=True, reason=model.reason)
    if model.reason:
        issues.append(_issue("unexpected_refusal_reason", "the output carries a reason but does not refuse", "reason"))

    if figures_of(_strip_rule_numbers(model.title)):
        issues.append(_issue("title_figure", "the title states no figure; the sentences cite them", "title"))
    family = forbidden_family(model.title)
    if family:
        issues.append(_issue("forbidden_claim", f"the title carries a {family.replace('_', ' ')} claim", "title"))

    seen = [section.section for section in model.sections]
    for key in seen:
        if key not in SECTION_KEYS:
            issues.append(_issue("unknown_section", "the output names a section the briefing does not have", "sections"))
    for key in REQUIRED_SECTIONS.get(purpose, REQUIRED_SECTIONS["brief"]):
        carrying = [s for s in model.sections if s.section == key and s.sentences]
        if not carrying:
            issues.append(_issue("missing_section", f"the briefing has no {key.replace('_', ' ')} section", "sections"))

    cited_facts: list[str] = []
    cited_rules: list[str] = []
    synthetic_said = False
    for s_index, section in enumerate(model.sections):
        base = f"sections.{s_index}"
        if section.question:
            if section.section != "question":
                issues.append(_issue("question_outside_section", "only a question section carries a question", f"{base}.question"))
            if figures_of(_strip_rule_numbers(section.question)):
                issues.append(_issue("question_figure", "a question states no figure; its answer cites them", f"{base}.question"))
            qfamily = forbidden_family(section.question)
            if qfamily:
                issues.append(_issue("forbidden_claim", f"the question carries a {qfamily.replace('_', ' ')} claim", f"{base}.question"))
        elif section.section == "question":
            issues.append(_issue("question_missing", "a question section names its question", f"{base}.question"))
        for t_index, sentence in enumerate(section.sentences):
            path = f"{base}.sentences.{t_index}"
            text = sentence.text.strip()
            if not text:
                issues.append(_issue("empty_sentence", "a sentence is empty", path))
                continue
            if synthetic and section.section == "summary" and "synthetic" in text.lower():
                synthetic_said = True

            family = forbidden_family(text)
            if family:
                issues.append(
                    _issue("forbidden_claim", f"the sentence carries a {family.replace('_', ' ')} claim", path)
                )

            allowed: list[float] = []
            # Claims: each repeats the typed fact it rests on.
            claim_directions: set[str] = set()
            for c_index, claim in enumerate(sentence.claims):
                cpath = f"{path}.claims.{c_index}"
                fact = by_id.get(claim.fact_id)
                if fact is None:
                    issues.append(_issue("unknown_fact", "the claim cites a fact the run does not hold", f"{cpath}.fact_id"))
                    continue
                mismatched = _claim_mismatch(claim, fact)
                if mismatched:
                    issues.append(
                        _issue(
                            "claim_mismatch",
                            f"the claim does not match its typed fact: {mismatched}",
                            f"{cpath}.{mismatched}",
                        )
                    )
                    continue
                cited_facts.append(fact.fact_id)
                claim_directions.add(fact.direction)
                number = _number(fact.value)
                if number is not None:
                    allowed.append(number)
                    if number != 0 and not any(_same(number, f) for f in figures_of(_strip_rule_numbers(text))):
                        issues.append(
                            _issue(
                                "claim_not_in_sentence",
                                "the claim cites a figure the sentence does not state",
                                cpath,
                            )
                        )

            # Rule sources: a section, a rule id or a threshold is named only through one.
            ref_sections: set[str] = set()
            ref_ids: set[str] = set()
            for r_index, ref in enumerate(sentence.rule_refs):
                rpath = f"{path}.rule_refs.{r_index}"
                source = sources.get((ref.configuration, ref.rule_id, ref.version))
                if source is None:
                    issues.append(
                        _issue("unknown_rule", "the rule source is not a versioned rule of this run", rpath)
                    )
                    continue
                wrong = next(
                    (
                        name
                        for name, given, held in (
                            ("citation", ref.citation, source.citation),
                            ("limit_value", ref.limit_value, source.limit_value),
                            ("unit", ref.unit, source.unit),
                        )
                        if given != held
                    ),
                    "",
                )
                if wrong:
                    issues.append(
                        _issue(
                            "rule_source_mismatch",
                            f"the rule source does not match the versioned rule: {wrong}",
                            f"{rpath}.{wrong}",
                        )
                    )
                    continue
                cited_rules.append(f"{source.configuration}:{source.rule_id}@{source.version}")
                ref_ids.add(source.rule_id)
                ref_sections |= _section_numbers(source.citation)
                limit = _number(source.limit_value)
                if limit is not None:
                    allowed.append(limit)
            for number in _section_numbers(text):
                if number not in ref_sections:
                    issues.append(
                        _issue(
                            "unknown_rule_number",
                            "the sentence names an ACME Code section no versioned rule source of the sentence carries",
                            path,
                        )
                    )
            for rule_id in set(_RULE_ID.findall(text)):
                if rule_id not in ref_ids:
                    issues.append(
                        _issue("unknown_rule_number", "the sentence names a rule no rule source of the sentence carries", path)
                    )

            # Figures: every figure is a claim's value or a rule source's limit.
            stated = figures_of(_strip_rule_numbers(text))
            if stated and not sentence.claims and not sentence.rule_refs:
                issues.append(_issue("uncited_figure", "the sentence states a figure and cites no typed fact", path))
            for value in stated:
                if not any(_same(value, known) for known in allowed):
                    issues.append(
                        _issue("figure_not_supported", "the sentence states a figure no cited fact or rule carries", path)
                    )
                    break

            # Direction: the words of the sentence must agree with the facts it cites.
            cues = direction_cues(text)
            for cue in cues:
                if cue not in claim_directions:
                    issues.append(
                        _issue(
                            "wrong_direction",
                            f"the sentence says {cue} and no fact it cites has that direction",
                            path,
                        )
                    )
            if claim_directions & {"increase", "decrease"} and cues:
                opposite = {"increase": "decrease", "decrease": "increase"}
                for direction in claim_directions & {"increase", "decrease"}:
                    if opposite[direction] in cues and direction not in cues:
                        issues.append(
                            _issue(
                                "wrong_direction",
                                f"the sentence says {opposite[direction]} for a fact that is an {direction}",
                                path,
                            )
                        )

    if synthetic and not synthetic_said:
        issues.append(
            _issue("synthetic_not_labelled", "the summary does not say that the cases are synthetic", "sections")
        )
    if issues:
        return BriefCheck(ValidationOutcome("failed", tuple(issues), checked))
    return BriefCheck(
        ValidationOutcome("passed", (), checked),
        cited_facts=tuple(dict.fromkeys(cited_facts)),
        cited_rules=tuple(dict.fromkeys(cited_rules)),
    )


def _claim_mismatch(claim: Any, fact: Fact) -> str:
    """Return the first field of a claim that differs from its fact, or ''."""
    held = _number(fact.value)
    given = _number(claim.value)
    if held is not None and given is not None:
        if not _same(held, given):
            return "value"
    elif str(claim.value).strip() != str(fact.value).strip():
        return "value"
    for name, given_text, held_text in (
        ("unit", claim.unit, fact.unit),
        ("direction", claim.direction, fact.direction),
        ("population", claim.population, fact.population),
        ("baseline_id", claim.baseline_id, fact.baseline_id),
        ("scenario_id", claim.scenario_id, fact.scenario_id),
    ):
        if str(given_text) != str(held_text):
            return name
    return ""


# -------------------------------------------------------------------- proposal

#: The fields a change of each kind may carry; every other field must be empty.
_KIND_FIELDS: Final = {
    "rule_threshold": ("rule_id", "limit_value", "operator"),
    "rule_retirement": ("rule_id", "condition"),
    "requirement": ("permit_type_key", "item_kind", "item", "action"),
    "process_category": ("permit_type_key", "process_category"),
    "discretionary": ("permit_type_key", "discretionary"),
    "service_target": ("permit_type_key", "service_target_days"),
    "fee": ("fee_schedule_id", "fixed_review_charge_cents", "valuation_multiplier"),
}
_TEXT_FIELDS: Final = (
    "rule_id", "limit_value", "operator", "condition", "permit_type_key", "item_kind", "item",
    "action", "process_category", "discretionary", "fee_schedule_id", "valuation_multiplier",
)


@dataclass(frozen=True)
class ProposalItem:
    """One proposed change and the outcome of its own validation."""

    index: int
    kind: str
    request: dict[str, Any] | None
    description: str
    rationale: str
    ok: bool
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProposalCheck:
    """The outcome of the validation of a proposal."""

    outcome: ValidationOutcome
    name: str = ""
    items: tuple[ProposalItem, ...] = ()
    declined: bool = False
    reason: str = ""
    changes: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def build_request(item: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Rebuild one flat proposed change into a change request.

    Returns the request and the problems found.  An unused field must be empty
    (or -1 for a number), so a stray value is refused rather than ignored.
    """
    kind = str(item.kind or "").strip().lower()
    problems: list[str] = []
    allowed_fields = _KIND_FIELDS.get(kind)
    if allowed_fields is None:
        # Names the release does not support still go to parse_change, which refuses them by name.
        allowed_fields = tuple(name for name in _TEXT_FIELDS if str(getattr(item, name)).strip())
    for name in _TEXT_FIELDS:
        if name not in allowed_fields and str(getattr(item, name)).strip():
            problems.append(f"the field {name} is not used by a {kind or 'blank'} change")
    for name in ("service_target_days", "fixed_review_charge_cents"):
        if name not in allowed_fields and getattr(item, name) != -1:
            problems.append(f"the field {name} is not used by a {kind or 'blank'} change")
    request: dict[str, Any] = {"kind": kind}
    for name in allowed_fields:
        value = getattr(item, name)
        if name == "discretionary":
            text = str(value).strip().lower()
            if text not in ("true", "false"):
                problems.append("discretionary must be true or false")
            else:
                request[name] = text == "true"
        elif name in ("service_target_days", "fixed_review_charge_cents"):
            if value != -1:
                request[name] = int(value)
        else:
            text = str(value).strip()
            if text:
                request["when" if name == "condition" else name] = text
    return (None if problems else request), problems


def validate_proposal(
    data: Mapping[str, Any], *, baseline: PolicyConfig, describe: Any
) -> ProposalCheck:
    """Return the validation of one proposed what-if.

    Every proposed change is read by ``parse_change`` and applied on its own
    to a copy of the baseline by ``apply_scenario``; the whole response is
    refused when any change fails.  ``describe`` turns a request into plain
    words (``policy.views.describe_change`` bound to the baseline).
    """
    try:
        model = PolicyProposeOutput.model_validate(dict(data))
    except PydanticValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ()))
        return ProposalCheck(
            ValidationOutcome(
                state="failed",
                issues=(
                    _issue(
                        "schema_invalid",
                        f"the output does not match the policy-propose schema: {first.get('msg', 'invalid')}",
                        location,
                    ),
                ),
            )
        )
    checked = ("schema", "kinds", "changes", "rationale", "combination")
    issues: list[ValidationIssue] = []
    if model.cannot_propose:
        if model.proposals:
            issues.append(_issue("answer_with_refusal", "the output refuses and carries changes", "proposals"))
        if model.reason not in PROPOSE_REFUSAL_REASONS:
            issues.append(_issue("invalid_refusal_reason", "the refusal reason is not one the City allows", "reason"))
        if issues:
            return ProposalCheck(ValidationOutcome("failed", tuple(issues), checked))
        return ProposalCheck(ValidationOutcome("passed", (), checked), declined=True, reason=model.reason)
    if model.reason:
        issues.append(_issue("unexpected_refusal_reason", "the output carries a reason but does not refuse", "reason"))
    if not model.proposals:
        issues.append(_issue("no_changes", "the output proposes no change and does not refuse", "proposals"))
    if len(model.proposals) > MAX_PROPOSED_CHANGES:
        issues.append(
            _issue("too_many_changes", f"a proposal holds at most {MAX_PROPOSED_CHANGES} changes", "proposals")
        )
    name = model.name.strip()
    if not name:
        issues.append(_issue("name_missing", "the proposed what-if has no name", "name"))
    elif forbidden_family(name):
        issues.append(_issue("forbidden_claim", "the name carries a claim the agent may not make", "name"))

    rules_by_id = {rule.rule_id: rule for rule in baseline.rules}
    items: list[ProposalItem] = []
    requests: list[dict[str, Any]] = []
    for index, proposed in enumerate(model.proposals[:MAX_PROPOSED_CHANGES]):
        path = f"proposals.{index}"
        found: list[str] = []
        request, problems = build_request(proposed)
        found.extend(problems)
        parsed = None
        if request is not None:
            try:
                parsed = change_module.parse_change(request)
            except change_module.ChangeError as error:
                found.append(error.message)
            else:
                if isinstance(parsed, change_module.UnsupportedChange):
                    found.append(change_module._UNSUPPORTED_MESSAGES[parsed.code])  # noqa: SLF001
                    parsed = None
        if parsed is not None:
            try:
                single = change_module.apply_scenario(
                    baseline, change_module.Scenario("proposal check", (parsed,))
                )
            except Exception as error:  # noqa: BLE001 - an unreadable change is a refusal, not a crash
                found.append(f"the change could not be applied: {error}")
            else:
                if single.config is None:
                    found.extend(i.message for i in single.issues)
                    found.extend(u.message for u in single.unsupported)

        rationale = proposed.rationale.strip()
        if not rationale:
            found.append("the change carries no rationale")
        else:
            family = forbidden_family(rationale)
            if family:
                found.append(f"the rationale carries a {family.replace('_', ' ')} claim")
            rule = rules_by_id.get(str(request.get("rule_id") or "")) if request else None
            allowed = [
                number
                for number in (
                    _number(request.get(key)) if request else None
                    for key in ("limit_value", "service_target_days", "fixed_review_charge_cents",
                                "valuation_multiplier")
                )
                if number is not None
            ]
            if rule is not None and rule.limit_value is not None:
                limit = _number(rule.limit_value)
                if limit is not None:
                    allowed.append(limit)
            for number in _section_numbers(rationale):
                if rule is None or number not in _section_numbers(rule.citation):
                    found.append("the rationale names an ACME Code section the changed rule does not carry")
                    break
            for rule_id in set(_RULE_ID.findall(rationale)):
                if rule is None or rule_id != rule.rule_id:
                    found.append("the rationale names a rule the change does not touch")
                    break
            for value in figures_of(_strip_rule_numbers(rationale)):
                if not any(_same(value, known) for known in allowed):
                    found.append("the rationale states a figure the change and its rule do not carry")
                    break
        ok = not found
        if request is not None and ok:
            requests.append(request)
        description = describe(request) if request is not None and parsed is not None else (
            f"A {proposed.kind or 'blank'} change that cannot be used"
        )
        items.append(ProposalItem(index, str(proposed.kind), request if ok else None, description,
                                  rationale, ok, tuple(found)))
        for text in found:
            issues.append(_issue("invalid_change", text, path))

    if not issues and requests:
        try:
            combined = change_module.apply_scenario(
                baseline, change_module.build_scenario(name, requests)
            )
        except change_module.ChangeError as error:
            issues.append(_issue("combination", error.message, "proposals"))
        else:
            if combined.config is None:
                for text in [i.message for i in combined.issues] + [u.message for u in combined.unsupported]:
                    issues.append(_issue("combination", text, "proposals"))
    if issues:
        return ProposalCheck(ValidationOutcome("failed", tuple(issues), checked), name=name, items=tuple(items))
    return ProposalCheck(
        ValidationOutcome("passed", (), checked),
        name=name,
        items=tuple(items),
        changes=tuple(requests),
    )


__all__ = [
    "BRIEF_REFUSAL_REASONS",
    "FIGURE_TOLERANCE",
    "MAX_PROPOSED_CHANGES",
    "PROPOSE_REFUSAL_REASONS",
    "REQUIRED_SECTIONS",
    "SECTION_KEYS",
    "BriefCheck",
    "ProposalCheck",
    "ProposalItem",
    "RuleSource",
    "build_request",
    "direction_cues",
    "figures_of",
    "forbidden_family",
    "rule_sources_of",
    "validate_brief",
    "validate_proposal",
]

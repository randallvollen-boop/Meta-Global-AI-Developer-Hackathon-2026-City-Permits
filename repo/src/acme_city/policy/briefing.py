"""The deterministic legislator briefing.

A briefing is built from the **typed facts** of one stored run and nothing
else: no model is called and no number is typed by hand.  Each fact carries a
value, a unit, a direction, the population and the identities of the
baseline and the scenario it compares.  Each sentence names the facts it uses.

The Muse-written briefing arrives with policy 3.  Its place is
:data:`MUSE_BRIEFING_WRITER`, a hook that is ``None`` in this release; a
writer plugged in there receives the same facts and must return a
:class:`Briefing`, which the screen then labels with its own source.
"""
# REQUIRES: PER-02, UX-01
# The briefing states only typed facts of a stored run; no model is called.

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from acme_city.persistence.models import policy as models
from acme_city.policy import views

DETERMINISTIC_SOURCE = "Deterministic briefing built from the typed facts of this run. No model was used."
FOOTER = (
    "Fictional ACME City data. Impact estimates from the ACME permit engine; "
    "not a forecast of staff time or a legal opinion."
)
SYNTHETIC_LABEL = "Synthetic data"
SYNTHETIC_BANNER = "The cases counted here are generated samples, not real applications."


@dataclass(frozen=True)
class Fact:
    """One measured value of a run, typed."""

    fact_id: str
    label: str
    value: int | str
    unit: str
    #: ``increase``, ``decrease``, ``unchanged`` or ``none`` (a single figure).
    direction: str
    population: str
    baseline_id: str
    scenario_id: str
    definition: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "direction": self.direction,
            "population": self.population,
            "baseline_id": self.baseline_id,
            "scenario_id": self.scenario_id,
            "definition": self.definition,
        }


@dataclass(frozen=True)
class Table:
    caption: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class BriefingSection:
    heading: str
    paragraphs: tuple[str, ...] = ()
    bullets: tuple[str, ...] = ()
    table: Table | None = None
    #: The fact ids the section's sentences use.
    fact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Briefing:
    title: str
    run_id: str
    scenario_name: str
    population_label: str
    synthetic: bool
    source_label: str
    sections: tuple[BriefingSection, ...]
    facts: tuple[Fact, ...]
    footer: str = FOOTER
    content_hash: str = ""


class BriefingWriter(Protocol):
    """The seam for the Muse-written briefing (policy 3)."""

    def write(self, facts: Sequence[Fact], run: models.PolicyRun) -> Briefing | None:
        """Return a briefing, or ``None`` to fall back to the deterministic one."""
        ...


#: Policy 3 plugs the Muse writer in here.  ``None`` means the briefing is
#: always the deterministic one.
MUSE_BRIEFING_WRITER: BriefingWriter | None = None


def _direction(old: int, new: int) -> str:
    return "increase" if new > old else "decrease" if new < old else "unchanged"


def _usd(cents: int) -> str:
    return f"{cents / 100:,.2f}"


def build_facts(run: models.PolicyRun) -> list[Fact]:
    """Return the typed facts of a run, in a fixed order."""
    result = run.result
    summary = result["summary"]
    population = run.population_label
    base_id = f"baseline {run.baseline_hash[:12]}"
    scen_id = f"scenario {run.proposed_hash[:12]}"
    facts: list[Fact] = []

    def add(fid: str, label: str, value: int | str, unit: str, direction: str, definition: str) -> None:
        facts.append(Fact(fid, label, value, unit, direction, population, base_id, scen_id, definition))

    add("population.size", "Cases in the population", run.population_size, "cases", "none",
        "How many cases were scored under both configurations.")
    add("cases.changed", "Cases with a different result", result["changed_case_total"], "cases", "none",
        "Cases whose rule result, recommendation or intake route differs between the baseline and the scenario.")
    for key in ("relaxed", "tightened", "changed_otherwise"):
        add(f"cases.{key}", f"Cases {key.replace('_', ' ')}", summary["by_direction"].get(key, 0), "cases",
            "none", "Cases whose result moved in that direction.")
    outcomes = result["outcome_counts"]["recommendation"]
    for key in views.OUTCOME_ORDER:
        old = outcomes["baseline"].get(key, 0)
        new = outcomes["scenario"].get(key, 0)
        add(f"outcome.{key}.baseline", f"{views.OUTCOME_LABELS[key]}, baseline", old, "cases", "none",
            "What the adjudication agent would recommend; a person decides.")
        add(f"outcome.{key}.scenario", f"{views.OUTCOME_LABELS[key]}, scenario", new, "cases",
            _direction(old, new), "What the adjudication agent would recommend; a person decides.")
    holds = summary["holds"]
    add("holds.baseline", "Recommendation holds, baseline", holds["baseline"], "cases", "none",
        result["notes"].get("recommendation_holds", ""))
    add("holds.scenario", "Recommendation holds, scenario", holds["scenario"], "cases",
        _direction(holds["baseline"], holds["scenario"]), result["notes"].get("recommendation_holds", ""))
    add("holds.cleared", "Recommendation holds cleared", holds["cleared"], "cases", "decrease",
        "Cases held in the baseline and not held in the scenario.")
    add("holds.added", "Recommendation holds added", holds["added"], "cases", "increase",
        "Cases not held in the baseline and held in the scenario.")
    needs = summary["needs_information"]
    add("needs.baseline", "Needs information, baseline", needs["baseline"], "cases", "none",
        result["notes"].get("needs_information", ""))
    add("needs.scenario", "Needs information, scenario", needs["scenario"], "cases",
        _direction(needs["baseline"], needs["scenario"]), result["notes"].get("needs_information", ""))
    add("safety.count", "Cases that stop failing a rule", len(summary["safety_signals"]), "cases", "none",
        result["notes"].get("safety_signals", ""))
    for row in summary["service_targets"]:
        add(f"target.{row['permit_type_key']}.baseline", f"Service target, {row['permit_type_key']}, baseline",
            row["before_days"], "days", "none", result["notes"].get("service_targets", ""))
        add(f"target.{row['permit_type_key']}.scenario", f"Service target, {row['permit_type_key']}, scenario",
            row["after_days"], "days", _direction(row["before_days"], row["after_days"]),
            result["notes"].get("service_targets", ""))
    fees = summary.get("fees")
    if fees:
        add("fees.baseline", "Hypothetical assessed fees, baseline", _usd(fees["baseline_total_cents"]), "USD",
            "none", fees["note"])
        add("fees.scenario", "Hypothetical assessed fees, scenario", _usd(fees["scenario_total_cents"]), "USD",
            _direction(fees["baseline_total_cents"], fees["scenario_total_cents"]), fees["note"])
        add("fees.unpriceable", "Cases that cannot be priced", len(fees["unpriceable"]), "cases", "none",
            "Cases with no usable valuation or fee schedule; they are left out of both totals.")
    return facts


def _plural(count: int, one: str, many: str | None = None) -> str:
    return one if count == 1 else (many or one + "s")


def _applied_text(stored: Mapping[str, Any], rule_id: str) -> Mapping[str, Any] | None:
    for rule in stored["rules"]:
        if rule["rule_id"] == rule_id:
            return rule
    return None


def build_deterministic(run: models.PolicyRun, facts: Sequence[Fact] | None = None) -> Briefing:
    """Return the deterministic briefing of a run."""
    chosen = list(facts if facts is not None else build_facts(run))
    fx = {f.fact_id: f for f in chosen}
    view = views.run_view(run)
    result = run.result
    summary = result["summary"]

    def v(fid: str) -> Any:
        return fx[fid].value

    sections: list[BriefingSection] = []
    size = v("population.size")
    population_sentence = (
        f"The what-if was tested on {size} {_plural(size, 'case')}: {run.population_label}."
    )
    sections.append(
        BriefingSection(
            "What was tested",
            paragraphs=(population_sentence,),
            bullets=tuple(view["changes"]),
            fact_ids=("population.size",),
        )
    )

    changed = v("cases.changed")
    if changed:
        parts = []
        for key, word in (("relaxed", "relaxed"), ("tightened", "tightened"), ("changed_otherwise", "changed in another way")):
            count = v(f"cases.{key}")
            if count:
                parts.append(f"{count} {word}")
        change_sentence = (
            f"{changed} of {size} {_plural(size, 'case')} would get a different result: "
            + ", ".join(parts) + "."
        )
    else:
        change_sentence = f"No case of the {size} gets a different result."
    rows = []
    for key in views.OUTCOME_ORDER:
        rows.append(
            (
                views.OUTCOME_LABELS[key],
                str(v(f"outcome.{key}.baseline")),
                str(v(f"outcome.{key}.scenario")),
            )
        )
    sections.append(
        BriefingSection(
            "What changes",
            paragraphs=(change_sentence,),
            table=Table(
                "Recommendation by outcome, baseline and scenario (a person decides every case)",
                ("Outcome", "Baseline", "Scenario"),
                tuple(rows),
            ),
            fact_ids=("cases.changed", "cases.relaxed", "cases.tightened")
            + tuple(f"outcome.{k}.{w}" for k in views.OUTCOME_ORDER for w in ("baseline", "scenario")),
        )
    )

    holds_sentence = (
        f"Recommendation holds: {v('holds.baseline')} in the baseline and {v('holds.scenario')} in the "
        f"scenario ({v('holds.cleared')} cleared, {v('holds.added')} added). "
        "A hold sends the case to a person; the decision and every identity, parcel, credential, "
        "finance and missing-input safeguard stay with the people and checks that own them."
    )
    needs_sentence = (
        f"Needs information at intake: {v('needs.baseline')} in the baseline and {v('needs.scenario')} "
        "in the scenario."
    )
    paragraphs = [holds_sentence, needs_sentence]
    if view["retires_a_rule"]:
        paragraphs.append(view["retire_note"])
    sections.append(
        BriefingSection(
            "Holds and missing information",
            paragraphs=tuple(paragraphs),
            fact_ids=("holds.baseline", "holds.scenario", "holds.cleared", "holds.added",
                      "needs.baseline", "needs.scenario"),
        )
    )

    safety = view["safety"]["signals"]
    count = v("safety.count")
    if count:
        sentence = (
            f"{count} {_plural(count, 'case')} would stop failing a rule. Each is listed so a person can judge the risk."
        )
        bullets = tuple(
            f"{s['case_ref']} ({s['type']}): {s['citation']} — {s['what']}" for s in safety[:25]
        )
        if count > 25:
            bullets += (f"…and {count - 25} more on the results screen.",)
    else:
        sentence = "No case would stop failing a rule."
        bullets = ()
    sections.append(BriefingSection("Safety signals", (sentence,), bullets, fact_ids=("safety.count",)))

    if view["targets"]:
        rows_t = tuple(
            (t["type"], str(t["before"]), str(t["after"])) for t in view["targets"]
        )
        sections.append(
            BriefingSection(
                "Service targets",
                ("The service targets as configured, before and after. No processing time is derived from them.",),
                table=Table("Service target in days", ("Permit type", "Baseline", "Scenario"), rows_t),
                fact_ids=tuple(f.fact_id for f in chosen if f.fact_id.startswith("target.")),
            )
        )

    if view["fees"]:
        paragraphs_f = [
            f"Hypothetical assessed fees for the priced cases: {v('fees.baseline')} USD in the baseline and "
            f"{v('fees.scenario')} USD in the scenario. These are not money collected and not a forecast of it.",
        ]
        unpriced = v("fees.unpriceable")
        if unpriced:
            paragraphs_f.append(
                f"{unpriced} {_plural(unpriced, 'case')} could not be priced and {_plural(unpriced, 'is', 'are')} "
                "left out of both totals."
            )
        sections.append(
            BriefingSection(
                "Hypothetical assessed fees",
                tuple(paragraphs_f),
                fact_ids=("fees.baseline", "fees.scenario", "fees.unpriceable"),
            )
        )

    code_rows: list[tuple[str, str, str]] = []
    for applied in result["applied_changes"]:
        if applied["kind"] not in ("rule_threshold", "rule_retirement"):
            continue
        rule_id = applied["change"].get("rule_id", "")
        rule = _applied_text(run.baseline_config, rule_id) or {}
        citation = applied["citations"][0] if applied["citations"] else rule.get("citation", rule_id)
        before = applied["before"]
        current = f"{rule.get('title', rule_id)}: {rule.get('operator', '')} {before.get('limit_value', '')}".strip()
        if applied["kind"] == "rule_retirement":
            proposed = "The rule is retired for every case."
        else:
            after = applied["after"]
            proposed = f"{rule.get('title', rule_id)}: {after.get('operator', '')} {after.get('limit_value', '')}".strip()
        code_rows.append((citation, current, proposed))
    if code_rows:
        sections.append(
            BriefingSection(
                "ACME Code sections affected",
                table=Table(
                    "Current and proposed rule",
                    ("ACME Code section", "Current", "Proposed"),
                    tuple(code_rows),
                ),
            )
        )

    method = (
        f"Method: the same intake and rule checks the ACME permit engine runs ({run.engine_version}) were applied "
        f"to the same {size} frozen cases under the baseline and under the scenario. Nothing in the live rules, fees "
        "or applications was changed. A change goes forward only as a draft for approval."
    )
    sections.append(
        BriefingSection(
            "Method and population",
            (method, view["population"]["note"]),
            bullets=(
                f"Analysis moment: {run.analysis_at.isoformat()}",
                f"Run content hash: {run.content_hash}",
            ),
        )
    )
    return Briefing(
        title=f"What-if briefing: {run.scenario_name}",
        run_id=run.id,
        scenario_name=run.scenario_name,
        population_label=run.population_label,
        synthetic=bool(run.population_synthetic),
        source_label=DETERMINISTIC_SOURCE,
        sections=tuple(sections),
        facts=tuple(chosen),
        content_hash=run.content_hash,
    )


def build_briefing(run: models.PolicyRun, *, writer: BriefingWriter | None = None) -> Briefing:
    """Return the briefing of a run: the Muse writer's if one is plugged in, else the deterministic one."""
    facts = build_facts(run)
    chosen = writer if writer is not None else MUSE_BRIEFING_WRITER
    if chosen is not None:
        written = chosen.write(facts, run)
        if written is not None:
            return written
    return build_deterministic(run, facts)


# ------------------------------------------------------------------- exports

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]#+!|<>&~])")


def md_escape(text: str) -> str:
    """Escape Markdown and HTML specials so exported text cannot become markup."""
    return _MD_SPECIAL.sub(r"\\\1", str(text)).replace("\n", " ")


def to_markdown(briefing: Briefing) -> str:
    lines = [f"# {md_escape(briefing.title)}", ""]
    if briefing.synthetic:
        lines += [f"**{md_escape(SYNTHETIC_LABEL)}.** {md_escape(SYNTHETIC_BANNER)}", ""]
    lines += [
        f"Population: {md_escape(briefing.population_label)}",
        "",
        f"Source: {md_escape(briefing.source_label)}",
        "",
    ]
    for section in briefing.sections:
        lines += [f"## {md_escape(section.heading)}", ""]
        for paragraph in section.paragraphs:
            lines += [md_escape(paragraph), ""]
        for bullet in section.bullets:
            lines.append(f"- {md_escape(bullet)}")
        if section.bullets:
            lines.append("")
        if section.table is not None:
            lines += [f"*{md_escape(section.table.caption)}*", ""]
            lines.append("| " + " | ".join(md_escape(h) for h in section.table.headers) + " |")
            lines.append("|" + "|".join(" --- " for _ in section.table.headers) + "|")
            for row in section.table.rows:
                lines.append("| " + " | ".join(md_escape(cell) for cell in row) + " |")
            lines.append("")
    lines += ["---", "", md_escape(briefing.footer), ""]
    return "\n".join(lines)


_HTML_STYLE = (
    "body{font:16px/1.5 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#1b1f24;background:#fff}"
    "h1{font-size:1.6rem}h2{font-size:1.2rem;margin-top:1.8rem}"
    "table{border-collapse:collapse;width:100%;margin:.5rem 0}th,td{border:1px solid #8a94a0;padding:.3rem .5rem;text-align:left}"
    ".badge{background:#fff3bf;color:#5c4400;border:1px solid #c9a227;border-radius:.25rem;padding:0 .4rem;font-weight:600}"
    ".foot{margin-top:2rem;border-top:1px solid #8a94a0;padding-top:.6rem;font-size:.9rem}"
    "@media print{body{margin:0;max-width:none}}"
)


def to_html(briefing: Briefing) -> str:
    """Return a self-contained HTML document with every text escaped."""
    e = html.escape
    out = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{e(briefing.title)}</title>",
        f"<style>{_HTML_STYLE}</style></head><body>",
        f"<h1>{e(briefing.title)}</h1>",
    ]
    if briefing.synthetic:
        out.append(f'<p><span class="badge">{e(SYNTHETIC_LABEL)}</span> {e(SYNTHETIC_BANNER)}</p>')
    out.append(f"<p>Population: {e(briefing.population_label)}</p>")
    out.append(f"<p>Source: {e(briefing.source_label)}</p>")
    for section in briefing.sections:
        out.append(f"<h2>{e(section.heading)}</h2>")
        for paragraph in section.paragraphs:
            out.append(f"<p>{e(paragraph)}</p>")
        if section.bullets:
            out.append("<ul>" + "".join(f"<li>{e(b)}</li>" for b in section.bullets) + "</ul>")
        if section.table is not None:
            table = section.table
            out.append(f"<table><caption>{e(table.caption)}</caption><thead><tr>")
            out.append("".join(f'<th scope="col">{e(h)}</th>' for h in table.headers))
            out.append("</tr></thead><tbody>")
            for row in table.rows:
                out.append("<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>")
            out.append("</tbody></table>")
    out.append(f'<p class="foot">{e(briefing.footer)}</p></body></html>')
    return "\n".join(out)


__all__ = [
    "DETERMINISTIC_SOURCE",
    "FOOTER",
    "MUSE_BRIEFING_WRITER",
    "SYNTHETIC_BANNER",
    "SYNTHETIC_LABEL",
    "Briefing",
    "BriefingSection",
    "BriefingWriter",
    "Fact",
    "Table",
    "build_briefing",
    "build_deterministic",
    "build_facts",
    "md_escape",
    "to_html",
    "to_markdown",
]

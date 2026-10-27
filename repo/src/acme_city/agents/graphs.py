"""The dependency graphs of the two agents.

Each graph is a list of nodes.  A node names its identifier, its label and
the dependency level it runs at: nodes of the same level run in parallel, and
a node of level ``n`` depends on every node of the levels before it.  The
graph is data, so the server-rendered diagram and the recorded run trace can
never disagree.
"""
# REQUIRES: AI-03, PER-04
# The graph of an agent is declared once; the diagram and the run trace are
# both projections of it.

from __future__ import annotations

from dataclasses import dataclass

#: The node identifiers of the intake agent.
INTAKE_CLASSIFIER = "classifier"
INTAKE_FIELD_EXTRACTOR = "field_extractor"
INTAKE_DOCUMENT_QC = "document_qc"
INTAKE_ADDRESS_LOCATOR = "address_locator"
INTAKE_DUPLICATE_FINDER = "duplicate_finder"
INTAKE_COMPLETENESS = "completeness"
INTAKE_ROUTER = "router"

#: The node identifiers of the adjudication agent.
ADJUDICATION_RULE_LOADER = "rule_loader"
ADJUDICATION_RULE_EVALUATOR = "rule_evaluator"
ADJUDICATION_CONDITION_BUILDER = "condition_builder"
ADJUDICATION_PRECEDENT_CHECK = "precedent_check"
ADJUDICATION_DISPOSITION = "disposition"


@dataclass(frozen=True)
class GraphNode:
    """One node of an agent graph."""

    node_id: str
    label: str
    level: int
    position: int
    description: str = ""


def _nodes(rows: tuple[tuple[str, str, int, str], ...]) -> tuple[GraphNode, ...]:
    """Return the nodes of one graph, in declaration order."""
    return tuple(
        GraphNode(
            node_id=node_id,
            label=label,
            level=level,
            position=position,
            description=description,
        )
        for position, (node_id, label, level, description) in enumerate(rows)
    )


#: The intake agent graph: classifier, then extraction and document QC in
#: parallel, then the address locator and completeness in parallel, then the
#: duplicate finder, then the router.
INTAKE_GRAPH: tuple[GraphNode, ...] = _nodes(
    (
        (
            INTAKE_CLASSIFIER,
            "Classifier",
            1,
            "Confirms the permit type and the channel, and sets the review area.",
        ),
        (
            INTAKE_FIELD_EXTRACTOR,
            "Field extractor",
            2,
            "Proposes field values from the received documents (Muse Spark, replay by default).",
        ),
        (
            INTAKE_DOCUMENT_QC,
            "Document QC",
            2,
            "Flags the scan-quality problems carried by the intake record.",
        ),
        (
            INTAKE_ADDRESS_LOCATOR,
            "Address locator",
            3,
            "Corrects the typed address to the closest official one and finds the parcel "
            "it falls in (simulated ArcGIS locator and parcel layer).",
        ),
        (
            INTAKE_COMPLETENESS,
            "Completeness",
            3,
            "Checks the required fields and documents of the permit type.",
        ),
        (
            INTAKE_DUPLICATE_FINDER,
            "Duplicate finder",
            4,
            "Finds a duplicate case and proposes the identity links.",
        ),
        (
            INTAKE_ROUTER,
            "Router",
            5,
            "Routes the case to early resolution or to review.",
        ),
    )
)

#: The adjudication agent graph: rule loader, rule evaluator, then condition
#: builder and precedent check in parallel, then the disposition.
ADJUDICATION_GRAPH: tuple[GraphNode, ...] = _nodes(
    (
        (
            ADJUDICATION_RULE_LOADER,
            "Rule loader",
            1,
            "Finds the published rules of the permit type and flags a discretionary type.",
        ),
        (
            ADJUDICATION_RULE_EVALUATOR,
            "Rule evaluator",
            2,
            "Runs the deterministic evaluator against the submitted facts.",
        ),
        (
            ADJUDICATION_CONDITION_BUILDER,
            "Condition builder",
            3,
            "Collects the conditions of approval from the condition results.",
        ),
        (
            ADJUDICATION_PRECEDENT_CHECK,
            "Precedent check",
            3,
            "Finds an earlier decided case of the same type on the same parcel.",
        ),
        (
            ADJUDICATION_DISPOSITION,
            "Disposition",
            4,
            "Chooses the recommendation: hold, deny, approve with conditions, or approve.",
        ),
    )
)

#: The graphs by agent key.
GRAPHS: dict[str, tuple[GraphNode, ...]] = {
    "intake": INTAKE_GRAPH,
    "adjudication": ADJUDICATION_GRAPH,
}


def node_for(agent_key: str, node_id: str) -> GraphNode:
    """Return one node of an agent graph by its identifier."""
    for node in GRAPHS.get(agent_key, ()):
        if node.node_id == node_id:
            return node
    raise KeyError(f"{agent_key} has no node {node_id!r}")


def graph_for(agent_key: str) -> tuple[GraphNode, ...]:
    """Return the graph of one agent."""
    return GRAPHS.get(agent_key, ())


def levels_of(agent_key: str) -> list[list[GraphNode]]:
    """Return the graph of one agent, grouped into dependency levels."""
    grouped: dict[int, list[GraphNode]] = {}
    for node in graph_for(agent_key):
        grouped.setdefault(node.level, []).append(node)
    return [grouped[level] for level in sorted(grouped)]


__all__ = [
    "ADJUDICATION_GRAPH",
    "ADJUDICATION_CONDITION_BUILDER",
    "ADJUDICATION_DISPOSITION",
    "ADJUDICATION_PRECEDENT_CHECK",
    "ADJUDICATION_RULE_EVALUATOR",
    "ADJUDICATION_RULE_LOADER",
    "GRAPHS",
    "INTAKE_CLASSIFIER",
    "INTAKE_COMPLETENESS",
    "INTAKE_DOCUMENT_QC",
    "INTAKE_DUPLICATE_FINDER",
    "INTAKE_FIELD_EXTRACTOR",
    "INTAKE_GRAPH",
    "INTAKE_ROUTER",
    "GraphNode",
    "graph_for",
    "levels_of",
]

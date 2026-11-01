"""The step graph of an agent: its columns, its states and its words.

The graph is a projection of the agent graph and of the recorded run, so the
cards of a run and the words of the states can never disagree.  Every state
names itself in words, so the graph reads without colour.
"""
# REQUIRES: UX-01

from __future__ import annotations

from html.parser import HTMLParser

import pytest

from acme_city.agents import graphs
from acme_city.ui.router import templates

#: The recorded rows of one run of the intake agent.
RECORDED: dict[str, dict[str, str]] = {
    "classifier": {"status": "ok", "note": "Review area: Building."},
    "field_extractor": {"status": "warn", "note": "A person must read the documents."},
    "document_qc": {"status": "ok", "note": "The scan is readable."},
    "address_locator": {"status": "block", "note": "The locator failed."},
    "completeness": {"status": "ok", "note": "Every document is there."},
    "duplicate_finder": {"status": "ok", "note": "No duplicate found."},
    "router": {"status": "ok", "note": "Ready for review in the Building area."},
}


class _Dag(HTMLParser):
    """Collect the cards, the columns and the arrows of a rendered graph."""

    def __init__(self, markup: str = "") -> None:
        super().__init__()
        self.nodes: list[dict[str, str]] = []
        self.levels = 0
        self.arrows = 0
        self.arrow_hidden = ""
        self.legend = ""
        self._capture = ""
        self._text: list[str] = []
        if markup:
            self.feed(markup)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = dict(attrs)
        classes = a.get("class") or ""
        if tag == "div" and a.get("data-testid") == "agent-dag-node":
            self.nodes.append(
                {
                    "node_id": a.get("data-node-id", ""),
                    "state": a.get("data-state", ""),
                    "class": classes,
                    "word": "",
                    "note": "",
                }
            )
        if tag == "div" and a.get("data-testid") == "agent-dag-level":
            self.levels += 1
        if tag == "div" and "agent-dag-arrow" in classes:
            self.arrows += 1
            self.arrow_hidden = a.get("aria-hidden", "")
        if tag == "p" and "agent-dag-state" in classes:
            self._capture = "word"
            self._text = []
        elif tag == "p" and "agent-dag-note" in classes:
            self._capture = "note"
            self._text = []
        elif tag == "p" and "agent-dag-legend" in classes:
            self._capture = "legend"
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "p" or not self._capture:
            return
        text = " ".join(" ".join(self._text).split())
        if self._capture == "legend":
            self.legend = text
        elif self.nodes:
            self.nodes[-1][self._capture] = text
        self._capture = ""
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def state_of(self, node_id: str) -> str:
        return next(node["state"] for node in self.nodes if node["node_id"] == node_id)

    def word_of(self, node_id: str) -> str:
        return next(node["word"] for node in self.nodes if node["node_id"] == node_id)

    def note_of(self, node_id: str) -> str:
        return next(node["note"] for node in self.nodes if node["node_id"] == node_id)


def _render(levels) -> str:
    """Render the step graph of the shared frame."""
    module = templates.env.get_template("components/agent_dag.html").module
    return str(module.agent_dag(levels))


@pytest.fixture()
def dag() -> _Dag:
    return _Dag(_render(graphs.levels_with_states("intake", RECORDED)))


def test_the_intake_graph_has_seven_nodes_in_five_columns(dag: _Dag) -> None:
    """The graph of the intake agent is the one the demo shows."""
    assert len(dag.nodes) == 7
    assert dag.levels == 5
    assert dag.arrows == 4


def test_the_states_and_the_words_match_the_recorded_rows(dag: _Dag) -> None:
    """Every card carries the state the run recorded and the word of it."""
    for node_id, row in RECORDED.items():
        assert dag.state_of(node_id) == row["status"], node_id
        assert f"agent-dag-node {row['status']}" in next(
            node["class"] for node in dag.nodes if node["node_id"] == node_id
        ), node_id
    assert dag.word_of("classifier") == "Clear"
    assert dag.word_of("field_extractor") == "Needs human"
    assert dag.word_of("address_locator") == "Blocking"


def test_the_note_of_a_step_stands_on_its_card(dag: _Dag) -> None:
    """The recorded note of a step is readable on the card of the step."""
    assert dag.note_of("router") == "Ready for review in the Building area."
    assert dag.note_of("field_extractor") == "A person must read the documents."


def test_an_agent_that_has_not_run_shows_every_step_in_grey() -> None:
    """A graph without a run is idle everywhere, and says so in words."""
    dag = _Dag(_render(graphs.levels_with_states("intake", {})))
    assert {node["state"] for node in dag.nodes} == {"idle"}
    assert {node["word"] for node in dag.nodes} == {"Not run"}
    assert all(node["note"] == "" for node in dag.nodes)


def test_the_arrows_are_hidden_and_the_legend_names_the_order(dag: _Dag) -> None:
    """The arrows are decoration and the legend tells the truth."""
    assert dag.arrow_hidden == "true"
    assert dag.legend == (
        "Steps run left to right; each column waits for the one before it."
    )


def test_the_state_words_are_the_words_of_the_original_sample() -> None:
    """The three states a run may record have the words of the sample app."""
    assert graphs.state_word("ok") == "Clear"
    assert graphs.state_word("warn") == "Needs human"
    assert graphs.state_word("block") == "Blocking"
    assert graphs.state_word("idle") == "Not run"
    # A state a run may not record never reaches a card.
    assert graphs.levels_with_states("intake", {"classifier": {"status": "pending"}})[0][0][
        "state"
    ] == "idle"

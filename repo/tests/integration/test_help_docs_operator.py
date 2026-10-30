"""Help assertions of the operator lane (the shared test_help_docs.py is frozen)."""
# REQUIRES: UX-01

from acme_city.help_docs import content


def test_operator_guidance_names_only_the_operator_screens() -> None:
    """The shared help introduction explains the limited operator workspace."""
    intro = content.howto_intro()
    assert "Agent Operator" in intro
    for label in ("Agents", "Intake agent", "Adjudication agent", "Run history"):
        assert f'"{label}"' in intro
    assert "permit decisions" in intro

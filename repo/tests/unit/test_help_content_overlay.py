"""Help content overlays: replace a step's text, never delete a step."""
# REQUIRES: UX-01

from __future__ import annotations

import json

import pytest

from acme_city.help_docs import content


@pytest.fixture
def overlay_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(content, "OVERLAY_DIR", tmp_path)
    content.reload()
    yield tmp_path
    content.reload()


def _write(directory, name, data):
    (directory / name).write_text(json.dumps(data), encoding="utf-8")
    content.reload()


def test_overlay_replaces_one_step_text(overlay_dir):
    base_guide = content.guides()[0]
    slug = base_guide["slug"]
    _write(overlay_dir, "a.json", {"howto": {"guides": [{"slug": slug, "steps": {"0": "Replaced."}}]}})
    guide = content.guide(slug)
    assert guide["steps"][0] == "Replaced."
    assert guide["steps"][1:] == base_guide["steps"][1:]


def test_overlay_replaces_tutorial_step_field(overlay_dir):
    before = content.tutorial()["sections"][0]
    pid = before["persona_id"]
    _write(overlay_dir, "a.json", {"tutorial": {"sections": [{"persona_id": pid, "steps": {"1": {"do": "New."}}}]}})
    after = content.tutorial()["sections"][0]
    assert after["steps"][1]["do"] == "New."
    assert after["steps"][1]["see"] == before["steps"][1]["see"]
    assert len(after["steps"]) == len(before["steps"])


def test_overlay_cannot_delete_a_step(overlay_dir):
    slug = content.guides()[0]["slug"]
    count = len(content.guide(slug)["steps"])
    with pytest.raises(ValueError):
        _write(overlay_dir, "a.json", {"howto": {"guides": [{"slug": slug, "steps": ["only one"]}]}})
        content.guide(slug)
    # An overlay that names fewer guides leaves the others in place.
    _write(overlay_dir, "a.json", {"howto": {"guides": [{"slug": slug}]}})
    assert len(content.guide(slug)["steps"]) == count
    assert len(content.guides()) > 1


def test_empty_overlays_leave_content_unchanged(overlay_dir):
    before = json.dumps(content._content(), sort_keys=True)
    _write(overlay_dir, "a.json", {})
    assert json.dumps(content._content(), sort_keys=True) == before


def _bad_overlays(slug, pid):
    return [
        {"howto": {"guides": None}},
        {"howto": {"guides": [{"slug": slug, "steps": None}]}},
        {"howto": {"guides": [{"slug": slug, "steps": "x"}]}},
        {"howto": {"guides": [{"slug": slug, "steps": {"0": None}}]}},
        {"howto": {"guides": [{"slug": slug, "steps": {"0": {"a": 1}}}]}},
        {"tutorial": {"sections": [{"persona_id": pid, "steps": {"1": None}}]}},
        {"tutorial": {"sections": [{"persona_id": pid, "steps": {"1": "text"}}]}},
        {"tutorial": {"sections": None}},
    ]


def test_overlay_cannot_delete_by_null_or_kind_change(overlay_dir):
    slug = content.guides()[0]["slug"]
    pid = content.tutorial()["sections"][0]["persona_id"]
    for bad in _bad_overlays(slug, pid):
        with pytest.raises(ValueError):
            _write(overlay_dir, "a.json", bad)
            content._content()


def test_overlay_appends_guide_section_and_step(overlay_dir):
    slug = content.guides()[0]["slug"]
    count = len(content.guide(slug)["steps"])
    _write(
        overlay_dir,
        "a.json",
        {
            "howto": {
                "guides": [
                    {"slug": slug, "steps": {str(count): "An extra step."}},
                    {"slug": "new-guide", "title": "New", "persona_ids": [], "steps": ["One."]},
                ]
            },
            "tutorial": {"sections": [{"persona_id": "persona_new_test", "steps": []}]},
        },
    )
    assert content.guide(slug)["steps"][count] == "An extra step."
    assert content.guide("new-guide")["steps"] == ["One."]
    assert content.tutorial()["sections"][-1]["persona_id"] == "persona_new_test"
    with pytest.raises(ValueError):
        _write(overlay_dir, "a.json", {"howto": {"guides": [{"slug": slug, "steps": {str(count + 1): "Gap."}}]}})
        content._content()


def test_two_overlays_cannot_set_the_same_value(overlay_dir):
    slug = content.guides()[0]["slug"]
    (overlay_dir / "a.json").write_text(
        json.dumps({"howto": {"guides": [{"slug": slug, "steps": {"0": "A."}}]}}), encoding="utf-8"
    )
    _write(overlay_dir, "b.json", {"howto": {"guides": [{"slug": slug, "steps": {"0": "B."}}]}})
    with pytest.raises(ValueError, match="also set by a"):
        content._content()


def test_shipped_overlays_have_no_dashes():
    for path in sorted(content.OVERLAY_DIR.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text and "\u2013" not in text, path.name
        assert "\u2014" not in json.loads(text).__repr__() and "\u2013" not in json.loads(text).__repr__()

"""The bundle of help documents that travels with the application.

The container image is built from ``repo/`` alone and has no project root
above it, so the documents of the project root are kept in
``repo/help_docs_bundle/``, at the same relative path.  These tests keep the
copies the same as the originals and show that the application reads them when
the originals are not there.
"""

from __future__ import annotations

import fnmatch
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from acme_city.help_docs import content

REPO = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPO.parent
BUNDLE = REPO / "help_docs_bundle"
SCRIPT = REPO / "scripts" / "sync_help_docs_bundle.py"


def project_entries() -> list[dict]:
    """The technical documents the help takes from the project root."""
    return [
        entry
        for entry in content.technical()["documents"]
        if entry.get("root") == "project"
    ]


def repo_entries() -> list[dict]:
    """The technical documents the help takes from the repository itself."""
    return [
        entry
        for entry in content.technical()["documents"]
        if entry.get("root") != "project"
    ]


def bundled_files() -> list[str]:
    """The relative paths of the files the bundle holds."""
    return sorted(
        str(path.relative_to(BUNDLE))
        for path in BUNDLE.rglob("*")
        if path.is_file()
    )


# ------------------------------------------------------------- the drift


def test_the_bundle_holds_every_document_of_the_project_root() -> None:
    entries = project_entries()
    assert entries, "the help names no document of the project root"
    assert bundled_files() == sorted(str(entry["path"]) for entry in entries)


def test_every_bundled_document_is_the_same_as_the_original() -> None:
    for entry in project_entries():
        original = PROJECT_ROOT / entry["path"]
        copy = BUNDLE / entry["path"]
        assert original.is_file(), entry["path"]
        assert copy.is_file(), entry["path"]
        assert copy.read_bytes() == original.read_bytes(), entry["path"]


def test_the_bundled_runbook_carries_the_note_about_the_sync_script() -> None:
    text = (BUNDLE / "docs" / "operations" / "RUNBOOK.md").read_text(encoding="utf-8")
    assert "scripts/sync_help_docs_bundle.py" in text


# ------------------------------------------------------- the image layout


def test_every_document_loads_when_the_project_root_is_not_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The image has no project root above ``repo/``; the bundle carries them."""
    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)
    for entry in content.technical()["documents"]:
        loaded = content.read_document(entry)
        assert loaded.text is not None, entry["slug"]
        assert loaded.message == "", entry["slug"]
        if entry.get("root") == "project":
            expected = BUNDLE / entry["path"]
        else:
            expected = content.REPO_DIR / entry["path"]
        assert loaded.text == expected.read_text(encoding="utf-8"), entry["slug"]


def test_a_document_that_is_nowhere_gives_the_plain_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(content, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(content, "BUNDLE_DIR", tmp_path / "no-bundle")
    loaded = content.read_document({"root": "project", "path": "docs/operations/RUNBOOK.md"})
    assert loaded.text is None
    assert "not available in this copy" in loaded.message


def test_a_path_that_leaves_the_bundle_is_refused() -> None:
    loaded = content.read_document({"root": "project", "path": "../README.md"})
    assert loaded.text is None and "outside" in loaded.message


def test_a_document_of_the_repository_is_read_from_the_repository() -> None:
    for entry in repo_entries():
        loaded = content.read_document(entry)
        assert loaded.text is not None, entry["slug"]
        assert loaded.text == (content.REPO_DIR / entry["path"]).read_text(encoding="utf-8")


# ---------------------------------------------------------- the image files


def test_both_images_carry_the_documents_and_their_copies() -> None:
    for name in ("Dockerfile", "Dockerfile-demo"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert "COPY README.md USER_TEST_GUIDE.md ./" in text, name
        assert "COPY help_docs_bundle ./help_docs_bundle" in text, name


def test_the_dockerignore_does_not_exclude_the_documents() -> None:
    patterns = [
        line.strip()
        for line in (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    names = ["README.md", "USER_TEST_GUIDE.md", "help_docs_bundle"]
    for name in names:
        for pattern in patterns:
            assert not fnmatch.fnmatch(name, pattern), (name, pattern)
            assert not name.startswith(pattern.rstrip("/") + "/"), (name, pattern)


# ------------------------------------------------------------ the script


def run_script(script: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def make_tree(tmp_path: Path) -> Path:
    """A miniature layout: a project root above a repository that holds the script."""
    root = tmp_path / "project"
    repo = root / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "config").mkdir(parents=True)
    shutil.copyfile(SCRIPT, repo / "scripts" / "sync_help_docs_bundle.py")
    (repo / "config" / "help_content.json").write_text(
        json.dumps(
            {
                "technical": {
                    "documents": [
                        {"slug": "runbook", "root": "project", "path": "docs/operations/RUNBOOK.md"},
                        {"slug": "readme", "root": "project", "path": "README.md"},
                        {"slug": "repo-readme", "root": "repo", "path": "README.md"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    for relative, text in (
        ("docs/operations/RUNBOOK.md", "# Runbook\n"),
        ("README.md", "# Project overview\n"),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_the_sync_script_check_passes_on_the_committed_tree() -> None:
    result = run_script(SCRIPT, "--check")
    assert result.returncode == 0, result.stderr


def test_the_sync_script_copies_the_documents_and_reports_a_difference(tmp_path: Path) -> None:
    root = make_tree(tmp_path)
    script = root / "repo" / "scripts" / "sync_help_docs_bundle.py"

    missing = run_script(script, "--check")
    assert missing.returncode == 1
    assert "missing in the bundle" in missing.stderr

    copied = run_script(script)
    assert copied.returncode == 0, copied.stderr
    bundle = root / "repo" / "help_docs_bundle"
    assert (bundle / "docs" / "operations" / "RUNBOOK.md").read_text(encoding="utf-8") == "# Runbook\n"
    assert (bundle / "README.md").read_text(encoding="utf-8") == "# Project overview\n"
    assert run_script(script, "--check").returncode == 0

    # The original changes: the copy drifts, and the script reports it.
    (root / "docs" / "operations" / "RUNBOOK.md").write_text("# Runbook, changed\n", encoding="utf-8")
    drifted = run_script(script, "--check")
    assert drifted.returncode == 1
    assert "differs from the original" in drifted.stderr

    assert run_script(script).returncode == 0
    assert (bundle / "docs" / "operations" / "RUNBOOK.md").read_text(encoding="utf-8") == "# Runbook, changed\n"
    assert run_script(script, "--check").returncode == 0


def test_the_sync_script_leaves_the_documents_of_the_repository_alone(tmp_path: Path) -> None:
    root = make_tree(tmp_path)
    script = root / "repo" / "scripts" / "sync_help_docs_bundle.py"
    assert run_script(script).returncode == 0
    bundle = root / "repo" / "help_docs_bundle"
    assert not (bundle / "repo-readme.md").exists()
    assert sorted(
        str(path.relative_to(bundle))
        for path in bundle.rglob("*")
        if path.is_file()
    ) == ["README.md", "docs/operations/RUNBOOK.md"]

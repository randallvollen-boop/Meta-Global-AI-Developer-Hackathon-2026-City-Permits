"""The publishable-tree scan admits only listed, genuine binaries with their recorded hash."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scan_publishable_tree.py"
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 fake-image"
PNG = b"\x89PNG\r\n\x1a\n fake-image"


@pytest.fixture()
def scanner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("scan_publishable_tree", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    return module


def write(root: Path, relative: str, content: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def write_manifest(root: Path, files: dict[str, bytes]) -> None:
    sets = [
        {
            "directory": "static",
            "source": "test",
            "added_in": [],
            "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
        }
    ]
    write(root, "config/publishable_binaries.json", json.dumps({"sets": sets}).encode())


def test_listed_genuine_binaries_pass(scanner, tmp_path: Path) -> None:
    write(tmp_path, "static/tile.webp", WEBP)
    write(tmp_path, "static/icon.png", PNG)
    write_manifest(tmp_path, {"tile.webp": WEBP, "icon.png": PNG})
    assert scanner.scan() == []


def test_an_unlisted_binary_is_a_finding(scanner, tmp_path: Path) -> None:
    write(tmp_path, "static/tile.webp", WEBP)
    write(tmp_path, "static/extra.webp", WEBP)
    write_manifest(tmp_path, {"tile.webp": WEBP})
    assert scanner.scan() == ["static/extra.webp: unexpected binary or file type"]


def test_a_changed_binary_is_a_finding(scanner, tmp_path: Path) -> None:
    write(tmp_path, "static/tile.webp", WEBP + b"changed")
    write_manifest(tmp_path, {"tile.webp": WEBP})
    assert scanner.scan() == [
        "static/tile.webp: sha256 differs from config/publishable_binaries.json"
    ]


def test_a_header_that_does_not_match_the_type_is_a_finding(scanner, tmp_path: Path) -> None:
    write(tmp_path, "static/tile.webp", PNG)
    write_manifest(tmp_path, {"tile.webp": PNG})
    assert scanner.scan() == ["static/tile.webp: content does not match its file type"]


def test_a_listed_file_missing_from_the_tree_is_a_finding(scanner, tmp_path: Path) -> None:
    write_manifest(tmp_path, {"gone.webp": WEBP})
    assert scanner.scan() == [
        "static/gone.webp: listed in config/publishable_binaries.json but not in the tree"
    ]


def test_ignored_files_are_not_scanned(scanner, tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", b"var/\n")
    write(tmp_path, "var/local.bin", b"\x00\x01")
    write_manifest(tmp_path, {})
    assert scanner.scan() == []

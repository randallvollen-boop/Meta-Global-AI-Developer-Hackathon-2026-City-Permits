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
MP3_TAG = b"ID3\x04\x00\x00\x00\x00\x00\x00 fake-clip"
MP3_FRAME = b"\xff\xfb\x90\x00 fake-clip"


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


def test_a_listed_set_may_raise_the_size_limit_for_its_own_files(
    scanner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Low enough for the sample image, high enough for the manifest itself.
    monkeypatch.setattr(scanner, "SIZE_LIMIT", 1024)
    large = WEBP + b"x" * 2048
    write(tmp_path, "static/large.webp", large)
    write_manifest(tmp_path, {"large.webp": large})
    assert scanner.scan() == ["static/large.webp: file exceeds its 1024 byte source-tree limit"]

    manifest = json.loads((tmp_path / "config/publishable_binaries.json").read_text())
    manifest["sets"][0]["max_bytes"] = len(large)
    write(tmp_path, "config/publishable_binaries.json", json.dumps(manifest).encode())
    assert scanner.scan() == []


def test_an_unpinned_folder_admits_its_types_on_header_and_size(scanner, tmp_path: Path) -> None:
    mp4 = b"\x00\x00\x00\x18ftypisom re-encoded draft"
    write(tmp_path, "video/tour.mp4", mp4)
    write(tmp_path, "video/poster.jpg", b"\xff\xd8\xff\xe0 still")
    sets = [{"directory": "video", "source": "test", "suffixes": [".mp4", ".jpg"]}]
    write(tmp_path, "config/publishable_binaries.json", json.dumps({"sets": sets}).encode())
    assert scanner.scan() == []

    write(tmp_path, "video/notes.webp", WEBP)
    write(tmp_path, "video/fake.mp4", b"not a video at all")
    assert scanner.scan() == [
        "video/fake.mp4: content does not match its file type",
        "video/notes.webp: unexpected binary or file type",
    ]


def test_an_mp3_clip_passes_on_its_tag_or_its_frame_sync(scanner, tmp_path: Path) -> None:
    sets = [{"directory": "tour-audio", "source": "test", "suffixes": [".mp3"]}]
    write(tmp_path, "config/publishable_binaries.json", json.dumps({"sets": sets}).encode())
    write(tmp_path, "tour-audio/intro.mp3", MP3_TAG)
    assert scanner.scan() == []

    write(tmp_path, "tour-audio/frame.mp3", MP3_FRAME)
    assert scanner.scan() == []

    write(tmp_path, "tour-audio/notes.mp3", b"not an audio clip at all")
    assert scanner.scan() == ["tour-audio/notes.mp3: content does not match its file type"]


def test_a_base64_fixture_is_read_as_text(scanner, tmp_path: Path) -> None:
    write(tmp_path, "tests/fixtures/clip.mp3.b64", b"SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjYw\n")
    write_manifest(tmp_path, {})
    assert scanner.scan() == []


def test_a_base64_fixture_is_still_scanned_for_secrets(scanner, tmp_path: Path) -> None:
    # The address is written in two parts, so the scanner does not read this
    # test file as a leak of its own.
    write(tmp_path, "tests/fixtures/clip.mp3.b64", b"aGVsbG8 " + b"someone@" + b"gmail.com\n")
    write_manifest(tmp_path, {})
    assert scanner.scan() == ["tests/fixtures/clip.mp3.b64: personal email"]


def test_an_env_example_is_scanned_as_text(scanner, tmp_path: Path) -> None:
    write(tmp_path, ".env.example", b"META_API_KEY=\nACME_MUSE_LIVE_CALL_CAP=2\n")
    write_manifest(tmp_path, {})
    assert scanner.scan() == []
    write(tmp_path, ".env.example", b"META_API_KEY=" + b"x" * 40 + b"\n")
    assert any("assigned provider key" in finding for finding in scanner.scan())

#!/usr/bin/env python3
"""Build the manifest for optional guided-tour narration clips."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOUR_AUDIO_DIR = REPO_ROOT / "src" / "acme_city" / "static" / "tour-audio"
MANIFEST_PATH = TOUR_AUDIO_DIR / "manifest.json"


def build_manifest(audio_dir: Path = TOUR_AUDIO_DIR) -> dict[str, str]:
    """Return every top-level MP3 clip, keyed by its expected stem."""
    return {
        clip.stem: clip.name
        for clip in sorted(audio_dir.glob("*.mp3"))
        if clip.is_file()
    }


def main() -> None:
    """Write the stable, human-readable manifest beside the clips."""
    TOUR_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(build_manifest(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

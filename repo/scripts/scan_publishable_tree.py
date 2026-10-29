#!/usr/bin/env python3
"""Scan the prospective public repository tree for local-only or secret material."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    "",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".lock",
    ".mako",
    ".md",
    ".py",
    ".svg",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
DENY_PATTERNS = {
    # Generic forms only, so the scanner itself names no person or machine.
    "personal email": re.compile(r"\b[A-Za-z0-9._%+-]+@(?:gmail|outlook|hotmail|yahoo|icloud)\.com\b", re.IGNORECASE),
    "local home path": re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+/"),
    "tailnet address": re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2}\b"),
    "assigned provider key": re.compile(r"(?m)^[ \t]*(?:export[ \t]+)?META_API_KEY[ \t]*=[ \t]*[^\s#][^\r\n]{19,}$"),
    "common secret token": re.compile(r"\b(?:sk|sk-proj|ghp|github_pat)_[A-Za-z0-9_-]{20,}\b"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
# Extra literal terms (for example a real name or host) can come from the environment.
for _index, _term in enumerate(t for t in os.environ.get("ACME_SCAN_PRIVATE_TERMS", "").split(",") if t.strip()):
    DENY_PATTERNS[f"private term {_index + 1}"] = re.compile(re.escape(_term.strip()), re.IGNORECASE)


#: The only binary files the tree may carry, each with its sha256 and provenance.
BINARY_MANIFEST = Path("config/publishable_binaries.json")
#: The header every allowed binary type must start with.
BINARY_HEADERS = {
    ".webp": lambda header: header[:4] == b"RIFF" and header[8:12] == b"WEBP",
    ".png": lambda header: header[:8] == b"\x89PNG\r\n\x1a\n",
}


def load_binary_manifest() -> dict[Path, str]:
    """Return every listed binary file with its expected sha256."""
    data = json.loads((REPO_ROOT / BINARY_MANIFEST).read_text(encoding="utf-8"))
    return {
        Path(entry["directory"]) / name: digest
        for entry in data["sets"]
        for name, digest in entry["files"].items()
    }


def binary_finding(relative: Path, path: Path, manifest: dict[Path, str]) -> str | None:
    """Return why a binary file may not be published, or None when it is listed and genuine."""
    expected = manifest.get(relative)
    if expected is None:
        return "unexpected binary or file type"
    check = BINARY_HEADERS.get(path.suffix.lower())
    content = path.read_bytes()
    if check is None or not check(content[:12]):
        return "content does not match its file type"
    if hashlib.sha256(content).hexdigest() != expected:
        return f"sha256 differs from {BINARY_MANIFEST}"
    return None


def candidate_files() -> list[Path]:
    """Return every file git would publish: tracked or untracked, never ignored."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return sorted(
        path
        for path in (REPO_ROOT / name for name in listed.split("\0") if name)
        if path.is_file() or path.is_symlink()
    )


def scan() -> list[str]:
    findings: list[str] = []
    manifest = load_binary_manifest()
    files = candidate_files()
    for missing in sorted(set(manifest) - {path.relative_to(REPO_ROOT) for path in files}):
        findings.append(f"{missing}: listed in {BINARY_MANIFEST} but not in the tree")
    for path in files:
        relative = path.relative_to(REPO_ROOT)
        if "intake" in relative.parts:
            findings.append(f"{relative}: intake content must remain outside the publishable tree")
            continue
        if path.is_symlink():
            findings.append(f"{relative}: symbolic links are not expected")
            continue
        if path.stat().st_size > 5 * 1024 * 1024:
            findings.append(f"{relative}: file exceeds the 5 MiB source-tree limit")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            problem = binary_finding(relative, path, manifest)
            if problem is not None:
                findings.append(f"{relative}: {problem}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(f"{relative}: non-UTF-8 content in a text file")
            continue
        for label, pattern in DENY_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{relative}: {label}")
    return findings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    findings = scan()
    if findings:
        for finding in findings:
            print(f"FINDING: {finding}")
        print(f"publishable-tree scan failed: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"publishable-tree scan passed: {len(candidate_files())} source files, zero findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

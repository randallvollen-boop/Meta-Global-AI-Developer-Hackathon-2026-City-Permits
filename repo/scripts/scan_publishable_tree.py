#!/usr/bin/env python3
"""Scan the prospective public repository tree for local-only or secret material."""

from __future__ import annotations

import argparse
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


#: The only binary files the tree may carry: bundled permit-type icons.
ALLOWED_IMAGE_DIR = Path("src/acme_city/static/permit-type-icons")


def is_allowed_image(relative: Path, path: Path) -> bool:
    """Return whether a binary file is a genuine WebP permit-type icon."""
    if relative.parent != ALLOWED_IMAGE_DIR or path.suffix.lower() != ".webp":
        return False
    header = path.read_bytes()[:12]
    return header[:4] == b"RIFF" and header[8:12] == b"WEBP"


def is_ignored(path: Path) -> bool:
    relative = path.relative_to(REPO_ROOT)
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", "--", str(relative)],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def candidate_files() -> list[Path]:
    return sorted(
        path
        for path in REPO_ROOT.rglob("*")
        if path.is_file() and ".git" not in path.parts and not is_ignored(path)
    )


def scan() -> list[str]:
    findings: list[str] = []
    for path in candidate_files():
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
            if is_allowed_image(relative, path):
                continue
            findings.append(f"{relative}: unexpected binary or file type")
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

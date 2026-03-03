#!/usr/bin/env python3
"""Fail-fast checks for unresolved merge conflicts.

This script detects two deterministic conflict classes:
1) Unmerged index entries (git conflict state)
2) Committed conflict markers left in tracked files
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


# This test intentionally includes conflict marker strings as fixture data.
ALLOWLIST_MARKER_FILES: set[str] = {"tests/unit/test_issues.py"}


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def check_unmerged_entries() -> list[str]:
    result = run(["git", "diff", "--name-only", "--diff-filter=U"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff --diff-filter=U failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def tracked_files() -> list[str]:
    result = run(["git", "ls-files"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git ls-files failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def find_conflict_markers(path: Path) -> list[tuple[int, str]]:
    markers: list[tuple[int, str]] = []
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return markers
    except OSError:
        return markers

    # Only treat markers as conflicts when they form a full conflict block:
    # <<<<<<< ... [optional ||||||| ...] ... ======= ... >>>>>>>
    in_conflict = False
    saw_separator = False
    start_line = 0

    for idx, line in enumerate(content.splitlines(), start=1):
        if line.startswith("<<<<<<< "):
            in_conflict = True
            saw_separator = False
            start_line = idx
            continue

        if not in_conflict:
            continue

        if line.startswith("======="):
            saw_separator = True
            continue

        if line.startswith(">>>>>>> "):
            if saw_separator:
                markers.append((start_line, "<<<<<<<"))
                markers.append((idx, ">>>>>>>"))
            in_conflict = False
            saw_separator = False
            start_line = 0
            continue

    # Unclosed conflict start should still fail preflight
    if in_conflict and start_line:
        markers.append((start_line, "<<<<<<<"))
    return markers


def main() -> int:
    errors: list[str] = []

    try:
        unmerged = check_unmerged_entries()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if unmerged:
        errors.append("Unmerged files found (resolve and stage these first):")
        errors.extend([f"  - {name}" for name in unmerged])

    try:
        files = tracked_files()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    for rel in files:
        if rel in ALLOWLIST_MARKER_FILES:
            continue
        marker_hits = find_conflict_markers(Path(rel))
        for line_no, marker in marker_hits:
            errors.append(f"{rel}:{line_no}: found {marker} conflict marker")

    if errors:
        print("Merge conflict preflight failed:\n", file=sys.stderr)
        for line in errors:
            print(line, file=sys.stderr)
        return 1

    print("Merge conflict preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

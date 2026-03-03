#!/usr/bin/env python3
"""Fail-fast checks for unresolved and impending merge conflicts.

This script detects two deterministic conflict classes:
1) Unmerged index entries (git conflict state)
2) Committed conflict markers left in tracked files
3) Conflicts that would occur when merging a base ref
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


# This test intentionally includes conflict marker strings as fixture data.
ALLOWLIST_MARKER_FILES: set[str] = {"tests/unit/test_issues.py"}


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True, cwd=cwd)


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


def git_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git rev-parse --show-toplevel failed")
    return Path(result.stdout.strip())


def verify_ref_exists(ref: str) -> None:
    result = run(["git", "rev-parse", "--verify", ref])
    if result.returncode != 0:
        raise RuntimeError(
            f"Base ref '{ref}' not found. Run `git fetch origin` and retry."
        )


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
        if line.startswith("<<<<<<<"):
            in_conflict = True
            saw_separator = False
            start_line = idx
            continue

        if not in_conflict:
            continue

        if line.startswith("======="):
            saw_separator = True
            continue

        if line.startswith(">>>>>>>"):
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


def check_mergeability_against(base_ref: str) -> list[str]:
    """Check whether HEAD can merge cleanly with base_ref.

    Uses a temporary detached worktree so the current working tree/index
    are never modified.
    """
    errors: list[str] = []
    repo = git_root()
    verify_ref_exists(base_ref)

    with tempfile.TemporaryDirectory(prefix="agenttree-merge-preflight-") as tmp:
        tmpdir = Path(tmp)

        add = run(["git", "worktree", "add", "--detach", str(tmpdir), "HEAD"], cwd=repo)
        if add.returncode != 0:
            raise RuntimeError(add.stderr.strip() or "git worktree add failed")

        try:
            merge = run(
                ["git", "merge", "--no-commit", "--no-ff", base_ref],
                cwd=tmpdir,
            )
            if merge.returncode == 0:
                run(["git", "merge", "--abort"], cwd=tmpdir)
                return errors

            unmerged = run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=tmpdir,
            )
            conflict_files = [line.strip() for line in unmerged.stdout.splitlines() if line.strip()]
            if conflict_files:
                errors.append(
                    f"Branch does not merge cleanly with {base_ref}. Conflicting files:"
                )
                errors.extend([f"  - {name}" for name in conflict_files])
            else:
                errors.append(
                    f"Merge simulation against {base_ref} failed (no file list available)."
                )

            run(["git", "merge", "--abort"], cwd=tmpdir)
            return errors
        finally:
            # Force remove in case merge state exists
            run(["git", "worktree", "remove", "--force", str(tmpdir)], cwd=repo)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check for unresolved and impending merge conflicts.",
    )
    parser.add_argument(
        "--base",
        default=None,
        help="Optional base ref to merge-simulate against (e.g. origin/main).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
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

    if args.base:
        try:
            errors.extend(check_mergeability_against(args.base))
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    if errors:
        print("Merge conflict preflight failed:\n", file=sys.stderr)
        for line in errors:
            print(line, file=sys.stderr)
        return 1

    print("Merge conflict preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

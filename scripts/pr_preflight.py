#!/usr/bin/env python3
"""Deterministic preflight checks for the /pr workflow."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys


DEFAULT_TEST_CMD = 'uv run pytest tests/unit -v --tb=short -m "not local_only"'


def run(
    cmd: list[str],
    *,
    capture_output: bool = True,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        capture_output=capture_output,
        check=check,
    )


def run_shell(cmd: str) -> int:
    proc = subprocess.run(cmd, text=True, shell=True)
    return proc.returncode


def current_branch() -> str:
    proc = run(["git", "branch", "--show-current"], check=True)
    return proc.stdout.strip()


def status_porcelain() -> list[str]:
    proc = run(["git", "status", "--porcelain"], check=True)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def print_section(title: str) -> None:
    print(f"\n== {title} ==")


def recommend_base_branch() -> tuple[str, str]:
    """Return (recommended_base, reason)."""
    branch = current_branch()
    try:
        pr_list_proc = run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--json",
                "number,headRefName,baseRefName",
                "--limit",
                "100",
            ],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ("main", "gh unavailable; defaulting to main")

    try:
        prs = json.loads(pr_list_proc.stdout)
    except json.JSONDecodeError:
        return ("main", "unable to parse gh pr list output; defaulting to main")

    candidates: list[tuple[str, int]] = []
    for pr in prs:
        head = pr.get("headRefName")
        if not head or head == branch:
            continue

        run(["git", "fetch", "origin", head], capture_output=True)
        ancestor = run(
            ["git", "merge-base", "--is-ancestor", f"origin/{head}", "HEAD"],
            capture_output=True,
        )
        if ancestor.returncode != 0:
            continue

        distance_proc = run(
            ["git", "rev-list", "--count", f"origin/{head}..HEAD"],
            check=True,
        )
        distance = int(distance_proc.stdout.strip() or "999999")
        candidates.append((head, distance))

    if not candidates:
        return ("main", "no open PR branch is an ancestor of HEAD")

    candidates.sort(key=lambda item: item[1])
    best, distance = candidates[0]
    return (best, f"closest ancestor open PR branch ({distance} commits away)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic /pr preflight checks.")
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Base ref used for merge-simulation conflict checks (default: origin/main).",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip local test command.",
    )
    parser.add_argument(
        "--tests-cmd",
        default=DEFAULT_TEST_CMD,
        help=f'Local test command (default: {DEFAULT_TEST_CMD})',
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print_section("PR Preflight")
    branch = current_branch()
    head = run(["git", "rev-parse", "--short", "HEAD"], check=True).stdout.strip()
    print(f"Branch: {branch}")
    print(f"HEAD:   {head}")

    if branch == "main":
        print("ERROR: You are on main. Create a feature branch first.", file=sys.stderr)
        return 1

    # Hard fail before any test run if conflict markers are present.
    # This avoids spending time on tests when the branch is already invalid.
    print_section("Conflict Marker Gate")
    marker_gate_cmd = [
        "uv",
        "run",
        "python",
        "scripts/check_merge_conflicts.py",
    ]
    print(f"Running: {' '.join(shlex.quote(x) for x in marker_gate_cmd)}")
    marker_gate = run(marker_gate_cmd, capture_output=False)
    if marker_gate.returncode != 0:
        print("ERROR: Unresolved merge conflicts/conflict markers detected.", file=sys.stderr)
        return marker_gate.returncode

    print_section("Working Tree")
    changes = status_porcelain()
    if changes:
        print("Working tree has local changes:")
        for line in changes[:20]:
            print(f"  {line}")
        if len(changes) > 20:
            print(f"  ... and {len(changes) - 20} more")
    else:
        print("Working tree clean.")

    print_section("Diff Summary vs main")
    print(run(["git", "diff", "--stat", "main...HEAD"], check=True).stdout.strip() or "(no diff)")

    print_section("Commits vs main")
    print(run(["git", "log", "--oneline", "main..HEAD"], check=True).stdout.strip() or "(no commits)")

    print_section("Fetch Base")
    fetch = run(["git", "fetch", "origin", "main"])
    if fetch.returncode != 0:
        print(fetch.stderr.strip(), file=sys.stderr)
        return 1
    print("Fetched origin/main.")

    print_section("Conflict Preflight")
    conflict_cmd = [
        "uv",
        "run",
        "python",
        "scripts/check_merge_conflicts.py",
        "--base",
        args.base,
    ]
    print(f"Running: {' '.join(shlex.quote(x) for x in conflict_cmd)}")
    conflict = run(conflict_cmd, capture_output=False)
    if conflict.returncode != 0:
        print("ERROR: Merge conflict preflight failed.", file=sys.stderr)
        return conflict.returncode

    print_section("Recommended Base Branch")
    base, reason = recommend_base_branch()
    print(f"RECOMMENDED_BASE={base}")
    print(f"Reason: {reason}")

    if not args.skip_tests:
        print_section("Local Tests")
        print(f"Running: {args.tests_cmd}")
        rc = run_shell(args.tests_cmd)
        if rc != 0:
            print("ERROR: Local tests failed.", file=sys.stderr)
            return rc
    else:
        print_section("Local Tests")
        print("Skipped (--skip-tests).")

    print_section("Result")
    print("Preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

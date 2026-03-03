#!/usr/bin/env python3
"""Deterministic PR checks/review status for /pr workflow."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time


FAIL_CONCLUSIONS = {
    "failure",
    "timed_out",
    "cancelled",
    "action_required",
    "startup_failure",
}


def run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def get_pr_number(arg_pr: int | None) -> int:
    if arg_pr is not None:
        return arg_pr
    proc = run(["gh", "pr", "view", "--json", "number"], check=True)
    data = json.loads(proc.stdout)
    return int(data["number"])


def repo_owner_name() -> str:
    proc = run(["gh", "repo", "view", "--json", "nameWithOwner"], check=True)
    data = json.loads(proc.stdout)
    return str(data["nameWithOwner"])


def pr_head_sha(pr: int) -> str:
    proc = run(["gh", "pr", "view", str(pr), "--json", "headRefOid"], check=True)
    data = json.loads(proc.stdout)
    return str(data["headRefOid"])


def check_runs(owner_repo: str, sha: str) -> list[dict]:
    proc = run(
        ["gh", "api", f"repos/{owner_repo}/commits/{sha}/check-runs"],
        check=True,
    )
    data = json.loads(proc.stdout)
    return list(data.get("check_runs", []))


def latest_comment(pr: int) -> str:
    proc = run(["gh", "pr", "view", str(pr), "--json", "comments"], check=True)
    data = json.loads(proc.stdout)
    comments = data.get("comments", [])
    if not comments:
        return ""
    body = comments[-1].get("body", "")
    return str(body)


def summarize(checks: list[dict]) -> tuple[int, int, int]:
    total = len(checks)
    pending = sum(1 for c in checks if c.get("status") != "completed")
    failed = sum(
        1
        for c in checks
        if c.get("status") == "completed" and c.get("conclusion") in FAIL_CONCLUSIONS
    )
    return total, pending, failed


def print_status(pr: int, sha: str, checks: list[dict]) -> None:
    total, pending, failed = summarize(checks)
    print(f"PR #{pr} HEAD: {sha}")
    print(f"Checks: total={total} pending={pending} failed={failed}")
    for check in checks:
        name = check.get("name", "unknown")
        status = check.get("status", "unknown")
        conclusion = check.get("conclusion") or "-"
        url = check.get("html_url", "")
        print(f"  - {name}: {status}/{conclusion} {url}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check PR CI/review status.")
    parser.add_argument("--pr", type=int, default=None, help="PR number (auto if omitted).")
    parser.add_argument("--watch", action="store_true", help="Poll until checks complete.")
    parser.add_argument("--interval", type=int, default=15, help="Polling interval seconds.")
    parser.add_argument("--timeout", type=int, default=1800, help="Max watch time seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pr = get_pr_number(args.pr)
    owner_repo = repo_owner_name()

    start = time.time()
    while True:
        sha = pr_head_sha(pr)
        checks = check_runs(owner_repo, sha)
        print_status(pr, sha, checks)

        comment = latest_comment(pr)
        if "CRITICAL_ISSUES_FOUND: YES" in comment:
            print("Review gate failed: latest review comment reports critical issues.")
            return 1

        total, pending, failed = summarize(checks)

        if not args.watch:
            if total == 0:
                print("No checks found for current PR head.")
                return 2
            if pending > 0:
                return 3
            if failed > 0:
                return 1
            print("All checks passed.")
            return 0

        if total > 0 and pending == 0:
            if failed > 0:
                print("Checks completed with failures.")
                return 1
            print("All checks passed.")
            return 0

        if time.time() - start >= args.timeout:
            print("Timed out waiting for checks.")
            return 4

        print(f"Waiting {args.interval}s for checks to complete...")
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        raise

"""Run mypy only on changed Python files under agenttree/."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def _changed_python_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", "main...HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return [path for path in files if path.startswith("agenttree/") and path.endswith(".py")]


def main() -> int:
    repo_root = _repo_root()
    targets = _changed_python_files(repo_root)

    if not targets:
        print("No changed Python files under agenttree/; skipping mypy.")
        return 0

    print(f"Running mypy on {len(targets)} changed files.")
    result = subprocess.run(
        ["mypy", "--ignore-missing-imports", *targets],
        cwd=repo_root,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

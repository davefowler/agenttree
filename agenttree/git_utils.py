"""Git utility functions for AgentTree.

This module provides common git operations used across the codebase.
All functions use subprocess to call git directly.
"""

import re
import subprocess
from pathlib import Path


def get_current_branch() -> str:
    """Get current git branch name.

    Returns:
        Current branch name

    Raises:
        subprocess.CalledProcessError: If git command fails
    """
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def has_uncommitted_changes() -> bool:
    """Check if there are uncommitted changes (staged or unstaged).

    Returns:
        True if there are uncommitted changes, False otherwise
    """
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(result.stdout.strip())


def get_default_branch() -> str:
    """Get the default branch name for the remote.

    Tries to detect from origin/HEAD, falls back to 'main', then 'master'.

    Returns:
        Default branch name (e.g., 'main' or 'master')
    """
    # Try to get from origin/HEAD symbolic ref
    result = subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        # Output is like "refs/remotes/origin/main"
        ref = result.stdout.strip()
        if ref.startswith("refs/remotes/origin/"):
            return ref.replace("refs/remotes/origin/", "")

    # Fallback: check if origin/main exists
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/main"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return "main"

    # Last resort: try master
    return "master"


def has_commits_to_push(branch: str | None = None) -> bool:
    """Check if there are unpushed commits.

    Args:
        branch: Branch name to check (defaults to current branch)

    Returns:
        True if there are unpushed commits, False otherwise
    """
    if branch is None:
        branch = get_current_branch()

    # First try checking against the remote branch with same name
    result = subprocess.run(
        ["git", "log", f"origin/{branch}..HEAD", "--oneline"],
        capture_output=True,
        text=True,
        check=False,  # Don't fail if remote branch doesn't exist
    )

    if result.returncode == 0 and result.stdout.strip():
        return True

    # Check if we have commits beyond upstream (whatever branch we're tracking)
    result = subprocess.run(
        ["git", "rev-list", "@{upstream}..HEAD", "--oneline"],
        capture_output=True,
        text=True,
        check=False,  # Don't fail if no upstream
    )

    if result.returncode == 0 and result.stdout.strip():
        return True

    # Fallback: check if we have ANY local commits not on default branch
    # This handles new branches that haven't been pushed and aren't tracking anything
    default_branch = get_default_branch()
    result = subprocess.run(
        ["git", "log", f"origin/{default_branch}..HEAD", "--oneline"],
        capture_output=True,
        text=True,
        check=False,
    )

    return bool(result.stdout.strip())


def get_git_diff_stats() -> dict[str, int]:
    """Get git diff statistics comparing current branch to default branch.

    Runs `git diff --shortstat <default_branch>...HEAD` and parses the output
    to extract files changed, lines added, and lines removed.

    Returns:
        Dict with keys 'files_changed', 'lines_added', 'lines_removed'.
        Returns zeros if there are no changes or on error.
    """
    default_branch = get_default_branch()

    result = subprocess.run(
        ["git", "diff", "--shortstat", f"{default_branch}...HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )

    stats = {'files_changed': 0, 'lines_added': 0, 'lines_removed': 0}

    if result.returncode != 0 or not result.stdout.strip():
        return stats

    output = result.stdout.strip()

    # Parse "5 files changed, 100 insertions(+), 20 deletions(-)"
    # Handle singular "file" vs "files", and optional insertions/deletions
    files_match = re.search(r'(\d+) files? changed', output)
    insertions_match = re.search(r'(\d+) insertions?\(\+\)', output)
    deletions_match = re.search(r'(\d+) deletions?\(-\)', output)

    if files_match:
        stats['files_changed'] = int(files_match.group(1))
    if insertions_match:
        stats['lines_added'] = int(insertions_match.group(1))
    if deletions_match:
        stats['lines_removed'] = int(deletions_match.group(1))

    return stats


def push_branch_to_remote(branch: str) -> None:
    """Push branch to remote, creating remote branch with same name.

    IMPORTANT: This explicitly pushes local branch to origin/{branch},
    NOT to whatever upstream the branch might be tracking. This ensures
    feature branches don't accidentally push to main.

    Args:
        branch: Branch name to push

    Raises:
        subprocess.CalledProcessError: If push fails
    """
    # Explicitly specify source:destination to avoid pushing to tracked branch
    # e.g., "git push -u origin mybranch:mybranch" ensures we create/update
    # origin/mybranch, not whatever origin/main the branch might be tracking
    subprocess.run(
        ["git", "push", "-u", "origin", f"{branch}:{branch}"],
        check=True,
        capture_output=True,
        text=True,
    )


def get_commits_behind_main(worktree_dir: str | None) -> int:
    """Get the number of commits the worktree is behind local main.

    Compares to local main branch (not origin/main) for fast lookups (~10ms).
    Local main is kept up to date by separate pull operations.

    Args:
        worktree_dir: Path to the worktree directory

    Returns:
        Number of commits behind main, or 0 if unable to determine
    """
    _, behind = get_commits_ahead_behind_main(worktree_dir)
    return behind


def get_commits_ahead_behind_main(worktree_dir: str | None) -> tuple[int, int]:
    """Get the number of commits ahead and behind local main.

    Args:
        worktree_dir: Path to the worktree directory

    Returns:
        Tuple of (ahead, behind) counts
    """
    if not worktree_dir:
        return 0, 0

    worktree_path = Path(worktree_dir)
    if not worktree_path.exists():
        return 0, 0

    try:
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "rev-list", "--left-right", "--count", "HEAD...main"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
        return 0, 0
    except (subprocess.TimeoutExpired, ValueError, Exception):
        return 0, 0


def rebase_issue_branch(issue_id: int | str) -> tuple[bool, str]:
    """Rebase an issue's worktree branch onto the latest main.

    Called from host (approve command, etc.) to ensure feature branches
    are up to date before implementation begins.

    Args:
        issue_id: Issue ID to rebase

    Returns:
        Tuple of (success, message)
    """
    from agenttree.issues import get_issue

    issue = get_issue(issue_id)
    if not issue:
        return False, f"Issue {issue_id} not found"

    if not issue.worktree_dir:
        return False, f"Issue {issue_id} has no worktree directory"

    worktree_path = Path(issue.worktree_dir)
    if not worktree_path.exists():
        return False, f"Worktree not found: {issue.worktree_dir}"

    try:
        # First, commit any uncommitted changes (so rebase doesn't fail)
        # Stage all changes
        subprocess.run(
            ["git", "-C", str(worktree_path), "add", "-A"],
            capture_output=True,
            timeout=10,
        )
        # Check if there are staged changes
        diff_result = subprocess.run(
            ["git", "-C", str(worktree_path), "diff", "--cached", "--quiet"],
            capture_output=True,
            timeout=10,
        )
        if diff_result.returncode != 0:
            # There are staged changes - commit them
            subprocess.run(
                ["git", "-C", str(worktree_path), "commit", "-m", "Auto-commit before rebase"],
                capture_output=True,
                text=True,
                timeout=30,
            )

        # Fetch latest from origin
        subprocess.run(
            ["git", "-C", str(worktree_path), "fetch", "origin", "main"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Rebase onto origin/main
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "rebase", "origin/main"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            # Check for conflicts
            if "conflict" in result.stderr.lower() or "conflict" in result.stdout.lower():
                # Abort the failed rebase
                subprocess.run(
                    ["git", "-C", str(worktree_path), "rebase", "--abort"],
                    capture_output=True,
                    timeout=10,
                )
                return False, "Rebase conflicts - manual resolution needed"
            return False, f"Rebase failed: {result.stderr}"

        return True, "Rebased successfully"

    except subprocess.TimeoutExpired:
        return False, "Rebase timed out"
    except Exception as e:
        return False, f"Rebase error: {e}"


def get_repo_remote_name() -> str:
    """Get the repository name from git remote.

    Parses owner/repo from URLs like:
    - git@github.com:owner/repo.git
    - https://github.com/owner/repo.git
    - https://github.com/owner/repo

    Returns:
        Repository name in format "owner/repo"

    Raises:
        subprocess.CalledProcessError: If git command fails
        ValueError: If URL format is unrecognized
    """
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=True,
    )
    url = result.stdout.strip()

    # Remove .git suffix if present
    if url.endswith(".git"):
        url = url[:-4]

    # Parse SSH URL: git@github.com:owner/repo
    if url.startswith("git@"):
        match = re.search(r"git@[^:]+:(.+)", url)
        if match:
            return match.group(1)

    # Parse HTTPS URL: https://github.com/owner/repo
    if url.startswith("https://") or url.startswith("http://"):
        match = re.search(r"github\.com/(.+)", url)
        if match:
            return match.group(1)

    raise ValueError(f"Unrecognized remote URL format: {url}")

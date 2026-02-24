"""Pull Request actions for AgentTree.

This module provides functions for creating, merging, and managing
GitHub pull requests as part of the workflow.
"""

import re
import subprocess
import time
from pathlib import Path
from typing import Any

from rich.console import Console

from agenttree.environment import is_running_in_container
from agenttree.git_utils import has_uncommitted_changes
from agenttree.issues import Issue

console = Console()


def _action_create_pr(issue_dir: Path, issue_id: str = "", issue_title: str = "", branch: str = "", **kwargs: Any) -> None:
    """Create PR for an issue (manager stage hook - runs on host).

    This hook runs on host for manager stages (role: manager).
    Agents can't push, so PR creation is handled by the host.

    Workflow:
    1. Agent advances to implementation_review (does nothing - manager stage)
    2. Host sync calls check_manager_stages()
    3. For issues in manager stages, host runs post_start hooks
    4. This hook (create_pr) calls ensure_pr_for_issue() to create the PR

    Raises:
        RuntimeError: If PR creation fails (prevents silent progression without a PR).
    """
    if not issue_id:
        raise RuntimeError("create_pr hook: no issue_id provided")

    if not ensure_pr_for_issue(issue_id):
        raise RuntimeError(f"Failed to create PR for issue #{issue_id}. Will retry on next heartbeat.")


def _try_update_pr_branch(pr_number: int) -> bool:
    """Try to update a PR branch by merging base branch into it.

    Uses GitHub API to merge the base branch (main) into the PR head branch.
    This resolves simple merge situations without needing manual intervention.

    Returns:
        True if branch was updated (or already up to date), False on conflict.
    """
    try:
        result = subprocess.run(
            ["gh", "api", "-X", "PUT",
             f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/update-branch",
             "-f", "expected_head_oid="],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            console.print("[dim]Branch updated with latest main[/dim]")
            time.sleep(3)  # Give GitHub a moment to process
            return True
        # 422 = conflicts, 409 = already up to date
        if "merge conflict" in result.stderr.lower() or "conflict" in result.stderr.lower():
            return False
        # Already up to date is fine
        return True
    except Exception:
        return True  # Best-effort; proceed to merge attempt anyway


def _action_merge_pr(pr_number: int | None, **kwargs: Any) -> None:
    """Merge PR for an issue. Tries to update branch first, redirects on conflict.

    Flow:
        1. Try to merge directly
        2. If merge fails (likely conflicts): try updating branch from main
        3. If update succeeds: retry merge
        4. If conflicts: raise StageRedirect so developer can rebase

    Raises:
        StageRedirect: If PR has merge conflicts that need developer intervention.
        RuntimeError: If merge fails for non-conflict reasons.
    """
    # Import here to avoid circular imports
    from agenttree.hooks import StageRedirect, run_host_hooks

    if pr_number is None:
        raise RuntimeError("No PR number provided for merge")

    # If in container, skip - host will handle
    if is_running_in_container():
        console.print("[yellow]Running in container - PR will be merged by host[/yellow]")
        return

    from agenttree.config import load_config
    from agenttree.github import merge_pr

    config = load_config()

    # First attempt: try to merge directly
    console.print(f"[dim]Merging PR #{pr_number}...[/dim]")
    try:
        merge_pr(pr_number, method=config.merge_strategy)
    except RuntimeError as e:
        error_msg = str(e).lower()

        if "already merged" in error_msg:
            console.print(f"[dim]PR #{pr_number} already merged[/dim]")
            return  # Desired state achieved

        is_conflict = any(word in error_msg for word in ("conflict", "not mergeable", "merge blocked"))

        if not is_conflict:
            raise  # Non-conflict errors fail loudly

        # Conflict: try updating branch from main first
        console.print("[yellow]Merge blocked - trying to update branch from main...[/yellow]")
        if _try_update_pr_branch(pr_number):
            # Branch updated, retry merge
            try:
                merge_pr(pr_number, method=config.merge_strategy)
            except RuntimeError:
                # Still can't merge after update - redirect to developer
                raise StageRedirect(
                    "implement.code",
                    reason=f"PR #{pr_number} can't be merged after branch update. Developer needs to rebase on main.",
                )
        else:
            # Can't auto-update (real conflicts) - redirect to developer
            raise StageRedirect(
                "implement.code",
                reason=f"PR #{pr_number} has merge conflicts. Developer needs to rebase on main.",
            )

    console.print(f"[green]✓ PR #{pr_number} merged[/green]")

    # Run post_merge hooks
    if config.hooks.post_merge:
        run_host_hooks(config.hooks.post_merge, {
            "issue_id": kwargs.get("issue_id", ""),
            "pr_number": pr_number,
            "branch": kwargs.get("branch", ""),
        })


def get_pr_approval_status(pr_number: int) -> bool:
    """Check if a PR is approved.

    Args:
        pr_number: GitHub PR number

    Returns:
        True if PR is approved, False otherwise
    """
    try:
        from agenttree.github import is_pr_approved
        return is_pr_approved(pr_number)
    except Exception:
        return False


def ensure_pr_for_issue(issue_id: int | str) -> bool:
    """Ensure a PR exists for an issue in a manager stage.

    Called by host via create_pr hook for manager stages (role: manager).
    Stage check is done by check_manager_stages(), not here.

    Args:
        issue_id: Issue ID to create PR for

    Returns:
        True if PR was created or already exists

    Raises:
        RuntimeError: If issue not found, no branch, worktree missing, push or PR creation fails
    """
    # Import here to avoid circular imports
    from agenttree.hooks import run_host_hooks

    from agenttree.issues import get_issue, update_issue_metadata
    from agenttree.github import create_pr
    from agenttree.config import load_config

    issue = get_issue(issue_id)
    if not issue:
        raise RuntimeError(f"Issue #{issue_id} not found")

    # Already has PR - idempotent
    if issue.pr_number:
        return True

    # Need branch info
    if not issue.branch:
        raise RuntimeError(f"Issue #{issue_id} has no branch")

    # Find the worktree for this issue
    if not issue.worktree_dir:
        raise RuntimeError(f"Issue #{issue_id} has no worktree_dir set")
    worktree_path = Path(issue.worktree_dir)
    if not worktree_path.exists():
        raise RuntimeError(f"Worktree {issue.worktree_dir} does not exist for issue #{issue_id}")

    console.print(f"[dim]Creating PR for issue #{issue_id} from host...[/dim]")

    # Auto-commit any uncommitted changes before pushing
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
        console.print("[dim]Auto-committing uncommitted changes...[/dim]")
        subprocess.run(
            ["git", "-C", str(worktree_path), "commit", "-m", f"Issue #{issue_id}: auto-commit before PR"],
            capture_output=True,
            text=True,
            timeout=30,
        )

    # Squash all branch commits into one clean commit before pushing.
    # Agent restarts create WIP + merge commits that bloat the PR.
    subprocess.run(
        ["git", "-C", str(worktree_path), "fetch", "origin", "main"],
        capture_output=True, timeout=30,
    )
    merge_base = subprocess.run(
        ["git", "-C", str(worktree_path), "merge-base", "HEAD", "origin/main"],
        capture_output=True, text=True, timeout=10,
    )
    if merge_base.returncode == 0:
        base_sha = merge_base.stdout.strip()
        commit_count = subprocess.run(
            ["git", "-C", str(worktree_path), "rev-list", "--count", f"{base_sha}..HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        count = int(commit_count.stdout.strip()) if commit_count.returncode == 0 else 0
        if count > 1:
            console.print(f"[dim]Squashing {count} commits into 1 for clean PR...[/dim]")
            subprocess.run(
                ["git", "-C", str(worktree_path), "reset", "--soft", base_sha],
                capture_output=True, timeout=10,
            )
            subprocess.run(
                ["git", "-C", str(worktree_path), "commit", "-m",
                 f"Issue #{issue_id}: {issue.title}"],
                capture_output=True, text=True, timeout=30,
            )

    # Detect the actual branch in the worktree (issue.branch may be stale/wrong)
    actual_branch_result = subprocess.run(
        ["git", "-C", str(worktree_path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, timeout=10,
    )
    actual_branch = actual_branch_result.stdout.strip() if actual_branch_result.returncode == 0 else ""
    push_branch = actual_branch or issue.branch

    if actual_branch and actual_branch != issue.branch:
        console.print(f"[yellow]Branch mismatch: issue says '{issue.branch}', worktree is on '{actual_branch}'. Using worktree branch.[/yellow]")
        # Fix stored branch name
        update_issue_metadata(issue_id, branch=actual_branch)

    # Push the branch from the worktree (force-with-lease since squash rewrites history)
    result = subprocess.run(
        ["git", "-C", str(worktree_path), "push", "--force-with-lease", "-u", "origin", push_branch],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to push branch for issue #{issue_id}: {result.stderr.strip()}")

    # Create PR with link back to issue
    title = f"[Issue {issue.id}] {issue.title}"

    # Build PR body with issue link and context
    body = "## Summary\n\n"
    body += f"Implementation for **Issue #{issue.id}**: {issue.title}\n\n"
    body += f"**Issue link:** [View in AgentTree Flow](http://localhost:8080/flow?issue={issue.id})\n\n"

    # Try to include brief context from spec.md if it exists
    spec_path = worktree_path / "_agenttree" / "issues" / issue.dir_name / "spec.md"

    if spec_path.exists():
        try:
            spec_content = spec_path.read_text()
            # Extract first few lines of Approach section if present
            if "## Approach" in spec_content:
                approach_start = spec_content.index("## Approach")
                approach_section = spec_content[approach_start:approach_start + 500]
                # Find end of section (next ## or end)
                if "\n## " in approach_section[10:]:
                    approach_section = approach_section[:approach_section.index("\n## ", 10)]
                body += f"### Approach\n{approach_section[12:].strip()[:400]}...\n\n"
        except Exception:
            pass

    body += "---\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"

    try:
        pr = create_pr(title=title, body=body, branch=push_branch, base="main")
        update_issue_metadata(issue.id, pr_number=pr.number, pr_url=pr.url)
        console.print(f"[green]✓ PR #{pr.number} created for issue #{issue_id}[/green]")

        # Run post_pr_create hooks
        config = load_config()
        if config.hooks.post_pr_create:
            run_host_hooks(config.hooks.post_pr_create, {
                "issue_id": issue.id,
                "issue_title": issue.title,
                "pr_number": pr.number,
                "pr_url": pr.url,
                "branch": issue.branch,
            })

        return True
    except Exception as e:
        error_msg = str(e)
        # Check if PR already exists - extract PR URL and update issue
        if "already exists" in error_msg:
            # Try to extract PR URL from error message
            match = re.search(r'https://github\.com/[^/]+/[^/]+/pull/(\d+)', error_msg)
            if match:
                pr_number = int(match.group(1))
                pr_url = match.group(0)
                update_issue_metadata(issue.id, pr_number=pr_number, pr_url=pr_url)
                console.print(f"[green]✓ PR #{pr_number} already exists for issue #{issue_id}[/green]")
                return True
        raise RuntimeError(f"Failed to create PR for issue #{issue_id}: {e}") from e



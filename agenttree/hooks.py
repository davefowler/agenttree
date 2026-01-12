"""Hook system for agenttree stage transitions.

This module provides a comprehensive hook system that allows validation,
automation, setup, and cleanup during workflow stage transitions.

Hook Types:
-----------
1. **Pre-transition hooks** - Validation before stage transitions (can block)
2. **Post-transition hooks** - Actions after successful transitions
3. **On-enter hooks** - Setup when entering a stage
4. **On-exit hooks** - Cleanup when leaving a stage

Usage:
------
    from agenttree.hooks import pre_transition, post_transition, on_enter, on_exit
    from agenttree.issues import Stage, Issue
    from agenttree.hooks import ValidationError

    @pre_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
    def require_commits(issue: Issue):
        if not has_commits_to_push():
            raise ValidationError("No commits to push")

    @post_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
    def create_pull_request(issue: Issue):
        # Create PR automatically
        ...

Hook Execution Order:
--------------------
1. on_exit - Cleanup from current stage
2. pre_transition - Validation (BLOCKS if ValidationError raised)
3. Stage update - The actual transition
4. post_transition - Actions (logs warnings but doesn't block)
5. on_enter - Setup for new stage
"""

import re
import subprocess
from typing import Callable, Dict, List, Optional, Tuple

from rich.console import Console

from agenttree.issues import Issue, Stage

console = Console()


class ValidationError(Exception):
    """Raised when pre-hook validation fails to block a stage transition."""

    pass


class HookRegistry:
    """Central registry for all hooks.

    Stores hooks for different stage transitions and provides methods to
    register and execute hooks.
    """

    def __init__(self):
        """Initialize empty hook dictionaries."""
        # Pre-transition: key = (from_stage, to_stage), value = list of hooks
        self.pre_transition: Dict[Tuple[Stage, Stage], List[Callable]] = {}

        # Post-transition: key = (from_stage, to_stage), value = list of hooks
        self.post_transition: Dict[Tuple[Stage, Stage], List[Callable]] = {}

        # On-enter: key = stage, value = list of hooks
        self.on_enter: Dict[Stage, List[Callable]] = {}

        # On-exit: key = stage, value = list of hooks
        self.on_exit: Dict[Stage, List[Callable]] = {}

    def register_pre_transition(
        self, from_stage: Stage, to_stage: Stage, func: Callable
    ):
        """Register a pre-transition hook.

        Args:
            from_stage: Stage transitioning from
            to_stage: Stage transitioning to
            func: Hook function to register
        """
        key = (from_stage, to_stage)
        if key not in self.pre_transition:
            self.pre_transition[key] = []
        self.pre_transition[key].append(func)

    def register_post_transition(
        self, from_stage: Stage, to_stage: Stage, func: Callable
    ):
        """Register a post-transition hook.

        Args:
            from_stage: Stage transitioning from
            to_stage: Stage transitioning to
            func: Hook function to register
        """
        key = (from_stage, to_stage)
        if key not in self.post_transition:
            self.post_transition[key] = []
        self.post_transition[key].append(func)

    def register_on_enter(self, stage: Stage, func: Callable):
        """Register an on-enter hook.

        Args:
            stage: Stage being entered
            func: Hook function to register
        """
        if stage not in self.on_enter:
            self.on_enter[stage] = []
        self.on_enter[stage].append(func)

    def register_on_exit(self, stage: Stage, func: Callable):
        """Register an on-exit hook.

        Args:
            stage: Stage being exited
            func: Hook function to register
        """
        if stage not in self.on_exit:
            self.on_exit[stage] = []
        self.on_exit[stage].append(func)

    def execute_pre_transition(
        self, issue: Issue, from_stage: Stage, to_stage: Stage
    ):
        """Execute all pre-transition hooks.

        Raises ValidationError if any hook fails, which blocks the transition.

        Args:
            issue: Issue being transitioned
            from_stage: Stage transitioning from
            to_stage: Stage transitioning to

        Raises:
            ValidationError: If validation fails
        """
        key = (from_stage, to_stage)
        for hook in self.pre_transition.get(key, []):
            hook(issue)  # Can raise ValidationError to block transition

    def execute_post_transition(
        self, issue: Issue, from_stage: Stage, to_stage: Stage
    ):
        """Execute all post-transition hooks.

        Logs errors but doesn't block - stage has already changed.

        Args:
            issue: Issue that was transitioned
            from_stage: Stage transitioned from
            to_stage: Stage transitioned to
        """
        key = (from_stage, to_stage)
        for hook in self.post_transition.get(key, []):
            try:
                hook(issue)
            except Exception as e:
                # Log error but don't fail - stage already changed
                console.print(f"[yellow]Warning: Post-transition hook failed: {e}[/yellow]")

    def execute_on_enter(self, issue: Issue, stage: Stage):
        """Execute all on-enter hooks for a stage.

        Logs errors but doesn't block.

        Args:
            issue: Issue entering the stage
            stage: Stage being entered
        """
        for hook in self.on_enter.get(stage, []):
            try:
                hook(issue)
            except Exception as e:
                console.print(f"[yellow]Warning: On-enter hook failed: {e}[/yellow]")

    def execute_on_exit(self, issue: Issue, stage: Stage):
        """Execute all on-exit hooks for a stage.

        Logs errors but doesn't block.

        Args:
            issue: Issue exiting the stage
            stage: Stage being exited
        """
        for hook in self.on_exit.get(stage, []):
            try:
                hook(issue)
            except Exception as e:
                console.print(f"[yellow]Warning: On-exit hook failed: {e}[/yellow]")


# Global registry instance
_registry = HookRegistry()


def get_registry() -> HookRegistry:
    """Get the global hook registry.

    Useful for testing or inspecting registered hooks.

    Returns:
        The global HookRegistry instance
    """
    return _registry


def execute_transition_hooks(
    issue: Issue, from_stage: Stage, to_stage: Stage
) -> None:
    """Execute all hooks for a stage transition in correct order.

    Execution order:
    1. on_exit hooks for from_stage
    2. pre_transition hooks (can raise ValidationError to block)
    3. post_transition hooks (logs errors but continues)
    4. on_enter hooks for to_stage

    Note: The actual stage update should happen between steps 2 and 3,
    but that's handled by the caller (cli.py).

    Args:
        issue: Issue being transitioned
        from_stage: Stage transitioning from
        to_stage: Stage transitioning to

    Raises:
        ValidationError: If pre_transition validation fails
    """
    # 1. Exit current stage
    _registry.execute_on_exit(issue, from_stage)

    # 2. Pre-transition validation (can block)
    _registry.execute_pre_transition(issue, from_stage, to_stage)

    # Note: Stage update happens here (in caller)

    # 3. Post-transition actions
    _registry.execute_post_transition(issue, from_stage, to_stage)

    # 4. Enter new stage
    _registry.execute_on_enter(issue, to_stage)


# Decorator functions for registering hooks


def pre_transition(from_stage: Stage, to_stage: Stage):
    """Decorator to register a pre-transition hook.

    Pre-transition hooks run before a stage transition and can block it
    by raising ValidationError.

    Example:
        @pre_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
        def require_commits(issue: Issue):
            if not has_commits():
                raise ValidationError("No commits to push")

    Args:
        from_stage: Stage transitioning from
        to_stage: Stage transitioning to

    Returns:
        Decorator function
    """

    def decorator(func: Callable):
        _registry.register_pre_transition(from_stage, to_stage, func)
        return func

    return decorator


def post_transition(from_stage: Stage, to_stage: Stage):
    """Decorator to register a post-transition hook.

    Post-transition hooks run after a successful stage transition.
    They cannot block the transition (stage has already changed).

    Example:
        @post_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
        def create_pull_request(issue: Issue):
            # Create PR automatically
            ...

    Args:
        from_stage: Stage transitioning from
        to_stage: Stage transitioning to

    Returns:
        Decorator function
    """

    def decorator(func: Callable):
        _registry.register_post_transition(from_stage, to_stage, func)
        return func

    return decorator


def on_enter(stage: Stage):
    """Decorator to register an on-enter hook.

    On-enter hooks run when entering a stage to set up the environment.

    Example:
        @on_enter(Stage.RESEARCH)
        def setup_research(issue: Issue):
            # Create plan.md from template
            ...

    Args:
        stage: Stage being entered

    Returns:
        Decorator function
    """

    def decorator(func: Callable):
        _registry.register_on_enter(stage, func)
        return func

    return decorator


def on_exit(stage: Stage):
    """Decorator to register an on-exit hook.

    On-exit hooks run when leaving a stage to clean up.

    Example:
        @on_exit(Stage.IMPLEMENT)
        def cleanup_implement(issue: Issue):
            # Archive temporary files
            ...

    Args:
        stage: Stage being exited

    Returns:
        Decorator function
    """

    def decorator(func: Callable):
        _registry.register_on_exit(stage, func)
        return func

    return decorator


# Git utility functions


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


def has_commits_to_push(branch: Optional[str] = None) -> bool:
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


def generate_pr_body(issue: Issue) -> str:
    """Generate PR body for the issue.

    Args:
        issue: Issue object

    Returns:
        Formatted PR body text
    """
    issue_id = issue.id

    return f"""## Issue #{issue_id}: {issue.title}

Automated PR created by agenttree workflow.

### Summary
This PR implements the changes for issue #{issue_id}.

### Review Checklist
- [ ] Code follows project conventions
- [ ] Tests pass
- [ ] Changes match the approved plan

---
*Generated by [agenttree](https://github.com/davefowler/agenttree)*
"""


def generate_commit_message(issue: Issue, stage: Stage) -> str:
    """Generate commit message from issue context and stage.

    Args:
        issue: Issue object
        stage: Current stage

    Returns:
        Formatted commit message
    """
    stage_prefixes = {
        Stage.PROBLEM: "Problem statement",
        Stage.RESEARCH: "Research",
        Stage.IMPLEMENT: "Implement",
        Stage.ACCEPTED: "Complete",
    }
    prefix = stage_prefixes.get(stage, stage.value.title())
    return f"{prefix} #{issue.id}: {issue.title}"


def auto_commit_changes(issue: Issue, stage: Stage) -> bool:
    """Auto-commit all changes with stage-appropriate message.

    Args:
        issue: Issue object
        stage: Current stage

    Returns:
        True if changes were committed, False if nothing to commit
    """
    if not has_uncommitted_changes():
        return False

    # Generate commit message from issue and stage context
    message = generate_commit_message(issue, stage)

    # Stage all changes
    subprocess.run(["git", "add", "-A"], check=True)

    # Commit with generated message
    subprocess.run(
        ["git", "commit", "-m", message],
        check=True,
    )
    return True


# Pre-transition validation hooks


@pre_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
def require_commits_for_review(issue: Issue):
    """Require that there are commits to push before creating PR.

    Blocks transition if there are no commits to push.

    Args:
        issue: Issue being transitioned

    Raises:
        ValidationError: If no commits to push
    """
    if not has_commits_to_push():
        raise ValidationError(
            "No commits to push. Make code changes and commit them before running 'agenttree next'."
        )


@pre_transition(Stage.IMPLEMENTATION_REVIEW, Stage.ACCEPTED)
def require_pr_approval(issue: Issue):
    """Require that PR is approved before merging.

    Blocks transition if PR doesn't exist or is not approved.

    Args:
        issue: Issue being transitioned

    Raises:
        ValidationError: If PR not found or not approved
    """
    if not issue.pr_number:
        raise ValidationError(
            "No PR number found. Cannot merge without a PR."
        )

    from agenttree.github import is_pr_approved

    if not is_pr_approved(issue.pr_number):
        raise ValidationError(
            f"PR #{issue.pr_number} requires approval before merging. "
            f"Ask a human to review and approve the PR."
        )


# Post-transition action hooks


@post_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
def create_pull_request_hook(issue: Issue):
    """Create PR when transitioning to implementation review.

    Automatically commits any uncommitted changes, pushes the branch,
    and creates a pull request.

    Args:
        issue: Issue that was transitioned
    """
    from agenttree.github import create_pr
    from agenttree.issues import update_issue_metadata

    # Get current branch
    branch = get_current_branch()

    # Auto-commit any uncommitted changes before pushing
    if has_uncommitted_changes():
        console.print(f"[dim]Auto-committing uncommitted changes...[/dim]")
        auto_commit_changes(issue, Stage.IMPLEMENT)

    # Push to remote (explicitly to origin/{branch}, not tracked branch)
    console.print(f"[dim]Pushing {branch} to origin/{branch}...[/dim]")
    push_branch_to_remote(branch)

    # Generate PR title and body
    title = f"[Issue {issue.id}] {issue.title}"
    body = generate_pr_body(issue)

    # Create PR
    console.print(f"[dim]Creating pull request...[/dim]")
    pr = create_pr(title=title, body=body, branch=branch, base="main")

    # Update issue with PR info
    update_issue_metadata(
        issue.id,
        pr_number=pr.number,
        pr_url=pr.url,
        branch=branch
    )

    console.print(f"[green]✓ PR created: {pr.url}[/green]")


@post_transition(Stage.IMPLEMENTATION_REVIEW, Stage.ACCEPTED)
def merge_pull_request_hook(issue: Issue):
    """Merge PR when transitioning to accepted.

    Args:
        issue: Issue that was transitioned
    """
    if not issue.pr_number:
        console.print("[yellow]Warning: No PR to merge[/yellow]")
        return

    console.print(f"[dim]Merging PR #{issue.pr_number}...[/dim]")

    from agenttree.github import merge_pr

    merge_pr(issue.pr_number, method="squash")

    console.print(f"[green]✓ PR #{issue.pr_number} merged and branch deleted[/green]")

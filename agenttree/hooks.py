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
from pathlib import Path
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

        # On-enter substage: key = (stage, substage), value = list of hooks
        self.on_enter_substage: Dict[Tuple[Stage, str], List[Callable]] = {}

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

    def register_on_enter(self, stage: Stage, func: Callable, substage: Optional[str] = None):
        """Register an on-enter hook.

        Args:
            stage: Stage being entered
            func: Hook function to register
            substage: Optional substage (if None, runs for entire stage)
        """
        if substage:
            key = (stage, substage)
            if key not in self.on_enter_substage:
                self.on_enter_substage[key] = []
            self.on_enter_substage[key].append(func)
        else:
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

    def execute_on_enter(self, issue: Issue, stage: Stage, substage: Optional[str] = None):
        """Execute all on-enter hooks for a stage/substage.

        Logs errors but doesn't block.

        Args:
            issue: Issue entering the stage
            stage: Stage being entered
            substage: Optional substage being entered
        """
        # Execute stage-level hooks
        for hook in self.on_enter.get(stage, []):
            try:
                hook(issue)
            except Exception as e:
                console.print(f"[yellow]Warning: On-enter hook failed: {e}[/yellow]")

        # Execute substage-specific hooks
        if substage:
            key = (stage, substage)
            for hook in self.on_enter_substage.get(key, []):
                try:
                    hook(issue)
                except Exception as e:
                    console.print(f"[yellow]Warning: On-enter substage hook failed: {e}[/yellow]")

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


def execute_pre_hooks(
    issue: Issue,
    from_stage: Stage,
    to_stage: Stage,
) -> None:
    """Execute hooks that run BEFORE stage update.

    Execution order:
    1. on_exit hooks for from_stage
    2. pre_transition hooks (can raise ValidationError to block)

    Call this BEFORE updating the issue stage. If ValidationError is raised,
    the transition should be blocked.

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


def execute_post_hooks(
    issue: Issue,
    from_stage: Stage,
    to_stage: Stage,
    to_substage: Optional[str] = None,
) -> None:
    """Execute hooks that run AFTER stage update.

    Execution order:
    1. post_transition hooks (logs errors but continues)
    2. on_enter hooks for to_stage (and substage if provided)

    Call this AFTER the issue stage has been updated in the database.

    Args:
        issue: Issue that was transitioned
        from_stage: Stage transitioned from
        to_stage: Stage transitioned to
        to_substage: Substage being entered (optional)
    """
    # 1. Post-transition actions
    _registry.execute_post_transition(issue, from_stage, to_stage)

    # 2. Enter new stage (and substage)
    _registry.execute_on_enter(issue, to_stage, to_substage)


def execute_transition_hooks(
    issue: Issue,
    from_stage: Stage,
    to_stage: Stage,
    to_substage: Optional[str] = None,
) -> None:
    """Execute all hooks for a stage transition (DEPRECATED - use split functions).

    This function is kept for backwards compatibility but doesn't correctly
    handle the timing of hooks relative to stage updates. New code should use:
    - execute_pre_hooks() before update_issue_stage()
    - execute_post_hooks() after update_issue_stage()

    Args:
        issue: Issue being transitioned
        from_stage: Stage transitioning from
        to_stage: Stage transitioning to
        to_substage: Substage being entered (optional)

    Raises:
        ValidationError: If pre_transition validation fails
    """
    execute_pre_hooks(issue, from_stage, to_stage)
    # Note: Stage update should happen here in caller - but doesn't with this API
    execute_post_hooks(issue, from_stage, to_stage, to_substage)


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


def on_enter(stage: Stage, substage: Optional[str] = None):
    """Decorator to register an on-enter hook.

    On-enter hooks run when entering a stage to set up the environment.
    Can optionally target a specific substage.

    Example:
        @on_enter(Stage.RESEARCH)
        def setup_research(issue: Issue):
            # Create plan.md from template
            ...

        @on_enter(Stage.IMPLEMENT, substage="code_review")
        def setup_code_review(issue: Issue):
            # Create review.md from template
            ...

    Args:
        stage: Stage being entered
        substage: Optional substage to target (if None, runs for entire stage)

    Returns:
        Decorator function
    """

    def decorator(func: Callable):
        _registry.register_on_enter(stage, func, substage)
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


@pre_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
def require_review_md_for_pr(issue: Issue):
    """Require that review.md exists with no unresolved Critical Issues before creating PR.

    Blocks transition if:
    - review.md doesn't exist in issue directory
    - Critical Issues section contains any items (checked or unchecked)

    Args:
        issue: Issue being transitioned

    Raises:
        ValidationError: If review.md is missing or has unresolved critical issues
    """
    import re

    issue_dir = _get_issue_dir(issue)
    review_path = issue_dir / "review.md"

    if not review_path.exists():
        raise ValidationError(
            "review.md not found. Complete the code_review substage and fill out review.md "
            "before creating a PR. Run 'agenttree next' from implement.debug to enter code_review."
        )

    content = review_path.read_text()

    # Find the Critical Issues section
    # Match variations like "## Critical Issues" or "## Critical Issues (Blocking)"
    critical_match = re.search(r'##\s*Critical Issues.*?\n(.*?)(?=\n##|\n---|\Z)', content, re.DOTALL | re.IGNORECASE)

    if critical_match:
        critical_section = critical_match.group(1)

        # Remove HTML comments
        critical_section = re.sub(r'<!--.*?-->', '', critical_section, flags=re.DOTALL)

        # Check for any list items (- [ ] or - [x])
        if re.search(r'-\s*\[[x ]\]', critical_section, re.IGNORECASE):
            raise ValidationError(
                "Critical Issues section in review.md is not empty. "
                "Fix all critical issues and remove them from the list before creating a PR. "
                "(Fixed issues should be removed, not checked off.)"
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


def is_running_in_container() -> bool:
    """Check if we're running inside a container.

    Checks for AGENTTREE_CONTAINER env var (set by agenttree when launching)
    as well as common container indicators.

    Returns:
        True if running in a container, False otherwise
    """
    import os
    # Check for agenttree-specific env var first (most reliable)
    if os.environ.get("AGENTTREE_CONTAINER") == "1":
        return True
    # Fall back to common container indicators
    return (
        os.path.exists("/.dockerenv") or
        os.path.exists("/run/.containerenv") or
        os.environ.get("CONTAINER_RUNTIME") is not None
    )


@post_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
def create_pull_request_hook(issue: Issue):
    """Create PR when transitioning to implementation review.

    If running in a container (no push access), only commits locally.
    The host will handle push/PR creation when it sees the stage change.

    Args:
        issue: Issue that was transitioned
    """
    from agenttree.issues import update_issue_metadata

    # Get current branch
    branch = get_current_branch()

    # Auto-commit any uncommitted changes
    if has_uncommitted_changes():
        console.print(f"[dim]Auto-committing uncommitted changes...[/dim]")
        auto_commit_changes(issue, Stage.IMPLEMENT)

    # Update issue with branch info
    update_issue_metadata(issue.id, branch=branch)

    # If in container, skip remote operations - host will handle them
    if is_running_in_container():
        console.print(f"[yellow]Running in container - PR will be created by host[/yellow]")
        console.print(f"[dim]Branch: {branch} (committed locally, awaiting push)[/dim]")
        return

    # On host: do the full push/PR
    from agenttree.github import create_pr

    # Push to remote
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


def ensure_pr_for_issue(issue_id: str) -> bool:
    """Ensure a PR exists for an issue at implementation_review stage.

    Called by host (sync or web server) to create PRs for issues
    where the agent couldn't push.

    Args:
        issue_id: Issue ID to create PR for

    Returns:
        True if PR was created or already exists, False on failure
    """
    from agenttree.issues import get_issue, update_issue_metadata
    from agenttree.github import create_pr
    from pathlib import Path
    import subprocess

    issue = get_issue(issue_id)
    if not issue:
        return False

    # Already has PR
    if issue.pr_number:
        return True

    # Not at implementation_review stage
    if issue.stage != "implementation_review":
        return False

    # Need branch info
    if not issue.branch:
        console.print(f"[yellow]Issue #{issue_id} has no branch info[/yellow]")
        return False

    # Find the worktree for this issue
    worktree_path = Path.cwd() / ".worktrees" / f"issue-{issue_id.zfill(3)}-{issue.slug[:30]}"
    if not worktree_path.exists():
        # Try without leading zeros
        for p in Path.cwd().glob(f".worktrees/issue-{issue_id}*"):
            worktree_path = p
            break

    if not worktree_path.exists():
        console.print(f"[yellow]Worktree not found for issue #{issue_id}[/yellow]")
        return False

    console.print(f"[dim]Creating PR for issue #{issue_id} from host...[/dim]")

    # Push the branch from the worktree
    result = subprocess.run(
        ["git", "-C", str(worktree_path), "push", "-u", "origin", issue.branch],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        console.print(f"[red]Failed to push: {result.stderr}[/red]")
        return False

    # Create PR
    title = f"[Issue {issue.id}] {issue.title}"
    body = f"## Summary\n\nImplementation for issue #{issue.id}: {issue.title}\n\n"
    body += f"🤖 Generated with [Claude Code](https://claude.com/claude-code)"

    try:
        pr = create_pr(title=title, body=body, branch=issue.branch, base="main")
        update_issue_metadata(issue.id, pr_number=pr.number, pr_url=pr.url)
        console.print(f"[green]✓ PR #{pr.number} created for issue #{issue_id}[/green]")
        return True
    except Exception as e:
        console.print(f"[red]Failed to create PR: {e}[/red]")
        return False


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


@post_transition(Stage.IMPLEMENTATION_REVIEW, Stage.ACCEPTED)
def cleanup_issue_agent_hook(issue: Issue):
    """Clean up agent resources when issue is accepted.

    Stops container, removes worktree, frees port.

    Args:
        issue: Issue that was transitioned
    """
    from agenttree.state import get_active_agent, unregister_agent

    agent = get_active_agent(issue.id)
    if not agent:
        return  # No agent to clean up

    console.print(f"[dim]Cleaning up agent for issue #{issue.id}...[/dim]")

    # Stop tmux session
    try:
        from agenttree.tmux import kill_session, session_exists
        if session_exists(agent.tmux_session):
            kill_session(agent.tmux_session)
            console.print(f"[dim]  Stopped tmux session: {agent.tmux_session}[/dim]")
    except Exception as e:
        console.print(f"[yellow]  Warning: Could not stop tmux session: {e}[/yellow]")

    # Stop container (if running)
    try:
        result = subprocess.run(
            ["docker", "stop", agent.container],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            console.print(f"[dim]  Stopped container: {agent.container}[/dim]")

        # Remove container
        subprocess.run(
            ["docker", "rm", agent.container],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as e:
        console.print(f"[yellow]  Warning: Could not stop container: {e}[/yellow]")

    # Unregister agent (frees port)
    unregister_agent(issue.id)
    console.print(f"[green]✓ Agent cleaned up for issue #{issue.id}[/green]")


# On-enter hooks for auto-creating documentation


def _get_issue_dir(issue: Issue) -> Path:
    """Get the issue directory path."""
    from agenttree.issues import get_issue_dir
    issue_dir = get_issue_dir(issue.id)
    if not issue_dir:
        raise ValueError(f"Issue directory not found for issue {issue.id}")
    return issue_dir


def _copy_template(template_name: str, dest_path: Path, issue: Issue) -> bool:
    """Copy a template file to destination, filling in placeholders.

    Args:
        template_name: Name of template file (e.g., "plan.md")
        dest_path: Destination path for the file
        issue: Issue object for filling placeholders

    Returns:
        True if file was created, False if it already exists
    """
    if dest_path.exists():
        return False  # Don't overwrite existing files

    from agenttree.issues import get_agenttrees_path

    template_path = get_agenttrees_path() / "templates" / template_name
    if not template_path.exists():
        console.print(f"[yellow]Warning: Template {template_name} not found[/yellow]")
        return False

    # Read template and fill placeholders
    content = template_path.read_text()

    # Common placeholder substitutions
    placeholders = {
        "{{issue_id}}": issue.id,
        "{{branch}}": issue.branch or "N/A",
        "{{pr_url}}": issue.pr_url or "N/A",
        "{{files_changed}}": "TBD",
        "{{lines_added}}": "TBD",
        "{{lines_removed}}": "TBD",
    }

    for placeholder, value in placeholders.items():
        content = content.replace(placeholder, str(value))

    # Write the file
    dest_path.write_text(content)
    return True


@on_enter(Stage.RESEARCH)
def create_research_md_on_research(issue: Issue):
    """Auto-create research.md when entering research stage.

    Args:
        issue: Issue entering research stage
    """
    issue_dir = _get_issue_dir(issue)
    research_path = issue_dir / "research.md"

    if _copy_template("research.md", research_path, issue):
        console.print(f"[dim]Created research.md in issue directory[/dim]")


@on_enter(Stage.PLAN)
def create_spec_md_on_plan(issue: Issue):
    """Auto-create spec.md when entering plan stage.

    Args:
        issue: Issue entering plan stage
    """
    issue_dir = _get_issue_dir(issue)
    spec_path = issue_dir / "spec.md"

    if _copy_template("spec.md", spec_path, issue):
        console.print(f"[dim]Created spec.md in issue directory[/dim]")


@on_enter(Stage.PLAN_ASSESS)
def create_spec_review_md_on_plan_assess(issue: Issue):
    """Auto-create spec_review.md when entering plan_assess stage.

    Args:
        issue: Issue entering plan_assess stage
    """
    issue_dir = _get_issue_dir(issue)
    spec_review_path = issue_dir / "spec_review.md"

    if _copy_template("spec_review.md", spec_review_path, issue):
        console.print(f"[dim]Created spec_review.md in issue directory[/dim]")


@on_enter(Stage.IMPLEMENT, substage="code_review")
def create_review_md_on_code_review(issue: Issue):
    """Auto-create review.md when entering code_review substage.

    Args:
        issue: Issue entering code_review substage
    """
    issue_dir = _get_issue_dir(issue)
    review_path = issue_dir / "review.md"

    if _copy_template("review.md", review_path, issue):
        console.print(f"[dim]Created review.md in issue directory[/dim]")


# Pre-transition hooks to enforce workflow order


@pre_transition(Stage.PLAN_REVIEW, Stage.IMPLEMENT)
def require_spec_md_for_implement(issue: Issue):
    """Require that spec.md exists and has content before implementing.

    Blocks transition if spec.md doesn't exist or is mostly empty.

    Args:
        issue: Issue being transitioned

    Raises:
        ValidationError: If spec.md doesn't exist or is incomplete
    """
    issue_dir = _get_issue_dir(issue)

    # Check for spec.md (new name) or plan.md (legacy)
    spec_path = issue_dir / "spec.md"
    plan_path = issue_dir / "plan.md"

    if spec_path.exists():
        content = spec_path.read_text()
        file_name = "spec.md"
    elif plan_path.exists():
        content = plan_path.read_text()
        file_name = "plan.md"
    else:
        raise ValidationError(
            "spec.md not found. Complete the plan stage and fill out spec.md "
            "before moving to implementation."
        )

    # Look for filled-in sections - at least Approach should have content
    approach_section = "## Approach"
    if approach_section in content:
        # Find content after "## Approach" header
        approach_idx = content.index(approach_section) + len(approach_section)
        next_section_idx = content.find("##", approach_idx)
        if next_section_idx == -1:
            next_section_idx = len(content)

        approach_content = content[approach_idx:next_section_idx].strip()
        # Remove HTML comments
        import re
        approach_content = re.sub(r'<!--.*?-->', '', approach_content, flags=re.DOTALL).strip()

        if len(approach_content) < 20:  # Minimum 20 chars of actual content
            raise ValidationError(
                f"{file_name} Approach section is too short. Describe your implementation "
                "approach before moving to implementation stage."
            )

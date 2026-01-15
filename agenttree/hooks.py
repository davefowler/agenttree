"""Hook system for agenttree stage transitions.

This module provides a config-driven hook system that allows validation,
automation, setup, and cleanup during workflow stage transitions.

Hook Types (configured in config.py DEFAULT_STAGES):
----------------------------------------------------
1. **on_exit hooks** - Validation/actions when exiting a stage (can block)
2. **on_enter hooks** - Setup when entering a stage (logs warnings but doesn't block)

Built-in Validators:
-------------------
- file_exists: Check that a file exists
- has_commits: Check that there are unpushed commits
- field_check: Check a YAML field value meets min/max threshold
- section_check: Check a markdown section (empty, not_empty, all_checked)
- pr_approved: Check that a PR is approved

Built-in Actions:
----------------
- create_file: Create a file from a template
- create_pr: Create a pull request
- merge_pr: Merge a pull request

Usage:
------
    from agenttree.hooks import execute_exit_hooks, execute_enter_hooks, ValidationError

    # Execute exit hooks (validation, can block)
    execute_exit_hooks(issue, stage, substage)

    # Execute enter hooks (setup, logs warnings)
    execute_enter_hooks(issue, stage, substage)

Configuration:
-------------
Hooks are configured in config.py DEFAULT_STAGES via on_exit and on_enter lists:

    StageConfig(
        name="implement",
        on_exit=[{"type": "create_pr"}],
        substages={
            "feedback": SubstageConfig(
                name="feedback",
                on_exit=[
                    {"type": "has_commits"},
                    {"type": "file_exists", "file": "review.md"},
                ],
            ),
        },
    )
"""

import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console

from agenttree.issues import (
    Issue,
    DEFINE,
    RESEARCH,
    PLAN,
    IMPLEMENT,
    ACCEPTED,
)

console = Console()


class ValidationError(Exception):
    """Raised when pre-hook validation fails to block a stage transition."""

    pass


# =============================================================================
# Config-Driven Validators (New System)
# =============================================================================


def _action_create_pr(issue_dir: Path, issue_id: str = "", issue_title: str = "", branch: str = "", **kwargs: Any) -> None:
    """Create PR for an issue (action hook helper).

    If running in a container, commits locally and lets host handle PR creation.
    """
    from agenttree.issues import update_issue_metadata

    # Get current branch if not provided
    if not branch:
        branch = get_current_branch()

    # Auto-commit any uncommitted changes
    if has_uncommitted_changes():
        console.print(f"[dim]Auto-committing uncommitted changes...[/dim]")
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True,
            check=False
        )
        subprocess.run(
            ["git", "commit", "-m", f"Issue #{issue_id}: auto-commit before PR"],
            capture_output=True,
            check=False
        )

    # Update issue with branch info
    if issue_id:
        update_issue_metadata(issue_id, branch=branch)

    # If in container, skip remote operations
    if is_running_in_container():
        console.print(f"[yellow]Running in container - PR will be created by host[/yellow]")
        console.print(f"[dim]Branch: {branch} (committed locally, awaiting push)[/dim]")
        return

    # On host: do the full push/PR
    from agenttree.github import create_pr

    # Push to remote
    console.print(f"[dim]Pushing {branch} to origin/{branch}...[/dim]")
    push_branch_to_remote(branch)

    # Create PR
    title = f"[Issue {issue_id}] {issue_title}" if issue_id else f"PR for {branch}"
    body = f"## Summary\n\nImplementation for issue #{issue_id}: {issue_title}\n\n" if issue_id else ""
    body += "🤖 Generated with [Claude Code](https://claude.com/claude-code)"

    console.print(f"[dim]Creating pull request...[/dim]")
    pr = create_pr(title=title, body=body, branch=branch, base="main")

    # Update issue with PR info
    if issue_id:
        update_issue_metadata(issue_id, pr_number=pr.number, pr_url=pr.url, branch=branch)

    console.print(f"[green]✓ PR created: {pr.url}[/green]")

    # Request Cursor code review
    try:
        subprocess.run(
            ["gh", "pr", "comment", str(pr.number), "--body", "@cursor do a code review"],
            capture_output=True,
            check=True,
        )
        console.print(f"[dim]Requested Cursor code review[/dim]")
    except Exception:
        pass  # Non-critical


def _action_merge_pr(pr_number: Optional[int], **kwargs: Any) -> None:
    """Merge PR for an issue (action hook helper)."""
    if pr_number is None:
        console.print("[yellow]No PR to merge[/yellow]")
        return

    # If in container, skip - host will handle
    if is_running_in_container():
        console.print(f"[yellow]Running in container - PR will be merged by host[/yellow]")
        return

    from agenttree.github import merge_pr

    console.print(f"[dim]Merging PR #{pr_number}...[/dim]")
    merge_pr(pr_number, method="squash")
    console.print(f"[green]✓ PR #{pr_number} merged[/green]")


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


def run_builtin_validator(
    issue_dir: Path,
    hook: Dict[str, Any],
    pr_number: Optional[int] = None,
    **kwargs: Any
) -> List[str]:
    """Run a built-in validator and return errors.

    Args:
        issue_dir: Path to issue directory (worktree)
        hook: Hook configuration dict with 'type' and parameters
        pr_number: Optional PR number for pr_approved validator
        **kwargs: Additional context (unused for now)

    Returns:
        List of error messages (empty if validation passes)
    """
    import yaml

    hook_type = hook.get("type")
    errors: List[str] = []

    if hook_type == "file_exists":
        file_path = issue_dir / hook["file"]
        if not file_path.exists():
            errors.append(f"File '{hook['file']}' does not exist")

    elif hook_type == "has_commits":
        if not has_commits_to_push():
            errors.append(
                "No commits to push. Make code changes and commit them before proceeding."
            )

    elif hook_type == "field_check":
        file_path = issue_dir / hook["file"]
        if not file_path.exists():
            errors.append(f"File '{hook['file']}' not found for field check")
        else:
            content = file_path.read_text()
            # Extract YAML from markdown code block
            yaml_match = re.search(r'```yaml\s*\n(.*?)```', content, re.DOTALL)
            if not yaml_match:
                errors.append(f"No YAML block found in {hook['file']}")
            else:
                try:
                    data = yaml.safe_load(yaml_match.group(1))
                    # Navigate nested path like "scores.average"
                    path_parts = hook["path"].split(".")
                    value = data
                    for part in path_parts:
                        if value is None or not isinstance(value, dict):
                            value = None
                            break
                        value = value.get(part)

                    if value is None:
                        errors.append(f"Field '{hook['path']}' not found in {hook['file']}")
                    elif "min" in hook and float(value) < hook["min"]:
                        errors.append(
                            f"Field '{hook['path']}' value {value} is below minimum {hook['min']}"
                        )
                    elif "max" in hook and float(value) > hook["max"]:
                        errors.append(
                            f"Field '{hook['path']}' value {value} is above maximum {hook['max']}"
                        )
                except yaml.YAMLError as e:
                    errors.append(f"Failed to parse YAML in {hook['file']}: {e}")

    elif hook_type == "section_check":
        file_path = issue_dir / hook["file"]
        if not file_path.exists():
            errors.append(f"File '{hook['file']}' not found for section check")
        else:
            content = file_path.read_text()
            section = hook["section"]
            expect = hook["expect"]

            # Find section content (between ## Section and next ## or end)
            pattern = rf'^##\s*{re.escape(section)}.*?\n(.*?)(?=\n##|\Z)'
            section_match = re.search(pattern, content, re.MULTILINE | re.DOTALL)

            if not section_match:
                errors.append(f"Section '{section}' not found in {hook['file']}")
            else:
                section_content = section_match.group(1)
                # Remove HTML comments
                section_content = re.sub(r'<!--.*?-->', '', section_content, flags=re.DOTALL)

                if expect == "empty":
                    # Check for list items
                    if re.search(r'^\s*[-*]\s+', section_content, re.MULTILINE):
                        errors.append(
                            f"Section '{section}' in {hook['file']} is not empty"
                        )
                elif expect == "not_empty":
                    # Check if section has content beyond whitespace
                    if not section_content.strip():
                        errors.append(
                            f"Section '{section}' in {hook['file']} is empty"
                        )
                elif expect == "all_checked":
                    # Find unchecked checkboxes
                    unchecked = re.findall(r'-\s*\[\s*\]\s*(.*)', section_content)
                    if unchecked:
                        items = ", ".join(item.strip() for item in unchecked[:3])
                        if len(unchecked) > 3:
                            items += f" (and {len(unchecked) - 3} more)"
                        errors.append(
                            f"Unchecked items in '{section}': {items}"
                        )

    elif hook_type == "pr_approved":
        if pr_number is None:
            errors.append("No PR number available to check approval status")
        elif not get_pr_approval_status(pr_number):
            errors.append(f"PR #{pr_number} is not approved")

    # Action types (side effects, don't return errors on success)
    elif hook_type == "create_file":
        # Create a file from template if it doesn't exist
        template = hook.get("template")
        dest = hook.get("dest")
        if template and dest:
            template_path = Path("_agenttree/templates") / template
            dest_path = issue_dir / dest
            if not dest_path.exists() and template_path.exists():
                dest_path.write_text(template_path.read_text())
                console.print(f"[dim]Created {dest} from template[/dim]")

    elif hook_type == "create_pr":
        # Create PR on transition to implementation_review
        try:
            _action_create_pr(issue_dir, **kwargs)
        except Exception as e:
            errors.append(f"Failed to create PR: {e}")

    elif hook_type == "merge_pr":
        # Merge PR on transition to accepted
        try:
            _action_merge_pr(pr_number, **kwargs)
        except Exception as e:
            errors.append(f"Failed to merge PR: {e}")

    else:
        # Unknown type - ignore silently (allows for future extensions)
        pass

    return errors


def run_command_hook(
    issue_dir: Path,
    hook: Dict[str, Any],
    issue_id: str = "",
    issue_title: str = "",
    branch: str = "",
    stage: str = "",
    substage: str = "",
    **kwargs: Any
) -> List[str]:
    """Run a shell command hook and return errors.

    Args:
        issue_dir: Path to run command in
        hook: Hook configuration dict with 'command' and optional 'context', 'timeout'
        issue_id: Issue ID for template variable substitution
        issue_title: Issue title for template variable substitution
        branch: Branch name for template variable substitution
        stage: Current stage for template variable substitution
        substage: Current substage for template variable substitution
        **kwargs: Additional template variables

    Returns:
        List of error messages (empty if command succeeds)
    """
    command = hook["command"]

    # Replace template variables
    command = command.replace("{{issue_id}}", issue_id)
    command = command.replace("{{issue_title}}", issue_title)
    command = command.replace("{{branch}}", branch)
    command = command.replace("{{stage}}", stage)
    command = command.replace("{{substage}}", substage)

    timeout = hook.get("timeout", 30)  # Default 30 seconds
    context = hook.get("context", "")

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=issue_dir,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        if result.returncode != 0:
            output = result.stdout + result.stderr
            if context:
                return [f"{context} failed:\n{output.strip()}"]
            return [output.strip() or f"Command failed: {command}"]

        return []

    except subprocess.TimeoutExpired:
        if context:
            return [f"{context} timed out after {timeout} seconds"]
        return [f"Command timed out after {timeout} seconds: {command}"]


def execute_hooks(
    issue_dir: Path,
    stage: str,
    substage_config: Any,  # SubstageConfig or StageConfig
    event: str,
    pr_number: Optional[int] = None,
    **kwargs: Any
) -> List[str]:
    """Execute all hooks for an event and collect errors.

    Args:
        issue_dir: Path to issue directory
        stage: Current stage name
        substage_config: SubstageConfig or StageConfig with hook definitions
        event: "on_exit" or "on_enter"
        pr_number: Optional PR number for pr_approved validator
        **kwargs: Additional context for hooks

    Returns:
        List of all error messages from failed hooks
    """
    errors: List[str] = []

    # Auto-check output file on exit (if not optional)
    if event == "on_exit":
        output_file = getattr(substage_config, "output", None)
        output_optional = getattr(substage_config, "output_optional", False)

        if output_file and not output_optional:
            file_path = issue_dir / output_file
            if not file_path.exists():
                errors.append(f"Required output file '{output_file}' does not exist")

    # Get configured hooks
    hooks = getattr(substage_config, event, [])

    # Run each hook
    for hook in hooks:
        if "type" in hook:
            # Built-in validator
            errors.extend(run_builtin_validator(issue_dir, hook, pr_number=pr_number, **kwargs))
        elif "command" in hook:
            # Shell command hook
            errors.extend(run_command_hook(issue_dir, hook, **kwargs))

    return errors


def execute_exit_hooks(issue: "Issue", stage: str, substage: Optional[str] = None) -> None:
    """Execute on_exit hooks for a stage/substage. Raises ValidationError if any fail.

    This is the config-driven replacement for execute_pre_hooks.

    Args:
        issue: Issue being transitioned
        stage: Current stage name
        substage: Current substage name (optional)

    Raises:
        ValidationError: If any validation fails (blocks transition)
    """
    from agenttree.config import load_config
    from agenttree.issues import get_issue_dir

    config = load_config()
    stage_config = config.get_stage(stage)
    if not stage_config:
        return  # Unknown stage, skip hooks

    # Get the appropriate config (substage or stage)
    if substage:
        hook_config = stage_config.get_substage(substage) or stage_config
    else:
        hook_config = stage_config

    # Get issue directory
    issue_dir = get_issue_dir(issue.id)
    if not issue_dir:
        return  # No issue directory, skip hooks

    # Execute hooks
    errors = execute_hooks(
        issue_dir,
        stage,
        hook_config,
        "on_exit",
        pr_number=issue.pr_number,
        issue_id=issue.id,
        issue_title=issue.title,
        branch=issue.branch or "",
        substage=substage or "",
    )

    if errors:
        if len(errors) == 1:
            raise ValidationError(errors[0])
        else:
            msg = "Multiple validation errors:\n"
            for i, error in enumerate(errors, 1):
                msg += f"  {i}. {error}\n"
            raise ValidationError(msg.strip())


def execute_enter_hooks(issue: "Issue", stage: str, substage: Optional[str] = None) -> None:
    """Execute on_enter hooks for a stage/substage. Logs warnings but doesn't block.

    This is the config-driven replacement for execute_post_hooks.

    Args:
        issue: Issue that was transitioned
        stage: New stage name
        substage: New substage name (optional)
    """
    from agenttree.config import load_config
    from agenttree.issues import get_issue_dir

    config = load_config()
    stage_config = config.get_stage(stage)
    if not stage_config:
        return  # Unknown stage, skip hooks

    # Get the appropriate config (substage or stage)
    if substage:
        hook_config = stage_config.get_substage(substage) or stage_config
    else:
        hook_config = stage_config

    # Get issue directory
    issue_dir = get_issue_dir(issue.id)
    if not issue_dir:
        return  # No issue directory, skip hooks

    # Execute hooks
    errors = execute_hooks(
        issue_dir,
        stage,
        hook_config,
        "on_enter",
        pr_number=issue.pr_number,
        issue_id=issue.id,
        issue_title=issue.title,
        branch=issue.branch or "",
        substage=substage or "",
    )

    # Log warnings but don't block
    if errors:
        for error in errors:
            console.print(f"[yellow]Warning: {error}[/yellow]")

    # Special handling for ACCEPTED stage - cleanup agent and check blocked issues
    if stage == ACCEPTED:
        cleanup_issue_agent(issue)
        check_and_start_blocked_issues(issue)


# Aliases for backward compatibility during transition
execute_pre_hooks = execute_exit_hooks
execute_post_hooks = execute_enter_hooks


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


def generate_commit_message(issue: Issue, stage: str) -> str:
    """Generate commit message from issue context and stage.

    Args:
        issue: Issue object
        stage: Current stage

    Returns:
        Formatted commit message with GitHub issue linking
    """
    stage_prefixes = {
        DEFINE: "Define problem for",
        RESEARCH: "Research for",
        PLAN: "Plan for",
        IMPLEMENT: "Implement",
        ACCEPTED: "Complete",
    }
    prefix = stage_prefixes.get(stage, stage.replace("_", " ").title() + " for")

    # Build message with issue reference
    message = f"{prefix} issue #{issue.id}: {issue.title}"

    # Add GitHub issue linking if we have a linked GitHub issue
    if issue.github_issue:
        message += f"\n\nFixes #{issue.github_issue}"

    return message


def auto_commit_changes(issue: Issue, stage: str) -> bool:
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

        # Request Cursor code review
        try:
            subprocess.run(
                ["gh", "pr", "comment", str(pr.number), "--body", "@cursor do a code review"],
                capture_output=True,
                check=True,
            )
            console.print(f"[dim]Requested Cursor code review[/dim]")
        except Exception:
            pass  # Non-critical, don't fail if comment fails

        return True
    except Exception as e:
        error_msg = str(e)
        # Check if PR already exists - extract PR URL and update issue
        if "already exists" in error_msg:
            # Try to extract PR URL from error message
            import re
            match = re.search(r'https://github\.com/[^/]+/[^/]+/pull/(\d+)', error_msg)
            if match:
                pr_number = int(match.group(1))
                pr_url = match.group(0)
                update_issue_metadata(issue.id, pr_number=pr_number, pr_url=pr_url)
                console.print(f"[green]✓ PR #{pr_number} already exists for issue #{issue_id}[/green]")
                return True
        console.print(f"[red]Failed to create PR: {e}[/red]")
        return False


def cleanup_issue_agent(issue: Issue) -> None:
    """Clean up agent resources when issue is accepted.

    Stops tmux session, stops container, frees port.

    Args:
        issue: Issue that was transitioned to accepted
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

    # Stop container (if running) - use detected runtime (container/docker/podman)
    try:
        from agenttree.container import get_container_runtime
        runtime = get_container_runtime()
        if runtime.runtime:
            result = subprocess.run(
                [runtime.runtime, "stop", agent.container],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                console.print(f"[dim]  Stopped container: {agent.container}[/dim]")

            # Remove container
            subprocess.run(
                [runtime.runtime, "rm", agent.container],
                capture_output=True,
                text=True,
                check=False,
            )
    except Exception as e:
        console.print(f"[yellow]  Warning: Could not stop container: {e}[/yellow]")

    # Unregister agent (frees port)
    unregister_agent(issue.id)
    console.print(f"[green]✓ Agent cleaned up for issue #{issue.id}[/green]")


def check_and_start_blocked_issues(issue: Issue) -> None:
    """Check for blocked issues that can now be started when a dependency completes.

    When an issue reaches ACCEPTED stage, scan all backlog issues that depend on it.
    For each, check if ALL dependencies are now met, and if so, auto-start them.

    This hook only runs on the host (not in containers) since agent dispatch
    requires host-level git and container operations.

    Args:
        issue: Issue that just reached ACCEPTED stage
    """
    # Only run on host
    if is_running_in_container():
        return

    from agenttree.issues import get_blocked_issues, check_dependencies_met

    blocked = get_blocked_issues(issue.id)
    if not blocked:
        return

    console.print(f"\n[cyan]Checking blocked issues after #{issue.id} completed...[/cyan]")

    for blocked_issue in blocked:
        # Check if ALL dependencies are now met
        all_met, unmet = check_dependencies_met(blocked_issue)
        if all_met:
            console.print(f"[green]→ Issue #{blocked_issue.id} ready to start (all dependencies met)[/green]")
            try:
                # Use subprocess to call agenttree start (safer than importing CLI)
                result = subprocess.run(
                    ["agenttree", "start", blocked_issue.id],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0:
                    console.print(f"[green]✓ Started agent for issue #{blocked_issue.id}[/green]")
                else:
                    console.print(f"[yellow]Could not start issue #{blocked_issue.id}: {result.stderr}[/yellow]")
            except Exception as e:
                console.print(f"[yellow]Failed to start issue #{blocked_issue.id}: {e}[/yellow]")
        else:
            console.print(f"[dim]→ Issue #{blocked_issue.id} still blocked by: {', '.join(unmet)}[/dim]")

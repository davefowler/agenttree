"""Hook system for agenttree stage transitions.

This module provides a config-driven hook system that allows validation,
automation, setup, and cleanup during workflow stage transitions.

Hook Types (configured in .agenttree.yaml stages):
----------------------------------------------------
1. **pre_completion hooks** - Validation/actions when completing a stage (can block)
2. **post_start hooks** - Setup when starting a stage (logs warnings but doesn't block)

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
- rebase: Rebase branch onto main (host-only)

Usage:
------
    from agenttree.hooks import execute_exit_hooks, execute_enter_hooks, ValidationError

    # Execute pre_completion hooks (validation, can block)
    execute_exit_hooks(issue, stage, substage)

    # Execute post_start hooks (setup, logs warnings)
    execute_enter_hooks(issue, stage, substage)

Configuration:
-------------
Hooks are configured in .agenttree.yaml via pre_completion and post_start lists:

    StageConfig(
        name="implement",
        pre_completion=[{"create_pr": True}],
        substages={
            "feedback": SubstageConfig(
                name="feedback",
                pre_completion=[
                    {"has_commits": True},
                    {"file_exists": "review.md"},
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

# Known hook types (used to detect hook type from key)
# Note: create_pr was removed - PR creation is handled by host sync via ensure_pr_for_issue()
HOOK_TYPES = {
    "file_exists", "has_commits", "field_check", "section_check", "pr_approved",
    "create_file", "merge_pr", "run", "rebase", "cleanup_agent", "start_blocked_issues",
    "min_words", "has_list_items", "contains"
}


def parse_hook(hook: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    """Parse a hook configuration dict to extract hook type and parameters.

    Supports both new format (hook type as key) and legacy format (type field).

    New format examples:
        {"file_exists": "review.md"}
        {"field_check": {"file": "review.md", "path": "average", "min": 7}}
        {"run": "agenttree lint", "optional": True, "context": "Lint"}
        {"create_pr": {}}
        {"rebase": {}}

    Legacy format (still supported):
        {"type": "file_exists", "file": "review.md"}
        {"command": "agenttree lint"}

    Args:
        hook: Hook configuration dict

    Returns:
        Tuple of (hook_type, parameters_dict)
    """
    # Legacy format: explicit "type" field
    if "type" in hook:
        hook_type = hook["type"]
        params = {k: v for k, v in hook.items() if k != "type"}
        return hook_type, params

    # Legacy format: "command" field (now "run")
    if "command" in hook:
        params = {k: v for k, v in hook.items() if k != "command"}
        params["command"] = hook["command"]
        return "run", params

    # New format: hook type is a key in the dict
    for key in hook:
        if key in HOOK_TYPES:
            value = hook[key]
            # Collect other keys as additional params (e.g., optional, context)
            extra_params = {k: v for k, v in hook.items() if k != key}

            if isinstance(value, dict):
                # {"field_check": {"file": "review.md", "path": "average"}}
                return key, {**value, **extra_params}
            elif isinstance(value, str):
                # {"file_exists": "review.md"} or {"run": "agenttree lint"}
                if key == "run":
                    return key, {"command": value, **extra_params}
                else:
                    return key, {"file": value, **extra_params}
            elif value is None or value == {}:
                # {"create_pr": {}} or {"create_pr": null}
                return key, extra_params
            else:
                return key, {"value": value, **extra_params}

    # Unknown hook type
    return "unknown", hook


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

    # Update issue with branch and worktree info
    # Use current working directory as worktree (not issue_dir which is _agenttree/issues/...)
    if issue_id:
        worktree_path = str(Path.cwd().resolve())
        update_issue_metadata(issue_id, branch=branch, worktree_dir=worktree_path)

    # If in container, skip remote operations - host will detect and push unpushed commits
    if is_running_in_container():
        console.print(f"[yellow]Running in container - PR will be created by host[/yellow]")
        console.print(f"[dim]Branch: {branch} (committed locally, awaiting push)[/dim]")
        console.print(f"[dim]Worktree: {issue_dir}[/dim]")
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

    # Run post_pr_create hooks
    from agenttree.config import load_config
    config = load_config()
    if config.hooks.post_pr_create:
        run_host_hooks(config.hooks.post_pr_create, {
            "issue_id": issue_id,
            "issue_title": issue_title,
            "pr_number": pr.number,
            "pr_url": pr.url,
            "branch": branch,
        })


def _action_merge_pr(pr_number: Optional[int], **kwargs: Any) -> None:
    """Merge PR for an issue (action hook helper)."""
    if pr_number is None:
        console.print("[yellow]No PR to merge[/yellow]")
        return

    # If in container, skip - host will handle
    if is_running_in_container():
        console.print(f"[yellow]Running in container - PR will be merged by host[/yellow]")
        return

    from agenttree.config import load_config
    from agenttree.github import merge_pr

    config = load_config()

    console.print(f"[dim]Merging PR #{pr_number}...[/dim]")
    merge_pr(pr_number, method=config.merge_strategy)
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


def run_builtin_validator(
    issue_dir: Path,
    hook: Dict[str, Any],
    pr_number: Optional[int] = None,
    **kwargs: Any
) -> List[str]:
    """Run a built-in validator and return errors.

    Args:
        issue_dir: Path to issue directory (worktree)
        hook: Hook configuration dict (new or legacy format)
        pr_number: Optional PR number for pr_approved validator
        **kwargs: Additional context (unused for now)

    Returns:
        List of error messages (empty if validation passes)
    """
    import yaml

    hook_type, params = parse_hook(hook)
    errors: List[str] = []

    if hook_type == "file_exists":
        file_path = issue_dir / params["file"]
        if not file_path.exists():
            errors.append(f"File '{params['file']}' does not exist")

    elif hook_type == "has_commits":
        if not has_commits_to_push():
            errors.append(
                "No commits to push. Make code changes and commit them before proceeding."
            )

    elif hook_type == "field_check":
        file_path = issue_dir / params["file"]
        if not file_path.exists():
            errors.append(f"File '{params['file']}' not found for field check")
        else:
            content = file_path.read_text()
            # Extract YAML from markdown code block
            yaml_match = re.search(r'```yaml\s*\n(.*?)```', content, re.DOTALL)
            if not yaml_match:
                errors.append(f"No YAML block found in {params['file']}")
            else:
                try:
                    data = yaml.safe_load(yaml_match.group(1))
                    # Navigate nested path like "scores.average"
                    path_parts = params["path"].split(".")
                    value = data
                    for part in path_parts:
                        if value is None or not isinstance(value, dict):
                            value = None
                            break
                        value = value.get(part)

                    if value is None:
                        errors.append(f"Field '{params['path']}' not found in {params['file']}")
                    elif "min" in params and float(value) < params["min"]:
                        errors.append(
                            f"Field '{params['path']}' value {value} is below minimum {params['min']}"
                        )
                    elif "max" in params and float(value) > params["max"]:
                        errors.append(
                            f"Field '{params['path']}' value {value} is above maximum {params['max']}"
                        )
                except yaml.YAMLError as e:
                    errors.append(f"Failed to parse YAML in {params['file']}: {e}")

    elif hook_type == "section_check":
        file_path = issue_dir / params["file"]
        if not file_path.exists():
            errors.append(f"File '{params['file']}' not found for section check")
        else:
            content = file_path.read_text()
            section = params["section"]
            expect = params["expect"]

            # Find section content (between ##/### Section and next ##/### or end)
            # Supports both h2 (##) and h3 (###) headers
            pattern = rf'^##[#]?\s*{re.escape(section)}.*?\n(.*?)(?=\n##|\Z)'
            section_match = re.search(pattern, content, re.MULTILINE | re.DOTALL)

            if not section_match:
                errors.append(f"Section '{section}' not found in {params['file']}")
            else:
                section_content = section_match.group(1)
                # Remove HTML comments
                section_content = re.sub(r'<!--.*?-->', '', section_content, flags=re.DOTALL)

                if expect == "empty":
                    # Check for list items
                    if re.search(r'^\s*[-*]\s+', section_content, re.MULTILINE):
                        errors.append(
                            f"Section '{section}' in {params['file']} is not empty"
                        )
                elif expect == "not_empty":
                    # Check if section has content beyond whitespace
                    if not section_content.strip():
                        errors.append(
                            f"Section '{section}' in {params['file']} is empty"
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

    elif hook_type == "min_words":
        # Check that a file or section has at least N words
        file_path = issue_dir / params["file"]
        min_count = params.get("min", 10)
        section = params.get("section")

        if not file_path.exists():
            errors.append(f"File '{params['file']}' not found for min_words check")
        else:
            content = file_path.read_text()

            if section:
                # Find section content
                pattern = rf'^##[#]?\s*{re.escape(section)}.*?\n(.*?)(?=\n##|\Z)'
                section_match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
                if not section_match:
                    errors.append(f"Section '{section}' not found in {params['file']}")
                else:
                    content = section_match.group(1)

            # Count words (split on whitespace, filter empty)
            words = [w for w in content.split() if w.strip()]
            if len(words) < min_count:
                target = f"section '{section}'" if section else f"file '{params['file']}'"
                errors.append(
                    f"{target.capitalize()} has {len(words)} words, minimum is {min_count}"
                )

    elif hook_type == "has_list_items":
        # Check that a section has at least one list item (- or *)
        file_path = issue_dir / params["file"]
        section = params["section"]
        min_items = params.get("min", 1)

        if not file_path.exists():
            errors.append(f"File '{params['file']}' not found for has_list_items check")
        else:
            content = file_path.read_text()
            pattern = rf'^##[#]?\s*{re.escape(section)}.*?\n(.*?)(?=\n##|\Z)'
            section_match = re.search(pattern, content, re.MULTILINE | re.DOTALL)

            if not section_match:
                errors.append(f"Section '{section}' not found in {params['file']}")
            else:
                section_content = section_match.group(1)
                # Count list items (lines starting with - or *)
                list_items = re.findall(r'^\s*[-*]\s+\S', section_content, re.MULTILINE)
                if len(list_items) < min_items:
                    errors.append(
                        f"Section '{section}' has {len(list_items)} list items, minimum is {min_items}"
                    )

    elif hook_type == "contains":
        # Check that a section contains one of the specified values
        file_path = issue_dir / params["file"]
        section = params["section"]
        values = params.get("values", [])  # List of acceptable values

        if not file_path.exists():
            errors.append(f"File '{params['file']}' not found for contains check")
        else:
            content = file_path.read_text()
            pattern = rf'^##[#]?\s*{re.escape(section)}.*?\n(.*?)(?=\n##|\Z)'
            section_match = re.search(pattern, content, re.MULTILINE | re.DOTALL)

            if not section_match:
                errors.append(f"Section '{section}' not found in {params['file']}")
            else:
                section_content = section_match.group(1).strip()
                # Check if any of the values appear in the section
                found = any(v.lower() in section_content.lower() for v in values)
                if not found:
                    errors.append(
                        f"Section '{section}' must contain one of: {', '.join(values)}"
                    )

    elif hook_type == "pr_approved":
        skip_approval = kwargs.get("skip_pr_approval", False)
        if skip_approval:
            console.print(f"[dim]Skipping PR approval check (--skip-approval)[/dim]")
        elif pr_number is None:
            errors.append("No PR number available to check approval status")
        else:
            # Auto-approve the PR if not already approved
            if not get_pr_approval_status(pr_number):
                try:
                    console.print(f"[dim]Auto-approving PR #{pr_number}...[/dim]")
                    result = subprocess.run(
                        ["gh", "pr", "review", str(pr_number), "--approve"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.returncode != 0:
                        # Check if it's because we're the author
                        if "Can not approve your own pull request" in result.stderr:
                            console.print(f"[yellow]Cannot self-approve PR #{pr_number} (you're the author)[/yellow]")
                            console.print(f"[dim]Use --skip-approval to bypass, or have someone else approve[/dim]")
                            errors.append(f"Cannot self-approve PR #{pr_number}. Use --skip-approval to bypass.")
                        else:
                            errors.append(f"Failed to approve PR #{pr_number}: {result.stderr}")
                    else:
                        console.print(f"[green]✓ PR #{pr_number} approved[/green]")
                except subprocess.TimeoutExpired:
                    errors.append(f"Timeout approving PR #{pr_number}")
                except Exception as e:
                    errors.append(f"Error approving PR #{pr_number}: {e}")

    # Action types (side effects, don't return errors on success)
    elif hook_type == "create_file":
        # Create a file from template if it doesn't exist
        template = params.get("template")
        dest = params.get("dest")
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

    elif hook_type == "cleanup_agent":
        # Clean up agent resources (container, tmux, port)
        issue = kwargs.get("issue")
        if issue:
            cleanup_issue_agent(issue)

    elif hook_type == "start_blocked_issues":
        # Check and start any issues that were blocked on this one
        issue = kwargs.get("issue")
        if issue:
            check_and_start_blocked_issues(issue)

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
        hook: Hook configuration dict with 'command' and optional 'context', 'timeout', 'host_only'
        issue_id: Issue ID for template variable substitution
        issue_title: Issue title for template variable substitution
        branch: Branch name for template variable substitution
        stage: Current stage for template variable substitution
        substage: Current substage for template variable substitution
        **kwargs: Additional template variables

    Returns:
        List of error messages (empty if command succeeds or skipped)
    """
    # Skip if host_only and running in container
    if hook.get("host_only") and is_running_in_container():
        return []

    command = hook["command"]

    # Replace template variables
    command = command.replace("{{issue_id}}", issue_id)
    command = command.replace("{{issue_title}}", issue_title)
    command = command.replace("{{branch}}", branch)
    command = command.replace("{{stage}}", stage)
    command = command.replace("{{substage}}", substage)

    # Additional variables from kwargs
    pr_number = kwargs.get("pr_number", "")
    pr_url = kwargs.get("pr_url", "")
    command = command.replace("{{pr_number}}", str(pr_number))
    command = command.replace("{{pr_url}}", str(pr_url))

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
        event: "pre_completion" or "post_start"
        pr_number: Optional PR number for pr_approved validator
        **kwargs: Additional context for hooks

    Returns:
        List of all error messages from failed hooks
    """
    errors: List[str] = []

    # Auto-check output file on pre_completion (if not optional)
    if event == "pre_completion":
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
        hook_type, params = parse_hook(hook)

        # Skip host-only hooks when running in container
        if hook.get("host_only") and is_running_in_container():
            console.print(f"[dim]Skipping {hook_type} (host-only hook)[/dim]")
            continue

        if hook_type == "run":
            # Shell command hook
            hook_errors = run_command_hook(issue_dir, params, **kwargs)
            # If optional flag is set and command returns "not configured", warn but don't block
            if params.get("optional") and any("not configured" in e.lower() for e in hook_errors):
                context = params.get("context", params.get("command", "command"))
                console.print(f"[yellow]Warning: {context} skipped - not configured[/yellow]")
                continue
            errors.extend(hook_errors)
        elif hook_type == "rebase":
            # Rebase hook - host-only, skips gracefully in container
            if is_running_in_container():
                console.print(f"[dim]Skipping rebase (running in container)[/dim]")
                continue
            issue_id = kwargs.get("issue_id", "")
            if issue_id:
                success, message = rebase_issue_branch(issue_id)
                if success:
                    console.print(f"[green]✓ {message}[/green]")
                else:
                    console.print(f"[yellow]Warning: {message}[/yellow]")
                    # Don't block on rebase failure - agent can handle conflicts
        elif hook_type != "unknown":
            # Built-in validator/action
            errors.extend(run_builtin_validator(issue_dir, hook, pr_number=pr_number, **kwargs))

    return errors


def execute_exit_hooks(issue: "Issue", stage: str, substage: Optional[str] = None, **extra_kwargs: Any) -> None:
    """Execute pre_completion hooks for a stage/substage. Raises ValidationError if any fail.

    This is the config-driven replacement for execute_pre_hooks.

    When exiting the LAST substage of a stage, this also runs stage-level pre_completion hooks.
    This ensures hooks like lint/test/create_pr run when leaving implement stage.

    Args:
        issue: Issue being transitioned
        stage: Current stage name
        substage: Current substage name (optional)
        **extra_kwargs: Additional args (e.g., skip_pr_approval=True)

    Raises:
        ValidationError: If any validation fails (blocks transition)
    """
    from agenttree.config import load_config
    from agenttree.issues import get_issue_dir

    config = load_config()
    stage_config = config.get_stage(stage)
    if not stage_config:
        return  # Unknown stage, skip hooks

    # Get issue directory
    issue_dir = get_issue_dir(issue.id)
    if not issue_dir:
        return  # No issue directory, skip hooks

    errors: List[str] = []
    hook_kwargs = {
        "issue_id": issue.id,
        "issue_title": issue.title,
        "branch": issue.branch or "",
        "substage": substage or "",
        **extra_kwargs,  # Pass through extra kwargs like skip_pr_approval
    }

    # Execute substage hooks first (if applicable)
    if substage:
        substage_config = stage_config.get_substage(substage)
        if substage_config:
            errors.extend(execute_hooks(
                issue_dir,
                stage,
                substage_config,
                "pre_completion",
                pr_number=issue.pr_number,
                **hook_kwargs,
            ))

    # Check if we're exiting the stage (last substage or no substages)
    substages = stage_config.substage_order()
    is_exiting_stage = not substages or (substage and substages[-1] == substage)

    # Execute stage-level hooks when exiting the stage
    if is_exiting_stage:
        errors.extend(execute_hooks(
            issue_dir,
            stage,
            stage_config,
            "pre_completion",
            pr_number=issue.pr_number,
            **hook_kwargs,
        ))

    if errors:
        if len(errors) == 1:
            raise ValidationError(errors[0])
        else:
            msg = "Multiple validation errors:\n"
            for i, error in enumerate(errors, 1):
                msg += f"  {i}. {error}\n"
            raise ValidationError(msg.strip())


def execute_enter_hooks(issue: "Issue", stage: str, substage: Optional[str] = None) -> None:
    """Execute post_start hooks for a stage/substage. Logs warnings but doesn't block.

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
        "post_start",
        pr_number=issue.pr_number,
        issue_id=issue.id,
        issue_title=issue.title,
        branch=issue.branch or "",
        substage=substage or "",
        issue=issue,  # Pass issue object for cleanup_agent and start_blocked_issues hooks
    )

    # Log warnings but don't block
    if errors:
        for error in errors:
            console.print(f"[yellow]Warning: {error}[/yellow]")


def run_host_hooks(hooks: List[Dict[str, Any]], context: Dict[str, Any]) -> None:
    """Run host action hooks (post_pr_create, post_merge, post_accepted).

    These hooks log errors but don't block operations.

    Args:
        hooks: List of hook configurations
        context: Template variables for substitution (issue_id, pr_number, etc.)
    """
    from pathlib import Path

    for hook in hooks:
        try:
            if "command" in hook:
                errors = run_command_hook(
                    Path.cwd(),
                    hook,
                    issue_id=context.get("issue_id", ""),
                    issue_title=context.get("issue_title", ""),
                    branch=context.get("branch", ""),
                    pr_number=str(context.get("pr_number", "")),
                    pr_url=context.get("pr_url", ""),
                )
                for error in errors:
                    console.print(f"[yellow]Warning: {error}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Hook error: {e}[/yellow]")


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


def rebase_issue_branch(issue_id: str) -> tuple[bool, str]:
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
        result = subprocess.run(
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
                return False, f"Rebase conflicts - manual resolution needed"
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
    from agenttree.config import load_config
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

    # Need branch info (silently skip if not started yet)
    if not issue.branch:
        return False

    # Find the worktree for this issue
    # Prefer stored worktree_dir, fall back to path guessing
    worktree_path: Optional[Path] = None
    if issue.worktree_dir:
        worktree_path = Path(issue.worktree_dir)
        if not worktree_path.exists():
            console.print(f"[yellow]Stored worktree_dir {issue.worktree_dir} doesn't exist[/yellow]")
            worktree_path = None

    # Fall back to guessing the path
    if not worktree_path:
        worktree_path = Path.cwd() / ".worktrees" / f"issue-{issue_id.zfill(3)}-{issue.slug[:30]}"
        if not worktree_path.exists():
            # Try without leading zeros
            for p in Path.cwd().glob(f".worktrees/issue-{issue_id}*"):
                worktree_path = p
                break

    if not worktree_path or not worktree_path.exists():
        console.print(f"[yellow]Worktree not found for issue #{issue_id}[/yellow]")
        return False

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
        console.print(f"[dim]Auto-committing uncommitted changes...[/dim]")
        subprocess.run(
            ["git", "-C", str(worktree_path), "commit", "-m", f"Issue #{issue_id}: auto-commit before PR"],
            capture_output=True,
            text=True,
            timeout=30,
        )

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

    from agenttree.config import load_config
    from agenttree.issues import get_blocked_issues, check_dependencies_met

    # Run post_accepted hooks
    config = load_config()
    if config.hooks.post_accepted:
        run_host_hooks(config.hooks.post_accepted, {
            "issue_id": issue.id,
        })

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

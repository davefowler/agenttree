"""Unified hook system for AgentTree.

This module provides a config-driven hook system used by both:
1. **Stage hooks** - Validation/actions during workflow stage transitions
2. **Manager hooks** - Post-sync operations for the manager

=============================================================================
HOOK CONFIGURATION
=============================================================================

Hooks are configured in .agenttree.yaml. Each hook is a dict with the hook
type as a key, and optional parameters as the value.

Built-in Validators (quick reference):
--------------------------------------
- file_exists: Check that a file exists
- has_commits: Check that there are unpushed commits
- field_check: Check a YAML field value meets min/max threshold
- section_check: Check a markdown section (empty, not_empty, all_checked)
- wrapup_verified: Check Implementation Wrapup checklist is complete
- pr_approved: Check that a PR is approved
- ci_check: Check CI status for a PR

Basic Format:
-------------
    # Simple hook (no params)
    - file_exists: "review.md"

    # Hook with parameters
    - field_check:
        file: review.md
        path: scores.average
        min: 7

    # Hook with common options
    - run: "npm test"
      optional: true
      context: "Run tests"
      timeout: 120

=============================================================================
COMMON HOOK OPTIONS (available for all hooks)
=============================================================================

optional: bool (default: false)
    If true, hook failure logs a warning but doesn't block the transition.

context: str
    Human-readable description shown in logs/errors.

host_only: bool (default: false)
    Only run this hook on the host (manager), skip in containers.

timeout: int (default: 30)
    Timeout in seconds for command hooks.

min_interval_s: int
    Rate limiting: minimum seconds between runs. Hook is skipped if
    run more recently than this interval.

run_every_n_syncs: int
    Rate limiting: only run every Nth sync. Useful for expensive operations.

=============================================================================
BUILT-IN VALIDATORS (return errors if validation fails)
=============================================================================

file_exists: str
    Check that a file exists in the issue directory.

    Example:
        - file_exists: "spec.md"

has_commits: {}
    Check that there are unpushed commits on the current branch.

    Example:
        - has_commits: {}

field_check:
    Check a YAML field in a markdown file meets min/max threshold.
    Looks for ```yaml blocks in the file.

    Parameters:
        file: str - File to check
        path: str - Dot-separated path to field (e.g., "scores.average")
        min: float - Minimum value (optional)
        max: float - Maximum value (optional)

    Example:
        - field_check:
            file: review.md
            path: scores.average
            min: 7

section_check:
    Check a markdown section's content.

    Parameters:
        file: str - File to check
        section: str - Section header name (without #)
        expect: str - One of:
            - "empty" - Section must be empty or contain only comments
            - "not_empty" - Section must have content
            - "all_checked" - All checkboxes must be checked [x]
        on_fail_stage: str (optional) - Stage to redirect to on failure
        on_fail_substage: str (optional) - Substage to redirect to on failure
            (stays in current stage, redirects to the named substage)

    Example:
        - section_check:
            file: review.md
            section: Self-Review Checklist
            expect: all_checked

        # Redirect to address_review substage if critical issues found
        - section_check:
            file: review.md
            section: Critical Issues
            expect: empty
            on_fail_substage: address_review

has_list_items:
    Check that a section has bullet list items (- or *).

    Parameters:
        file: str - File to check
        section: str - Section header name
        min: int - Minimum number of items (default: 1)

    Example:
        - has_list_items:
            file: spec.md
            section: Implementation Steps

min_words:
    Check that a section has a minimum word count.

    Parameters:
        file: str - File to check
        section: str - Section header name
        min: int - Minimum word count

    Example:
        - min_words:
            file: problem.md
            section: Context
            min: 50

contains:
    Check that a section contains one of the specified values.

    Parameters:
        file: str - File to check
        section: str - Section header name
        values: list[str] - Acceptable values

    Example:
        - contains:
            file: spec_review.md
            section: Verdict
            values: ["Ready for implementation", "Approved"]

pr_approved: {}
    Check that the PR is approved (requires pr_number in context).

    Example:
        - pr_approved: {}

server_running:
    Check that a dev server is running on the issue's port.
    Useful for validating that an agent has started a dev server before
    allowing a stage transition.

    Parameters:
        health_endpoint: str - URL path to check (default: "/")
        timeout: int - Request timeout in seconds (default: 5)
        retries: int - Number of retry attempts (default: 3)
        retry_delay: int - Seconds to wait between retries (default: 2)

    Example:
        - server_running:
            health_endpoint: /health
            timeout: 10

=============================================================================
BUILT-IN ACTIONS (perform side effects)
=============================================================================

run: str
    Execute a shell command. Supports template variables:
    {{issue_id}}, {{issue_title}}, {{branch}}, {{stage}}, {{substage}},
    {{pr_number}}, {{pr_url}}

    Example:
        - run: "npm test"
          context: "Run tests"
          timeout: 120
          optional: true

create_file:
    Create a file from a template.

    Parameters:
        template: str - Template file name (from _agenttree/templates/)
        dest: str - Destination file name in issue directory

    Example:
        - create_file:
            template: spec.md
            dest: spec.md

create_pr: {}
    Create a pull request for the issue's branch. Host-only.

    Example:
        - create_pr: {}

merge_pr: {}
    Merge the PR (using configured merge strategy). Host-only.

    Example:
        - merge_pr: {}

rebase: {}
    Rebase the issue branch onto main. Host-only.

    Example:
        - rebase: {}

cleanup_agent: {}
    Clean up the agent container/worktree after acceptance. Host-only.

    Example:
        - cleanup_agent: {}

start_blocked_issues: {}
    Start issues that were blocked by this issue. Host-only.

    Example:
        - start_blocked_issues: {}

=============================================================================
CONTROLLER HOOKS (run after sync operations)
=============================================================================

Manager hooks run after each sync and support rate limiting.
Configure in .agenttree.yaml under manager_hooks:

    manager_hooks:
      post_sync:
        - push_pending_branches: {}
        - check_manager_stages: {}
        - check_merged_prs: {}
        - check_ci_status:
            min_interval_s: 60
            run_every_n_syncs: 5

Built-in manager hooks:
    push_pending_branches - Push any local branches with unpushed commits
    check_manager_stages - Process issues in manager-owned stages
    ensure_review_branches - Create missing PRs and rebase branches in implementation_review
    check_custom_agent_stages - Spawn custom agents for issues in custom agent stages
    check_merged_prs - Detect externally merged PRs and update issue status

Custom commands work here too:
    - notify_slack:
        command: "curl -X POST $SLACK_WEBHOOK"
        min_interval_s: 300

=============================================================================
RATE LIMITING
=============================================================================

Rate limiting prevents hooks from running too frequently. Useful for:
- Expensive operations (CI status checks)
- External API calls (notifications, webhooks)
- Operations that don't need to run every sync

Options:
    min_interval_s: Minimum seconds since last run
    run_every_n_syncs: Only run every Nth sync (manager hooks only)

Both can be combined - both conditions must pass for hook to run.

State is stored in _agenttree/.heartbeat_state.yaml

=============================================================================
USAGE
=============================================================================

Stage hooks (for workflow transitions):
    from agenttree.hooks import execute_exit_hooks, execute_enter_hooks

    # Pre-completion hooks (validation, can block)
    execute_exit_hooks(issue, stage, substage)

    # Post-start hooks (setup, warnings only)
    execute_enter_hooks(issue, stage, substage)

Manager hooks (for post-sync operations):
    from agenttree.manager_hooks import run_post_manager_hooks

    run_post_manager_hooks(agents_dir)

"""

import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console

from agenttree.issues import (
    Issue,
    get_issue_context,
)
from agenttree.config import load_config

console = Console()


class ValidationError(Exception):
    """Raised when pre-hook validation fails to block a stage transition."""

    pass


class StageRedirect(Exception):
    """Raised when a hook failure should redirect to a different stage.

    Used with on_fail option in hooks. Target is a dot path (e.g., "implement.code")
    or a relative substage name that gets resolved by the caller.
    """

    def __init__(self, target: str, reason: str = ""):
        self.target = target
        self.reason = reason
        super().__init__(f"Redirect to stage '{target}': {reason}")


def _extract_markdown_section(content: str, section: str) -> tuple[bool, str]:
    """Extract section content from markdown, supporting ## and ### headers.

    Finds content between a section header (## or ###) and the next same-level
    or higher header, or end of file.

    Args:
        content: The full markdown content to search
        section: The section name to find (without # prefix)

    Returns:
        Tuple of (found, section_content) where found is True if section exists
        and section_content is the text between the header and next header/EOF.
    """
    pattern = rf'^##[#]?\s*{re.escape(section)}.*?\n(.*?)(?=\n##[#]? |\Z)'
    match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    if match:
        return True, match.group(1)
    return False, ""


# =============================================================================
# Hook Type Registry
# =============================================================================

# All known hook types (validators, actions, and manager hooks)
HOOK_TYPES = {
    # Validators (return errors if validation fails)
    "file_exists", "has_commits", "field_check", "section_check", "pr_approved",
    "min_words", "has_list_items", "contains", "ci_check", "wrapup_verified",
    "title_set", "server_running",
    "checkbox_checked",  # Review loop: check if checkbox is marked
    # Actions (perform side effects)
    "create_file", "create_pr", "merge_pr", "run", "rebase",
    "cleanup_agent", "start_blocked_issues", "cleanup_resources",
    "rollback",  # Review loop: programmatic rollback to earlier stage (with optional max_rollbacks limit)
    # Manager hooks (run on post-sync)
    "push_pending_branches", "check_manager_stages", "ensure_review_branches",
    "check_merged_prs", "check_ci_status", "check_custom_agent_stages",
}

# =============================================================================
# Base Hook Options (inherited by ALL hooks)
# =============================================================================
#
# Every hook, regardless of type, supports these universal options.
# These are handled by run_hook() before delegating to type-specific execution.
#
# Example config showing base options:
#
#     - section_check:           # <-- hook type with specific params
#         file: spec.md
#         section: Approach
#         expect: not_empty
#       optional: true           # <-- base option: don't block on failure
#       context: "Check spec"    # <-- base option: human-readable name
#       min_interval_s: 60       # <-- base option: rate limiting
#
BASE_HOOK_OPTIONS = {
    # Execution control
    "optional": False,      # bool: If true, failure logs warning but doesn't block
    "context": None,        # str: Human-readable description for logs/errors
    "host_only": False,     # bool: Only run on host (manager), skip in containers

    # Timeouts (for run/command hooks)
    "timeout": 30,          # int: Timeout in seconds for command execution

    # Rate limiting (prevents running too frequently)
    "min_interval_s": None,     # int: Minimum seconds between runs
    "run_every_n_syncs": None,  # int: Only run every Nth sync (manager hooks)
}

# Alias for backwards compatibility
COMMON_HOOK_OPTIONS = set(BASE_HOOK_OPTIONS.keys())


# =============================================================================
# Rate Limiting — delegated to events.py (single source of truth)
# =============================================================================

from agenttree.events import (
    check_action_rate_limit as check_rate_limit,
    update_action_state as update_hook_state,
    load_event_state as load_hook_state,
    save_event_state as save_hook_state,
)

# =============================================================================
# Re-exports from split modules (backward compatibility)
# =============================================================================
#
# These functions were extracted to focused modules but are re-exported here
# to maintain backward compatibility with existing imports.

from agenttree.git_utils import (
    get_current_branch,
    has_uncommitted_changes,
    get_default_branch,
    has_commits_to_push,
    get_git_diff_stats,
    push_branch_to_remote,
    get_commits_behind_main,
    get_commits_ahead_behind_main,
    rebase_issue_branch,
    get_repo_remote_name,
)

from agenttree.environment import (
    is_running_in_container,
    get_code_directory,
    get_current_role,
    can_agent_operate_in_stage,
)

from agenttree.pr_actions import (
    _action_create_pr,
    _try_update_pr_branch,
    _action_merge_pr,
    get_pr_approval_status,
    ensure_pr_for_issue,
    generate_pr_body,
    generate_commit_message,
    auto_commit_changes,
)


# =============================================================================
# Hook Parsing
# =============================================================================


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
        on_fail = params.get("on_fail") or params.get("on_fail_substage") or params.get("on_fail_stage")
        if not file_path.exists():
            errors.append(f"File '{params['file']}' not found for section check")
        else:
            content = file_path.read_text()
            section = params["section"]
            expect = params["expect"]

            found, section_content = _extract_markdown_section(content, section)

            if not found:
                errors.append(f"Section '{section}' not found in {params['file']}")
            else:
                # Remove HTML comments
                section_content = re.sub(r'<!--.*?-->', '', section_content, flags=re.DOTALL)

                check_failed = False
                fail_msg = ""

                if expect == "empty":
                    # Check for list items
                    if re.search(r'^\s*[-*]\s+', section_content, re.MULTILINE):
                        check_failed = True
                        fail_msg = f"Section '{section}' in {params['file']} is not empty"
                elif expect == "not_empty":
                    # Check if section has content beyond whitespace
                    if not section_content.strip():
                        check_failed = True
                        fail_msg = f"Section '{section}' in {params['file']} is empty"
                elif expect == "all_checked":
                    # Find unchecked checkboxes
                    unchecked = re.findall(r'-\s*\[\s*\]\s*(.*)', section_content)
                    if unchecked:
                        check_failed = True
                        items = ", ".join(item.strip() for item in unchecked[:3])
                        if len(unchecked) > 3:
                            items += f" (and {len(unchecked) - 3} more)"
                        fail_msg = f"Unchecked items in '{section}': {items}"

                if check_failed:
                    if on_fail:
                        # Resolve relative substage names to full dot paths
                        target = on_fail
                        if "." not in target:
                            # Relative: resolve against current stage group
                            current_stage = kwargs.get("stage", "")
                            if "." in current_stage:
                                group, _ = current_stage.split(".", 1)
                                target = f"{group}.{target}"
                            else:
                                target = f"{current_stage}.{target}"
                        raise StageRedirect(target, fail_msg)
                    else:
                        errors.append(fail_msg)

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
                found, section_content = _extract_markdown_section(content, section)
                if not found:
                    errors.append(f"Section '{section}' not found in {params['file']}")
                else:
                    content = section_content

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
            found, section_content = _extract_markdown_section(content, section)

            if not found:
                errors.append(f"Section '{section}' not found in {params['file']}")
            else:
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
            found, section_content = _extract_markdown_section(content, section)

            if not found:
                errors.append(f"Section '{section}' not found in {params['file']}")
            else:
                section_content = section_content.strip()
                # Check if any of the values appear in the section
                value_found = any(v.lower() in section_content.lower() for v in values)
                if not value_found:
                    errors.append(
                        f"Section '{section}' must contain one of: {', '.join(values)}"
                    )

    elif hook_type == "wrapup_verified":
        # Check that Implementation Wrapup has completed Verification Checklist
        file_path = issue_dir / params["file"]
        if not file_path.exists():
            errors.append(f"File '{params['file']}' not found for wrapup verification")
        else:
            content = file_path.read_text()

            # Find Implementation Wrapup section
            wrapup_pattern = r'^##\s*Implementation Wrapup.*?\n(.*?)(?=\n##(?!#)|\Z)'
            wrapup_match = re.search(wrapup_pattern, content, re.MULTILINE | re.DOTALL)

            if not wrapup_match:
                errors.append(f"Implementation Wrapup section not found in {params['file']}")
            else:
                wrapup_content = wrapup_match.group(1)

                # Find Verification Checklist subsection within wrapup
                checklist_pattern = r'^###\s*Verification Checklist.*?\n(.*?)(?=\n###|\Z)'
                checklist_match = re.search(checklist_pattern, wrapup_content, re.MULTILINE | re.DOTALL)

                if not checklist_match:
                    errors.append("Verification Checklist section not found in Implementation Wrapup")
                else:
                    checklist_content = checklist_match.group(1)
                    # Remove HTML comments
                    checklist_content = re.sub(r'<!--.*?-->', '', checklist_content, flags=re.DOTALL)

                    # Find unchecked items (empty [ ] checkboxes)
                    unchecked = re.findall(r'-\s*\[\s*\]\s*(.*)', checklist_content)
                    if unchecked:
                        items = ", ".join(item.strip() for item in unchecked[:3])
                        if len(unchecked) > 3:
                            items += f" (and {len(unchecked) - 3} more)"
                        errors.append(
                            f"Wrapup verification incomplete. Unchecked items: {items}"
                        )

    elif hook_type == "pr_approved":
        # Check both explicit kwarg and config setting
        from agenttree.config import load_config as _load_config
        _cfg = _load_config()
        skip_approval = kwargs.get("skip_pr_approval", False) or _cfg.allow_self_approval
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

    elif hook_type == "ci_check":
        # Quick CI status gate — checks current GH status, no blocking poll
        if pr_number is None:
            errors.append("No PR number available to check CI status")
        else:
            from agenttree.github import get_pr_checks, get_pr_comments, get_check_failed_logs

            console.print(f"[dim]Checking CI status for PR #{pr_number}...[/dim]")
            checks = get_pr_checks(pr_number)

            if not checks:
                errors.append(f"No CI checks found for PR #{pr_number}. Wait for CI to start.")
            else:
                pending = [c for c in checks if c.state == "PENDING"]
                failed = [c for c in checks if c.state == "FAILURE"]

                if pending:
                    names = ", ".join(c.name for c in pending)
                    errors.append(f"CI still running: {names}. Wait for completion.")
                elif failed:
                    # Write ci_feedback.md with failure details
                    if issue_dir:
                        feedback_content = "# CI Failure Report\n\nThe following CI checks failed:\n\n"
                        for check in checks:
                            status = "PASSED" if check.state == "SUCCESS" else "FAILED"
                            feedback_content += f"- **{check.name}**: {status}\n"

                        for check in failed:
                            logs = get_check_failed_logs(check)
                            if logs:
                                feedback_content += f"\n---\n\n## Failed Logs: {check.name}\n\n```\n{logs}\n```\n"

                        comments = get_pr_comments(pr_number)
                        if comments:
                            feedback_content += "\n---\n\n## Review Comments\n\n"
                            for comment in comments:
                                feedback_content += f"### From @{comment.author}\n\n"
                                feedback_content += f"{comment.body}\n\n"

                        feedback_content += "\n---\n\nPlease fix these issues and run `agenttree next` to re-submit.\n"
                        feedback_path = issue_dir / "ci_feedback.md"
                        feedback_path.write_text(feedback_content)
                        console.print(f"[dim]Created {feedback_path}[/dim]")

                    check_names = ", ".join(c.name for c in failed)
                    errors.append(f"CI checks failed: {check_names}")
                else:
                    console.print(f"[green]✓ CI checks passed for PR #{pr_number}[/green]")

    # Action types (side effects, don't return errors on success)
    elif hook_type == "create_file":
        # Create a file from template with Jinja rendering
        template_name = params.get("template")
        dest = params.get("dest")
        if template_name and dest:
            template_path = Path("_agenttree/templates") / template_name
            dest_path = issue_dir / dest
            # Template MUST exist - fail loudly if not
            if not template_path.exists():
                errors.append(f"Template '{template_name}' not found at {template_path}")
            elif not dest_path.exists():
                template_content = template_path.read_text()

                # Build Jinja context using unified function
                from jinja2 import Template
                from agenttree.commands import get_referenced_commands, get_command_output

                issue = kwargs.get("issue")
                context: Dict[str, Any] = {}

                if issue:
                    # Use get_issue_context for all issue fields
                    context = get_issue_context(issue, include_docs=True)

                    # Add latest_independent_review - find highest-numbered version
                    # Looks for independent_review_v*.md and uses the highest version
                    versioned_reviews = sorted(issue_dir.glob("independent_review_v*.md"))
                    if versioned_reviews:
                        # Use the latest versioned review
                        context["latest_independent_review"] = versioned_reviews[-1].read_text()
                    elif (issue_dir / "independent_review.md").exists():
                        # Fall back to unversioned file
                        context["latest_independent_review"] = (issue_dir / "independent_review.md").read_text()
                    else:
                        context["latest_independent_review"] = ""

                    # Add latest_independent_review_response - for re-reviews to see implementer's response
                    versioned_responses = sorted(issue_dir.glob("independent_review_response_v*.md"))
                    if versioned_responses:
                        context["latest_independent_review_response"] = versioned_responses[-1].read_text()
                    elif (issue_dir / "independent_review_response.md").exists():
                        context["latest_independent_review_response"] = (issue_dir / "independent_review_response.md").read_text()
                    else:
                        context["latest_independent_review_response"] = ""

                    # Count review iterations for context
                    context["review_iteration"] = len(versioned_reviews) + 1

                # Add git diff stats for review templates
                git_stats = get_git_diff_stats()
                context["files_changed"] = git_stats['files_changed']
                context["lines_added"] = git_stats['lines_added']
                context["lines_removed"] = git_stats['lines_removed']

                # Inject command outputs for referenced commands
                config = load_config()
                if config.commands:
                    # Determine working directory for commands
                    cwd = get_code_directory(issue, issue_dir)

                    # Find commands referenced in the template
                    referenced = get_referenced_commands(template_content, config.commands)

                    for cmd_name in referenced:
                        # Don't overwrite built-in context variables
                        if cmd_name not in context:
                            context[cmd_name] = get_command_output(
                                config.commands, cmd_name, cwd=cwd
                            )

                # Render template
                try:
                    jinja_template = Template(template_content)
                    rendered = jinja_template.render(**context)
                except Exception:
                    # If rendering fails, use raw content
                    rendered = template_content

                dest_path.write_text(rendered)
                console.print(f"[dim]Created {dest} from template[/dim]")

    elif hook_type == "create_pr":
        # Create PR on transition to implementation_review
        try:
            _action_create_pr(issue_dir, **kwargs)
        except Exception as e:
            errors.append(f"Failed to create PR: {e}")

    elif hook_type == "merge_pr":
        # Merge PR on transition to accepted
        # StageRedirect propagates (e.g., conflict → redirect to developer)
        try:
            _action_merge_pr(pr_number, **kwargs)
        except StageRedirect:
            raise  # Let redirect propagate to caller
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

    elif hook_type == "cleanup_resources":
        # Run global resource cleanup and optionally log what was cleaned
        # Tracking helps identify workflow failures - high cleanup frequency
        # indicates broken workflow steps
        log_file = params.get("log_file")
        dry_run = params.get("dry_run", False)
        cleanup_result = run_resource_cleanup(dry_run=dry_run, log_file=log_file)
        if cleanup_result.get("errors"):
            for err in cleanup_result["errors"]:
                errors.append(f"Cleanup error: {err}")

    # === Review loop hooks ===

    elif hook_type == "checkbox_checked":
        # Check that a specific checkbox is marked in a markdown file
        # Supports on_fail_stage/on_fail_substage for conditional routing
        file_path = issue_dir / params["file"]
        checkbox_text = params.get("checkbox", "")
        on_fail = params.get("on_fail") or params.get("on_fail_substage") or params.get("on_fail_stage")

        if not file_path.exists():
            errors.append(f"File '{params['file']}' not found for checkbox check")
        else:
            content = file_path.read_text()
            # Look for checked checkbox with the specified text
            # Pattern: [x] or [X] followed by the checkbox text
            checked_pattern = rf'\[[ ]?[xX][ ]?\]\s*\**{re.escape(checkbox_text)}'
            unchecked_pattern = rf'\[\s*\]\s*\**{re.escape(checkbox_text)}'

            if re.search(checked_pattern, content):
                # Checkbox is checked, validation passes
                pass
            elif re.search(unchecked_pattern, content):
                # Checkbox exists but is unchecked
                fail_msg = f"Checkbox '{checkbox_text}' is not checked in {params['file']}"
                if on_fail:
                    target = on_fail
                    if "." not in target:
                        current_stage = kwargs.get("stage", "")
                        if "." in current_stage:
                            group, _ = current_stage.split(".", 1)
                            target = f"{group}.{target}"
                        else:
                            target = f"{current_stage}.{target}"
                    raise StageRedirect(target, fail_msg)
                else:
                    errors.append(fail_msg)
            else:
                errors.append(f"Checkbox '{checkbox_text}' not found in {params['file']}")

    elif hook_type == "rollback":
        # Programmatic rollback to an earlier stage
        # Used in post_completion to loop back for re-review
        to_stage = params.get("to") or params.get("to_stage", "")
        auto_yes = params.get("yes", True)  # Default to auto-confirm for programmatic rollback
        max_rollbacks = params.get("max_rollbacks")  # Optional iteration limit

        # Resolve relative substage name to full dot path
        if to_stage and "." not in to_stage:
            current_stage = kwargs.get("stage", "")
            if "." in current_stage:
                group, _ = current_stage.split(".", 1)
                to_stage = f"{group}.{to_stage}"

        if not to_stage:
            errors.append("rollback hook requires 'to' parameter")
        else:
            issue = kwargs.get("issue")
            if issue:
                try:
                    # Import from rollback module to avoid circular imports
                    from agenttree.rollback import execute_rollback
                    success = execute_rollback(
                        issue_id=issue.id,
                        target_stage=to_stage,
                        yes=auto_yes,
                        reset_worktree=False,
                        keep_changes=True,
                        max_rollbacks=max_rollbacks,
                    )
                    if success:
                        console.print(f"[green]✓ Rolled back to {to_stage}[/green]")
                    else:
                        errors.append(f"Rollback to {to_stage} failed")
                except Exception as e:
                    errors.append(f"Rollback failed: {e}")
            else:
                errors.append("rollback hook requires issue context")

    # Manager hooks (delegated to agents_repo functions)
    elif hook_type == "push_pending_branches":
        from agenttree.agents_repo import push_pending_branches
        agents_dir = kwargs.get("agents_dir")
        if agents_dir:
            push_pending_branches(agents_dir)

    elif hook_type == "check_manager_stages":
        from agenttree.agents_repo import check_manager_stages
        agents_dir = kwargs.get("agents_dir")
        if agents_dir:
            check_manager_stages(agents_dir)

    elif hook_type == "ensure_review_branches":
        from agenttree.agents_repo import ensure_review_branches
        agents_dir = kwargs.get("agents_dir")
        if agents_dir:
            ensure_review_branches(agents_dir)

    elif hook_type == "check_merged_prs":
        from agenttree.agents_repo import check_merged_prs
        agents_dir = kwargs.get("agents_dir")
        if agents_dir:
            check_merged_prs(agents_dir)

    elif hook_type == "check_ci_status":
        from agenttree.agents_repo import check_ci_status
        agents_dir = kwargs.get("agents_dir")
        if agents_dir:
            check_ci_status(agents_dir)

    elif hook_type == "check_custom_agent_stages":
        from agenttree.agents_repo import check_custom_agent_stages
        agents_dir = kwargs.get("agents_dir")
        if agents_dir:
            check_custom_agent_stages(agents_dir)

    # NOTE: check_stalled_agents is handled by the actions system (actions.py),
    # not the hook system. See actions.py:check_stalled_agents.

    elif hook_type == "server_running":
        # Check that a dev server is running on the issue's port
        import urllib.request
        import urllib.error
        import time

        issue = kwargs.get("issue")
        if issue is None:
            errors.append("No issue provided for server_running check")
        else:
            # Get port from config using issue ID
            server_config = load_config()
            port = server_config.get_port_for_issue(issue.id)
            health_endpoint = params.get("health_endpoint", "/")
            timeout = params.get("timeout", 5)
            retries = params.get("retries", 3)
            retry_delay = params.get("retry_delay", 2)

            url = f"http://localhost:{port}{health_endpoint}"

            # Try multiple times with backoff to handle race conditions
            for attempt in range(retries):
                try:
                    req = urllib.request.Request(url, method="GET")
                    with urllib.request.urlopen(req, timeout=timeout) as response:
                        if 200 <= response.status < 400:
                            console.print(f"[green]✓ Dev server running at {url}[/green]")
                            break  # Success
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as err:
                    if attempt < retries - 1:
                        console.print(f"[dim]Server not ready, retrying in {retry_delay}s... ({attempt + 1}/{retries})[/dim]")
                        time.sleep(retry_delay)
                    else:
                        errors.append(
                            f"Dev server not responding at {url} after {retries} attempts: {err}. "
                            f"Make sure the server is running on port {port}."
                        )

    elif hook_type == "title_set":
        # Check that the issue title is not "(untitled)" or other placeholder
        issue = kwargs.get("issue")
        if issue is None:
            errors.append("No issue provided for title_set check")
        else:
            placeholder_titles = ["(untitled)", "untitled", ""]
            if issue.title.lower().strip() in placeholder_titles:
                errors.append(
                    f"Issue title is '{issue.title}'. Please set a descriptive title in issue.yaml "
                    f"(edit the 'title:' field in {issue.id}-{issue.slug}/issue.yaml)"
                )

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
    command = command.replace("{{issue_id}}", str(issue_id))
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
            return [f"{context} timeout after {timeout} seconds"]
        return [f"Command timeout after {timeout} seconds: {command}"]


def run_hook(
    hook: Dict[str, Any],
    context_dir: Path,
    hook_state: Optional[Dict[str, Any]] = None,
    sync_count: Optional[int] = None,
    verbose: bool = False,
    **kwargs: Any,
) -> tuple[List[str], bool]:
    """Run a single hook with all common options (rate limiting, host_only, etc).

    This is the unified entry point for running any hook type. It handles:
    - Rate limiting (min_interval_s, run_every_n_syncs)
    - Host-only checks
    - Optional flag handling
    - State updates

    Args:
        hook: Hook configuration dict
        context_dir: Directory context (issue_dir for stage hooks, agents_dir for manager)
        hook_state: Optional state dict for rate limiting (updated in place)
        sync_count: Current sync count for run_every_n_syncs rate limiting
        verbose: If True, print detailed output
        **kwargs: Additional context passed to hook execution

    Returns:
        Tuple of (errors, was_skipped):
        - errors: List of error messages
        - was_skipped: True if hook was skipped (rate limited, host_only, etc)
    """
    hook_type, params = parse_hook(hook)

    # Generate a unique key for this hook in state
    hook_key = hook_type
    if "context" in params:
        hook_key = f"{hook_type}:{params['context']}"

    # Check host_only
    if params.get("host_only") and is_running_in_container():
        if verbose:
            console.print(f"[dim]Skipping {hook_type} (host-only hook)[/dim]")
        return [], True

    # Check rate limiting
    if hook_state is not None:
        should_run, reason = check_rate_limit(hook_key, params, hook_state, sync_count)
        if not should_run:
            if verbose:
                console.print(f"[dim]Skipping {hook_type}: {reason}[/dim]")
            return [], True

    # Execute the hook
    errors: List[str] = []
    try:
        if hook_type == "run":
            # Shell command hook
            errors = run_command_hook(context_dir, params, **kwargs)
        elif hook_type in ("push_pending_branches", "check_manager_stages", "ensure_review_branches", "check_merged_prs", "check_custom_agent_stages"):
            # Manager hooks need agents_dir - use from kwargs if provided, otherwise context_dir
            if "agents_dir" not in kwargs:
                kwargs["agents_dir"] = context_dir
            errors = run_builtin_validator(context_dir, hook, **kwargs)
        else:
            # Built-in validator/action
            errors = run_builtin_validator(context_dir, hook, **kwargs)

        # Update state (tracks last_run_at for rate limiting)
        if hook_state is not None:
            update_hook_state(hook_key, hook_state)

    except Exception as e:
        error_msg = f"Hook {hook_type} failed: {e}"
        errors = [error_msg]
        if hook_state is not None:
            update_hook_state(hook_key, hook_state)

    # Handle optional flag
    if params.get("optional") and errors:
        context = params.get("context", hook_type)
        if verbose:
            console.print(f"[yellow]Warning: {context} failed (optional): {errors[0]}[/yellow]")
        return [], False  # Treat as success, not skipped

    return errors, False


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
    # Make stage available in kwargs for on_fail resolution in validators
    kwargs["stage"] = stage
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
            # Shell command hook - use correct directory based on context
            issue = kwargs.get("issue")
            cwd = get_code_directory(issue, issue_dir)
            hook_errors = run_command_hook(cwd, params, **kwargs)
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


def execute_exit_hooks(issue: "Issue", dot_path: str, **extra_kwargs: Any) -> None:
    """Execute pre_completion hooks for a dot path. Raises ValidationError if any fail.

    Args:
        issue: Issue being transitioned
        dot_path: Current dot path (e.g., "explore.define", "implement.code_review")
        **extra_kwargs: Additional args (e.g., skip_pr_approval=True)

    Raises:
        ValidationError: If any validation fails (blocks transition)
        StageRedirect: If a hook with on_fail fails (redirect to different stage)
    """
    from agenttree.config import load_config
    from agenttree.issues import get_issue_dir

    config = load_config()
    stage_name, substage_name = config.parse_stage(dot_path)
    stage_config = config.get_stage(stage_name)
    if not stage_config:
        return  # Unknown stage, skip hooks

    # Get issue directory
    issue_dir = get_issue_dir(issue.id)
    if not issue_dir:
        return  # No issue directory, skip hooks

    errors: List[str] = []
    hook_kwargs = {
        "issue_id": str(issue.id),
        "issue_title": issue.title,
        "branch": issue.branch or "",
        "issue": issue,  # Pass issue for worktree_dir access in run hooks
        **extra_kwargs,  # Pass through extra kwargs like skip_pr_approval
    }

    # Execute hooks from the substage config (if a substage), else from stage config
    if substage_name:
        substage_config = stage_config.get_substage(substage_name)
        if substage_config:
            errors.extend(execute_hooks(
                issue_dir,
                dot_path,
                substage_config,
                "pre_completion",
                pr_number=issue.pr_number,
                **hook_kwargs,
            ))
    else:
        errors.extend(execute_hooks(
            issue_dir,
            dot_path,
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


def execute_enter_hooks(issue: "Issue", dot_path: str) -> None:
    """Execute post_start hooks for a dot path.

    Non-critical errors are logged as warnings. Critical failures (like merge conflicts)
    raise StageRedirect so the issue can be routed back for developer intervention.

    For manager stages (role: manager), hooks are skipped when running in a container.
    The host will execute them via check_manager_stages() during sync.

    Args:
        issue: Issue that was transitioned
        dot_path: New dot path (e.g., "explore.define", "implement.code")

    Raises:
        StageRedirect: If a hook needs to route the issue elsewhere (e.g., merge conflict).
    """
    from agenttree.config import load_config
    from agenttree.issues import get_issue_dir

    config = load_config()
    stage_name, substage_name = config.parse_stage(dot_path)
    stage_config = config.get_stage(stage_name)
    if not stage_config:
        return  # Unknown stage, skip hooks

    # Determine effective role for this dot path
    effective_role = config.role_for(dot_path)

    # Skip hooks for manager stages when in a container
    if effective_role == "manager" and is_running_in_container():
        console.print(f"[dim]Manager stage - hooks will run on host sync[/dim]")
        return

    # Get issue directory
    issue_dir = get_issue_dir(issue.id)
    if not issue_dir:
        return  # No issue directory, skip hooks

    errors: List[str] = []
    hook_kwargs = {
        "issue_id": str(issue.id),
        "issue_title": issue.title,
        "branch": issue.branch or "",
        "issue": issue,  # Pass issue object for cleanup_agent and start_blocked_issues hooks
    }

    # Execute hooks from the substage config (if a substage), else from stage config
    if substage_name:
        substage_config = stage_config.get_substage(substage_name)
        if substage_config:
            errors.extend(execute_hooks(
                issue_dir,
                dot_path,
                substage_config,
                "post_start",
                pr_number=issue.pr_number,
                **hook_kwargs,
            ))
    else:
        errors.extend(execute_hooks(
            issue_dir,
            dot_path,
            stage_config,
            "post_start",
            pr_number=issue.pr_number,
            **hook_kwargs,
        ))

    # Log warnings but don't block
    if errors:
        for error in errors:
            console.print(f"[yellow]Warning: {error}[/yellow]")


def run_host_hooks(hooks: List[Dict[str, Any]], context: Dict[str, Any]) -> None:
    """Run host action hooks (post_pr_create, post_merge, post_accepted).

    These hooks log errors but don't block operations.

    Hooks can optionally run asynchronously (fire-and-forget) by setting `async: true`:
    - `async: true` - Start command immediately, don't wait for completion. Errors
      are logged when they complete.
    - No `async` or `async: false` - Wait for completion before proceeding (default)

    Thread pool is limited to 5 concurrent workers to prevent resource exhaustion.

    Args:
        hooks: List of hook configurations
        context: Template variables for substitution (issue_id, pr_number, etc.)
    """
    from pathlib import Path

    # Create executor for async hooks (max 5 concurrent)
    executor = ThreadPoolExecutor(max_workers=5)

    def execute_hook_sync(hook: Dict[str, Any]) -> List[str]:
        """Execute a single hook synchronously and return errors."""
        if "command" in hook:
            return run_command_hook(
                Path.cwd(),
                hook,
                issue_id=context.get("issue_id", ""),
                issue_title=context.get("issue_title", ""),
                branch=context.get("branch", ""),
                pr_number=str(context.get("pr_number", "")),
                pr_url=context.get("pr_url", ""),
            )
        return []

    def async_done_callback(future: Any, hook: Dict[str, Any]) -> None:
        """Log errors when async hook completes."""
        try:
            errors = future.result()
            for error in errors:
                console.print(f"[yellow]Warning (async): {error}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Hook error (async): {e}[/yellow]")

    for hook in hooks:
        try:
            is_async = hook.get("async", False)

            if is_async:
                # Fire-and-forget: submit to thread pool and continue
                future = executor.submit(execute_hook_sync, hook)
                # Add callback to log errors when done (capture hook in closure)
                def make_callback(h: Dict[str, Any]) -> Any:
                    return lambda f: async_done_callback(f, h)
                future.add_done_callback(make_callback(hook))
            else:
                # Synchronous: execute and wait for completion
                errors = execute_hook_sync(hook)
                for error in errors:
                    console.print(f"[yellow]Warning: {error}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Hook error: {e}[/yellow]")


# Aliases for backward compatibility during transition
execute_pre_hooks = execute_exit_hooks
execute_post_hooks = execute_enter_hooks


def cleanup_issue_agent(issue: Issue) -> None:
    """Clean up agent resources when issue is accepted.

    Stops tmux session, stops container, frees port.
    Uses the consolidated stop_agent function from state.py.

    Args:
        issue: Issue that was transitioned to accepted
    """
    from agenttree.api import stop_all_agents_for_issue

    # Stop all agents for this issue (handles tmux, container, and state cleanup)
    count = stop_all_agents_for_issue(issue.id)
    if count == 0:
        console.print(f"[dim]No active agents to clean up for issue #{issue.id}[/dim]")


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
            "issue_id": str(issue.id),
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
                from agenttree.api import start_agent, IssueNotFoundError, AgentStartError

                start_agent(blocked_issue.id, quiet=True)
                console.print(f"[green]✓ Started agent for issue #{blocked_issue.id}[/green]")
            except (IssueNotFoundError, AgentStartError) as e:
                console.print(f"[yellow]Could not start issue #{blocked_issue.id}: {e}[/yellow]")
            except Exception as e:
                console.print(f"[yellow]Failed to start issue #{blocked_issue.id}: {e}[/yellow]")
        else:
            console.print(f"[dim]→ Issue #{blocked_issue.id} still blocked by: {', '.join(str(u) for u in unmet)}[/dim]")


def run_resource_cleanup(dry_run: bool = False, log_file: str | None = None) -> dict:
    """Run global resource cleanup and optionally log results.

    This is used by the cleanup_resources hook to clean up stale resources
    and track what was cleaned. Tracking helps identify workflow failures -
    if we're frequently cleaning the same types of resources, it indicates
    something upstream is breaking.

    Args:
        dry_run: If True, don't actually clean anything, just report
        log_file: Optional path to log file for tracking cleanup

    Returns:
        Dict with 'cleaned' list and 'errors' list
    """
    from datetime import datetime
    from agenttree.config import load_config
    from agenttree.worktree import list_worktrees, remove_worktree
    from agenttree.tmux import list_sessions, kill_session
    from agenttree.issues import list_issues
    from agenttree.state import get_active_agent
    from agenttree.container import get_container_runtime

    config = load_config()
    repo_path = Path.cwd()

    # Track results
    cleaned: list[dict] = []
    errors: list[str] = []

    # Get all issues for reference
    all_issues = list_issues()
    issue_by_id = {i.id: i for i in all_issues}

    # 1. Find stale worktrees
    try:
        git_worktrees = list_worktrees(repo_path)
        for wt in git_worktrees:
            wt_path = Path(wt["path"])
            if wt_path == repo_path:
                continue
            wt_name = wt_path.name
            if not wt_name.startswith("issue-"):
                continue

            parts = wt_name.split("-")
            if len(parts) < 2:
                continue

            try:
                issue_id = int(parts[1])
            except ValueError:
                continue
            issue = issue_by_id.get(issue_id)

            reason = None
            if not issue:
                reason = "issue not found"
            elif config.is_parking_lot(issue.stage):
                # Parking lot stages may have worktrees cleaned up
                # For backlog, keep worktree if there are uncommitted changes
                if issue.stage == "backlog":
                    status_result = subprocess.run(
                        ["git", "status", "--porcelain"],
                        cwd=wt_path,
                        capture_output=True,
                        text=True,
                    )
                    if not status_result.stdout.strip():
                        reason = "backlogged with no changes"
                else:
                    # Other parking lots (accepted, not_doing) always clean up
                    reason = f"issue in {issue.stage} stage"

            if reason:
                if not dry_run:
                    try:
                        remove_worktree(repo_path, wt_path)
                        cleaned.append({"type": "worktree", "path": str(wt_path), "reason": reason})
                        console.print(f"[green]✓ Removed worktree: {wt_path.name}[/green]")
                    except Exception as e:
                        errors.append(f"Failed to remove worktree {wt_path}: {e}")
                else:
                    cleaned.append({"type": "worktree", "path": str(wt_path), "reason": reason})
    except Exception as e:
        errors.append(f"Worktree cleanup failed: {e}")

    # 2. Find stale branches
    try:
        result = subprocess.run(
            ["git", "branch", "--list"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        local_branches = [b.strip().lstrip("* ") for b in result.stdout.strip().split("\n") if b.strip()]

        result = subprocess.run(
            ["git", "branch", "--merged", "main"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        merged_branches = {b.strip().lstrip("* ") for b in result.stdout.strip().split("\n") if b.strip()}

        for branch in local_branches:
            if branch in ("main", "master", "HEAD"):
                continue

            branch_issue_id: int | None = None
            if branch.startswith("issue-"):
                parts = branch.split("-")
                if len(parts) >= 2:
                    try:
                        branch_issue_id = int(parts[1])
                    except ValueError:
                        pass

            reason = None
            if branch in merged_branches and branch != "main":
                reason = "merged to main"
            elif branch_issue_id is not None:
                issue = issue_by_id.get(branch_issue_id)
                if not issue:
                    reason = "issue not found"
                elif config.is_parking_lot(issue.stage) and issue.stage != "backlog":
                    # Clean branches for done/abandoned stages, but keep backlog branches
                    reason = f"issue in {issue.stage} stage"

            if reason:
                if not dry_run:
                    try:
                        subprocess.run(
                            ["git", "branch", "-D", branch],
                            cwd=repo_path,
                            check=True,
                            capture_output=True,
                        )
                        cleaned.append({"type": "branch", "name": branch, "reason": reason})
                        console.print(f"[green]✓ Deleted branch: {branch}[/green]")
                    except subprocess.CalledProcessError as e:
                        errors.append(f"Failed to delete branch {branch}: {e}")
                else:
                    cleaned.append({"type": "branch", "name": branch, "reason": reason})
    except Exception as e:
        errors.append(f"Branch cleanup failed: {e}")

    # 3. Find stale tmux sessions
    try:
        all_sessions = list_sessions()

        for session in all_sessions:
            if not config.is_project_session(session.name):
                continue

            # Extract issue ID from session name (format: project-role-id)
            parts = session.name.split("-")
            if len(parts) < 3:
                continue
            try:
                issue_id = int(parts[-1])  # ID is always the last part
            except ValueError:
                continue

            issue = issue_by_id.get(issue_id)
            reason = None
            if not issue:
                reason = "issue not found"
            elif config.is_parking_lot(issue.stage):
                # Parking lot stages shouldn't have active sessions
                reason = f"issue in {issue.stage} stage"

            if reason:
                if not dry_run:
                    try:
                        kill_session(session.name)
                        cleaned.append({"type": "session", "name": session.name, "reason": reason})
                        console.print(f"[green]✓ Killed session: {session.name}[/green]")
                    except Exception as e:
                        errors.append(f"Failed to kill session {session.name}: {e}")
                else:
                    cleaned.append({"type": "session", "name": session.name, "reason": reason})
    except Exception as e:
        errors.append(f"Session cleanup failed: {e}")

    # Log results if requested
    if log_file and cleaned:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().isoformat()
            log_entries = []
            for item in cleaned:
                entry = f"{timestamp} | {item['type']} | {item.get('path') or item.get('name')} | {item['reason']}"
                log_entries.append(entry)

            with open(log_path, "a") as f:
                f.write("\n".join(log_entries) + "\n")

            console.print(f"[dim]Logged {len(cleaned)} cleanup actions to {log_file}[/dim]")
        except Exception as e:
            errors.append(f"Failed to write cleanup log: {e}")

    # Summary
    if cleaned:
        console.print(f"\n[yellow]Cleanup summary: {len(cleaned)} items cleaned[/yellow]")
        # Group by type for analysis
        by_type: dict[str, list] = {}
        for item in cleaned:
            by_type.setdefault(item["type"], []).append(item)
        for item_type, items in by_type.items():
            console.print(f"  - {item_type}: {len(items)}")

        # Group by reason - this helps identify patterns
        by_reason: dict[str, int] = {}
        for item in cleaned:
            by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
        console.print(f"\n[cyan]Cleanup reasons (indicates potential workflow issues):[/cyan]")
        for reason, count in sorted(by_reason.items(), key=lambda x: -x[1]):
            console.print(f"  - {reason}: {count}")

    return {"cleaned": cleaned, "errors": errors}

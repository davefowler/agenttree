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

    Example:
        - section_check:
            file: review.md
            section: Self-Review Checklist
            expect: all_checked

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

State is stored in _agenttree/.hook_state.yaml

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
from concurrent.futures import ThreadPoolExecutor
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
    get_issue_context,
)
from agenttree.config import load_config

console = Console()


class ValidationError(Exception):
    """Raised when pre-hook validation fails to block a stage transition."""

    pass


class StageRedirect(Exception):
    """Raised when a hook failure should redirect to a different stage instead of blocking.

    Used with on_fail_stage option in hooks.
    """

    def __init__(self, target_stage: str, reason: str = ""):
        self.target_stage = target_stage
        self.reason = reason
        super().__init__(f"Redirect to stage '{target_stage}': {reason}")


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
    pattern = rf'^##[#]?\s*{re.escape(section)}.*?\n(.*?)(?=\n##[#]? [A-Za-z]|\Z)'
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
    "checkbox_checked",  # Review loop: check if checkbox is marked
    # Actions (perform side effects)
    "create_file", "create_pr", "merge_pr", "run", "rebase",
    "cleanup_agent", "start_blocked_issues", "cleanup_resources",
    "version_file",  # Review loop: rename file to versioned name
    "loop_check",  # Review loop: count iterations and fail if max exceeded
    "rollback",  # Review loop: programmatic rollback to earlier stage
    # Manager hooks (run on post-sync)
    "push_pending_branches", "check_manager_stages", "check_merged_prs",
    "check_ci_status", "check_custom_agent_stages", "check_stalled_agents",
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
# Rate Limiting
# =============================================================================

def check_rate_limit(
    hook_name: str,
    hook_config: Dict[str, Any],
    state: Dict[str, Any],
    sync_count: Optional[int] = None,
) -> tuple[bool, str]:
    """Check if a rate-limited hook should run.

    All hooks support rate limiting via:
    - min_interval_s: Minimum seconds between runs
    - run_every_n_syncs: Only run every Nth sync (requires sync_count)

    Args:
        hook_name: Identifier for this hook (used for state lookup)
        hook_config: Hook configuration with optional rate limit settings
        state: Hook state dict with last_run_at timestamps
        sync_count: Current sync count (for run_every_n_syncs)

    Returns:
        Tuple of (should_run, reason)
    """
    from datetime import datetime, timezone

    hook_state = state.get(hook_name, {})

    # Check time-based rate limit
    min_interval = hook_config.get("min_interval_s")
    if min_interval:
        last_run = hook_state.get("last_run_at")
        if last_run:
            try:
                last_run_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                elapsed = (datetime.now(timezone.utc) - last_run_dt).total_seconds()
                if elapsed < min_interval:
                    return False, f"Rate limited: {elapsed:.0f}s < {min_interval}s"
            except (ValueError, TypeError):
                pass  # Invalid timestamp, allow run

    # Check count-based rate limit
    run_every_n = hook_config.get("run_every_n_syncs")
    if run_every_n and sync_count is not None:
        if sync_count % run_every_n != 0:
            return False, f"Skipped: sync #{sync_count} (runs every {run_every_n})"

    return True, "Running"


def update_hook_state(
    hook_name: str,
    state: Dict[str, Any],
    success: bool = True,
    error: Optional[str] = None,
) -> None:
    """Update hook state after running.

    Args:
        hook_name: Identifier for this hook
        state: State dict to update in place
        success: Whether the hook succeeded
        error: Error message if failed
    """
    from datetime import datetime, timezone

    if hook_name not in state:
        state[hook_name] = {}

    hook_state = state[hook_name]
    hook_state["last_run_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hook_state["run_count"] = hook_state.get("run_count", 0) + 1
    hook_state["last_success"] = success

    if error:
        hook_state["last_error"] = error
    elif "last_error" in hook_state:
        del hook_state["last_error"]


def load_hook_state(agents_dir: Path) -> Dict[str, Any]:
    """Load hook state from _agenttree/.hook_state.yaml

    Args:
        agents_dir: Path to _agenttree directory

    Returns:
        State dict, empty if file doesn't exist
    """
    import yaml

    state_file = agents_dir / ".hook_state.yaml"
    if state_file.exists():
        try:
            with open(state_file) as f:
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_hook_state(agents_dir: Path, state: Dict[str, Any]) -> None:
    """Save hook state to _agenttree/.hook_state.yaml

    Args:
        agents_dir: Path to _agenttree directory
        state: State dict to save
    """
    import yaml

    state_file = agents_dir / ".hook_state.yaml"
    try:
        with open(state_file, "w") as f:
            yaml.dump(state, f, default_flow_style=False, sort_keys=False)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not save hook state: {e}[/yellow]")


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


def _action_create_pr(issue_dir: Path, issue_id: str = "", issue_title: str = "", branch: str = "", **kwargs: Any) -> None:
    """Create PR for an issue (manager stage hook - runs on host).

    This hook runs on host for manager stages (role: manager).
    Agents can't push, so PR creation is handled by the host.

    Workflow:
    1. Agent advances to implementation_review (does nothing - manager stage)
    2. Host sync calls check_manager_stages()
    3. For issues in manager stages, host runs post_start hooks
    4. This hook (create_pr) calls ensure_pr_for_issue() to create the PR
    """
    if not issue_id:
        console.print(f"[yellow]create_pr hook: no issue_id provided[/yellow]")
        return

    # Delegate to ensure_pr_for_issue which handles the actual PR creation
    ensure_pr_for_issue(issue_id)


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

            found, section_content = _extract_markdown_section(content, section)

            if not found:
                errors.append(f"Section '{section}' not found in {params['file']}")
            else:
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

    elif hook_type == "ci_check":
        # CI status check hook - waits for CI to complete and reports failures
        if pr_number is None:
            errors.append("No PR number available to check CI status")
        else:
            from agenttree.github import wait_for_ci, get_pr_checks, get_pr_comments, get_check_failed_logs

            timeout = params.get("timeout", 600)
            poll_interval = params.get("poll_interval", 30)

            console.print(f"[dim]Waiting for CI checks on PR #{pr_number}...[/dim]")
            ci_passed = wait_for_ci(pr_number, timeout, poll_interval)

            if ci_passed:
                console.print(f"[green]✓ CI checks passed for PR #{pr_number}[/green]")
            else:
                # Get detailed check status
                checks = get_pr_checks(pr_number)

                # Filter to failed/incomplete checks
                # state is FAILURE for failed checks, PENDING for still running
                failed_checks = [
                    check for check in checks
                    if check.state in ("FAILURE", "PENDING")
                ]

                if failed_checks:
                    # Create ci_feedback.md file in issue directory with logs and comments
                    if issue_dir:
                        feedback_path = issue_dir / "ci_feedback.md"
                        feedback_content = "# CI Failure Report\n\nThe following CI checks failed:\n\n"
                        for check in failed_checks:
                            feedback_content += f"- **{check.name}**: {check.state}\n"

                        # Fetch and include failed logs for each failed check
                        for check in failed_checks:
                            if check.state == "FAILURE":
                                logs = get_check_failed_logs(check)
                                if logs:
                                    feedback_content += f"\n---\n\n## Failed Logs: {check.name}\n\n```\n{logs}\n```\n"

                        # Fetch and include PR review comments
                        comments = get_pr_comments(pr_number)
                        if comments:
                            feedback_content += "\n---\n\n## Review Comments\n\n"
                            for comment in comments:
                                feedback_content += f"### From @{comment.author}\n\n"
                                feedback_content += f"{comment.body}\n\n"

                        feedback_content += "\n---\n\nPlease fix these issues and run `agenttree next` to re-submit for CI.\n"
                        feedback_path.write_text(feedback_content)
                        console.print(f"[dim]Created {feedback_path}[/dim]")

                    # Build error message
                    check_names = ", ".join(c.name for c in failed_checks)
                    errors.append(f"CI checks failed: {check_names}")
                else:
                    # No checks at all, or all passed but timeout
                    errors.append("CI check timed out or failed")

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
        # Supports on_fail_stage for conditional routing
        file_path = issue_dir / params["file"]
        checkbox_text = params.get("checkbox", "")
        on_fail_stage = params.get("on_fail_stage")

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
                if on_fail_stage:
                    # Raise redirect instead of error
                    raise StageRedirect(
                        on_fail_stage,
                        f"Checkbox '{checkbox_text}' is not checked in {params['file']}"
                    )
                else:
                    errors.append(f"Checkbox '{checkbox_text}' is not checked in {params['file']}")
            else:
                errors.append(f"Checkbox '{checkbox_text}' not found in {params['file']}")

    elif hook_type == "version_file":
        # Rename file.md to file_v{N}.md where N is next available version
        # Used in post_start to preserve history before creating new version
        filename = params.get("file", "")
        if not filename:
            errors.append("version_file hook requires 'file' parameter")
        else:
            file_path = issue_dir / filename
            if file_path.exists():
                # Find next version number
                base_name = file_path.stem
                ext = file_path.suffix
                version = 1
                while (issue_dir / f"{base_name}_v{version}{ext}").exists():
                    version += 1

                # Rename to versioned name
                versioned_path = issue_dir / f"{base_name}_v{version}{ext}"
                file_path.rename(versioned_path)
                console.print(f"[dim]Versioned {filename} → {versioned_path.name}[/dim]")
            # If file doesn't exist, silently skip (it might not exist on first iteration)

    elif hook_type == "loop_check":
        # Count versioned files and fail if max exceeded
        # Used to prevent infinite review loops
        pattern = params.get("count_files", "")
        max_iterations = params.get("max", 3)
        error_msg = params.get("error", f"Review loop exceeded {max_iterations} iterations")

        if pattern:
            # Count matching files (using pathlib's glob, not the glob module)
            matches = list(issue_dir.glob(pattern))
            if len(matches) >= max_iterations:
                errors.append(f"{error_msg} (found {len(matches)} iterations)")
                console.print(f"[yellow]Loop limit reached: {len(matches)} >= {max_iterations}[/yellow]")

    elif hook_type == "rollback":
        # Programmatic rollback to an earlier stage
        # Used in post_completion to loop back for re-review
        to_stage = params.get("to_stage", "")
        auto_yes = params.get("yes", True)  # Default to auto-confirm for programmatic rollback

        if not to_stage:
            errors.append("rollback hook requires 'to_stage' parameter")
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

    elif hook_type == "check_stalled_agents":
        from agenttree.manager_agent import get_stalled_agents

        agents_dir = kwargs.get("agents_dir")
        if agents_dir:
            threshold = params.get("threshold_min", 20)
            stalled = get_stalled_agents(agents_dir, threshold_min=threshold)

            for agent_info in stalled:
                issue_id = agent_info["issue_id"]
                minutes = agent_info["minutes_stalled"]

                # Send nudge via agenttree send --interrupt to actually interrupt the agent
                message = f"STALL DETECTED ({minutes}m). Run `agenttree next` NOW to check your progress and advance."
                try:
                    result = subprocess.run(
                        ["agenttree", "send", issue_id, message, "--interrupt"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.returncode == 0:
                        console.print(f"[yellow]Nudged stalled agent #{issue_id} ({minutes}m)[/yellow]")
                    else:
                        console.print(f"[red]Failed to nudge #{issue_id}: {result.stderr}[/red]")
                except subprocess.TimeoutExpired:
                    console.print(f"[red]Nudge timed out for #{issue_id}[/red]")
                except Exception as e:
                    console.print(f"[red]Failed to nudge #{issue_id}: {e}[/red]")

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

            if port is None:
                errors.append(
                    f"Issue {issue.id} has no valid port assigned. "
                    "Issue ID must be numeric and within the configured port_range."
                )
            else:
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
        elif hook_type in ("push_pending_branches", "check_manager_stages", "check_merged_prs", "check_custom_agent_stages"):
            # Manager hooks need agents_dir - use from kwargs if provided, otherwise context_dir
            if "agents_dir" not in kwargs:
                kwargs["agents_dir"] = context_dir
            errors = run_builtin_validator(context_dir, hook, **kwargs)
        else:
            # Built-in validator/action
            errors = run_builtin_validator(context_dir, hook, **kwargs)

        # Update state on success
        if hook_state is not None:
            update_hook_state(hook_key, hook_state, success=len(errors) == 0)

    except Exception as e:
        error_msg = f"Hook {hook_type} failed: {e}"
        errors = [error_msg]
        if hook_state is not None:
            update_hook_state(hook_key, hook_state, success=False, error=str(e))

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


def execute_exit_hooks(issue: "Issue", stage: str, substage: Optional[str] = None, **extra_kwargs: Any) -> None:
    """Execute pre_completion hooks for a stage/substage. Raises ValidationError if any fail.

    This is the config-driven replacement for execute_pre_hooks.

    Hook execution order: stage → substage (outer to inner).
    When exiting the LAST substage, runs stage-level hooks first, then substage hooks.
    This ensures stage-level requirements are checked before substage-specific ones.

    Args:
        issue: Issue being transitioned
        stage: Current stage name
        substage: Current substage name (optional)
        **extra_kwargs: Additional args (e.g., skip_pr_approval=True)

    Raises:
        ValidationError: If any validation fails (blocks transition)
        StageRedirect: If a hook with on_fail_stage fails (redirect to different stage)
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
        "issue": issue,  # Pass issue for worktree_dir access in run hooks
        **extra_kwargs,  # Pass through extra kwargs like skip_pr_approval
    }

    # Check if we're exiting the stage (last substage or no substages)
    substages = stage_config.substage_order()
    is_exiting_stage = not substages or (substage and substages[-1] == substage)

    # Execute stage-level hooks FIRST when exiting the stage (stage → substage order)
    if is_exiting_stage:
        errors.extend(execute_hooks(
            issue_dir,
            stage,
            stage_config,
            "pre_completion",
            pr_number=issue.pr_number,
            **hook_kwargs,
        ))

    # Execute substage hooks SECOND (if applicable)
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

    Hook execution order: substage → stage (inner to outer).
    When entering the FIRST substage, runs substage hooks first, then stage-level hooks.
    This ensures stage-level setup (like create_pr) runs when entering a stage with substages.

    For manager stages (role: manager), hooks are skipped when running in a container.
    The host will execute them via check_manager_stages() during sync.

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

    # Skip hooks for manager stages when in a container
    # Host will run them via check_manager_stages() during sync
    if stage_config.role == "manager" and is_running_in_container():
        console.print(f"[dim]Manager stage - hooks will run on host sync[/dim]")
        return

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
        "issue": issue,  # Pass issue object for cleanup_agent and start_blocked_issues hooks
    }

    # Execute substage hooks FIRST (if applicable)
    if substage:
        substage_config = stage_config.get_substage(substage)
        if substage_config:
            errors.extend(execute_hooks(
                issue_dir,
                stage,
                substage_config,
                "post_start",
                pr_number=issue.pr_number,
                **hook_kwargs,
            ))

    # Check if we're entering the stage (first substage or no substages)
    substages = stage_config.substage_order()
    is_entering_stage = not substages or (substage and substages[0] == substage)

    # Execute stage-level hooks SECOND when entering the stage (substage → stage order)
    if is_entering_stage:
        errors.extend(execute_hooks(
            issue_dir,
            stage,
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


def get_git_diff_stats() -> Dict[str, int]:
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


def get_commits_behind_main(worktree_dir: Optional[str]) -> int:
    """Get the number of commits the worktree is behind local main.

    Compares to local main branch (not origin/main) for fast lookups (~10ms).
    Local main is kept up to date by separate pull operations.

    Args:
        worktree_dir: Path to the worktree directory

    Returns:
        Number of commits behind main, or 0 if unable to determine
    """
    if not worktree_dir:
        return 0

    worktree_path = Path(worktree_dir)
    if not worktree_path.exists():
        return 0

    try:
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "rev-list", "--count", "HEAD..main"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            return int(result.stdout.strip())
        return 0
    except (subprocess.TimeoutExpired, ValueError, Exception):
        return 0


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


def get_code_directory(issue: Optional["Issue"], issue_dir: Path) -> Path:
    """Get the correct working directory for code operations.

    Inside containers, code is always mounted at /workspace regardless of
    the issue's worktree_dir (which is a host path). On the host, use the
    issue's worktree_dir if set, otherwise fall back to issue_dir.

    Args:
        issue: The issue object (may be None)
        issue_dir: The issue's _agenttree/issues/ directory (fallback)

    Returns:
        Path to the directory containing the code
    """
    if is_running_in_container():
        return Path("/workspace")

    if issue and hasattr(issue, 'worktree_dir') and issue.worktree_dir:
        return Path(issue.worktree_dir)

    return issue_dir


def get_current_role() -> str:
    """Get the current agent role.

    The role is determined by the AGENTTREE_ROLE env var.
    If not set, defaults to "developer" for containers or "manager" for host.

    Returns:
        Role name (e.g., "developer", "manager", "reviewer")
    """
    import os

    # Check for explicit role
    role = os.environ.get("AGENTTREE_ROLE")
    if role:
        return role

    # Default: "developer" if in container, "manager" if on host
    if is_running_in_container():
        return "developer"
    return "manager"


def can_agent_operate_in_stage(stage_role: str) -> bool:
    """Check if the current agent can operate in a stage with the given role.

    Agents can only operate in stages where the stage's role matches their identity.
    - Default agents (role="developer") can only operate in role="developer" stages
    - Custom agents (role="reviewer") can only operate in role="reviewer" stages
    - Manager can operate in any stage (it's human-driven)

    Args:
        stage_role: The role value from the stage config (e.g., "developer", "manager", "reviewer")

    Returns:
        True if the current agent can operate in this stage, False otherwise
    """
    current_role = get_current_role()

    # Manager (human) can operate anywhere
    if current_role == "manager":
        return True

    # Agents can only operate in their own role stages
    return current_role == stage_role


def ensure_pr_for_issue(issue_id: str) -> bool:
    """Ensure a PR exists for an issue in a manager stage.

    Called by host via create_pr hook for manager stages (role: manager).
    Stage check is done by check_manager_stages(), not here.

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

    # Already has PR - idempotent
    if issue.pr_number:
        return True

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

    # Create PR with link back to issue
    title = f"[Issue {issue.id}] {issue.title}"

    # Build PR body with issue link and context
    body = f"## Summary\n\n"
    body += f"Implementation for **Issue #{issue.id}**: {issue.title}\n\n"
    body += f"**Issue link:** [View in AgentTree Flow](http://localhost:8080/flow?issue={issue.id})\n\n"

    # Try to include brief context from spec.md if it exists
    spec_path = worktree_path / "_agenttree" / "issues" / f"{issue.id.zfill(3)}-{issue.slug[:40]}" / "spec.md"
    if not spec_path.exists():
        # Try finding it with glob
        for p in (worktree_path / "_agenttree" / "issues").glob(f"{issue.id.zfill(3)}-*/spec.md"):
            spec_path = p
            break

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

    body += f"---\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"

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
    Uses the consolidated stop_agent function from state.py.

    Args:
        issue: Issue that was transitioned to accepted
    """
    from agenttree.state import stop_all_agents_for_issue

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
    from agenttree.issues import list_issues, BACKLOG
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

            issue_id = parts[1]
            issue = issue_by_id.get(issue_id)

            reason = None
            if not issue:
                reason = "issue not found"
            elif config.is_parking_lot(issue.stage):
                # Parking lot stages may have worktrees cleaned up
                # For backlog, keep worktree if there are uncommitted changes
                if issue.stage == BACKLOG:
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

            branch_issue_id: str | None = None
            if branch.startswith("issue-"):
                parts = branch.split("-")
                if len(parts) >= 2:
                    branch_issue_id = parts[1]

            reason = None
            if branch in merged_branches and branch != "main":
                reason = "merged to main"
            elif branch_issue_id:
                issue = issue_by_id.get(branch_issue_id)
                if not issue:
                    reason = "issue not found"
                elif config.is_parking_lot(issue.stage) and issue.stage != BACKLOG:
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
        project_prefix = f"{config.project}-issue-"

        for session in all_sessions:
            if not session.name.startswith(project_prefix):
                continue

            suffix = session.name[len(project_prefix):]
            issue_id = suffix.split("-")[0]

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

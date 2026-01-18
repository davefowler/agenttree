"""Unified hook system for AgentTree.

This module provides a config-driven hook system used by both:
1. **Stage hooks** - Validation/actions during workflow stage transitions
2. **Controller hooks** - Post-sync operations for the controller

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
    Only run this hook on the host (controller), skip in containers.

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

Controller hooks run after each sync and support rate limiting.
Configure in .agenttree.yaml under controller_hooks:

    controller_hooks:
      post_sync:
        - push_pending_branches: {}
        - check_controller_stages: {}
        - check_merged_prs: {}
        - check_ci_status:
            min_interval_s: 60
            run_every_n_syncs: 5

Built-in controller hooks:
    push_pending_branches - Push any local branches with unpushed commits
    check_controller_stages - Process issues in controller-owned stages
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
    run_every_n_syncs: Only run every Nth sync (controller hooks only)

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

Controller hooks (for post-sync operations):
    from agenttree.controller_hooks import run_post_controller_hooks

    run_post_controller_hooks(agents_dir)

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
)
from agenttree.config import load_config

console = Console()


class ValidationError(Exception):
    """Raised when pre-hook validation fails to block a stage transition."""

    pass


# =============================================================================
# Hook Type Registry
# =============================================================================

# All known hook types (validators, actions, and controller hooks)
HOOK_TYPES = {
    # Validators (return errors if validation fails)
    "file_exists", "has_commits", "field_check", "section_check", "pr_approved",
    "min_words", "has_list_items", "contains", "ci_check", "wrapup_verified",
    # Actions (perform side effects)
    "create_file", "create_pr", "merge_pr", "run", "rebase",
    "cleanup_agent", "start_blocked_issues",
    # Controller hooks (run on post-sync)
    "push_pending_branches", "check_controller_stages", "check_merged_prs",
    "check_ci_status",
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
    "host_only": False,     # bool: Only run on host (controller), skip in containers

    # Timeouts (for run/command hooks)
    "timeout": 30,          # int: Timeout in seconds for command execution

    # Rate limiting (prevents running too frequently)
    "min_interval_s": None,     # int: Minimum seconds between runs
    "run_every_n_syncs": None,  # int: Only run every Nth sync (controller hooks)
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
    """Create PR for an issue (controller stage hook - runs on host).

    This hook runs on host for controller stages (host: controller).
    Agents can't push, so PR creation is handled by the host.

    Workflow:
    1. Agent advances to implementation_review (does nothing - controller stage)
    2. Host sync calls check_controller_stages()
    3. For issues in controller stages, host runs post_start hooks
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
            from agenttree.github import wait_for_ci, get_pr_checks

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
                # A check is considered failed if:
                # - It's still pending (not completed)
                # - Its conclusion is "failure"
                # - It's not successful and not skipped
                failed_checks = [
                    check for check in checks
                    if (check.state == "PENDING")
                    or (check.conclusion == "failure")
                    or (check.state != "SUCCESS" and check.conclusion not in ("success", "skipped", None))
                ]

                # If no specific failed checks but wait_for_ci returned False, it's a timeout
                if not failed_checks and checks:
                    failed_checks = [
                        check for check in checks
                        if check.state == "PENDING" or check.conclusion not in ("success", "skipped")
                    ]

                if failed_checks:
                    # Create ci_feedback.md file in issue directory
                    if issue_dir:
                        feedback_path = issue_dir / "ci_feedback.md"
                        feedback_content = "# CI Failure Report\n\nThe following CI checks failed:\n\n"
                        for check in failed_checks:
                            feedback_content += f"## {check.name}\n"
                            feedback_content += f"- **State:** {check.state}\n"
                            feedback_content += f"- **Conclusion:** {check.conclusion}\n\n"
                        feedback_content += "Please fix these issues and run `agenttree next` to re-submit for CI.\n"
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
            if not dest_path.exists() and template_path.exists():
                template_content = template_path.read_text()

                # Build Jinja context
                from jinja2 import Template
                from agenttree.commands import get_referenced_commands, get_command_output

                issue = kwargs.get("issue")
                context: Dict[str, Any] = {}

                if issue:
                    context = {
                        "issue_id": issue.id,
                        "issue_title": issue.title,
                        "issue_dir": str(issue_dir),
                        "issue_dir_rel": f"_agenttree/issues/{issue.id}-{issue.slug}" if hasattr(issue, 'slug') else "",
                    }

                    # Add document contents if they exist
                    for doc_name in ["problem.md", "research.md", "spec.md", "spec_review.md", "review.md"]:
                        doc_path = issue_dir / doc_name
                        var_name = doc_name.replace(".md", "_md").replace("-", "_")
                        if doc_path.exists():
                            context[var_name] = doc_path.read_text()
                        else:
                            context[var_name] = ""

                # Add git diff stats for review templates
                git_stats = get_git_diff_stats()
                context["files_changed"] = git_stats['files_changed']
                context["lines_added"] = git_stats['lines_added']
                context["lines_removed"] = git_stats['lines_removed']

                # Inject command outputs for referenced commands
                config = load_config()
                if config.commands:
                    # Determine working directory for commands
                    cwd = None
                    if issue and hasattr(issue, 'worktree_dir') and issue.worktree_dir:
                        cwd = Path(issue.worktree_dir)
                    else:
                        cwd = issue_dir

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

    # Controller hooks (delegated to agents_repo functions)
    elif hook_type == "push_pending_branches":
        from agenttree.agents_repo import push_pending_branches
        agents_dir = kwargs.get("agents_dir")
        if agents_dir:
            push_pending_branches(agents_dir)

    elif hook_type == "check_controller_stages":
        from agenttree.agents_repo import check_controller_stages
        agents_dir = kwargs.get("agents_dir")
        if agents_dir:
            check_controller_stages(agents_dir)

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
        context_dir: Directory context (issue_dir for stage hooks, agents_dir for controller)
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
        elif hook_type in ("push_pending_branches", "check_controller_stages", "check_merged_prs"):
            # Controller hooks need agents_dir - use from kwargs if provided, otherwise context_dir
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
            # Shell command hook - use worktree_dir if available, otherwise issue_dir
            issue = kwargs.get("issue")
            if issue and hasattr(issue, 'worktree_dir') and issue.worktree_dir:
                cwd = Path(issue.worktree_dir)
            else:
                cwd = issue_dir
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
        "issue": issue,  # Pass issue for worktree_dir access in run hooks
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

    For controller stages (host: controller), hooks are skipped when running in a container.
    The host will execute them via check_controller_stages() during sync.

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

    # Skip hooks for controller stages when in a container
    # Host will run them via check_controller_stages() during sync
    if stage_config.host == "controller" and is_running_in_container():
        console.print(f"[dim]Controller stage - hooks will run on host sync[/dim]")
        return

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


def ensure_pr_for_issue(issue_id: str) -> bool:
    """Ensure a PR exists for an issue in a controller stage.

    Called by host via create_pr hook for controller stages (host: controller).
    Stage check is done by check_controller_stages(), not here.

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

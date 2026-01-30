"""Rollback functionality for AgentTree issues.

This module provides programmatic rollback functionality used by both
the CLI rollback command and the rollback hook.

Separated into its own module to avoid circular imports between
hooks.py and cli.py.
"""

import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()


def execute_rollback(
    issue_id: str,
    target_stage: str,
    yes: bool = True,
    reset_worktree: bool = False,
    keep_changes: bool = True,
    skip_sync: bool = False,
) -> bool:
    """Execute a rollback programmatically. Used by both CLI and hooks.

    Args:
        issue_id: Issue ID to rollback
        target_stage: Stage to rollback to
        yes: Auto-confirm (default True for programmatic use)
        reset_worktree: Reset worktree to origin/main
        keep_changes: Keep code changes (default True)
        skip_sync: Skip syncing changes (for hook use where caller handles sync)

    Returns:
        True if rollback succeeded, False otherwise
    """
    from datetime import datetime, timezone
    from agenttree.state import get_active_agent, unregister_agent
    from agenttree.config import load_config
    from agenttree.issues import get_issue, get_issue_dir
    from agenttree.agents_repo import delete_session
    import shutil
    import yaml as pyyaml

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = get_issue(issue_id_normalized)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        return False

    # Load config and validate stage
    config = load_config()
    stage_names = config.get_stage_names()

    if target_stage not in stage_names:
        console.print(f"[red]Invalid stage: '{target_stage}'[/red]")
        return False

    # Check if target stage is before or same as current stage
    try:
        current_idx = stage_names.index(issue.stage)
        target_idx = stage_names.index(target_stage)
    except ValueError:
        console.print(f"[red]Issue is at unknown stage: {issue.stage}[/red]")
        return False

    if target_idx >= current_idx:
        console.print(f"[red]Cannot rollback: target stage '{target_stage}' is not before current stage '{issue.stage}'[/red]")
        return False

    # Cannot rollback to terminal stages
    target_stage_config = config.get_stage(target_stage)
    if target_stage_config and target_stage_config.terminal:
        console.print(f"[red]Cannot rollback to terminal stage '{target_stage}'[/red]")
        return False

    # Determine first substage of target stage
    target_substage = None
    if target_stage_config:
        substages = target_stage_config.substage_order()
        if substages:
            target_substage = substages[0]

    # Collect stages after target that will have output files archived
    stages_to_archive = stage_names[target_idx + 1 : current_idx + 1]

    # Collect output files from stages being rolled back
    files_to_archive: list[str] = []
    for stage in stages_to_archive:
        stage_config = config.get_stage(stage)
        if stage_config:
            if stage_config.output:
                files_to_archive.append(stage_config.output)
            for substage_config in stage_config.substages.values():
                if substage_config.output:
                    files_to_archive.append(substage_config.output)

    # Determine worktree reset behavior
    implement_idx = stage_names.index("implement") if "implement" in stage_names else -1
    auto_reset = target_idx < implement_idx if implement_idx >= 0 else False
    should_reset = reset_worktree or (auto_reset and not keep_changes)

    # Check for active agent
    active_agent = get_active_agent(issue_id_normalized)
    issue_dir = get_issue_dir(issue_id_normalized)

    # Archive output files
    if issue_dir and files_to_archive:
        archive_dir = issue_dir / "archive"
        archive_dir.mkdir(exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rollback_dir = archive_dir / f"rollback_{timestamp}"
        rollback_dir.mkdir(exist_ok=True)

        archived_count = 0
        for filename in files_to_archive:
            src = issue_dir / filename
            if src.exists():
                dst = rollback_dir / filename
                shutil.move(str(src), str(dst))
                console.print(f"  [dim]Archived: {filename}[/dim]")
                archived_count += 1

        if archived_count > 0:
            console.print(f"[dim]Archived {archived_count} file(s) to archive/rollback_{timestamp}/[/dim]")

    # Update issue stage with rollback history entry
    if issue_dir:
        yaml_path = issue_dir / "issue.yaml"
        if yaml_path.exists():
            with open(yaml_path) as fh:
                data = pyyaml.safe_load(fh)

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            data["stage"] = target_stage
            data["substage"] = target_substage
            data["updated"] = now

            history_entry = {
                "stage": target_stage,
                "substage": target_substage,
                "timestamp": now,
                "type": "rollback",
            }
            if "history" not in data:
                data["history"] = []
            data["history"].append(history_entry)

            # Clear PR metadata
            if "pr_number" in data:
                del data["pr_number"]
            if "pr_url" in data:
                del data["pr_url"]

            with open(yaml_path, "w") as fh:
                pyyaml.dump(data, fh, default_flow_style=False, sort_keys=False)

    # Clear agent session
    delete_session(issue_id_normalized)

    # Unregister active agent
    if active_agent:
        unregister_agent(issue_id_normalized)

    # Reset worktree if requested
    if should_reset and active_agent:
        worktree_path = active_agent.worktree
        if worktree_path.exists():
            try:
                subprocess.run(
                    ["git", "reset", "--hard", "origin/main"],
                    cwd=worktree_path,
                    capture_output=True,
                    check=True,
                )
            except subprocess.CalledProcessError:
                pass  # Non-fatal

    # Sync changes (unless skipped)
    if not skip_sync:
        from agenttree.agents_repo import sync_agents_repo
        from agenttree.issues import get_agenttree_path
        agents_path = get_agenttree_path()
        sync_agents_repo(agents_path, pull_only=False, commit_message=f"Rollback issue {issue_id} to {target_stage}")

    return True

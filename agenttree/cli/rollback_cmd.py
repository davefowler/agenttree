"""Rollback command for issues."""

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml as pyyaml

from agenttree.cli.common import console
from agenttree.config import load_config
from agenttree.hooks import is_running_in_container
from agenttree.issues import (
    get_issue as get_issue_func,
    get_issue_dir,
    delete_session,
)


def _execute_rollback(
    issue_id: str,
    target_stage: str,
    yes: bool = True,
    reset_worktree: bool = False,
    keep_changes: bool = True,
    skip_sync: bool = False,
) -> bool:
    """Execute a rollback programmatically. Used by both CLI and hooks.

    This is a thin wrapper around agenttree.rollback.execute_rollback to avoid
    circular imports between hooks.py and cli.py.

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
    from agenttree.rollback import execute_rollback
    return execute_rollback(
        issue_id=issue_id,
        target_stage=target_stage,
        yes=yes,
        reset_worktree=reset_worktree,
        keep_changes=keep_changes,
        skip_sync=skip_sync,
    )


@click.command("rollback")
@click.argument("issue_id", type=str)
@click.argument("stage_name", type=str)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.option(
    "--reset-worktree",
    is_flag=True,
    help="Reset worktree to origin/main (discards code changes)",
)
@click.option(
    "--keep-changes",
    is_flag=True,
    help="Keep code changes in worktree (default for pre-implement stages)",
)
def rollback_issue(
    issue_id: str,
    stage_name: str,
    yes: bool,
    reset_worktree: bool,
    keep_changes: bool,
) -> None:
    """Roll back an issue to an earlier stage.

    Archives output files from stages after the target stage and resets
    the issue state. Use this when an issue has gone down the wrong path
    and needs to be redone from an earlier point.

    Examples:
        agenttree rollback 085 research      # Roll back to research stage
        agenttree rollback 042 plan --yes    # Skip confirmation
        agenttree rollback 042 define --reset-worktree  # Also discard code changes
    """
    from agenttree.state import get_active_agents_for_issue, unregister_all_agents_for_issue

    # Block if in container
    if is_running_in_container():
        console.print("[red]Error: 'rollback' cannot be run from inside a container[/red]")
        console.print("[dim]This command is for human reviewers only.[/dim]")
        sys.exit(1)

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    # Load config and validate stage
    config = load_config()
    stage_names = config.get_stage_names()

    if stage_name not in stage_names:
        console.print(f"[red]Invalid stage: '{stage_name}'[/red]")
        console.print(f"[dim]Valid stages: {', '.join(stage_names)}[/dim]")
        sys.exit(1)

    # Check if target stage is before or same as current stage
    try:
        current_idx = stage_names.index(issue.stage)
        target_idx = stage_names.index(stage_name)
    except ValueError:
        console.print(f"[red]Issue is at unknown stage: {issue.stage}[/red]")
        sys.exit(1)

    if target_idx >= current_idx:
        console.print(f"[red]Cannot rollback: target stage '{stage_name}' is not before current stage '{issue.stage}'[/red]")
        console.print("[dim]Rollback is for going backwards in the workflow.[/dim]")
        sys.exit(1)

    # Cannot rollback to redirect_only stages (they're not in normal progression)
    target_stage_config = config.get_stage(stage_name)
    if target_stage_config and target_stage_config.redirect_only:
        console.print(f"[red]Cannot rollback to redirect-only stage '{stage_name}'[/red]")
        sys.exit(1)

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
            # Stage-level output
            if stage_config.output:
                files_to_archive.append(stage_config.output)
            # Substage outputs
            for substage_config in stage_config.substages.values():
                if substage_config.output:
                    files_to_archive.append(substage_config.output)

    # Determine worktree reset behavior
    # Auto-reset if rolling back to before implement stage
    implement_idx = stage_names.index("implement") if "implement" in stage_names else -1
    auto_reset = target_idx < implement_idx if implement_idx >= 0 else False

    should_reset = reset_worktree or (auto_reset and not keep_changes)

    # Check for active agents (all hosts)
    active_agents = get_active_agents_for_issue(issue_id_normalized)
    active_agent = active_agents[0] if active_agents else None  # For worktree reference

    # Show confirmation
    issue_dir = get_issue_dir(issue_id_normalized)

    console.print(f"\n[bold]Rollback Issue #{issue.id}: {issue.title}[/bold]")
    console.print(f"\n  Current stage: [yellow]{issue.stage}[/yellow]")
    target_str = stage_name
    if target_substage:
        target_str += f".{target_substage}"
    console.print(f"  Target stage:  [green]{target_str}[/green]")

    if files_to_archive:
        console.print(f"\n  Files to archive:")
        for f in files_to_archive:
            file_path = issue_dir / f if issue_dir else Path(f)
            exists = " (exists)" if file_path.exists() else " (not found)"
            console.print(f"    - {f}{exists}")

    if active_agents:
        console.print(f"\n  [yellow]⚠ {len(active_agents)} active agent(s) will be unregistered[/yellow]")

    if should_reset:
        console.print(f"\n  [yellow]⚠ Worktree will be reset to origin/main[/yellow]")
    else:
        console.print(f"\n  [dim]Worktree changes will be preserved[/dim]")

    console.print()

    # Confirm unless --yes
    if not yes:
        if not click.confirm("Proceed with rollback?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    # === Execute rollback ===

    # 1. Archive output files
    if issue_dir and files_to_archive:
        archive_dir = issue_dir / "archive"
        archive_dir.mkdir(exist_ok=True)

        # Create timestamped subdirectory for this rollback
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
            console.print(f"[green]✓ Archived {archived_count} file(s) to archive/rollback_{timestamp}/[/green]")

    # 2. Update issue stage with rollback history entry
    if issue_dir:
        yaml_path = issue_dir / "issue.yaml"
        if yaml_path.exists():
            with open(yaml_path) as fh:
                data = pyyaml.safe_load(fh)

            # Update stage
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            data["stage"] = stage_name
            data["substage"] = target_substage
            data["updated"] = now

            # Add rollback history entry
            history_entry = {
                "stage": stage_name,
                "substage": target_substage,
                "timestamp": now,
                "type": "rollback",
            }
            if "history" not in data:
                data["history"] = []
            data["history"].append(history_entry)

            # Clear PR metadata (don't close the PR, just clear the reference)
            if "pr_number" in data:
                del data["pr_number"]
            if "pr_url" in data:
                del data["pr_url"]

            with open(yaml_path, "w") as fh:
                pyyaml.dump(data, fh, default_flow_style=False, sort_keys=False)

            console.print(f"[green]✓ Issue stage set to {target_str}[/green]")

    # 3. Clear agent session
    delete_session(issue_id_normalized)
    console.print("[green]✓ Cleared agent session[/green]")

    # 4. Unregister all active agents (if any)
    if active_agents:
        unregister_all_agents_for_issue(issue_id_normalized)
        console.print(f"[green]✓ Unregistered {len(active_agents)} active agent(s)[/green]")

    # 5. Reset worktree if requested
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
                console.print(f"[green]✓ Reset worktree to origin/main[/green]")
            except subprocess.CalledProcessError as e:
                console.print(f"[yellow]Warning: Failed to reset worktree: {e}[/yellow]")

    # 6. Sync changes
    from agenttree.agents_repo import sync_agents_repo
    from agenttree.issues import get_agenttree_path
    agents_path = get_agenttree_path()
    sync_agents_repo(agents_path, pull_only=False, commit_message=f"Rollback issue {issue_id} to {stage_name}")

    console.print(f"\n[green]✓ Issue #{issue.id} rolled back to {target_str}[/green]")
    if active_agent:
        console.print(f"\n[dim]Restart the agent when ready:[/dim]")
        console.print(f"  agenttree start {issue.id}")

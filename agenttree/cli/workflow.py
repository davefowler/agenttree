"""Workflow commands (status, next, approve, defer, shutdown, rollback)."""

import subprocess
import sys
from pathlib import Path

import click
from rich.table import Table

from agenttree.cli._utils import console, load_config, get_issue_func, get_issue_dir, normalize_issue_id
from agenttree.tmux import TmuxManager, save_tmux_history_to_file
from agenttree.hooks import (
    execute_exit_hooks,
    execute_enter_hooks,
    ValidationError,
    StageRedirect,
    is_running_in_container,
    get_current_role,
)
from agenttree.issues import (
    Issue,
    list_issues as list_issues_func,
    get_next_stage,
    get_issue_context,
    update_issue_stage,
    update_issue_metadata,
    load_skill,
    load_persona,
    create_session,
    get_session,
    is_restart,
    mark_session_oriented,
    update_session_stage,
    delete_session,
)


def _format_duration(minutes: int) -> str:
    """Format minutes as a human-readable duration (e.g., '5m', '2h', '1d')."""
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"


def _time_in_stage(issue: Issue) -> str:
    """Compute time in current stage from last history entry."""
    from datetime import datetime, timezone

    if not issue.history:
        return "?"
    try:
        ts = issue.history[-1].timestamp
        stage_start = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elapsed_min = int((datetime.now(timezone.utc) - stage_start).total_seconds() / 60)
        return _format_duration(elapsed_min)
    except (ValueError, TypeError):
        return "?"


@click.command("status")
@click.option("--issue", "-i", "issue_id", help="Issue ID (if not in agent context)")
@click.option("--active-only", is_flag=True, help="Show only issues where an agent should be actively working")
def stage_status(issue_id: str | None, active_only: bool) -> None:
    """Show current issue and stage status.

    Examples:
        agenttree status
        agenttree status --active-only
        agenttree status --issue 001
    """
    # Try to get issue from argument or agent context
    if not issue_id:
        config = load_config()

        if active_only:
            console.print("[dim]Showing issues where agents should be actively working:[/dim]\n")
        else:
            console.print("[dim]Showing all active issues (use --issue ID for details):[/dim]\n")

        # Show all non-backlog, non-accepted issues
        active_issues = [
            i for i in list_issues_func()
            if i.stage not in ("backlog", "accepted", "not_doing")
        ]

        if active_only:
            # Filter out parking lots, human review stages, manager stages
            active_issues = [
                i for i in active_issues
                if not config.is_parking_lot(i.stage)
                and not config.is_human_review(i.stage)
                and config.role_for(i.stage) != "manager"
            ]

        if not active_issues:
            console.print("[dim]No active issues[/dim]")
            return

        table = Table(title="Active Issues")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("Stage", style="magenta")
        table.add_column("Time", style="yellow", justify="right")

        for active_issue in active_issues:
            table.add_row(
                active_issue.id,
                active_issue.title[:40],
                active_issue.stage,
                _time_in_stage(active_issue),
            )

        console.print(table)
        return

    issue = get_issue_func(issue_id)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    console.print(f"\n[bold cyan]Issue {issue.id}: {issue.title}[/bold cyan]")
    console.print(f"[bold]Stage:[/bold] {issue.stage}")

    # Check if waiting for non-developer role
    config_for_status = load_config()
    stage_group, _ = config_for_status.parse_stage(issue.stage)
    status_stage_config = config_for_status.get_stage(stage_group)
    if status_stage_config and status_stage_config.role != "developer":
        if status_stage_config.role == "manager":
            console.print(f"\n[yellow]⏳ Waiting for human review[/yellow]")
        else:
            console.print(f"\n[yellow]⏳ Waiting for '{status_stage_config.role}' agent[/yellow]")
    elif issue.stage == "accepted":
        console.print(f"\n[green]✓ Issue completed[/green]")


@click.command("next")
@click.option("--issue", "-i", "issue_id", required=False, help="Issue ID (auto-detected from branch if not provided)")
@click.option("--reassess", is_flag=True, help="Go back to plan_assess for another review cycle")
def stage_next(issue_id: str | None, reassess: bool) -> None:
    """Move to the next substage or stage.

    Examples:
        agenttree next --issue 001
        agenttree next  # Auto-detects issue from branch
        agenttree next --reassess  # Cycle back to plan_assess from plan_revise
    """
    from agenttree.issues import get_issue_from_branch

    # Auto-detect issue from branch if not provided
    if not issue_id:
        issue_id = get_issue_from_branch()
        if not issue_id:
            console.print("[red]No issue ID provided and couldn't detect from branch name[/red]")
            console.print("[dim]Use --issue <ID> or run from a branch like 'issue-042-slug'[/dim]")
            sys.exit(1)
        console.print(f"[dim]Detected issue {issue_id} from branch[/dim]")

    issue = get_issue_func(issue_id)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    if issue.stage == "accepted":
        console.print(f"[yellow]Issue is already accepted[/yellow]")
        return

    if issue.stage == "not_doing":
        console.print(f"[yellow]Issue is marked as not doing[/yellow]")
        return

    # Block agents from operating in manager (human review) stages only
    # Other agent stages can be advanced - hooks will enforce requirements
    config = load_config()
    stage_role = config.role_for(issue.stage)
    current_role = get_current_role()
    # Only block if this is a manager stage and we're not the manager
    if stage_role == "manager" and current_role != "manager":
        console.print(f"\n[yellow]⏳ Waiting for human review[/yellow]")
        console.print(f"[dim]Stage '{issue.stage}' requires human review.[/dim]")
        console.print(f"[dim]A human will run 'agenttree approve {issue.id}' when ready.[/dim]")
        return

    # Check for restart and re-orient if needed
    session = get_session(issue_id)
    if session is None:
        # No session exists - create one (fresh start or legacy case)
        session = create_session(issue_id)

    if is_restart(issue_id, issue.stage):
        # This is a restart - re-orient the agent instead of advancing
        console.print(f"\n[cyan]🔄 Session restart detected[/cyan]")
        console.print(f"[dim]Resuming work on issue #{issue.id}: {issue.title}[/dim]\n")

        console.print(f"[bold]Current stage:[/bold] {issue.stage}")

        # Show existing files
        issue_dir = get_issue_dir(issue_id)
        if issue_dir:
            existing_files = [f.name for f in issue_dir.iterdir() if f.is_file() and not f.name.startswith('.')]
            if existing_files:
                console.print(f"[bold]Existing work:[/bold] {', '.join(existing_files)}")

        # Show uncommitted changes if any (both staged and unstaged)
        try:
            result = subprocess.run(
                ["git", "diff", "--stat", "HEAD"],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                console.print(f"\n[bold]Uncommitted changes:[/bold]")
                console.print(result.stdout[:500])
        except Exception as e:
            console.print(f"[dim]Note: Could not check git status: {e}[/dim]")

        # Determine if this is a takeover (not starting from beginning)
        is_takeover = issue.stage not in ("backlog", "explore.define")

        # Load and display persona for context
        persona = load_persona(
            agent_type="developer",  # TODO: Get from host config
            issue=issue,
            is_takeover=is_takeover,
            current_stage=issue.stage,
        )
        if persona:
            console.print(f"\n{'='*60}")
            console.print(f"[bold cyan]AGENT PERSONA[/bold cyan]")
            console.print(f"{'='*60}\n")
            console.print(persona)

            # Add takeover context message
            if is_takeover:
                console.print(f"\n[yellow]{'='*60}[/yellow]")
                console.print(f"[bold yellow]TAKEOVER NOTICE[/bold yellow]")
                console.print(f"[yellow]{'='*60}[/yellow]\n")
                console.print(
                    f"You are taking over for another agent who completed stages before [bold]{issue.stage}[/bold].\n"
                    f"Please review their work in the existing files and continue from here."
                )

        # Load and display current stage instructions
        skill = load_skill(issue.stage, issue=issue)
        if skill:
            display_name = config.stage_display_name(issue.stage)
            console.print(f"\n{'='*60}")
            console.print(f"[bold cyan]Continue working on: {display_name}[/bold cyan]")
            console.print(f"{'='*60}\n")
            console.print(skill)

        console.print(f"\n[dim]When ready to advance, run 'agenttree next' again.[/dim]")

        # Mark as oriented and sync stage so next call will advance
        mark_session_oriented(issue_id, issue.stage)
        return

    # Block agents from advancing past human_review stages — only `agenttree approve` can do that
    current_stage_config = config.get_stage(issue.stage)
    if current_stage_config and current_stage_config.human_review and is_running_in_container():
        console.print(f"\n[yellow]⏳ Waiting for human review at {issue.stage}[/yellow]")
        console.print(f"[dim]This stage requires human approval.[/dim]")
        console.print(f"[dim]Use 'agenttree approve {issue_id}' from the host to advance.[/dim]")
        return

    # Handle --reassess flag for plan revision cycling
    if reassess:
        if issue.stage != "plan.revise":
            console.print(f"[red]--reassess only works from plan.revise stage[/red]")
            sys.exit(1)
        next_stage = "plan.assess"
        is_human_review = False
    else:
        # Calculate next stage (pass issue context for condition evaluation)
        issue_ctx = get_issue_context(issue, include_docs=False)
        next_stage, is_human_review = get_next_stage(
            issue.stage, issue.flow, issue_context=issue_ctx
        )

    # Check if we're already at the next stage (no change)
    if next_stage == issue.stage:
        console.print(f"[yellow]Already at final stage[/yellow]")
        return

    # Execute exit hooks (can block with ValidationError or redirect with StageRedirect)
    from_stage = issue.stage
    try:
        execute_exit_hooks(issue, from_stage)
    except StageRedirect as redirect:
        # Redirect to a different stage instead of normal next
        console.print(f"[yellow]Redirecting to {redirect.target}: {redirect.reason}[/yellow]")
        next_stage = redirect.target
        is_human_review = False  # Redirect target is typically not human review
    except ValidationError as e:
        console.print(f"[red]Cannot proceed: {e}[/red]")
        sys.exit(1)

    # Save tmux history if enabled in config
    if config.save_tmux_history:
        issue_dir = get_issue_dir(issue_id)
        if issue_dir:
            session_name = config.get_issue_tmux_session(issue_id)
            history_file = issue_dir / "tmux_history.log"
            if save_tmux_history_to_file(session_name, history_file, from_stage):
                console.print(f"[dim]Saved tmux history to {history_file.name}[/dim]")

    # Update issue stage in database
    updated = update_issue_stage(issue_id, next_stage)
    if not updated:
        console.print(f"[red]Failed to update issue[/red]")
        sys.exit(1)

    # Update session to track stage advancement
    update_session_stage(issue_id, next_stage)

    # Execute enter hooks (after stage updated)
    execute_enter_hooks(updated, next_stage)

    console.print(f"[green]✓ Moved to {next_stage}[/green]")

    # Check if next stage requires a different role
    next_role = config.role_for(next_stage)
    if next_role != "developer" and is_running_in_container():
        if next_role == "manager" or is_human_review:
            console.print(f"\n[yellow]⏳ Waiting for human review[/yellow]")
            console.print(f"[dim]Your work has been submitted for review.[/dim]")
            console.print(f"[dim]You will receive instructions when the review is complete.[/dim]")
        else:
            console.print(f"\n[yellow]⏳ Waiting for '{next_role}' agent[/yellow]")
            console.print(f"[dim]The '{next_role}' agent will handle the next stage.[/dim]")
            console.print(f"[dim]You will receive instructions when that stage is complete.[/dim]")
            return

    # Determine if this is first agent entry (should include AGENTS.md system prompt)
    is_first_stage = next_stage == "explore.define" and from_stage == "backlog"

    # Load and display skill for next stage with Jinja rendering
    skill = load_skill(next_stage, issue=updated, include_system=is_first_stage)
    if skill:
        display_name = config.stage_display_name(next_stage)
        console.print(f"\n{'='*60}")
        console.print(f"[bold cyan]Stage Instructions: {display_name}[/bold cyan]")
        console.print(f"{'='*60}\n")
        console.print(skill)




@click.command("approve")
@click.argument("issue_id", type=str)
@click.option("--skip-approval", is_flag=True, help="Skip PR approval check (useful if you're the PR author)")
def approve_issue(issue_id: str, skip_approval: bool) -> None:
    """Approve an issue at a human review stage.

    Only works at human review stages (plan_review, implementation_review).
    Cannot be run from inside a container - humans only.

    For implementation_review: will auto-approve the PR on GitHub unless you're the author.
    Use --skip-approval to bypass if you've already reviewed the changes.

    Example:
        agenttree approve 042
        agenttree approve 042 --skip-approval  # Skip PR approval check
    """
    # Block if in container
    if is_running_in_container():
        console.print(f"[red]Error: 'approve' cannot be run from inside a container[/red]")
        console.print(f"[dim]This command is for human reviewers only.[/dim]")
        sys.exit(1)

    # Normalize issue ID
    issue_id_normalized = normalize_issue_id(issue_id)
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    # Check if at a stage that requires human approval (human_review=true or role=manager)
    approve_config = load_config()
    approve_role = approve_config.role_for(issue.stage)
    if not (approve_config.is_human_review(issue.stage) or approve_role == "manager"):
        human_review_stages = approve_config.get_human_review_stages()
        console.print(f"[red]Issue is at '{issue.stage}', not a human review stage[/red]")
        console.print(f"[dim]Human review stages: {', '.join(human_review_stages)}[/dim]")
        sys.exit(1)

    # Calculate next stage (pass issue context for condition evaluation)
    issue_ctx = get_issue_context(issue, include_docs=False)
    next_stage, _ = get_next_stage(
        issue.stage, issue.flow, issue_context=issue_ctx
    )

    # Use consolidated transition_issue() — handles exit hooks, stage update, enter hooks
    from agenttree.api import transition_issue
    try:
        updated = transition_issue(
            issue_id_normalized,
            next_stage,
            skip_pr_approval=skip_approval,
            trigger="cli",
        )
    except StageRedirect as redirect:
        console.print(f"[yellow]Redirecting to {redirect.target}: {redirect.reason}[/yellow]")
        return
    except ValidationError as e:
        console.print(f"[red]Cannot approve: {e}[/red]")
        sys.exit(1)
    except RuntimeError as e:
        console.print(f"[red]Failed: {e}[/red]")
        sys.exit(1)

    console.print(f"[green]✓ Approved! Issue #{issue.id} moved to {updated.stage}[/green]")

    # Auto-notify agent to continue (if active)
    from agenttree.state import get_active_agent

    agent = get_active_agent(issue_id_normalized)
    if agent:
        config = load_config()
        tmux_manager = TmuxManager(config)
        if tmux_manager.is_issue_running(agent.tmux_session):
            message = "Your work was approved! Run `agenttree next` for instructions."
            tmux_manager.send_message_to_issue(agent.tmux_session, message, interrupt=False)
            console.print(f"[green]✓ Notified agent to continue[/green]")


@click.command("reject")
@click.argument("issue_id", type=str)
@click.option("--message", "-m", help="Feedback message to send to the agent")
def reject_issue(issue_id: str, message: str | None) -> None:
    """Reject an issue at a human review stage and move it back.

    Only works at human review stages (plan_review, implementation_review).
    Cannot be run from inside a container - humans only.

    Moves the issue back to its corresponding work stage:
    - plan_review → plan_revise
    - implementation_review → implement

    Example:
        agenttree reject 042
        agenttree reject 042 --message "Please fix the test failures"
    """
    from datetime import datetime, timezone
    import yaml as pyyaml

    # Block if in container
    if is_running_in_container():
        console.print("[red]Error: 'reject' cannot be run from inside a container[/red]")
        console.print("[dim]This command is for human reviewers only.[/dim]")
        sys.exit(1)

    # Normalize issue ID
    issue_id_normalized = normalize_issue_id(issue_id)
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    # Check if at a human review stage (using config for validation)
    config = load_config()
    if not config.is_human_review(issue.stage):
        human_review_stages = config.get_human_review_stages()
        console.print(f"[red]Issue is at '{issue.stage}', not a human review stage[/red]")
        console.print(f"[dim]Human review stages: {', '.join(human_review_stages)}[/dim]")
        sys.exit(1)

    # Map review stage to target stage (hierarchical dot-path format)
    REJECT_TARGET_STAGES = {
        "plan.review": "plan.revise",
        "implement.review": "implement.code",
        "implement.independent_review": "implement.code",
    }
    target_stage = REJECT_TARGET_STAGES.get(issue.stage)
    if not target_stage:
        console.print(f"[red]No target stage defined for rejecting from '{issue.stage}'[/red]")
        sys.exit(1)

    # Update issue.yaml directly (like rollback, skip hooks)
    # Note: target_stage is already a complete dot-path like "implement.code"
    issue_dir = get_issue_dir(issue_id_normalized)
    if not issue_dir:
        console.print(f"[red]Issue directory not found[/red]")
        sys.exit(1)

    yaml_path = issue_dir / "issue.yaml"
    if not yaml_path.exists():
        console.print(f"[red]Issue yaml not found at {yaml_path}[/red]")
        sys.exit(1)

    with open(yaml_path) as fh:
        data = pyyaml.safe_load(fh)

    # Update stage (hierarchical dot-path format, no separate substage field)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["stage"] = target_stage
    data["updated"] = now

    # Add reject history entry
    history_entry = {
        "stage": target_stage,
        "timestamp": now,
        "type": "reject",
    }
    if "history" not in data:
        data["history"] = []
    data["history"].append(history_entry)

    # NOTE: Unlike rollback, we preserve PR metadata since the PR just needs updates

    with open(yaml_path, "w") as fh:
        pyyaml.dump(data, fh, default_flow_style=False, sort_keys=False)

    console.print(f"[green]✓ Rejected! Issue #{issue.id} moved to {target_stage}[/green]")

    # Sync to agents repo
    from agenttree.agents_repo import sync_agents_repo
    from agenttree.issues import get_agenttree_path
    agents_path = get_agenttree_path()
    sync_agents_repo(agents_path, pull_only=False, commit_message=f"Reject issue {issue_id} to {target_stage}")

    # Notify agent with message
    from agenttree.state import get_active_agent

    agent = get_active_agent(issue_id_normalized)
    if agent:
        tmux_manager = TmuxManager(config)
        if tmux_manager.is_issue_running(agent.tmux_session):
            if message:
                notify_message = f"Review feedback: {message}. Run `agenttree next` to continue."
            else:
                notify_message = "Your work was rejected. Run `agenttree next` for instructions."
            tmux_manager.send_message_to_issue(agent.tmux_session, notify_message, interrupt=False)
            console.print("[green]✓ Notified agent with feedback[/green]")


@click.command("defer")
@click.argument("issue_id", type=str)
def defer_issue(issue_id: str) -> None:
    """Move an issue to backlog (defer for later).

    This removes the issue from active work. Any running agent should be stopped.

    Example:
        agenttree defer 042
    """
    # Block if in container
    if is_running_in_container():
        console.print(f"[red]Error: 'defer' cannot be run from inside a container[/red]")
        console.print(f"[dim]This command is for human reviewers only.[/dim]")
        sys.exit(1)

    # Normalize issue ID
    issue_id_normalized = normalize_issue_id(issue_id)
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    if issue.stage == "backlog":
        console.print(f"[yellow]Issue is already in backlog[/yellow]")
        return

    if issue.stage == "accepted":
        console.print(f"[yellow]Issue is already accepted, cannot defer[/yellow]")
        return

    # Move to backlog
    updated = update_issue_stage(issue_id_normalized, "backlog")
    if not updated:
        console.print(f"[red]Failed to update issue[/red]")
        sys.exit(1)

    # Delete session (agent should be stopped)
    delete_session(issue_id_normalized)

    console.print(f"[green]✓ Issue #{issue.id} moved to backlog[/green]")
    console.print(f"\n[dim]Stop the agent if running:[/dim]")
    console.print(f"  agenttree kill {issue.id}")


@click.command("shutdown")
@click.argument("issue_id")
@click.argument("stage", type=click.Choice(["backlog", "not_doing", "accepted"]))
@click.option(
    "--changes", "-c",
    type=click.Choice(["stash", "commit", "discard", "error"]),
    default=None,
    help="How to handle uncommitted changes (default: stage-specific)"
)
@click.option(
    "--keep-worktree/--remove-worktree",
    default=None,
    help="Override worktree handling (default: keep for backlog, remove for others)"
)
@click.option(
    "--keep-branch/--delete-branch",
    default=None,
    help="Override branch handling (default: keep for backlog/accepted, delete for not_doing)"
)
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Skip confirmation prompts"
)
@click.option(
    "--message", "-m",
    default="WIP: shutdown",
    help="Commit message when using --changes commit"
)
def shutdown_issue(
    issue_id: str,
    stage: str,
    changes: str | None,
    keep_worktree: bool | None,
    keep_branch: bool | None,
    force: bool,
    message: str,
) -> None:
    """Shutdown an issue's agent and clean up resources.

    Stops the agent, handles uncommitted changes, and optionally removes
    the worktree and branch. The STAGE determines the default behavior:

    \b
    backlog:   Pause work. Keep worktree/branch, stash changes.
    not_doing: Abandon work. Remove worktree, delete branch, discard changes.
    accepted:  Work complete. Remove worktree, keep branch, error on uncommitted.

    Examples:
        agenttree shutdown 042 backlog           # Pause for later
        agenttree shutdown 042 not_doing         # Abandon issue
        agenttree shutdown 042 not_doing -f      # Abandon without prompts
        agenttree shutdown 042 backlog -c commit # Commit changes instead of stash
    """
    from agenttree.worktree import remove_worktree

    # Block if in container
    if is_running_in_container():
        console.print("[red]Error: 'shutdown' cannot be run from inside a container[/red]")
        sys.exit(1)

    # Normalize issue ID
    issue_id_normalized = normalize_issue_id(issue_id)
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    # Check if already in target stage - return early
    if issue.stage == stage:
        console.print(f"[yellow]Issue #{issue.id} is already in {stage}[/yellow]")
        return

    # Set defaults based on stage
    if changes is None:
        if stage == "backlog":
            changes = "stash"
        elif stage == "not_doing":
            changes = "discard"
        else:  # accepted
            changes = "error"

    if keep_worktree is None:
        keep_worktree = stage == "backlog"

    if keep_branch is None:
        keep_branch = stage != "not_doing"

    config = load_config()
    repo_path = Path.cwd()

    # Stop ALL agents for this issue FIRST to avoid race conditions with worktree operations
    from agenttree.api import stop_all_agents_for_issue
    count = stop_all_agents_for_issue(issue_id_normalized, quiet=True)
    if count > 0:
        console.print(f"[dim]Stopped {count} agent(s) for issue #{issue.id}[/dim]")

    # Get worktree path
    worktree_path = None
    if issue.worktree_dir:
        worktree_path = repo_path / issue.worktree_dir
        if not worktree_path.exists():
            worktree_path = None

    # Handle uncommitted changes in worktree
    if worktree_path and worktree_path.exists():
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        has_changes = bool(status_result.stdout.strip())

        if has_changes:
            if changes == "error":
                console.print("[red]Error: Uncommitted changes in worktree[/red]")
                console.print("[dim]Use --changes stash|commit|discard to handle them[/dim]")
                sys.exit(1)
            elif changes == "discard":
                if not force:
                    console.print("[yellow]Warning: Uncommitted changes will be discarded:[/yellow]")
                    console.print(status_result.stdout)
                    if not click.confirm("Discard changes?"):
                        console.print("[dim]Aborted[/dim]")
                        sys.exit(0)
                try:
                    subprocess.run(["git", "checkout", "."], cwd=worktree_path, check=True, capture_output=True)
                    subprocess.run(["git", "clean", "-fd"], cwd=worktree_path, check=True, capture_output=True)
                    console.print("[dim]Discarded uncommitted changes[/dim]")
                except subprocess.CalledProcessError as e:
                    console.print(f"[red]Error discarding changes: {e}[/red]")
                    sys.exit(1)
            elif changes == "stash":
                try:
                    subprocess.run(["git", "stash", "push", "-m", f"shutdown: {issue.id}"], cwd=worktree_path, check=True, capture_output=True)
                    console.print("[dim]Stashed uncommitted changes[/dim]")
                except subprocess.CalledProcessError as e:
                    console.print(f"[red]Error stashing changes: {e}[/red]")
                    sys.exit(1)
            elif changes == "commit":
                try:
                    subprocess.run(["git", "add", "-A"], cwd=worktree_path, check=True, capture_output=True)
                    subprocess.run(["git", "commit", "-m", message], cwd=worktree_path, check=True, capture_output=True)
                    console.print(f"[dim]Committed changes: {message}[/dim]")
                except subprocess.CalledProcessError as e:
                    console.print(f"[red]Error committing changes: {e}[/red]")
                    sys.exit(1)

        # Check for unpushed commits - handle case where branch has no upstream
        has_unpushed = False
        unpushed_output = ""

        # First try checking against upstream
        unpushed_result = subprocess.run(
            ["git", "log", "--oneline", "@{u}..HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )

        if unpushed_result.returncode == 0:
            # Upstream exists, check if there are unpushed commits
            has_unpushed = bool(unpushed_result.stdout.strip())
            unpushed_output = unpushed_result.stdout
        else:
            # No upstream - check against origin/main as fallback
            # This catches local-only branches that were never pushed
            fallback_result = subprocess.run(
                ["git", "log", "--oneline", "origin/main..HEAD"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
            )
            if fallback_result.returncode == 0 and fallback_result.stdout.strip():
                has_unpushed = True
                unpushed_output = fallback_result.stdout
                console.print("[yellow]Warning: Branch has no upstream tracking branch[/yellow]")

        if has_unpushed and not keep_branch:
            if not force:
                console.print("[yellow]Warning: Unpushed commits will be lost:[/yellow]")
                console.print(unpushed_output)
                if not click.confirm("Continue anyway?"):
                    console.print("[dim]Aborted[/dim]")
                    sys.exit(0)

    # Remove worktree if requested
    if not keep_worktree and worktree_path and worktree_path.exists():
        remove_worktree(repo_path, worktree_path)
        console.print(f"[dim]Removed worktree: {worktree_path}[/dim]")
        # Clear worktree_dir in issue metadata
        update_issue_metadata(issue_id_normalized, worktree_dir="")

    # Delete branch if requested
    if not keep_branch and issue.branch:
        # Delete local branch (may fail if checked out elsewhere, that's ok)
        subprocess.run(
            ["git", "branch", "-D", issue.branch],
            cwd=repo_path,
            capture_output=True,
        )
        console.print(f"[dim]Deleted local branch: {issue.branch}[/dim]")

    # Update issue stage
    if issue.stage != stage:
        updated = update_issue_stage(issue_id_normalized, stage)
        if not updated:
            console.print(f"[red]Failed to update issue stage[/red]")
            sys.exit(1)

    # Delete session file
    delete_session(issue_id_normalized)

    console.print(f"[green]✓ Issue #{issue.id} shutdown to {stage}[/green]")


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
    from datetime import datetime, timezone
    import shutil
    import yaml as pyyaml

    # Block if in container
    if is_running_in_container():
        console.print("[red]Error: 'rollback' cannot be run from inside a container[/red]")
        console.print("[dim]This command is for human reviewers only.[/dim]")
        sys.exit(1)

    # Normalize issue ID
    issue_id_normalized = normalize_issue_id(issue_id)
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    # Load config and validate stage (stage_name can be a dot path)
    config = load_config()
    flow_stages = config.get_flow_stage_names(issue.flow)

    if stage_name not in flow_stages:
        console.print(f"[red]Invalid stage: '{stage_name}'[/red]")
        console.print(f"[dim]Valid stages: {', '.join(flow_stages)}[/dim]")
        sys.exit(1)

    # Check if target stage is before or same as current stage
    try:
        current_idx = flow_stages.index(issue.stage)
        target_idx = flow_stages.index(stage_name)
    except ValueError:
        console.print(f"[red]Issue is at unknown stage: {issue.stage}[/red]")
        sys.exit(1)

    if target_idx >= current_idx:
        console.print(f"[red]Cannot rollback: target stage '{stage_name}' is not before current stage '{issue.stage}'[/red]")
        console.print("[dim]Rollback is for going backwards in the workflow.[/dim]")
        sys.exit(1)

    # Cannot rollback to redirect_only stages (they're not in normal progression)
    target_group, _ = config.parse_stage(stage_name)
    target_stage_config = config.get_stage(target_group)
    if target_stage_config and target_stage_config.redirect_only:
        console.print(f"[red]Cannot rollback to redirect-only stage '{stage_name}'[/red]")
        sys.exit(1)

    # Collect output files from stages after target that are being rolled back
    stages_to_archive = flow_stages[target_idx + 1 : current_idx + 1]

    files_to_archive: list[str] = []
    for dot_path in stages_to_archive:
        output = config.output_for(dot_path)
        if output:
            files_to_archive.append(output)

    # Determine worktree reset behavior
    # Auto-reset if rolling back to before any implement stage
    implement_paths = [dp for dp in flow_stages if dp.startswith("implement")]
    if implement_paths:
        first_implement_idx = flow_stages.index(implement_paths[0])
        auto_reset = target_idx < first_implement_idx
    else:
        auto_reset = False

    should_reset = reset_worktree or (auto_reset and not keep_changes)

    # Check for active agents (all hosts)
    from agenttree.state import get_active_agents_for_issue
    active_agents = get_active_agents_for_issue(issue_id_normalized)
    active_agent = active_agents[0] if active_agents else None  # For worktree reference

    # Show confirmation
    issue_dir = get_issue_dir(issue_id_normalized)

    console.print(f"\n[bold]Rollback Issue #{issue.id}: {issue.title}[/bold]")
    console.print(f"\n  Current stage: [yellow]{issue.stage}[/yellow]")
    console.print(f"  Target stage:  [green]{stage_name}[/green]")

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

            # Update stage and substage (first substage of target, or clear)
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            data["stage"] = stage_name
            data["updated"] = now

            # Add rollback history entry
            history_entry = {
                "stage": stage_name,
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

            console.print(f"[green]✓ Issue stage set to {stage_name}[/green]")

    # 3. Clear agent session
    delete_session(issue_id_normalized)
    console.print("[green]✓ Cleared agent session[/green]")

    # 4. Unregister all active agents (if any)
    if active_agents:
        from agenttree.state import unregister_all_agents_for_issue
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

    console.print(f"\n[green]✓ Issue #{issue.id} rolled back to {stage_name}[/green]")
    if active_agent:
        console.print(f"\n[dim]Restart the agent when ready:[/dim]")
        console.print(f"  agenttree start {issue.id}")

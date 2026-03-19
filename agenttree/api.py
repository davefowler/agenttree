"""High-level API for AgentTree operations.

This module provides programmatic access to core AgentTree functionality.
Agents run as `claude -p` subprocesses in worktree directories - no containers.

Example:
    from agenttree.api import start_issue, send_message

    # Start an agent for an issue
    agent = start_issue("042", quiet=True)

    # Send a message to the messenger
    result = send_message("0", "What's the status?", quiet=True)
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from agenttree.config import DEFAULT_ROLE

if TYPE_CHECKING:
    from agenttree.issues import Issue
    from agenttree.state import ActiveAgent

log = logging.getLogger("agenttree.api")

__all__ = [
    "start_issue",
    "send_message",
    "start_messenger",
    "start_role",
    "stop_agent",
    "stop_all_agents_for_issue",
    "transition_issue",
    "reset_issue",
    "reimplement_issue",
    "IssueNotFoundError",
    "AgentStartError",
    "AgentAlreadyRunningError",
    "PreflightError",
    "MessengerNotRunningError",
]


# Custom exceptions for API errors


class IssueNotFoundError(Exception):
    """Raised when the specified issue does not exist."""

    def __init__(self, issue_id: int | str):
        self.issue_id = issue_id
        super().__init__(f"Issue #{issue_id} not found")


class AgentStartError(Exception):
    """Raised when an agent fails to start."""

    def __init__(self, issue_id: int | str, reason: str):
        self.issue_id = issue_id
        self.reason = reason
        super().__init__(f"Failed to start agent for issue #{issue_id}: {reason}")


class AgentAlreadyRunningError(Exception):
    """Raised when trying to start an agent that's already running."""

    def __init__(self, issue_id: int | str, host: str = DEFAULT_ROLE):
        self.issue_id = issue_id
        self.host = host
        super().__init__(
            f"Agent already running for issue #{issue_id} (host: {host}). "
            f"Use force=True to restart."
        )


class PreflightError(Exception):
    """Raised when preflight checks fail."""

    def __init__(self, failures: list[str]):
        self.failures = failures
        super().__init__(f"Preflight checks failed: {', '.join(failures)}")


class MessengerNotRunningError(Exception):
    """Raised when messenger is not running but required."""

    def __init__(self) -> None:
        super().__init__("Messenger not running. Start with: agenttree start messenger")


# Keep backward compat aliases
ContainerUnavailableError = AgentStartError
ControllerNotRunningError = MessengerNotRunningError
HOST_TMUX_ROLES: set[str] = {"messenger", "manager", "architect"}


def start_issue(
    issue_id: int | str,
    *,
    host: str = DEFAULT_ROLE,
    skip_preflight: bool = False,
    force: bool = False,
    tool: str | None = None,
    quiet: bool = False,
    force_api_key: bool = False,
) -> "ActiveAgent":
    """Start an agent for an issue.

    Creates a worktree and starts a `claude -p` subprocess.

    Args:
        issue_id: Issue ID (int or string like "042")
        host: Agent host type (default: "developer")
        skip_preflight: Skip preflight checks if True
        force: Force restart if agent already running
        tool: AI tool to use (default: from config)
        quiet: Suppress console output if True
        force_api_key: Force API key mode (unused in new model)

    Returns:
        ActiveAgent with agent details

    Raises:
        IssueNotFoundError: If issue doesn't exist
        AgentAlreadyRunningError: If agent already running (without force)
        PreflightError: If preflight checks fail
        AgentStartError: If agent fails to start
    """
    from agenttree.config import load_config
    from agenttree.ids import parse_issue_id
    from agenttree.issues import get_issue, update_issue_stage, update_issue_metadata
    from agenttree.preflight import run_preflight
    from agenttree.state import get_active_agent, create_agent_for_issue, get_issue_names
    from agenttree.issues import create_session
    from agenttree.worktree import (
        create_worktree,
        sync_local_agenttree_config,
        update_worktree_with_main,
    )
    from agenttree.process import start_agent, stop_agent_process, build_agent_prompt

    # Normalize issue_id to int
    if isinstance(issue_id, str):
        issue_id = parse_issue_id(issue_id)

    if not quiet:
        from rich.console import Console
        console = Console()

    repo_path = Path.cwd()
    config = load_config(repo_path)

    # Run preflight checks unless skipped
    if not skip_preflight:
        if not quiet:
            console.print("[dim]Running preflight checks...[/dim]")
        results = run_preflight()
        failed = [r for r in results if not r.passed]
        if failed:
            raise PreflightError([f"{r.name}: {r.message}" for r in failed])
        if not quiet:
            console.print("[green]✓ Preflight checks passed[/green]\n")

    # Load issue
    issue = get_issue(issue_id)
    if not issue:
        raise IssueNotFoundError(issue_id)

    # If issue is in a resumable parking lot, move to first real stage
    if config.is_resumable_stage(issue.stage):
        first_stage = config.get_first_stage(issue.flow)
        if not quiet:
            console.print(f"[cyan]Moving issue from {issue.stage} to {first_stage}...[/cyan]")
        update_issue_stage(issue.id, first_stage)
        issue.stage = first_stage

    # Check if agent already running
    existing_agent = get_active_agent(issue.id, host)
    if existing_agent and not force:
        raise AgentAlreadyRunningError(issue.id, host)

    # If force, stop existing agent
    if force:
        stop_agent_process(issue.id, host)

    # Get names for this issue
    names = get_issue_names(issue.id, config.project, host)

    # Create worktree for issue
    worktree_path = config.get_issue_worktree_path(issue.id)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    has_merge_conflicts = False
    is_restart = False
    if worktree_path.exists():
        is_restart = True
        if not quiet:
            console.print("[cyan]Restarting: Rebasing worktree onto latest main...[/cyan]")
        update_success = update_worktree_with_main(worktree_path)
        if update_success:
            if not quiet:
                console.print("[green]✓ Worktree rebased successfully[/green]")
        else:
            has_merge_conflicts = True
            if not quiet:
                console.print("[yellow]⚠ Merge conflicts detected - agent will need to resolve[/yellow]")
    else:
        branch_exists = subprocess.run(
            ["git", "rev-parse", "--verify", names["branch"]],
            cwd=repo_path,
            capture_output=True,
        ).returncode == 0

        if branch_exists:
            is_restart = True
            if not quiet:
                console.print(f"[dim]Restarting from existing branch: {names['branch']}[/dim]")
            create_worktree(repo_path, worktree_path, names["branch"])
            if not quiet:
                console.print("[cyan]Rebasing onto latest main...[/cyan]")
            update_success = update_worktree_with_main(worktree_path)
            if update_success:
                if not quiet:
                    console.print("[green]✓ Worktree rebased successfully[/green]")
            else:
                has_merge_conflicts = True
                if not quiet:
                    console.print("[yellow]⚠ Merge conflicts detected[/yellow]")
        else:
            if not quiet:
                console.print(f"[dim]Creating worktree: {worktree_path.name}[/dim]")
            create_worktree(repo_path, worktree_path, names["branch"])

    sync_local_agenttree_config(repo_path, worktree_path)

    # Get deterministic port
    port = config.get_port_for_issue(issue.id)
    if not quiet:
        console.print(f"[dim]Using port: {port} (derived from issue #{issue.id})[/dim]")

    # Save branch and worktree info to issue metadata
    update_issue_metadata(issue.id, branch=names["branch"], worktree_dir=str(worktree_path))

    role_label = f" ({host})" if host != DEFAULT_ROLE else ""
    if not quiet:
        console.print(f"[green]✓ Starting agent{role_label} for issue #{issue.id}: {issue.title}[/green]")

    # Create session for restart detection
    create_session(issue.id)

    # Build prompt and start subprocess
    tool_name = tool or config.default_tool
    model_name = config.model_for(issue.stage)

    if not quiet:
        console.print(f"[dim]Model: {model_name}[/dim]")

    prompt = build_agent_prompt(
        issue.id,
        has_merge_conflicts=has_merge_conflicts,
        is_restart=is_restart,
    )

    agent_proc = start_agent(
        issue_id=issue.id,
        role=host,
        worktree_path=worktree_path,
        branch=names["branch"],
        port=port,
        prompt=prompt,
        model=model_name,
        tool=tool_name,
    )

    if not quiet:
        console.print(f"[green]✓ Started {tool_name} -p (PID {agent_proc.pid})[/green]")
        console.print(f"\n[bold]Agent{role_label} ready for issue #{issue.id}[/bold]")

    # Start serve session if serve command is configured
    serve_command = config.commands.get("serve")
    if serve_command:
        from agenttree.ids import serve_session_name
        from agenttree.tmux import session_exists, kill_session, create_session as tmux_create_session

        serve_session = serve_session_name(config.project, issue.id)
        try:
            if session_exists(serve_session):
                kill_session(serve_session)
            serve_cmd = f"PORT={port} {serve_command}"
            tmux_create_session(serve_session, worktree_path, serve_cmd)
        except subprocess.CalledProcessError as e:
            log.warning("Could not start serve session: %s", e)

    # Return ActiveAgent
    from agenttree.state import ActiveAgent
    return ActiveAgent(
        issue_id=issue.id,
        role=host,
        pid=agent_proc.pid,
        worktree=worktree_path,
        branch=names["branch"],
        port=port,
        log_file=agent_proc.log_file,
        started=agent_proc.started,
    )


def start_messenger(
    *,
    tool: str | None = None,
    force: bool = False,
    quiet: bool = False,
) -> None:
    """Start the messenger agent (interactive claude in tmux). Replaces start_controller."""
    start_role("messenger", tool=tool, force=force, quiet=quiet)


# Backward compat
start_controller = start_messenger


def start_role(
    role_name: str,
    *,
    tool: str | None = None,
    force: bool = False,
    quiet: bool = False,
) -> None:
    """Start a host-level role agent (e.g., messenger, architect).

    These run in tmux as interactive claude sessions (not claude -p).

    Args:
        role_name: Role name (e.g., "messenger", "architect")
        tool: AI tool override
        force: Force restart if already running
        quiet: Suppress console output if True
    """
    from agenttree.config import load_config
    from agenttree.tmux import TmuxManager, session_exists, kill_session

    if not quiet:
        from rich.console import Console
        console = Console()

    repo_path = Path.cwd()
    config = load_config(repo_path)

    # Look up role config
    role_config = config.roles.get(role_name)
    if not role_config:
        raise ValueError(f"Unknown role: '{role_name}'. Available: {', '.join(config.roles.keys())}")

    tmux_manager = TmuxManager(config)
    session_name = config.get_role_tmux_session(role_name)

    # Resolve tool and model
    tool_name = tool or role_config.tool or config.default_tool
    model = role_config.model or config.default_model

    # Check if already running
    if session_exists(session_name):
        if not force:
            raise AgentAlreadyRunningError(role_name, role_name)
        if not quiet:
            console.print(f"[dim]Killing existing {role_name} session...[/dim]")
        kill_session(session_name)

    if not quiet:
        console.print(f"[green]Starting {role_name}...[/green]")
        console.print(f"[dim]Tool: {tool_name}, Model: {model}[/dim]")

    tmux_manager.start_host_role(
        session_name=session_name,
        repo_path=repo_path,
        tool_name=tool_name,
        model=model,
        skill_file=role_config.skill_file,
    )

    if not quiet:
        console.print(f"[green]✓ {role_name.capitalize()} started[/green]")
        console.print(f"[dim]Attach with: agenttree attach {role_name}[/dim]")


def send_message(
    issue_id: int | str,
    message: str,
    *,
    host: str = DEFAULT_ROLE,
    auto_start: bool = True,
    interrupt: bool = False,
    quiet: bool = False,
) -> str:
    """Send a message to an agent.

    For the messenger (issue 0): sends to tmux session.
    For sub-agents: cannot send messages mid-flight. If the agent is dead,
    restarts it with the message as additional context.

    Args:
        issue_id: Issue ID, or 0 for messenger
        message: Message to send
        host: Agent host type
        auto_start: Start agent if not running
        interrupt: Send Ctrl+C first (messenger only)
        quiet: Suppress output

    Returns:
        Status: "sent", "restarted", "no_agent", "error"
    """
    from agenttree.config import load_config
    from agenttree.ids import parse_issue_id
    from agenttree.issues import get_issue
    from agenttree.state import get_active_agent
    from agenttree.tmux import session_exists, send_message as tmux_send_message

    if not quiet:
        from rich.console import Console
        console = Console()

    config = load_config()
    parsed_id = parse_issue_id(issue_id) if isinstance(issue_id, str) else issue_id

    # Messenger (issue 0)
    if parsed_id == 0:
        session_name = config.get_role_tmux_session("messenger")
        # Fall back to legacy manager session name
        if not session_exists(session_name):
            session_name = config.get_manager_tmux_session()
        if not session_exists(session_name):
            raise MessengerNotRunningError()
        result = tmux_send_message(session_name, message, interrupt=interrupt)
        if result != "sent":
            if not quiet:
                console.print(f"[red]Error: Failed to send to messenger ({result})[/red]")
            return "error"
        if not quiet:
            console.print("[green]✓ Sent message to messenger[/green]")
        return "sent"

    # Sub-agent: check if running
    issue = get_issue(parsed_id)
    if not issue:
        raise IssueNotFoundError(parsed_id)

    agent = get_active_agent(issue.id, host)
    if agent and agent.pid > 0:
        # Agent is running as a subprocess - can't send messages mid-flight
        if not quiet:
            console.print(
                f"[yellow]Agent for issue #{issue.id} is running (PID {agent.pid}). "
                f"Sub-agents don't accept messages mid-flight.[/yellow]"
            )
        return "sent"  # Best we can do

    # Agent not running
    if not auto_start:
        return "no_agent"

    # Restart the agent (the message becomes part of the restart context)
    role_label = f" ({host})" if host != DEFAULT_ROLE else ""
    if not quiet:
        console.print(f"[dim]Agent{role_label} not running, starting...[/dim]")

    try:
        start_issue(issue.id, host=host, skip_preflight=True, quiet=quiet)
        if not quiet:
            console.print(f"[green]✓ Started agent{role_label}[/green]")
        return "restarted"
    except (AgentStartError, PreflightError) as e:
        if not quiet:
            console.print(f"[red]Error: Could not start agent: {e}[/red]")
        return "error"


# =============================================================================
# Stage Transitions
# =============================================================================


def transition_issue(
    issue_id: int | str,
    next_stage: str,
    *,
    skip_pr_approval: bool = False,
    trigger: str = "cli",
) -> "Issue":
    """Transition an issue from its current stage to the next.

    This is THE function for stage transitions.
    """
    from agenttree.hooks import execute_exit_hooks, execute_enter_hooks, StageRedirect
    from agenttree.ids import parse_issue_id
    from agenttree.issues import get_issue, update_issue_stage

    if isinstance(issue_id, str):
        issue_id = parse_issue_id(issue_id)

    issue = get_issue(issue_id)
    if not issue:
        raise RuntimeError(f"Issue #{issue_id} not found")

    from_stage = issue.stage

    # 1. Execute exit hooks (validation - can block)
    try:
        execute_exit_hooks(issue, from_stage, skip_pr_approval=skip_pr_approval)
    except StageRedirect as redirect:
        next_stage = redirect.target

    # 2. Update issue stage
    updated = update_issue_stage(issue_id, next_stage)
    if not updated:
        raise RuntimeError(f"Failed to update issue #{issue_id} to {next_stage}")

    # 3. Execute enter hooks
    try:
        execute_enter_hooks(updated, next_stage)
    except StageRedirect as redirect:
        log.info("Enter hook redirected issue #%s to %s: %s",
                 issue_id, redirect.target, redirect.reason)
        redirected = update_issue_stage(issue_id, redirect.target)
        if redirected:
            _ensure_stage_agent(issue_id, redirect.target)
            return redirected
        raise RuntimeError(f"Failed to redirect issue #{issue_id} to {redirect.target}")
    except Exception as e:
        log.warning("Enter hooks failed for issue #%s (%s trigger): %s", issue_id, trigger, e)
        rolled_back = update_issue_stage(issue_id, from_stage)
        if not rolled_back:
            raise RuntimeError(
                f"Enter hooks failed for issue #{issue_id} and rollback to {from_stage} also failed"
            ) from e
        _ensure_stage_agent(issue_id, from_stage)
        raise RuntimeError(
            f"Enter hooks failed for issue #{issue_id} transitioning to {next_stage}: {e}"
        ) from e

    # 4. Ensure the right agent is running for the new stage
    _ensure_stage_agent(issue_id, next_stage)

    return updated


def _notify_agent(issue_id: int, message: str, *, interrupt: bool = False) -> None:
    """Best-effort notify an active agent. Never raises.

    For sub-agents (claude -p), this is a no-op since they can't receive messages.
    For messenger, sends via tmux.
    """
    try:
        if issue_id == 0:
            from agenttree.tmux import send_message as tmux_send, session_exists
            from agenttree.config import load_config
            config = load_config()
            session_name = config.get_role_tmux_session("messenger")
            if not session_exists(session_name):
                session_name = config.get_manager_tmux_session()
            if session_exists(session_name):
                tmux_send(session_name, message, interrupt=interrupt)
    except Exception as e:
        log.warning("Failed to notify agent for issue #%s: %s", issue_id, e)


def _ensure_stage_agent(issue_id: int, stage: str) -> None:
    """Best-effort ensure an agent is running for the given stage.

    Uses send_message() which auto-starts the agent if not running.
    Skips parking lots, human review stages, and manager stages.
    """
    try:
        from agenttree.config import load_config
        config = load_config()

        if config.is_parking_lot(stage):
            return
        if config.is_human_review(stage):
            return

        role = config.role_for(stage)
        if role in ("manager", "messenger"):
            return

        send_message(
            issue_id,
            f"Stage is now {stage}. Run `agenttree next` for your instructions.",
            host=role,
            quiet=True,
        )
        log.info("Ensured agent for issue #%s at %s (role=%s)", issue_id, stage, role)
    except Exception as e:
        log.warning("Could not ensure agent for issue #%s at %s: %s", issue_id, stage, e)


# =============================================================================
# Stop/Cleanup Functions
# =============================================================================


def stop_agent(issue_id: int, role: str = DEFAULT_ROLE, quiet: bool = False) -> bool:
    """Stop an active agent - kills process and cleans up.

    Args:
        issue_id: Issue ID to stop
        role: Agent role
        quiet: Suppress output

    Returns:
        True if something was stopped
    """
    from agenttree.config import load_config
    from agenttree.ids import serve_session_name as get_serve_session_name
    from agenttree.process import stop_agent_process
    from agenttree.tmux import kill_session, session_exists

    config = load_config()
    stopped_something = False

    if not quiet:
        from rich.console import Console
        console = Console()

    # 1. Kill serve session if it exists
    try:
        serve_session = get_serve_session_name(config.project, issue_id)
        if session_exists(serve_session):
            kill_session(serve_session)
            stopped_something = True
            if not quiet:
                console.print(f"[dim]  Stopped serve session: {serve_session}[/dim]")
    except subprocess.CalledProcessError as e:
        log.warning("Could not stop serve session for issue %s: %s", issue_id, e)

    # 2. Stop the agent process
    if stop_agent_process(issue_id, role):
        stopped_something = True
        if not quiet:
            console.print(f"[dim]  Stopped agent process for issue #{issue_id} ({role})[/dim]")

    if stopped_something and not quiet:
        console.print(f"[green]✓ Agent stopped for issue #{issue_id}[/green]")

    return stopped_something


def stop_all_agents_for_issue(issue_id: int, quiet: bool = False) -> int:
    """Stop all agents for an issue.

    Returns:
        Number of agents stopped
    """
    from agenttree.process import stop_all_for_issue
    return stop_all_for_issue(issue_id)


def cleanup_orphaned_containers(quiet: bool = False) -> int:
    """No-op - containers no longer used. Kept for backward compat."""
    return 0


def cleanup_all_agenttree_containers(quiet: bool = False) -> int:
    """No-op - containers no longer used. Kept for backward compat."""
    return 0


def cleanup_all_with_retry(max_passes: int = 3, delay_s: float = 2.0, quiet: bool = False) -> None:
    """No-op - containers no longer used. Kept for backward compat."""
    pass


# =============================================================================
# Reset Functions
# =============================================================================


def _clean_issue_files(issue_id: int, keep_files: set[str] | None = None) -> list[str]:
    """Remove generated files from an issue directory, keeping issue.yaml."""
    from agenttree.issues import get_issue_dir

    issue_dir = get_issue_dir(issue_id)
    if not issue_dir or not issue_dir.exists():
        return []

    keep = {"issue.yaml"}
    if keep_files:
        keep.update(keep_files)

    removed: list[str] = []
    for f in issue_dir.iterdir():
        if f.name in keep or f.name.startswith("."):
            continue
        if f.is_dir():
            import shutil
            shutil.rmtree(f)
            removed.append(f"{f.name}/")
        else:
            f.unlink()
            removed.append(f.name)

    return removed


def _delete_issue_branch(issue_id: int, branch: str | None, quiet: bool = False) -> None:
    """Delete the git branch for an issue (local only)."""
    if not branch:
        return

    repo_path = Path.cwd()
    result = subprocess.run(
        ["git", "branch", "-D", branch],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and not quiet:
        log.info("Deleted branch %s for issue #%s", branch, issue_id)


def _remove_issue_worktree(issue_id: int, worktree_dir: str | None, quiet: bool = False) -> None:
    """Remove worktree for an issue."""
    from agenttree.config import load_config
    from agenttree.worktree import remove_worktree

    config = load_config()
    repo_path = Path.cwd()

    paths_to_try = []
    if worktree_dir:
        paths_to_try.append(Path(worktree_dir))
    paths_to_try.append(config.get_issue_worktree_path(issue_id))

    for wt_path in paths_to_try:
        if wt_path.exists():
            remove_worktree(repo_path, wt_path)
            if not quiet:
                log.info("Removed worktree %s for issue #%s", wt_path, issue_id)
            return


def reset_issue(issue_id: int | str, *, quiet: bool = False) -> None:
    """Fully reset an issue as if it was never started."""
    from agenttree.ids import parse_issue_id
    from agenttree.issues import get_issue, HistoryEntry
    from datetime import datetime, timezone

    if isinstance(issue_id, str):
        issue_id = parse_issue_id(issue_id)

    issue = get_issue(issue_id)
    if not issue:
        raise IssueNotFoundError(issue_id)

    if not quiet:
        from rich.console import Console
        console = Console()
        console.print(f"[cyan]Resetting issue #{issue_id}: {issue.title}[/cyan]")

    # 1. Stop all agents
    stop_all_agents_for_issue(issue_id, quiet=quiet)

    # 2. Remove worktree
    _remove_issue_worktree(issue_id, issue.worktree_dir, quiet=quiet)

    # 3. Delete branch
    _delete_issue_branch(issue_id, issue.branch, quiet=quiet)

    # 4. Clean all generated files
    removed = _clean_issue_files(issue_id)
    if removed and not quiet:
        console.print(f"[dim]Removed files: {', '.join(removed)}[/dim]")

    # 5. Reset issue.yaml
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue.stage = "backlog"
    issue.branch = None
    issue.worktree_dir = None
    issue.pr_number = None
    issue.pr_url = None
    issue.processing = None
    issue.agent_ensured = None
    issue.ci_escalated = False
    issue.ci_notified = None
    issue.manager_hooks_executed = None
    issue.history = [HistoryEntry(stage="backlog", timestamp=now, type="reset")]
    issue.updated = now
    issue.save()

    # 6. Delete session file
    from agenttree.issues import delete_session
    delete_session(issue_id)

    if not quiet:
        console.print(f"[green]✓ Issue #{issue_id} fully reset to backlog[/green]")


def reimplement_issue(issue_id: int | str, *, quiet: bool = False) -> None:
    """Reset an issue to the start of implementation."""
    from agenttree.ids import parse_issue_id
    from agenttree.issues import get_issue, HistoryEntry
    from datetime import datetime, timezone

    if isinstance(issue_id, str):
        issue_id = parse_issue_id(issue_id)

    issue = get_issue(issue_id)
    if not issue:
        raise IssueNotFoundError(issue_id)

    if not quiet:
        from rich.console import Console
        console = Console()
        console.print(f"[cyan]Re-implementing issue #{issue_id}: {issue.title}[/cyan]")

    # 1. Stop all agents
    stop_all_agents_for_issue(issue_id, quiet=quiet)

    # 2. Remove worktree
    _remove_issue_worktree(issue_id, issue.worktree_dir, quiet=quiet)

    # 3. Delete branch
    _delete_issue_branch(issue_id, issue.branch, quiet=quiet)

    # 4. Clean implementation files, keep pre-implement files
    pre_implement_files = {"problem.md", "research.md", "spec.md", "spec_review.md"}
    removed = _clean_issue_files(issue_id, keep_files=pre_implement_files)
    if removed and not quiet:
        console.print(f"[dim]Removed files: {', '.join(removed)}[/dim]")

    # 5. Reset issue.yaml
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    kept_history = [h for h in issue.history if not h.stage.startswith("implement")]
    kept_history.append(HistoryEntry(stage="implement.setup", timestamp=now, type="reimplement"))

    issue.stage = "implement.setup"
    issue.branch = None
    issue.worktree_dir = None
    issue.pr_number = None
    issue.pr_url = None
    issue.processing = None
    issue.agent_ensured = None
    issue.ci_escalated = False
    issue.ci_notified = None
    issue.manager_hooks_executed = None
    issue.history = kept_history
    issue.updated = now
    issue.save()

    # 6. Delete session file
    from agenttree.issues import delete_session
    delete_session(issue_id)

    if not quiet:
        console.print(f"[green]✓ Issue #{issue_id} reset to implement.setup[/green]")

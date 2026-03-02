"""High-level API for AgentTree operations.

This module provides programmatic access to core AgentTree functionality
that was previously only available through CLI commands. Internal code
should import these functions directly instead of shelling out via subprocess.

Example:
    from agenttree.api import start_agent, send_message

    # Start an agent for an issue
    agent = start_agent("042", quiet=True)

    # Send a message to an agent
    result = send_message("042", "Please run the tests", quiet=True)
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from agenttree.ids import serve_session_name as get_serve_session_name

if TYPE_CHECKING:
    from agenttree.issues import Issue
    from agenttree.state import ActiveAgent

log = logging.getLogger("agenttree.api")

__all__ = [
    "start_agent",
    "send_message",
    "start_controller",
    "stop_agent",
    "stop_all_agents_for_issue",
    "transition_issue",
    "cleanup_orphaned_containers",
    "cleanup_all_agenttree_containers",
    "cleanup_all_with_retry",
    "IssueNotFoundError",
    "AgentStartError",
    "AgentAlreadyRunningError",
    "PreflightError",
    "ContainerUnavailableError",
    "ControllerNotRunningError",
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

    def __init__(self, issue_id: int | str, host: str = "developer"):
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


class ContainerUnavailableError(Exception):
    """Raised when no container runtime is available."""

    def __init__(self, recommendation: str):
        self.recommendation = recommendation
        super().__init__(f"No container runtime available. {recommendation}")


class ControllerNotRunningError(Exception):
    """Raised when controller is not running but required."""

    def __init__(self) -> None:
        super().__init__("Controller not running. Start with: agenttree start 0")


def start_agent(
    issue_id: int | str,
    *,
    host: str = "developer",
    skip_preflight: bool = False,
    force: bool = False,
    tool: str | None = None,
    quiet: bool = False,
) -> "ActiveAgent":
    """Start an agent for an issue.

    Creates a worktree, container, and tmux session for the agent.

    Args:
        issue_id: Issue ID (int or string like "042")
        host: Agent host type (default: "developer", can be "reviewer" etc.)
        skip_preflight: Skip preflight checks if True
        force: Force restart if agent already running
        tool: AI tool to use (default: from config)
        quiet: Suppress console output if True

    Returns:
        ActiveAgent with agent details

    Raises:
        IssueNotFoundError: If issue doesn't exist
        AgentAlreadyRunningError: If agent already running (without force)
        PreflightError: If preflight checks fail
        ContainerUnavailableError: If no container runtime available
        AgentStartError: If agent fails to start
    """
    from agenttree.config import load_config
    from agenttree.container import get_container_runtime
    from agenttree.ids import parse_issue_id
    from agenttree.issues import get_issue, update_issue_stage, update_issue_metadata
    from agenttree.preflight import run_preflight
    from agenttree.state import (
        get_active_agent,
        create_agent_for_issue,
        get_issue_names,
        unregister_agent,
    )
    from agenttree.tmux import TmuxManager
    from agenttree.issues import create_session
    from agenttree.worktree import create_worktree, update_worktree_with_main
    import subprocess
    import time

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

    # If issue is in backlog, move it to first real stage
    if issue.stage == "backlog":
        if not quiet:
            console.print(f"[cyan]Moving issue from backlog to explore.define...[/cyan]")
        update_issue_stage(issue.id, "explore.define")
        issue.stage = "explore.define"

    # Check if agent already running (tmux session check)
    existing_agent = get_active_agent(issue.id, host)
    if existing_agent and not force:
        raise AgentAlreadyRunningError(issue.id, host)

    # Check if container already running (catches orphaned containers without tmux sessions)
    # Only check for developer role — custom role agents (review etc.) coexist with
    # the developer container, and container names don't encode role.
    from agenttree.container import is_container_running
    container_name = config.get_issue_container_name(issue.id)
    if host == "developer" and is_container_running(container_name) and not force:
        raise AgentAlreadyRunningError(issue.id, host)

    # If force, clean up existing container before proceeding
    if force:
        runtime = get_container_runtime()
        if runtime.runtime:
            from agenttree.container import cleanup_container
            cleanup_container(runtime.runtime, container_name)

    # Initialize managers
    tmux_manager = TmuxManager(config)

    # Get names for this issue and host
    names = get_issue_names(issue.id, config.project, host)

    # Create worktree for issue
    worktree_path = config.get_issue_worktree_path(issue.id)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    has_merge_conflicts = False
    is_restart = False
    if worktree_path.exists():
        # Worktree exists - this is a restart scenario
        is_restart = True
        if not quiet:
            console.print(f"[cyan]Restarting: Rebasing worktree onto latest main...[/cyan]")
        update_success = update_worktree_with_main(worktree_path)
        if update_success:
            if not quiet:
                console.print(f"[green]✓ Worktree rebased successfully[/green]")
        else:
            has_merge_conflicts = True
            if not quiet:
                console.print(f"[yellow]⚠ Merge conflicts detected - agent will need to resolve[/yellow]")
    else:
        # Check if branch exists
        branch_exists = subprocess.run(
            ["git", "rev-parse", "--verify", names["branch"]],
            cwd=repo_path,
            capture_output=True,
        ).returncode == 0

        if branch_exists:
            # Branch exists - this is a restart scenario
            is_restart = True
            if not quiet:
                console.print(f"[dim]Restarting from existing branch: {names['branch']}[/dim]")
            create_worktree(repo_path, worktree_path, names["branch"])
            if not quiet:
                console.print(f"[cyan]Rebasing onto latest main...[/cyan]")
            update_success = update_worktree_with_main(worktree_path)
            if update_success:
                if not quiet:
                    console.print(f"[green]✓ Worktree rebased successfully[/green]")
            else:
                has_merge_conflicts = True
                if not quiet:
                    console.print(f"[yellow]⚠ Merge conflicts detected - agent will need to resolve[/yellow]")
        else:
            if not quiet:
                console.print(f"[dim]Creating worktree: {worktree_path.name}[/dim]")
            create_worktree(repo_path, worktree_path, names["branch"])

    # Get deterministic port using config method
    port = config.get_port_for_issue(issue.id)
    if not quiet:
        console.print(f"[dim]Using port: {port} (derived from issue #{issue.id})[/dim]")

    # Register agent in state
    agent = create_agent_for_issue(
        issue_id=issue.id,
        worktree_path=worktree_path,
        port=port,
        project=config.project,
        role=host,
    )

    # Save branch and worktree info to issue metadata
    update_issue_metadata(issue.id, branch=names["branch"], worktree_dir=str(worktree_path))

    role_label = f" ({host})" if host != "developer" else ""
    if not quiet:
        console.print(f"[green]✓ Starting agent{role_label} for issue #{issue.id}: {issue.title}[/green]")

    # Create session for restart detection
    create_session(issue.id)

    # Start agent in container
    tool_name = tool or config.default_tool
    model_name = config.model_for(issue.stage)
    runtime = get_container_runtime()

    if not runtime.is_available():
        raise ContainerUnavailableError(runtime.get_recommended_action())

    if not quiet:
        console.print(f"[dim]Container runtime: {runtime.get_runtime_name()}[/dim]")
        console.print(f"[dim]Model: {model_name}[/dim]")

    start_success = tmux_manager.start_issue_agent_in_container(
        issue_id=issue.id,
        session_name=agent.tmux_session,
        worktree_path=worktree_path,
        tool_name=tool_name,
        container_runtime=runtime,
        model=model_name,
        role=host,
        has_merge_conflicts=has_merge_conflicts,
        is_restart=is_restart,
    )

    if not start_success:
        unregister_agent(issue.id, host)
        raise AgentStartError(issue.id, "Claude prompt not detected within timeout")

    if not quiet:
        console.print(f"[green]✓ Started {tool_name} in container[/green]")

    if not quiet:
        console.print(f"\n[bold]Agent{role_label} ready for issue #{issue.id}[/bold]")

    return agent


def start_controller(
    *,
    tool: str | None = None,
    force: bool = False,
    quiet: bool = False,
) -> None:
    """Start the controller agent (issue 0).

    The controller runs on the host (not in a container) and orchestrates
    other agents.

    Args:
        tool: AI tool to use (default: from config)
        force: Force restart if already running
        quiet: Suppress console output if True

    Raises:
        AgentAlreadyRunningError: If controller already running (without force)
    """
    from agenttree.config import load_config
    from agenttree.tmux import TmuxManager, session_exists, kill_session

    if not quiet:
        from rich.console import Console
        console = Console()

    repo_path = Path.cwd()
    config = load_config(repo_path)
    tmux_manager = TmuxManager(config)

    session_name = config.get_manager_tmux_session()
    tool_name = tool or config.default_tool

    # Check if already running
    if session_exists(session_name):
        if not force:
            raise AgentAlreadyRunningError("0", "controller")
        if not quiet:
            console.print("[dim]Killing existing controller session...[/dim]")
        kill_session(session_name)

    if not quiet:
        console.print("[green]✓ Starting controller...[/green]")

    tmux_manager.start_manager(
        session_name=session_name,
        repo_path=repo_path,
        tool_name=tool_name,
    )

    if not quiet:
        console.print(f"[green]✓ Controller started[/green]")
        console.print(f"\n[bold]Controller ready[/bold]")
        console.print(f"[dim]Attach with: agenttree attach 0[/dim]")


def send_message(
    issue_id: int | str,
    message: str,
    *,
    host: str = "developer",
    auto_start: bool = True,
    interrupt: bool = False,
    quiet: bool = False,
) -> str:
    """Send a message to an agent.

    If the agent is not running and auto_start is True, it will be started
    automatically.

    Args:
        issue_id: Issue ID (int or string), or 0/"0" for controller
        message: Message to send
        host: Agent host type (default: "developer")
        auto_start: Start agent if not running (default: True)
        interrupt: Send Ctrl+C first to interrupt current task (default: False)
        quiet: Suppress console output if True

    Returns:
        Status string: "sent", "restarted", "no_agent", "error"

    Raises:
        IssueNotFoundError: If issue doesn't exist
        ControllerNotRunningError: If sending to controller and it's not running
    """
    from agenttree.config import load_config
    from agenttree.ids import parse_issue_id
    from agenttree.issues import get_issue
    from agenttree.state import get_active_agent
    from agenttree.tmux import TmuxManager, session_exists, send_message as tmux_send_message

    if not quiet:
        from rich.console import Console
        console = Console()

    config = load_config()
    tmux_manager = TmuxManager(config)

    # Parse issue ID to int
    parsed_id = parse_issue_id(issue_id) if isinstance(issue_id, str) else issue_id

    # Special handling for controller (issue 0)
    if parsed_id == 0:
        session_name = config.get_manager_tmux_session()
        if not session_exists(session_name):
            raise ControllerNotRunningError()
        result = tmux_send_message(session_name, message, interrupt=interrupt)
        if result != "sent":
            if not quiet:
                console.print(f"[red]Error: Failed to send to controller ({result})[/red]")
            return "error"
        if not quiet:
            console.print("[green]✓ Sent message to controller[/green]")
        return "sent"

    # Get issue to validate it exists
    issue = get_issue(parsed_id)
    if not issue:
        raise IssueNotFoundError(parsed_id)

    def ensure_agent_running() -> bool:
        """Start agent if not running. Returns True if agent is now running."""
        agent = get_active_agent(issue.id, host)
        if agent and tmux_manager.is_issue_running(agent.tmux_session):
            return True

        if not auto_start:
            return False

        role_label = f" ({host})" if host != "developer" else ""
        if not quiet:
            console.print(f"[dim]Agent{role_label} not running, starting...[/dim]")

        try:
            start_agent(
                issue.id,
                host=host,
                skip_preflight=True,
                quiet=quiet,
            )
            if not quiet:
                console.print(f"[green]✓ Started agent{role_label}[/green]")
            return True
        except (AgentStartError, ContainerUnavailableError, PreflightError) as e:
            if not quiet:
                console.print(f"[red]Error: Could not start agent: {e}[/red]")
            return False

    # Ensure agent is running
    if not ensure_agent_running():
        return "no_agent"

    # Re-fetch agent after potential start
    agent = get_active_agent(issue.id, host)
    if not agent:
        if not quiet:
            console.print(f"[red]Error: Agent started but not found in state[/red]")
        return "error"

    # Send the message
    result = tmux_manager.send_message_to_issue(agent.tmux_session, message, interrupt=interrupt)

    role_label = f" ({agent.role})" if agent.role != "developer" else ""
    if result == "sent":
        if not quiet:
            console.print(f"[green]✓ Sent message to issue #{agent.issue_id}{role_label}[/green]")
        return "sent"
    elif result == "claude_exited":
        # Claude exited - restart and try again
        if not quiet:
            console.print(f"[yellow]Claude CLI exited, restarting agent...[/yellow]")
        if ensure_agent_running():
            agent = get_active_agent(issue.id, host)
            if agent:
                result = tmux_manager.send_message_to_issue(agent.tmux_session, message, interrupt=interrupt)
                if result == "sent":
                    if not quiet:
                        console.print(f"[green]✓ Sent message to issue #{agent.issue_id}{role_label}[/green]")
                    return "restarted"
        if not quiet:
            console.print(f"[red]Error: Could not send message after restart[/red]")
        return "error"
    elif result == "no_session":
        if not quiet:
            console.print(f"[red]Error: Tmux session not found[/red]")
        return "no_agent"
    else:
        if not quiet:
            console.print(f"[red]Error: Failed to send message[/red]")
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
) -> Issue:
    """Transition an issue from its current stage to the next.

    This is THE function for stage transitions. CLI (agenttree next/approve),
    web (/api/issues/{id}/approve), and manager heartbeat all call this to
    ensure consistent behavior: exit hooks -> stage update -> enter hooks.

    Args:
        issue_id: Issue ID (int or string)
        next_stage: Target dot path (e.g., "explore.define", "implement.code")
        skip_pr_approval: Skip PR approval check (for self-approval)
        trigger: What triggered this transition ("cli", "web", "manager")

    Returns:
        The updated Issue object

    Raises:
        ValidationError: If exit hooks fail (blocks transition)
        StageRedirect: If a hook redirects to a different stage (from exit hooks)
        RuntimeError: If stage update fails
    """
    from agenttree.hooks import execute_exit_hooks, execute_enter_hooks, StageRedirect
    from agenttree.ids import parse_issue_id
    from agenttree.issues import get_issue, update_issue_stage

    # Normalize to int
    if isinstance(issue_id, str):
        issue_id = parse_issue_id(issue_id)

    issue = get_issue(issue_id)
    if not issue:
        raise RuntimeError(f"Issue #{issue_id} not found")

    from_stage = issue.stage

    # 1. Execute exit hooks (validation — can block)
    # ValidationError propagates to caller (blocks transition)
    # StageRedirect from exit hooks changes the target
    try:
        execute_exit_hooks(issue, from_stage, skip_pr_approval=skip_pr_approval)
    except StageRedirect as redirect:
        next_stage = redirect.target

    # 2. Update issue stage
    updated = update_issue_stage(issue_id, next_stage)
    if not updated:
        raise RuntimeError(f"Failed to update issue #{issue_id} to {next_stage}")

    # 3. Execute enter hooks
    # StageRedirect here means e.g. merge_pr hit conflicts -> redirect to implement
    try:
        execute_enter_hooks(updated, next_stage)
    except StageRedirect as redirect:
        log.info("Enter hook redirected issue #%s to %s: %s",
                 issue_id, redirect.target, redirect.reason)
        redirected = update_issue_stage(issue_id, redirect.target)
        if redirected:
            _notify_agent(issue_id, f"Issue redirected to {redirect.target}: {redirect.reason}. Run `agenttree next` for instructions.", interrupt=True)
            return redirected
        raise RuntimeError(f"Failed to redirect issue #{issue_id} to {redirect.target}")
    except Exception as e:
        log.warning("Enter hooks failed for issue #%s (%s trigger): %s", issue_id, trigger, e)

    return updated


def _notify_agent(issue_id: int, message: str, *, interrupt: bool = False) -> None:
    """Best-effort notify an active agent via tmux. Never raises.

    Args:
        issue_id: The issue ID to notify
        message: Message to send to the agent
        interrupt: If True, send Ctrl+C first to interrupt current task
    """
    try:
        from agenttree.state import get_active_agent
        from agenttree.tmux import send_message as tmux_send, session_exists as tmux_session_exists

        agent = get_active_agent(issue_id)
        if agent and agent.tmux_session and tmux_session_exists(agent.tmux_session):
            tmux_send(agent.tmux_session, message, interrupt=interrupt)
            log.info("Notified agent for issue #%s", issue_id)
    except Exception as e:
        log.warning("Failed to notify agent for issue #%s: %s", issue_id, e)


# =============================================================================
# Stop/Cleanup Functions
# =============================================================================


def stop_agent(issue_id: int, role: str = "developer", quiet: bool = False) -> bool:
    """Stop an active agent - kills tmux and stops container.

    Uses config methods to ensure consistent naming across the system.

    Args:
        issue_id: Issue ID to stop
        role: Agent role (default: "developer")
        quiet: If True, suppress output messages

    Returns:
        True if something was stopped, False if nothing to stop
    """
    from agenttree.config import load_config
    from agenttree.container import get_container_runtime
    from agenttree.ids import format_issue_id
    from agenttree.tmux import kill_session, session_exists

    config = load_config()
    stopped_something = False

    if not quiet:
        from rich.console import Console
        console = Console()

    # 1. Kill serve session (if it exists) - runs on host, not in container
    try:
        serve_session = get_serve_session_name(config.project, issue_id)
        if session_exists(serve_session):
            kill_session(serve_session)
            stopped_something = True
            if not quiet:
                console.print(f"[dim]  Stopped serve session: {serve_session}[/dim]")
    except subprocess.CalledProcessError as e:
        log.warning("Could not stop serve session for issue %s: %s", issue_id, e)

    # 2. Kill tmux session if it exists
    try:
        session_name = config.get_issue_tmux_session(issue_id, role)
        if session_exists(session_name):
            kill_session(session_name)
            stopped_something = True
            if not quiet:
                console.print(f"[dim]  Stopped tmux session: {session_name}[/dim]")
    except Exception as e:
        if not quiet:
            console.print(f"[yellow]  Warning: Could not stop tmux session: {e}[/yellow]")

    # 3. Stop container by name (fast and reliable)
    try:
        runtime = get_container_runtime()
        if runtime.runtime:
            # Use config method for consistent container naming
            container_name = config.get_issue_container_name(issue_id)

            if runtime.stop(container_name):
                stopped_something = True
                if not quiet:
                    console.print(f"[dim]  Stopped container: {container_name}[/dim]")

            # Remove container (Apple Containers do NOT auto-remove, Docker needs explicit rm too)
            if runtime.delete(container_name):
                stopped_something = True
    except Exception as e:
        if not quiet:
            console.print(f"[yellow]  Warning: Could not stop container: {e}[/yellow]")

    if stopped_something and not quiet:
        console.print(f"[green]✓ Agent stopped for issue #{issue_id}[/green]")

    return stopped_something


def stop_all_agents_for_issue(issue_id: int, quiet: bool = False) -> int:
    """Stop all agents for an issue (across all roles).

    Stops agents found via tmux sessions, then always attempts to stop the
    container by name — even if no tmux sessions exist. This prevents orphaned
    containers from continuing to modify issue state after archiving.

    Args:
        issue_id: Issue ID
        quiet: If True, suppress output messages

    Returns:
        Number of agents stopped
    """
    from agenttree.state import get_active_agents_for_issue

    agents = get_active_agents_for_issue(issue_id)
    roles_stopped: set[str] = set()
    count = 0
    for agent in agents:
        if stop_agent(issue_id, agent.role, quiet):
            count += 1
        roles_stopped.add(agent.role)

    # Always try to stop the container directly — tmux session may be gone
    # while the container is still running and modifying issue state.
    if "developer" not in roles_stopped:
        if stop_agent(issue_id, "developer", quiet):
            count += 1
    return count


def cleanup_orphaned_containers(quiet: bool = False) -> int:
    """Stop containers that don't have a corresponding tmux session.

    This handles the case where tmux sessions are killed but containers keep running.
    Looks for containers named with agenttree pattern and stops any that don't have
    a matching tmux session. Uses the container runtime abstraction instead of raw
    subprocess calls.

    Args:
        quiet: If True, suppress output messages

    Returns:
        Number of containers stopped
    """
    import re
    from agenttree.config import load_config
    from agenttree.container import get_container_runtime
    from agenttree.tmux import session_exists

    if not quiet:
        from rich.console import Console
        console = Console()

    runtime = get_container_runtime()
    if not runtime.runtime:
        return 0

    config = load_config()
    stopped = 0

    # Get list of all containers using runtime abstraction
    containers = runtime.list_all()

    # Check each container to see if it matches our naming pattern
    # Pattern: agenttree-{project}-{issue_id} or agenttree-{project}-{issue_id}-{suffix}
    pattern = rf"^agenttree-{re.escape(config.project)}-(\d+)(?:-[a-f0-9]+)?$"

    for container in containers:
        name = container.get("name", "") or ""
        if isinstance(name, list):
            name = name[0] if name else ""
        name = name.strip("/")  # Docker adds leading slash

        match = re.match(pattern, name)
        if not match:
            continue

        issue_id = int(match.group(1))

        # Check if there's a tmux session for this container (developer is default role)
        session_name = config.get_issue_tmux_session(issue_id, "developer")

        if not session_exists(session_name):
            # Orphaned container - stop and remove it
            container_id = container.get("id", "") or name

            try:
                runtime.stop(container_id)
                runtime.delete(container_id)
                stopped += 1
                if not quiet:
                    console.print(f"[dim]Cleaned up orphaned container: {name}[/dim]")
            except Exception as e:
                # Container cleanup can fail if already removed - continue with others
                if not quiet:
                    console.print(f"[yellow]Warning: Could not cleanup container {name}: {e}[/yellow]")

    if not quiet and stopped > 0:
        console.print(f"[green]✓ Cleaned up {stopped} orphaned container(s)[/green]")

    return stopped


def cleanup_all_agenttree_containers(quiet: bool = False) -> int:
    """Remove ALL agenttree containers (by name prefix OR image name).

    Uses the container runtime abstraction which handles differences
    between Apple Container, Docker, and Podman.

    Args:
        quiet: If True, suppress output messages

    Returns:
        Number of containers removed
    """
    from agenttree.config import load_config
    from agenttree.container import get_container_runtime

    if not quiet:
        from rich.console import Console
        console = Console()

    runtime = get_container_runtime()
    if not runtime.runtime:
        return 0

    config = load_config()
    project_prefix = f"agenttree-{config.project}-"

    # Get all containers and filter for agenttree ones
    containers = runtime.list_all()
    removed = 0

    for c in containers:
        name = c.get("name", "") or c.get("id", "")
        image = c.get("image", "")

        # Match by name prefix OR by agenttree image (catches legacy unnamed containers)
        is_ours = (
            name.startswith(project_prefix) or
            name.startswith("agenttree-") or
            "agenttree" in image
        )

        if is_ours and name:
            runtime.stop(name)
            if runtime.delete(name):
                removed += 1
                if not quiet:
                    console.print(f"[dim]Removed: {name}[/dim]")

    if not quiet and removed:
        console.print(f"[green]✓ Removed {removed} container(s)[/green]")

    return removed


def cleanup_all_with_retry(max_passes: int = 3, delay_s: float = 2.0, quiet: bool = False) -> None:
    """Perform multi-pass cleanup of all agenttree containers with retry logic.

    Sometimes containers need multiple passes to fully clean up due to timing
    issues or dependency ordering. This function performs multiple cleanup
    passes with configurable delay between them.

    Args:
        max_passes: Number of cleanup passes to perform
        delay_s: Delay in seconds between passes
        quiet: If True, suppress output messages
    """
    import time
    for i in range(max_passes):
        cleanup_all_agenttree_containers(quiet)
        # Sleep between passes, but not after the last pass
        if i < max_passes - 1:
            time.sleep(delay_s)

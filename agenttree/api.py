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

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agenttree.state import ActiveAgent

__all__ = [
    "start_agent",
    "send_message",
    "start_controller",
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

    def __init__(self, issue_id: str):
        self.issue_id = issue_id
        super().__init__(f"Issue #{issue_id} not found")


class AgentStartError(Exception):
    """Raised when an agent fails to start."""

    def __init__(self, issue_id: str, reason: str):
        self.issue_id = issue_id
        self.reason = reason
        super().__init__(f"Failed to start agent for issue #{issue_id}: {reason}")


class AgentAlreadyRunningError(Exception):
    """Raised when trying to start an agent that's already running."""

    def __init__(self, issue_id: str, host: str = "developer"):
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
    issue_id: str,
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
        issue_id: Issue ID (e.g., "042" or "42")
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
    from agenttree.container import get_container_runtime, find_container_by_worktree
    from agenttree.issues import get_issue, update_issue_stage, update_issue_metadata
    from agenttree.preflight import run_preflight
    from agenttree.state import (
        get_active_agent,
        create_agent_for_issue,
        get_port_for_issue,
        get_issue_names,
        unregister_agent,
    )
    from agenttree.tmux import TmuxManager
    from agenttree.issues import create_session
    from agenttree.worktree import create_worktree, update_worktree_with_main
    import subprocess
    import time

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

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"

    # Load issue
    issue = get_issue(issue_id_normalized)
    if not issue:
        raise IssueNotFoundError(issue_id)

    # If issue is in backlog, move it to define stage first
    if issue.stage == "backlog":
        if not quiet:
            console.print(f"[cyan]Moving issue from backlog to define...[/cyan]")
        update_issue_stage(issue.id, "define")
        issue.stage = "define"

    # Check if agent already running
    existing_agent = get_active_agent(issue.id, host)
    if existing_agent and not force:
        raise AgentAlreadyRunningError(issue.id, host)

    # Initialize managers
    tmux_manager = TmuxManager(config)

    # Get names for this issue and host
    names = get_issue_names(issue.id, issue.slug, config.project, host)

    # Create worktree for issue
    worktree_path = config.get_issue_worktree_path(issue.id, issue.slug)
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

    # Get deterministic port
    base_port = int(config.port_range.split("-")[0])
    port = get_port_for_issue(issue.id, base_port=base_port)
    if not quiet:
        console.print(f"[dim]Using port: {port} (derived from issue #{issue.id})[/dim]")

    # Register agent in state
    agent = create_agent_for_issue(
        issue_id=issue.id,
        slug=issue.slug,
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
    model_name = config.model_for(issue.stage, issue.substage)
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

    # For Apple Containers, look up the UUID
    if runtime.get_runtime_name() == "container":
        from agenttree.state import update_agent_container_id

        for _ in range(10):
            time.sleep(0.5)
            container_uuid = find_container_by_worktree(worktree_path)
            if container_uuid:
                update_agent_container_id(issue.id, container_uuid, host)
                if not quiet:
                    console.print(f"[dim]Container UUID: {container_uuid[:12]}...[/dim]")
                break
        else:
            if not quiet:
                console.print(f"[yellow]Warning: Could not find container UUID for cleanup tracking[/yellow]")

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

    session_name = f"{config.project}-controller-000"
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
    issue_id: str,
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
        issue_id: Issue ID (e.g., "042" or "42"), or "0" for controller
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
    from agenttree.issues import get_issue
    from agenttree.state import get_active_agent
    from agenttree.tmux import TmuxManager, session_exists, send_keys

    if not quiet:
        from rich.console import Console
        console = Console()

    config = load_config()
    tmux_manager = TmuxManager(config)

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"

    # Special handling for controller
    if issue_id_normalized == "0":
        session_name = f"{config.project}-controller-000"
        if not session_exists(session_name):
            raise ControllerNotRunningError()
        send_keys(session_name, message, interrupt=interrupt)
        if not quiet:
            console.print("[green]✓ Sent message to controller[/green]")
        return "sent"

    # Get issue to validate it exists
    issue = get_issue(issue_id_normalized)
    if not issue:
        raise IssueNotFoundError(issue_id)

    issue_id_normalized = issue.id

    def ensure_agent_running() -> bool:
        """Start agent if not running. Returns True if agent is now running."""
        agent = get_active_agent(issue_id_normalized, host)
        if agent and tmux_manager.is_issue_running(agent.tmux_session):
            return True

        if not auto_start:
            return False

        role_label = f" ({host})" if host != "developer" else ""
        if not quiet:
            console.print(f"[dim]Agent{role_label} not running, starting...[/dim]")

        try:
            start_agent(
                issue_id_normalized,
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
    agent = get_active_agent(issue_id_normalized, host)
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
            agent = get_active_agent(issue_id_normalized, host)
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

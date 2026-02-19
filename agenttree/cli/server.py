"""Server commands (run, stop-all, stalls)."""

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from agenttree.cli._utils import console, load_config, get_manager_session_name
from agenttree.tmux import TmuxManager

if TYPE_CHECKING:
    from agenttree.config import Config


def _start_manager(
    tool: str | None,
    force: bool,
    config: "Config",
    repo_path: Path,
) -> None:
    """Start the manager agent (agent 0).

    The manager runs on the host (not in a container) and orchestrates
    work across all issues. It uses the main branch.
    """
    from agenttree.tmux import session_exists

    tmux_manager = TmuxManager(config)
    session_name = get_manager_session_name(config)

    # Check if manager already running
    if session_exists(session_name) and not force:
        console.print("[yellow]Manager already running[/yellow]")
        console.print(f"\nUse --force to restart, or attach with:")
        console.print(f"  agenttree attach 0")
        sys.exit(1)

    tool_name = tool or config.default_tool
    # Resolve model through standard chain: stage → role → default
    # Manager has no stage, so this picks up the role model (e.g., sonnet)
    model_name = config.model_for("manager", role="manager")

    console.print(f"[green]Starting manager agent...[/green]")
    console.print(f"[dim]Tool: {tool_name}[/dim]")
    console.print(f"[dim]Model: {model_name}[/dim]")
    console.print(f"[dim]Session: {session_name}[/dim]")

    # Start manager on host (not in container)
    tmux_manager.start_manager(
        session_name=session_name,
        repo_path=repo_path,
        tool_name=tool_name,
        model=model_name,
    )

    console.print(f"\n[bold]Manager ready[/bold]")
    console.print(f"\n[dim]Commands:[/dim]")
    console.print(f"  agenttree attach 0")
    console.print(f"  agenttree send 0 'message'")
    console.print(f"  agenttree kill 0")


@click.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=None, type=int, help="Port to bind to (default: from port_range config)")
@click.option("--skip-agents", is_flag=True, help="Don't auto-start agents")
def run(host: str, port: int | None, skip_agents: bool) -> None:
    """Start AgentTree: server + agents for all active issues.

    This is the main entry point that:
    1. Starts agents for all issues NOT in parking lot stages (backlog, accepted, not_doing)
    2. Starts the manager agent (agent 0)
    3. Starts the web server with sync/heartbeat

    Use 'agenttree shutdown' to stop everything.

    Examples:
        agenttree run                  # Start everything
        agenttree run --skip-agents    # Just start the server
        agenttree run --port 9000      # Use custom port
    """
    from agenttree.web.app import run_server
    from agenttree.issues import list_issues
    from agenttree.state import get_active_agent
    from agenttree.tmux import session_exists

    repo_path = Path.cwd()
    config = load_config(repo_path)

    if port is None:
        port = config.server_port

    if not skip_agents:
        # Get parking lot stages to filter out
        parking_lot_stages = config.get_parking_lot_stages()

        # Start agents for all issues not in parking lot stages
        issues = list_issues(sync=True)
        started_count = 0
        skipped_count = 0

        for issue in issues:
            if issue.stage in parking_lot_stages:
                skipped_count += 1
                continue

            # Check if agent already running
            if get_active_agent(issue.id):
                console.print(f"[dim]Issue #{issue.id} already has an agent running[/dim]")
                continue

            # Start agent for this issue
            console.print(f"[cyan]Starting agent for issue #{issue.id} ({issue.stage})...[/cyan]")
            result = subprocess.run(
                ["agenttree", "start", issue.id, "--skip-preflight"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                started_count += 1
                console.print(f"[green]✓ Started agent for #{issue.id}[/green]")
            else:
                console.print(f"[yellow]Could not start agent for #{issue.id}: {result.stderr.strip()}[/yellow]")

        console.print(f"\n[bold]Agents: {started_count} started, {skipped_count} in parking lot[/bold]")

        # Start manager agent (agent 0) if not already running
        manager_session = get_manager_session_name(config)
        if not session_exists(manager_session):
            console.print(f"\n[cyan]Starting manager agent...[/cyan]")
            _start_manager(tool=None, force=False, config=config, repo_path=repo_path)
        else:
            console.print(f"[dim]Manager agent already running[/dim]")

    # Start the web server
    console.print(f"\n[cyan]Starting AgentTree server at http://{host}:{port}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    run_server(host=host, port=port)


@click.command("stop-all")
def stop_all() -> None:
    """Stop all agents (opposite of 'agenttree run').

    This stops:
    1. All running issue agents
    2. The manager agent (agent 0)

    Use 'agenttree run' to start everything again.

    Examples:
        agenttree stop-all            # Stop all agents
    """
    from agenttree.state import list_active_agents
    from agenttree.api import stop_agent
    from agenttree.tmux import session_exists, kill_session

    config = load_config()

    # Stop all issue agents
    agents = list_active_agents()
    stopped_count = 0
    for agent in agents:
        console.print(f"[cyan]Stopping agent for issue #{agent.issue_id}...[/cyan]")
        if stop_agent(agent.issue_id, agent.role, quiet=True):
            stopped_count += 1
            console.print(f"[green]✓ Stopped agent for #{agent.issue_id}[/green]")

    # Stop manager agent
    manager_session = get_manager_session_name(config)
    if session_exists(manager_session):
        console.print(f"[cyan]Stopping manager agent...[/cyan]")
        kill_session(manager_session)
        console.print(f"[green]✓ Stopped manager[/green]")

    console.print(f"\n[bold green]✓ Shutdown complete: {stopped_count} agents stopped[/bold green]")


@click.command()
@click.option("--threshold", "-t", default=None, type=int, help="Override stall threshold (minutes)")
def stalls(threshold: int | None) -> None:
    """List agents that appear stalled (in same stage too long).

    Detects agents that have been in a non-review stage for longer than
    the configured threshold (default 20 minutes) without advancing.

    Examples:
        agenttree stalls              # Check for stalled agents
        agenttree stalls -t 30        # Use 30-minute threshold
    """
    from agenttree.manager_agent import get_stalled_agents

    config = load_config()
    agents_dir = Path.cwd() / "_agenttree"

    # Use config threshold or override
    threshold_min = threshold if threshold is not None else config.manager.stall_threshold_min

    stalled = get_stalled_agents(agents_dir, threshold_min=threshold_min)

    if not stalled:
        console.print(f"[green]No stalled agents detected[/green] (threshold: {threshold_min} min)")
        return

    console.print(f"[yellow]Found {len(stalled)} stalled agent(s):[/yellow]\n")

    for agent in stalled:
        console.print(f"  [bold]Issue #{agent['issue_id']}[/bold]: {agent['title']}")
        console.print(f"    Stage: {agent['stage']}")
        console.print(f"    Stalled for: {agent['minutes_stalled']} minutes")
        console.print()

    console.print("[dim]Use 'agenttree send <id> \"message\"' to nudge a stalled agent[/dim]")

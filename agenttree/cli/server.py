"""Server commands (start, server, run, stop-all, stalls)."""

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


def _start_agents_background(config: "Config", repo_path: Path) -> None:
    """Start all agents in parallel (runs in a background thread)."""
    from agenttree.issues import list_issues
    from agenttree.state import get_active_agent
    from agenttree.tmux import session_exists

    parking_lot_stages = config.get_parking_lot_stages()
    issues = list_issues(sync=True)

    # Launch all agent starts in parallel
    pending: list[tuple[int, subprocess.Popen[str]]] = []
    skipped_count = 0

    for issue in issues:
        if issue.stage in parking_lot_stages:
            skipped_count += 1
            continue
        if get_active_agent(issue.id):
            console.print(f"[dim]Issue #{issue.id} already has an agent running[/dim]")
            continue

        console.print(f"[cyan]Starting agent for issue #{issue.id} ({issue.stage})...[/cyan]")
        proc = subprocess.Popen(
            ["agenttree", "start", str(issue.id), "--skip-preflight"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        pending.append((issue.id, proc))

    # Wait for all to finish
    started_count = 0
    for issue_id, proc in pending:
        returncode = proc.wait()
        if returncode == 0:
            started_count += 1
            console.print(f"[green]✓ Started agent for #{issue_id}[/green]")
        else:
            stderr = proc.stderr.read() if proc.stderr else ""
            console.print(f"[yellow]Could not start agent for #{issue_id}: {stderr.strip()}[/yellow]")

    console.print(f"\n[bold]Agents: {started_count} started, {skipped_count} in parking lot[/bold]")

    # Start manager agent (agent 0) if not already running
    manager_session = get_manager_session_name(config)
    if not session_exists(manager_session):
        console.print(f"\n[cyan]Starting manager agent...[/cyan]")
        _start_manager(tool=None, force=False, config=config, repo_path=repo_path)
    else:
        console.print(f"[dim]Manager agent already running[/dim]")


@click.command(name="start")
@click.argument("issue_id", required=False, default=None, type=str)
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=None, type=int, help="Port to bind to (default: from port_range config)")
@click.option("--tool", help="AI tool to use (default: from config)")
@click.option("--role", default="developer", help="Agent role (default: developer)")
@click.option("--force", is_flag=True, help="Force start even if already running")
@click.option("--skip-preflight", is_flag=True, help="Skip preflight environment checks")
def start_all(
    issue_id: str | None,
    host: str,
    port: int | None,
    tool: str | None,
    role: str,
    force: bool,
    skip_preflight: bool,
) -> None:
    """Start AgentTree or a specific agent.

    With no arguments, starts everything: server + agents + manager.
    With an ISSUE_ID, starts a single agent for that issue.

    Examples:
        agenttree start                # Start everything
        agenttree start 42             # Start agent for issue #42
        agenttree start --port 9000    # Use custom port for server
    """
    if issue_id is not None:
        from agenttree.cli.agents import start_agent
        ctx = click.get_current_context()
        ctx.invoke(
            start_agent,
            issue_id=issue_id,
            tool=tool,
            role=role,
            force=force,
            skip_preflight=skip_preflight,
        )
        return

    import threading
    from agenttree.web.app import run_server

    repo_path = Path.cwd()
    config = load_config(repo_path)

    if port is None:
        port = config.server_port

    thread = threading.Thread(
        target=_start_agents_background,
        args=(config, repo_path),
        daemon=True,
    )
    thread.start()

    console.print(f"[cyan]Starting AgentTree server at http://{host}:{port}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    run_server(host=host, port=port)


@click.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=None, type=int, help="Port to bind to (default: from port_range config)")
def server(host: str, port: int | None) -> None:
    """Start just the AgentTree web server (no agents).

    Use this in serve configs to avoid recursive agent startup.

    Examples:
        agenttree server               # Start web server only
        agenttree server --port 9042   # On a specific port
    """
    from agenttree.web.app import run_server

    config = load_config()

    if port is None:
        port = config.server_port

    console.print(f"[cyan]Starting AgentTree server at http://{host}:{port}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    run_server(host=host, port=port)


@click.command(name="cmd")
@click.argument("cmd_name", type=str)
@click.option("--issue-id", default=None, type=int, help="Issue ID (default: from env AGENTTREE_ISSUE_ID)")
def run_command(cmd_name: str, issue_id: int | None) -> None:
    """Run a configured command from .agenttree.yaml.

    CMD_NAME is the command key from the 'commands:' section of your config.

    Environment variables PORT, AGENTTREE_ISSUE_ID, AGENTTREE_ROLE are
    injected automatically when inside a container.

    Examples:
        agenttree cmd serve            # Run the serve command
        agenttree cmd test             # Run the test command
        agenttree cmd lint             # Run the lint command
    """
    import os

    config = load_config()

    if cmd_name not in config.commands:
        console.print(f"[red]Error: Unknown command '{cmd_name}'[/red]")
        console.print("[dim]Available commands:[/dim]")
        for name in sorted(config.commands):
            console.print(f"  {name}: {config.commands[name]}")
        sys.exit(1)

    command_str = config.commands[cmd_name]
    if isinstance(command_str, list):
        command_str = " && ".join(command_str)

    env = os.environ.copy()
    if issue_id is None:
        issue_id_str = os.environ.get("AGENTTREE_ISSUE_ID")
        if issue_id_str:
            issue_id = int(issue_id_str)

    if issue_id is not None:
        env["PORT"] = str(config.get_port_for_issue(issue_id))
        env["AGENTTREE_ISSUE_ID"] = str(issue_id)

    console.print(f"[cyan]Running: {command_str}[/cyan]")
    result = subprocess.run(command_str, shell=True, env=env)
    sys.exit(result.returncode)


@click.command("stop-all")
def stop_all() -> None:
    """Stop all agents.

    This stops:
    1. All running issue agents
    2. The manager agent (agent 0)

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

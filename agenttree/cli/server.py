"""Server and web dashboard commands."""

import subprocess
import sys
from pathlib import Path

import click

from agenttree.config import load_config
from agenttree.github import ensure_gh_cli
from agenttree.cli.common import console


@click.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8080, type=int, help="Port to bind to")
@click.option("--config", "config_path", type=click.Path(exists=True), help="Path to config file")
def web(host: str, port: int, config_path: str | None) -> None:
    """Start the web dashboard for monitoring agents.

    The dashboard provides:
    - Real-time agent status monitoring
    - Live tmux output streaming
    - Task start via web UI
    - Command execution for agents
    """
    from agenttree.web.app import run_server

    console.print(f"[cyan]Starting AgentTree dashboard at http://{host}:{port}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    config_path_obj = Path(config_path) if config_path else None
    run_server(host=host, port=port, config_path=config_path_obj)


@click.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8080, type=int, help="Port to bind to")
def serve(host: str, port: int) -> None:
    """Start the AgentTree server (runs syncs, spawns agents).

    This is the main controller process that:
    - Syncs the _agenttree repo periodically
    - Spawns agents for issues in agent stages
    - Runs hooks for controller stages
    - Provides the web dashboard

    Use 'agenttree start' to run this in a tmux session.
    """
    from agenttree.web.app import run_server

    console.print(f"[cyan]Starting AgentTree server at http://{host}:{port}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    run_server(host=host, port=port)


@click.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8080, type=int, help="Port to bind to")
@click.option("--skip-agents", is_flag=True, help="Don't auto-start agents")
def run(host: str, port: int, skip_agents: bool) -> None:
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
    from agenttree.cli.agent import _start_controller

    repo_path = Path.cwd()
    config = load_config(repo_path)

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
        manager_session = f"{config.project}-controller-000"
        if not session_exists(manager_session):
            console.print(f"\n[cyan]Starting manager agent...[/cyan]")
            _start_controller(tool=None, force=False, config=config, repo_path=repo_path)
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
    from agenttree.state import list_active_agents, stop_agent
    from agenttree.tmux import session_exists, kill_session

    config = load_config()

    # Stop all issue agents
    agents = list_active_agents()
    stopped_count = 0
    for agent in agents:
        console.print(f"[cyan]Stopping agent for issue #{agent.issue_id}...[/cyan]")
        if stop_agent(agent.issue_id, agent.host, quiet=True):
            stopped_count += 1
            console.print(f"[green]✓ Stopped agent for #{agent.issue_id}[/green]")

    # Stop manager agent
    manager_session = f"{config.project}-controller-000"
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
    from agenttree.controller_agent import get_stalled_agents

    config = load_config()
    agents_dir = Path.cwd() / "_agenttree"

    # Use config threshold or override
    threshold_min = threshold if threshold is not None else config.controller.stall_threshold_min

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


@click.command()
@click.argument("pr_number", type=int)
@click.option("--no-approval", is_flag=True, help="Skip approval requirement")
@click.option("--monitor", is_flag=True, help="Monitor PR until ready to merge")
@click.option("--timeout", default=3600, type=int, help="Max wait time in seconds (for --monitor)")
def auto_merge(pr_number: int, no_approval: bool, monitor: bool, timeout: int) -> None:
    """Auto-merge a PR when CI passes and approved.

    Examples:
        agenttree auto-merge 123                    # Check once, merge if ready
        agenttree auto-merge 123 --monitor          # Wait for CI + approval
        agenttree auto-merge 123 --no-approval      # Merge when CI passes (skip approval check)
    """
    from agenttree.github import auto_merge_if_ready, monitor_pr_and_auto_merge

    ensure_gh_cli()

    if monitor:
        console.print(f"[cyan]Monitoring PR #{pr_number}...[/cyan]")
        console.print(f"[dim]Will auto-merge when CI passes{'  and approved' if not no_approval else ''}[/dim]\n")

        success = monitor_pr_and_auto_merge(
            pr_number,
            require_approval=not no_approval,
            max_wait=timeout
        )

        if success:
            console.print(f"[green]✓ PR #{pr_number} auto-merged successfully![/green]")
        else:
            console.print(f"[yellow]⚠ PR #{pr_number} not ready or timed out[/yellow]")
            sys.exit(1)
    else:
        console.print(f"[cyan]Checking PR #{pr_number}...[/cyan]")

        if auto_merge_if_ready(pr_number, require_approval=not no_approval):
            console.print(f"[green]✓ PR #{pr_number} merged![/green]")
        else:
            console.print(f"[yellow]⚠ PR #{pr_number} not ready to merge[/yellow]")
            console.print("[dim]Use --monitor to wait for CI + approval[/dim]")
            sys.exit(1)

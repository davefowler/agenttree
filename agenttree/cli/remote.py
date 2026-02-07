"""Remote agent management commands."""

import sys

import click
from rich.table import Table

from agenttree.cli.common import console


@click.group()
def remote() -> None:
    """Manage remote agents via Tailscale + SSH."""
    pass


@remote.command("list")
def remote_list() -> None:
    """List available remote hosts on Tailscale network."""
    from agenttree.remote import is_tailscale_available, get_tailscale_hosts

    if not is_tailscale_available():
        console.print("[red]Error: Tailscale CLI not found[/red]")
        console.print("[dim]Install: https://tailscale.com/download[/dim]")
        sys.exit(1)

    hosts = get_tailscale_hosts()

    if not hosts:
        console.print("[yellow]No Tailscale hosts found[/yellow]")
        return

    table = Table(title="Tailscale Hosts")
    table.add_column("Hostname", style="cyan")

    for host in hosts:
        table.add_row(host)

    console.print(table)


@remote.command("start")
@click.argument("hostname")
@click.argument("agent_num", type=int)
@click.option("--user", default="agent", help="SSH user")
@click.option("--agents-repo", default="~/agents", help="Path to agents repo on remote")
def remote_start(hostname: str, agent_num: int, user: str, agents_repo: str) -> None:
    """Start a task on a remote agent.

    This will:
    1. SSH into the remote host
    2. Pull latest from _agenttree/ repo
    3. Notify the agent's tmux session

    Example:
        agenttree remote start my-home-pc 1
    """
    from agenttree.remote import RemoteHost, dispatch_task_to_remote_agent

    host = RemoteHost(name=hostname, host=hostname, user=user, is_tailscale=True)

    console.print(f"[cyan]Starting task on {hostname} agent-{agent_num}...[/cyan]")

    success = dispatch_task_to_remote_agent(
        host,
        agent_num,
        project_name="agenttree",  # Could be made configurable
        agents_repo_path=agents_repo
    )

    if success:
        console.print(f"[green]✓ Task started on {hostname}[/green]")
    else:
        console.print(f"[red]✗ Failed to start task[/red]")
        sys.exit(1)

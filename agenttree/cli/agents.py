"""Agent management commands (start, agents, attach, send, output, stop)."""

import sys
from pathlib import Path

import click
from rich.table import Table

from agenttree.config import DEFAULT_ROLE
from agenttree.cli._utils import console, load_config, get_issue_func, normalize_issue_id, format_role_label, get_manager_session_name, get_role_session_if_running, require_manager_running, require_role_running, get_manager_session_if_running


@click.command(name="start-agent", hidden=True)
@click.argument("issue_id", type=str)
@click.option("--tool", help="AI tool to use (default: from config)")
@click.option("--role", default=DEFAULT_ROLE, help="Agent role (default: developer)")
@click.option("--force", is_flag=True, help="Force start even if agent already exists")
@click.option("--skip-preflight", is_flag=True, help="Skip preflight environment checks")
@click.option("--api-key", "force_api_key", is_flag=True, help="Force API key mode (legacy, ignored)")
def start_issue(
    issue_id: str,
    tool: str | None,
    role: str,
    force: bool,
    skip_preflight: bool,
    force_api_key: bool,
) -> None:
    """Start an agent for an issue (creates worktree + claude -p subprocess).

    ISSUE_ID is the issue number (e.g., "23" or "023").

    This creates a dedicated agent for the issue with:
    - A new worktree (issue-023/)
    - A claude -p subprocess running in that worktree
    """
    from agenttree.preflight import run_preflight

    repo_path = Path.cwd()
    config = load_config(repo_path)

    # Check if issue_id is a role name (e.g., "messenger", "manager")
    is_role = issue_id in config.roles
    if not is_role:
        try:
            if normalize_issue_id(issue_id) == 0:
                is_role = True
                issue_id = "messenger"
        except (ValueError, SystemExit):
            pass

    from agenttree.api import HOST_TMUX_ROLES, start_role, AgentAlreadyRunningError

    if is_role:
        target_role = issue_id
    elif role in HOST_TMUX_ROLES:
        target_role = role
    else:
        target_role = None

    if not skip_preflight and target_role != "setup":
        console.print("[dim]Running preflight checks...[/dim]")
        results = run_preflight()
        failed = [r for r in results if not r.passed]
        if failed:
            console.print("[red]Preflight checks failed:[/red]")
            for result in failed:
                console.print(f"  [red]✗[/red] {result.name}: {result.message}")
                if result.fix_hint:
                    console.print(f"    [dim]Hint: {result.fix_hint}[/dim]")
            console.print("\n[yellow]Use --skip-preflight to bypass these checks[/yellow]")
            sys.exit(1)
        console.print("[green]✓ Preflight checks passed[/green]\n")

    if target_role:
        try:
            start_role(target_role, tool=tool, force=force)
        except AgentAlreadyRunningError:
            console.print(f"[yellow]{target_role.capitalize()} already running. Use --force to restart.[/yellow]")
            sys.exit(1)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)
        return

    # Start issue agent via API
    from agenttree.api import start_issue as api_start_issue, IssueNotFoundError, AgentStartError, AgentAlreadyRunningError as AlreadyRunning

    try:
        agent = api_start_issue(
            issue_id,
            host=role,
            skip_preflight=skip_preflight,
            force=force,
            tool=tool,
        )
        console.print(f"\n[bold]Agent ready for issue #{agent.issue_id}[/bold]")
        console.print(f"  PID: {agent.pid}")
        console.print(f"  Port: {agent.port}")
        console.print(f"  Role: {role}")
        console.print(f"  Log: {agent.log_file}")
        console.print(f"\n[dim]Commands:[/dim]")
        role_flag = f" --role {role}" if role != DEFAULT_ROLE else ""
        console.print(f"  agenttree output {issue_id}{role_flag}")
        console.print(f"  agenttree stop {issue_id}{role_flag}")
    except IssueNotFoundError:
        console.print(f"[red]Error: Issue #{issue_id} not found[/red]")
        console.print("[yellow]Create it with: agenttree issue create 'title'[/yellow]")
        sys.exit(1)
    except AlreadyRunning:
        console.print(f"[yellow]Issue #{issue_id} already has an active {role} agent. Use --force to restart.[/yellow]")
        sys.exit(1)
    except AgentStartError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@click.command("agents")
def agents_status() -> None:
    """Show status of all active issue agents."""
    from agenttree.state import list_active_agents
    from agenttree.tmux import session_exists
    from agenttree.ids import serve_session_name
    from agenttree.process import is_pid_alive

    config = load_config()

    agents = list_active_agents()
    active_host_roles = []
    for role_name in sorted(config.roles.keys()):
        session_name = config.get_role_tmux_session(role_name)
        if session_exists(session_name):
            active_host_roles.append(role_name)

    if not agents and not active_host_roles:
        console.print("[dim]No active agents[/dim]")
        console.print("\nStart an agent with:")
        console.print("  agenttree start <issue_id>")
        console.print("  agenttree start messenger")
        return

    table = Table(title="Active Agents")
    table.add_column("ID", style="bold cyan")
    table.add_column("Role", style="blue")
    table.add_column("Title", style="cyan")
    table.add_column("PID", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Dev Server", style="green")
    table.add_column("Branch", style="yellow")

    for agent in agents:
        is_running = is_pid_alive(agent.pid)
        issue = get_issue_func(agent.issue_id)
        issue_title = issue.title[:30] if issue else "Unknown"

        status_str = "🟢 Running" if is_running else "⚪ Stopped"

        # Check serve session
        serve_session = serve_session_name(config.project, agent.issue_id)
        if session_exists(serve_session):
            dev_server_url = config.get_dev_server_url(agent.issue_id)
            dev_server_str = f"[link={dev_server_url}]{dev_server_url}[/link]"
        elif agent.port:
            dev_server_str = f"[dim]:{agent.port}[/dim]"
        else:
            dev_server_str = "[dim]-[/dim]"

        table.add_row(
            str(agent.issue_id),
            agent.role,
            issue_title,
            str(agent.pid),
            status_str,
            dev_server_str,
            agent.branch[:20],
        )

    if agents:
        console.print(table)

    if active_host_roles:
        host_table = Table(title="Running Host Roles")
        host_table.add_column("Role", style="bold cyan")
        host_table.add_column("Description", style="cyan")
        host_table.add_column("Status", style="magenta")

        for role_name in active_host_roles:
            role_config = config.roles[role_name]
            host_table.add_row(
                role_name,
                getattr(role_config, "description", "") or "-",
                "🟢 Running",
            )

        console.print(host_table)

    console.print("\n[dim]Commands:[/dim]")
    console.print("  agenttree output <id> [--role <role>]")
    console.print("  agenttree stop <id> [--role <role>]")
    console.print("  agenttree attach messenger")
    console.print("  agenttree output messenger")


@click.command()
@click.argument("issue_id", type=str)
@click.option("--role", default=DEFAULT_ROLE, help="Agent role (default: developer)")
def attach(issue_id: str, role: str) -> None:
    """Attach to a tmux session (messenger/serve only).

    Sub-agents run as non-interactive claude -p processes and cannot be attached to.
    Use `agenttree output <id>` to see their output instead.
    """
    from agenttree.tmux import session_exists, attach_session

    config = load_config()

    # Host roles can be addressed by name
    if issue_id in config.roles:
        session_name = config.get_role_tmux_session(issue_id)
        if not session_exists(session_name):
            console.print(f"[red]Error: {issue_id.capitalize()} not running[/red]")
            console.print(f"[yellow]Start it with: agenttree start {issue_id}[/yellow]")
            sys.exit(1)
        console.print(f"Attaching to {issue_id} (Ctrl+B, D to detach)...")
        attach_session(session_name)
        return

    # Normalize issue ID
    try:
        issue_id_normalized = normalize_issue_id(issue_id)
    except (SystemExit, ValueError):
        available_roles = ", ".join(sorted(config.roles.keys()))
        console.print(f"[red]Error: Invalid issue ID or role '{issue_id}'[/red]")
        console.print(f"[yellow]Use an issue number or one of: {available_roles}[/yellow]")
        sys.exit(1)

    # Manager/messenger (agent 0)
    if issue_id_normalized == 0:
        for role_name in ("manager", "messenger"):
            session_name = config.get_role_tmux_session(role_name)
            if session_exists(session_name):
                console.print(f"Attaching to {role_name} (Ctrl+B, D to detach)...")
                attach_session(session_name)
                return
        console.print("[red]Manager not running. Start with: agenttree start 0[/red]")
        sys.exit(1)

    # Sub-agents don't have tmux sessions
    console.print(f"[yellow]Sub-agents run as non-interactive processes (claude -p).[/yellow]")
    console.print(f"[yellow]Use 'agenttree output {issue_id}' to see their output.[/yellow]")
    sys.exit(1)


@click.command()
@click.argument("issue_id", type=str)
@click.option("--role", default=DEFAULT_ROLE, help="Agent role (default: developer)")
@click.option("--lines", "-n", default=50, help="Number of lines to show (default: 50)")
def output(issue_id: str, role: str, lines: int) -> None:
    """Show recent output from an agent.

    For sub-agents: reads from the agent's log file.
    For messenger/roles: captures from tmux pane.
    """
    from agenttree.tmux import capture_pane

    config = load_config()

    # Host roles use tmux
    if issue_id in config.roles:
        session_name = require_role_running(config, issue_id, hint=False)
        output_text = capture_pane(session_name, lines=lines)
        console.print(output_text)
        return

    issue_id_normalized = normalize_issue_id(issue_id)

    # Messenger
    if issue_id_normalized == 0:
        session_name = require_manager_running(config, hint=False)
        output_text = capture_pane(session_name, lines=lines)
        console.print(output_text)
        return

    # Sub-agent: read from log file
    from agenttree.process import get_agent_output
    output_text = get_agent_output(issue_id_normalized, role, lines=lines)
    if not output_text:
        console.print(f"[dim]No output available for issue #{issue_id} ({role})[/dim]")
        return
    console.print(output_text)


@click.command()
@click.argument("issue_id", type=str)
@click.argument("message")
@click.option("--role", default=DEFAULT_ROLE, help="Agent role (default: developer)")
@click.option("--interrupt", is_flag=True, help="Send Ctrl+C first (messenger only)")
def send(issue_id: str, message: str, role: str, interrupt: bool) -> None:
    """Send a message to an agent.

    For messenger: sends to tmux session.
    For sub-agents: cannot send mid-flight. Will restart if dead.
    """
    from agenttree.tmux import send_message as tmux_send

    config = load_config()

    # Host roles use tmux directly
    if issue_id in config.roles:
        session_name = require_role_running(config, issue_id)
        tmux_send(session_name, message, interrupt=interrupt)
        console.print(f"[green]✓ Sent message to {issue_id}[/green]")
        return

    from agenttree.api import send_message as api_send, MessengerNotRunningError, IssueNotFoundError

    try:
        result = api_send(issue_id, message, host=role, interrupt=interrupt)
        if result == "error":
            sys.exit(1)
    except MessengerNotRunningError:
        console.print("[red]Messenger not running. Start with: agenttree start messenger[/red]")
        sys.exit(1)
    except IssueNotFoundError:
        console.print(f"[red]Error: Issue #{issue_id} not found[/red]")
        sys.exit(1)


@click.command()
@click.argument("issue_id", type=str)
@click.option("--role", default=DEFAULT_ROLE, help="Agent role (default: developer)")
@click.option("--all", "all_roles", is_flag=True, help="Stop all agents for this issue")
def stop(issue_id: str, role: str, all_roles: bool) -> None:
    """Stop an issue's agent.

    ISSUE_ID is the issue number, or a role name (e.g., "messenger").
    """
    from agenttree.api import stop_agent, stop_all_agents_for_issue
    from agenttree.tmux import session_exists, kill_session

    config = load_config()

    # Host roles
    if issue_id in config.roles:
        session_name = get_role_session_if_running(config, issue_id)
        if not session_name:
            console.print(f"[yellow]{issue_id.capitalize()} not running[/yellow]")
            return
        kill_session(session_name)
        console.print(f"[green]✓ Stopped {issue_id}[/green]")
        return

    issue_id_normalized = normalize_issue_id(issue_id)

    # Messenger
    if issue_id_normalized == 0:
        session_name = get_role_session_if_running(config, "messenger")
        if not session_name:
            console.print("[yellow]Messenger not running[/yellow]")
            return
        kill_session(session_name)
        console.print("[green]✓ Stopped messenger[/green]")
        return

    # Stop all agents for this issue
    if all_roles:
        count = stop_all_agents_for_issue(issue_id_normalized)
        if count == 0:
            console.print(f"[yellow]No active agents for issue #{issue_id}[/yellow]")
        return

    # Stop specific agent
    issue = get_issue_func(issue_id_normalized)
    actual_id = issue.id if issue else issue_id_normalized

    if not stop_agent(actual_id, role):
        console.print(f"[yellow]No active {role} agent for issue #{issue_id}[/yellow]")

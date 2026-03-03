"""Agent management commands (start, agents, sandbox, attach, send, output, stop, kill)."""

import shutil
import subprocess
import sys
from pathlib import Path

import click
from rich.table import Table

from agenttree.cli._utils import console, load_config, get_issue_func, normalize_issue_id, format_role_label, get_manager_session_name, require_manager_running, get_manager_session_if_running
from agenttree.tmux import TmuxManager
from agenttree.container import get_container_runtime
from agenttree.agents_repo import AgentsRepository
from agenttree.preflight import run_preflight
from agenttree.issues import update_issue_metadata, create_session


def prepare_git_mounts(
    runtime_name: str,
    share_git: bool,
    staging_dir: Path,
) -> list[str]:
    """Prepare mount arguments for sharing git credentials.

    Handles both regular file mounts (Docker) and directory mounts (Apple Container).
    Apple Container cannot mount individual files, so we stage .gitconfig in a directory.

    Args:
        runtime_name: Container runtime name ("container", "docker", "podman")
        share_git: Whether to share git credentials
        staging_dir: Directory to stage .gitconfig for Apple Container

    Returns:
        List of mount arguments (without -v prefix, e.g., ["~/.ssh:/home/agent/.ssh:ro"])
    """
    if not share_git:
        return []

    home = Path.home()
    mounts: list[str] = []

    # SSH directory
    ssh_dir = home / ".ssh"
    if ssh_dir.exists():
        mounts.append(f"{ssh_dir}:/home/agent/.ssh:ro")
        console.print("[dim]Sharing ~/.ssh (read-only)[/dim]")

    # Git config
    gitconfig = home / ".gitconfig"
    if gitconfig.exists():
        if runtime_name == "container":
            # Apple Container can only mount directories, not files.
            # Stage .gitconfig in a directory and mount that.
            gitconfig_staging = staging_dir / ".apple-container-gitconfig"
            gitconfig_staging.mkdir(exist_ok=True)
            shutil.copy2(gitconfig, gitconfig_staging / ".gitconfig")
            mounts.append(f"{gitconfig_staging}:/home/agent/.gitconfig-host:ro")
        else:
            mounts.append(f"{gitconfig}:/home/agent/.gitconfig:ro")
        console.print("[dim]Sharing ~/.gitconfig (read-only)[/dim]")

    return mounts


@click.command(name="start-agent", hidden=True)
@click.argument("issue_id", type=str)
@click.option("--tool", help="AI tool to use (default: from config)")
@click.option("--role", default="developer", help="Agent role (default: developer)")
@click.option("--force", is_flag=True, help="Force start even if agent already exists")
@click.option("--skip-preflight", is_flag=True, help="Skip preflight environment checks")
def start_agent(
    issue_id: str,
    tool: str | None,
    role: str,
    force: bool,
    skip_preflight: bool,
) -> None:
    """Start an agent for an issue (creates container + worktree).

    ISSUE_ID is the issue number (e.g., "23" or "023").

    This creates a dedicated agent for the issue with:
    - A new worktree (issue-023-slug/)
    - A new container (agenttree-{role}-023)
    - A tmux session for interaction

    The agent is automatically cleaned up when the issue is accepted.

    Use --role to start a non-default agent (e.g., --role reviewer for code review).
    """
    from agenttree.state import (
        get_active_agent,
        create_agent_for_issue,
        get_issue_names,
    )
    from agenttree.worktree import create_worktree, update_worktree_with_main
    from agenttree.cli.server import _start_manager

    repo_path = Path.cwd()
    config = load_config(repo_path)

    # Run preflight checks unless skipped
    if not skip_preflight:
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

    # Normalize issue ID (strip leading zeros for lookup, keep for display)
    issue_id_normalized = normalize_issue_id(issue_id)

    # Special handling for manager (agent 0)
    if issue_id_normalized == 0:
        _start_manager(tool, force, config, repo_path)
        return

    # Load issue from local _agenttree/issues/
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Error: Issue #{issue_id} not found in _agenttree/issues/[/red]")
        console.print(f"[yellow]Create it with: agenttree issue create 'title'[/yellow]")
        sys.exit(1)

    # If issue is in backlog, move it to explore.define stage first
    if issue.stage == "backlog":
        from agenttree.issues import update_issue_stage
        console.print(f"[cyan]Moving issue from backlog to explore.define...[/cyan]")
        update_issue_stage(issue.id, "explore.define")
        issue.stage = "explore.define"  # Update local reference

    # Check if issue already has an active agent for this role
    existing_agent = get_active_agent(issue.id, role)
    if existing_agent:
        if not force:
            console.print(f"[yellow]Issue #{issue.id} already has an active {role} agent[/yellow]")
            console.print(f"  Container: {existing_agent.container}")
            console.print(f"  Port: {existing_agent.port}")
            console.print(f"\nUse --force to replace it, or attach with:")
            console.print(f"  agenttree attach {issue.id}" + (f" --role {role}" if role != "developer" else ""))
            sys.exit(1)
        # --force: stop the existing agent via consolidated API
        from agenttree.api import stop_agent as api_stop_agent
        api_stop_agent(issue.id, role, quiet=True)
        console.print(f"[dim]Stopped existing {role} agent[/dim]")

    # Initialize managers
    tmux_manager = TmuxManager(config)
    agents_repo = AgentsRepository(repo_path)

    # Ensure agents repo exists
    agents_repo.ensure_repo()

    # Get names for this issue and role
    names = get_issue_names(issue.id, config.project, role)

    # Create worktree for issue
    worktree_path = config.get_issue_worktree_path(issue.id)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    has_merge_conflicts = False
    is_restart = False
    if worktree_path.exists():
        # Worktree exists - this is a restart scenario
        is_restart = True
        # Update with latest main to get newest CLI code while preserving agent's work
        console.print(f"[cyan]Restarting: Rebasing worktree onto latest main...[/cyan]")
        update_success = update_worktree_with_main(worktree_path)
        if update_success:
            console.print(f"[green]✓ Worktree rebased successfully[/green]")
        else:
            has_merge_conflicts = True
            console.print(f"[yellow]⚠ Merge conflicts detected - agent will need to resolve[/yellow]")
    else:
        # No worktree - check if branch exists (agent worked on this before but worktree was removed)
        branch_exists = subprocess.run(
            ["git", "rev-parse", "--verify", names["branch"]],
            cwd=repo_path,
            capture_output=True,
        ).returncode == 0

        if branch_exists:
            # Branch exists - create worktree from it, then update with main
            is_restart = True
            console.print(f"[dim]Restarting from existing branch: {names['branch']}[/dim]")
            create_worktree(repo_path, worktree_path, names["branch"])
            console.print(f"[cyan]Rebasing onto latest main...[/cyan]")
            update_success = update_worktree_with_main(worktree_path)
            if update_success:
                console.print(f"[green]✓ Worktree rebased successfully[/green]")
            else:
                has_merge_conflicts = True
                console.print(f"[yellow]⚠ Merge conflicts detected - agent will need to resolve[/yellow]")
        else:
            # Fresh start - create new worktree from main
            console.print(f"[dim]Creating worktree: {worktree_path.name}[/dim]")
            create_worktree(repo_path, worktree_path, names["branch"])

    # Get deterministic port from issue number
    port = config.get_port_for_issue(issue.id)
    console.print(f"[dim]Using port: {port} (derived from issue #{issue.id})[/dim]")

    # Register agent in state
    agent = create_agent_for_issue(
        issue_id=issue.id,
        worktree_path=worktree_path,
        port=port,
        project=config.project,
        role=role,
    )

    # Save branch and worktree info to issue metadata
    update_issue_metadata(issue.id, branch=names["branch"], worktree_dir=str(worktree_path))

    role_label = format_role_label(role)
    console.print(f"[green]✓ Starting agent{role_label} for issue #{issue.id}: {issue.title}[/green]")

    # Create session for restart detection
    create_session(issue.id)

    # Start agent in tmux (always in container)
    tool_name = tool or config.default_tool
    # Resolve model: dot_path → role → default
    model_name = config.model_for(issue.stage, role=role)
    runtime = get_container_runtime()

    if not runtime.is_available():
        console.print(f"[red]Error: No container runtime available[/red]")
        console.print(f"Recommendation: {runtime.get_recommended_action()}")
        sys.exit(1)

    console.print(f"[dim]Container runtime: {runtime.get_runtime_name()}[/dim]")
    console.print(f"[dim]Model: {model_name}[/dim]")

    start_success = tmux_manager.start_issue_agent_in_container(
        issue_id=issue.id,
        session_name=agent.tmux_session,
        worktree_path=worktree_path,
        tool_name=tool_name,
        container_runtime=runtime,
        model=model_name,
        role=role,
        has_merge_conflicts=has_merge_conflicts,
        is_restart=is_restart,
    )

    if not start_success:
        # Startup failed - clean up state and exit
        from agenttree.state import unregister_agent
        unregister_agent(issue.id, role)
        console.print(f"[red]Error: Agent failed to start (Claude prompt not detected within timeout)[/red]")
        console.print(f"[dim]State has been cleaned up. Try running 'agenttree start {issue.id}' again.[/dim]")
        sys.exit(1)

    console.print(f"[green]✓ Started {tool_name} in container[/green]")

    # Note: Container tracking is now handled dynamically by the state system

    console.print(f"\n[bold]Agent{role_label} ready for issue #{issue.id}[/bold]")
    console.print(f"  Container: {agent.container}")
    console.print(f"  Port: {agent.port}")
    console.print(f"  Role: {role}")
    console.print(f"\n[dim]Commands:[/dim]")
    role_flag = f" --role {role}" if role != "developer" else ""
    console.print(f"  agenttree attach {issue.id}{role_flag}")
    console.print(f"  agenttree send {issue.id}{role_flag} 'message'")
    console.print(f"  agenttree agents")


@click.command("agents")
def agents_status() -> None:
    """Show status of all active issue agents."""
    from agenttree.state import list_active_agents
    from agenttree.tmux import session_exists
    from agenttree.ids import serve_session_name

    config = load_config()
    tmux_manager = TmuxManager(config)

    agents = list_active_agents()

    if not agents:
        console.print("[dim]No active agents[/dim]")
        console.print("\nStart an agent with:")
        console.print("  agenttree start <issue_id>")
        return

    table = Table(title="Active Agents")
    table.add_column("ID", style="bold cyan")
    table.add_column("Role", style="blue")
    table.add_column("Title", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Dev Server", style="green")
    table.add_column("Branch", style="yellow")

    for agent in agents:
        # Check if tmux session is running
        is_running = tmux_manager.is_issue_running(agent.tmux_session)

        # Get issue info
        issue = get_issue_func(agent.issue_id)
        issue_title = issue.title[:30] if issue else "Unknown"

        # Determine status
        if is_running:
            status_str = "🟢 Running"
        else:
            status_str = "⚪ Stopped"

        # Check if serve session is running and show dev server URL
        serve_session = serve_session_name(config.project, agent.issue_id)
        if session_exists(serve_session):
            dev_server_url = config.get_dev_server_url(agent.issue_id)
            # Show with green color indicator
            dev_server_str = f"[link={dev_server_url}]{dev_server_url}[/link]"
        elif agent.port:
            # Port configured but serve session not running
            dev_server_str = f"[dim]:{agent.port}[/dim]"
        else:
            dev_server_str = "[dim]-[/dim]"

        table.add_row(
            str(agent.issue_id),
            agent.role,
            issue_title,
            status_str,
            dev_server_str,
            agent.branch[:20],
        )

    console.print(table)
    console.print(f"\n[dim]Commands (use ID from table above, add --role if not 'developer'):[/dim]")
    console.print(f"  agenttree attach <id> [--role <role>]")
    console.print(f"  agenttree send <id> [--role <role>] 'message'")
    console.print(f"  agenttree stop <id> [--role <role>]")



@click.command()
@click.argument("issue_id", type=str)
@click.option("--role", default="developer", help="Agent role (default: developer)")
def attach(issue_id: str, role: str) -> None:
    """Attach to an issue's agent tmux session.

    ISSUE_ID is the issue number (e.g., "23" or "023"), or "0" for manager.
    """
    from agenttree.state import get_active_agent
    from agenttree.tmux import session_exists, attach_session

    config = load_config()
    tmux_manager = TmuxManager(config)

    # Normalize issue ID
    issue_id_normalized = normalize_issue_id(issue_id)

    # Special handling for manager (agent 0)
    if issue_id_normalized == 0:
        session_name = require_manager_running(config)
        console.print("Attaching to manager (Ctrl+B, D to detach)...")
        attach_session(session_name)
        return

    # Get active agent for this issue and role
    agent = get_active_agent(issue_id_normalized, role)
    if not agent:
        # Try with padded ID
        issue = get_issue_func(issue_id_normalized)
        if issue:
            agent = get_active_agent(issue.id, role)

    if not agent:
        role_label = format_role_label(role)
        console.print(f"[red]Error: No active{role_label} agent for issue #{issue_id}[/red]")
        role_flag = f" --role {role}" if role != "developer" else ""
        console.print(f"[yellow]Start one with: agenttree start {issue_id}{role_flag}[/yellow]")
        sys.exit(1)

    try:
        role_label = format_role_label(agent.role)
        console.print(f"Attaching to issue #{agent.issue_id}{role_label} (Ctrl+B, D to detach)...")
        tmux_manager.attach_to_issue(agent.tmux_session)
    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@click.command()
@click.argument("issue_id", type=str)
@click.option("--role", default="developer", help="Agent role (default: developer)")
@click.option("--lines", "-n", default=50, help="Number of lines to show (default: 50)")
def output(issue_id: str, role: str, lines: int) -> None:
    """Show recent output from an agent's tmux session.

    ISSUE_ID is the issue number (e.g., "23" or "023"), or "0" for manager.

    Examples:
        agenttree output 137        # Show last 50 lines from agent #137
        agenttree output 0          # Show manager output
        agenttree output 137 -n 100 # Show last 100 lines
    """
    from agenttree.state import get_active_agent
    from agenttree.tmux import session_exists, capture_pane

    config = load_config()

    # Normalize issue ID
    issue_id_normalized = normalize_issue_id(issue_id)

    # Special handling for manager (agent 0)
    if issue_id_normalized == 0:
        session_name = require_manager_running(config, hint=False)
        output_text = capture_pane(session_name, lines=lines)
        console.print(output_text)
        return

    # Get active agent for this issue and role
    agent = get_active_agent(issue_id_normalized, role)
    if not agent:
        # Try with padded ID
        issue = get_issue_func(issue_id_normalized)
        if issue:
            agent = get_active_agent(issue.id, role)

    if not agent:
        role_label = format_role_label(role)
        console.print(f"[red]Error: No active{role_label} agent for issue #{issue_id}[/red]")
        sys.exit(1)

    if not session_exists(agent.tmux_session):
        console.print(f"[red]Error: Tmux session '{agent.tmux_session}' not found[/red]")
        sys.exit(1)

    output_text = capture_pane(agent.tmux_session, lines=lines)
    console.print(output_text)


@click.command()
@click.argument("issue_id", type=str)
@click.argument("message")
@click.option("--role", default="developer", help="Agent role (default: developer)")
@click.option("--interrupt", is_flag=True, help="Send Ctrl+C first to interrupt current task")
def send(issue_id: str, message: str, role: str, interrupt: bool) -> None:
    """Send a message to an issue's agent.

    ISSUE_ID is the issue number (e.g., "23" or "023"), or "0" for manager.

    If the agent is not running, it will be automatically started.

    Use --interrupt to stop the agent's current task (sends Ctrl+C) before sending.
    """
    from agenttree.state import get_active_agent
    from agenttree.tmux import session_exists, send_message

    config = load_config()
    tmux_manager = TmuxManager(config)

    # Normalize issue ID
    issue_id_normalized = normalize_issue_id(issue_id)

    # Special handling for manager (agent 0)
    if issue_id_normalized == 0:
        session_name = require_manager_running(config)
        result = send_message(session_name, message, interrupt=interrupt)
        if result != "sent":
            console.print(f"[red]Error: Failed to send to manager ({result})[/red]")
            sys.exit(1)
        console.print("[green]✓ Sent message to manager[/green]")
        return

    # Get issue to validate it exists
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Error: Issue #{issue_id} not found[/red]")
        sys.exit(1)

    # Use the canonical issue ID
    issue_id_normalized = issue.id

    # Helper to start agent if needed
    def ensure_agent_running() -> bool:
        """Start agent if not running. Returns True if agent is now running."""
        agent = get_active_agent(issue_id_normalized, role)
        if agent and tmux_manager.is_issue_running(agent.tmux_session):
            return True

        # Agent not running - start it
        role_label = format_role_label(role)
        console.print(f"[dim]Agent{role_label} not running, starting...[/dim]")

        result = subprocess.run(
            ["agenttree", "start", str(issue_id_normalized)] + (["--role", role] if role != "developer" else []) + ["--skip-preflight"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print(f"[red]Error: Could not start agent: {result.stderr}[/red]")
            return False

        console.print(f"[green]✓ Started agent{role_label}[/green]")
        return True

    # Ensure agent is running
    if not ensure_agent_running():
        sys.exit(1)

    # Re-fetch agent after potential start
    agent = get_active_agent(issue_id_normalized, role)
    if not agent:
        console.print(f"[red]Error: Agent started but not found in state[/red]")
        sys.exit(1)

    # Send the message
    result = tmux_manager.send_message_to_issue(agent.tmux_session, message, interrupt=interrupt)

    role_label = format_role_label(agent.role)
    if result == "sent":
        console.print(f"[green]✓ Sent message to issue #{agent.issue_id}{role_label}[/green]")
    elif result == "claude_exited":
        # Claude exited - restart and try again
        console.print(f"[yellow]Claude CLI exited, restarting agent...[/yellow]")
        if ensure_agent_running():
            agent = get_active_agent(issue_id_normalized, role)
            if agent:
                result = tmux_manager.send_message_to_issue(agent.tmux_session, message, interrupt=interrupt)
                if result == "sent":
                    console.print(f"[green]✓ Sent message to issue #{agent.issue_id}{role_label}[/green]")
                    return
        console.print(f"[red]Error: Could not send message after restart[/red]")
        sys.exit(1)
    elif result == "no_session":
        console.print(f"[red]Error: Tmux session not found[/red]")
        sys.exit(1)
    else:
        console.print(f"[red]Error: Failed to send message[/red]")
        sys.exit(1)


@click.command()
@click.argument("issue_id", type=str)
@click.option("--role", default="developer", help="Agent role (default: developer)")
@click.option("--all", "all_roles", is_flag=True, help="Stop all agents for this issue (all roles)")
def stop(issue_id: str, role: str, all_roles: bool) -> None:
    """Stop an issue's agent (kills tmux, stops container, cleans up state).

    ISSUE_ID is the issue number (e.g., "23" or "023"), or "0" for manager.

    Examples:
        agenttree stop 23              # Stop the default agent for issue 23
        agenttree stop 23 --role reviewer  # Stop the review agent
        agenttree stop 23 --all        # Stop all agents for issue 23
    """
    from agenttree.state import get_active_agent
    from agenttree.api import stop_agent, stop_all_agents_for_issue
    from agenttree.tmux import session_exists, kill_session

    config = load_config()

    # Normalize issue ID
    issue_id_normalized = normalize_issue_id(issue_id)

    # Special handling for manager (agent 0)
    if issue_id_normalized == 0:
        session_name = get_manager_session_if_running(config)
        if not session_name:
            console.print("[yellow]Manager not running[/yellow]")
            return
        kill_session(session_name)
        console.print("[green]✓ Stopped manager[/green]")
        return

    # Stop all agents for this issue if --all flag
    if all_roles:
        count = stop_all_agents_for_issue(issue_id_normalized)
        if count == 0:
            console.print(f"[yellow]No active agents for issue #{issue_id}[/yellow]")
        return

    # Try with normalized ID first, then try getting the issue
    issue = get_issue_func(issue_id_normalized)
    actual_id = issue.id if issue else issue_id_normalized

    # Check if agent exists
    agent = get_active_agent(actual_id, role)
    if not agent:
        role_label = format_role_label(role)
        console.print(f"[red]Error: No active{role_label} agent for issue #{issue_id}[/red]")
        sys.exit(1)

    # Use consolidated stop_agent function
    stop_agent(actual_id, role)


@click.command(name="new")
@click.argument("container_type", type=str)
@click.argument("name", type=str)
@click.option("--tool", help="AI tool to use (default: from config)")
@click.option("--share-git/--no-share-git", default=True, help="Share ~/.ssh and ~/.gitconfig (default: true)")
@click.option("--kill", is_flag=True, help="Kill the container instead of starting")
@click.option("--list", "list_containers", is_flag=True, help="List all containers of this type")
def new_container(
    container_type: str,
    name: str,
    tool: str | None,
    share_git: bool,
    kill: bool,
    list_containers: bool,
) -> None:
    """Create a new container from a configured type.

    CONTAINER_TYPE is the container type from config (e.g., "sandbox", "data-science").
    NAME is a unique name for this container instance.

    Container types are defined in .agenttree.yaml under 'containers:'. Each type
    can specify image, mounts, env vars, sessions, and lifecycle hooks.

    Examples:
        agenttree new sandbox my-sandbox           # Start a sandbox container
        agenttree new sandbox my-sandbox --kill    # Stop the container
        agenttree new data-science analysis-1      # Start a data science container
        agenttree new sandbox x --list             # List all sandbox containers

    If no containers are configured, creates a default sandbox container using
    the agenttree-agent image with the default AI tool.
    """
    from agenttree.config import ContainerTypeConfig, resolve_container_type
    from agenttree.container import build_container_command
    from agenttree.ids import container_type_session_name
    from agenttree.tmux import (
        session_exists,
        attach_session,
        kill_session,
        create_session,
        list_sessions,
        wait_for_prompt,
        send_keys,
    )

    config = load_config()
    runtime = get_container_runtime()

    # List containers of this type
    if list_containers:
        prefix = f"{config.project}-{container_type}-"
        sessions = [s for s in list_sessions() if s.name.startswith(prefix)]
        if not sessions:
            console.print(f"[yellow]No {container_type} containers running[/yellow]")
        else:
            console.print(f"[bold]Running {container_type} containers:[/bold]")
            for session in sessions:
                # Extract the name from the session (e.g., "myproject-sandbox-foo" -> "foo")
                instance_name = session.name[len(prefix):]
                console.print(f"  • {instance_name}")
        return

    # Generate session name
    session_name = container_type_session_name(config.project, container_type, name)

    # Kill mode
    if kill:
        if session_exists(session_name):
            kill_session(session_name)
            console.print(f"[green]✓ Killed {container_type} '{name}'[/green]")
        else:
            console.print(f"[yellow]{container_type.capitalize()} '{name}' not running[/yellow]")
        return

    # Attach to existing container
    if session_exists(session_name):
        console.print(f"[cyan]Attaching to existing {container_type} '{name}' (Ctrl+B, D to detach)...[/cyan]")
        attach_session(session_name)
        return

    # Check runtime
    if not runtime.is_available():
        console.print("[red]Error: No container runtime available[/red]")
        console.print(f"Recommendation: {runtime.get_recommended_action()}")
        sys.exit(1)

    console.print(f"[cyan]Starting {container_type} '{name}'...[/cyan]")
    console.print(f"[dim]Container runtime: {runtime.get_runtime_name()}[/dim]")

    # Ensure container system is running
    runtime.ensure_system_running()

    # Get container type config
    if container_type in config.containers:
        resolved_type = resolve_container_type(container_type, config.containers)
    else:
        console.print(f"[red]Error: Unknown container type '{container_type}'[/red]")
        console.print("[dim]Define it in .agenttree.yaml under 'containers:'[/dim]")
        if config.containers:
            console.print(f"[dim]Available types: {', '.join(config.containers.keys())}[/dim]")
        sys.exit(1)

    # Build container command
    repo_path = Path.cwd()

    # Add user mounts for git sharing using shared helper
    git_mounts = prepare_git_mounts(
        runtime_name=runtime.get_runtime_name(),
        share_git=share_git,
        staging_dir=repo_path,
    )

    if git_mounts:
        resolved_type = ContainerTypeConfig(
            image=resolved_type.image,
            mounts=list(resolved_type.mounts) + git_mounts,
            env=dict(resolved_type.env),
            allow_dangerous=resolved_type.allow_dangerous,
        )

    # Get tool config
    tool_name = tool or config.default_tool
    tool_config = config.get_tool_config(tool_name)
    container_name_str = f"agenttree-{config.project}-{container_type}-{name}"

    cmd = build_container_command(
        runtime=runtime.runtime or "docker",
        worktree_path=repo_path,
        container_type=resolved_type,
        container_name=container_name_str,
        tool_config=tool_config,
        role=container_type,  # Use container type as role
        model=config.default_model,
    )
    cmd_str = " ".join(cmd)

    # Create tmux session running the container
    create_session(session_name, repo_path, cmd_str)
    console.print(f"[green]✓ Started {container_type} '{name}'[/green]")

    # Wait for prompt and send a friendly message
    if wait_for_prompt(session_name, prompt_char="❯", timeout=30.0):
        send_keys(session_name, f"echo '{container_type.capitalize()} ready! Working in {repo_path.name}.'")

    console.print(f"\n[bold]{container_type.capitalize()} '{name}' ready[/bold]")
    console.print("\n[dim]Commands:[/dim]")
    console.print(f"  agenttree new {container_type} {name}        # Attach")
    console.print(f"  agenttree new {container_type} {name} --kill # Stop")
    console.print(f"  agenttree new {container_type} x --list      # List all")

    # Auto-attach
    console.print("\n[cyan]Attaching... (Ctrl+B, D to detach)[/cyan]")
    attach_session(session_name)

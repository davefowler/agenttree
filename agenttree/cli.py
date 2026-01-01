"""CLI for AgentTree."""

import sys
from pathlib import Path
from typing import Optional
import click
from rich.console import Console
from rich.table import Table

from agenttree.config import load_config
from agenttree.worktree import WorktreeManager
from agenttree.tmux import TmuxManager
from agenttree.github import GitHubManager, get_issue, ensure_gh_cli
from agenttree.container import get_container_runtime
from agenttree.agents_repo import AgentsRepository

console = Console()


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """AgentTree: Multi-Agent Development Framework

    Orchestrate multiple AI coding agents across git worktrees.
    """
    pass


@main.command()
@click.option(
    "--worktrees-dir",
    type=click.Path(),
    help="Directory for worktrees (default: ~/Projects/worktrees)",
)
@click.option("--project", help="Project name for tmux sessions")
def init(worktrees_dir: Optional[str], project: Optional[str]) -> None:
    """Initialize AgentTree in the current repository."""
    repo_path = Path.cwd()

    # Check if we're in a git repo
    if not (repo_path / ".git").exists():
        console.print("[red]Error: Not a git repository[/red]")
        sys.exit(1)

    config_file = repo_path / ".agenttree.yaml"

    if config_file.exists():
        console.print("[yellow]Warning: .agenttree.yaml already exists[/yellow]")
        if not click.confirm("Overwrite?"):
            return

    # Determine project name
    if not project:
        project = repo_path.name

    # Create config
    config_data = {
        "project": project,
        "worktrees_dir": worktrees_dir or "~/Projects/worktrees",
        "port_range": "8001-8009",
        "default_tool": "claude",
        "tools": {
            "claude": {
                "command": "claude",
                "startup_prompt": "Check TASK.md and start working on it.",
            },
            "aider": {
                "command": "aider --model sonnet",
                "startup_prompt": "/read TASK.md",
            },
        },
    }

    import yaml

    with open(config_file, "w") as f:
        yaml.dump(config_data, f, default_flow_style=False)

    console.print(f"[green]✓ Created {config_file}[/green]")

    # Initialize agents repository
    console.print("\n[cyan]Initializing agents repository...[/cyan]")
    try:
        ensure_gh_cli()
        agents_repo = AgentsRepository(repo_path)
        agents_repo.ensure_repo()
        console.print("[green]✓ Agents repository created[/green]")
    except RuntimeError as e:
        console.print(f"[yellow]Warning: Could not create agents repository:[/yellow]")
        console.print(f"  {e}")
        console.print("\n[yellow]You can create it later by running 'agenttree init' again[/yellow]")

    console.print("\nNext steps:")
    console.print("  1. agenttree setup 1 2 3    # Set up agent worktrees")
    console.print("  2. agenttree dispatch 1 42  # Dispatch issue #42 to agent-1")


@main.command()
@click.argument("agent_numbers", nargs=-1, type=int, required=True)
def setup(agent_numbers: tuple) -> None:
    """Set up worktrees for agents."""
    repo_path = Path.cwd()
    config = load_config(repo_path)

    manager = WorktreeManager(repo_path, config)

    for agent_num in agent_numbers:
        try:
            console.print(f"Setting up agent-{agent_num}...")
            worktree_path = manager.setup_agent(agent_num)

            # Create .env file with agent-specific PORT
            env_file = worktree_path / ".env"
            port = config.get_port_for_agent(agent_num)

            if (repo_path / ".env").exists():
                import shutil

                shutil.copy(repo_path / ".env", env_file)

            # Update or add PORT
            if env_file.exists():
                with open(env_file, "r") as f:
                    lines = f.readlines()

                with open(env_file, "w") as f:
                    port_written = False
                    for line in lines:
                        if line.startswith("PORT="):
                            f.write(f"PORT={port}\n")
                            port_written = True
                        else:
                            f.write(line)

                    if not port_written:
                        f.write(f"PORT={port}\n")
            else:
                with open(env_file, "w") as f:
                    f.write(f"PORT={port}\n")

            console.print(f"[green]✓ Agent {agent_num} ready at {worktree_path}[/green]")
        except Exception as e:
            console.print(f"[red]✗ Failed to set up agent {agent_num}: {e}[/red]")


@main.command()
@click.argument("agent_num", type=int)
@click.argument("issue_number", type=int, required=False)
@click.option("--task", help="Ad-hoc task description")
@click.option("--tool", help="AI tool to use (default: from config)")
@click.option("--force", is_flag=True, help="Force dispatch even if agent is busy")
@click.option(
    "--container", is_flag=True, help="Run agent in container (isolated mode)"
)
@click.option(
    "--dangerous",
    is_flag=True,
    help="Run in dangerous mode (skip permissions, requires --container)",
)
def dispatch(
    agent_num: int,
    issue_number: Optional[int],
    task: Optional[str],
    tool: Optional[str],
    force: bool,
    container: bool,
    dangerous: bool,
) -> None:
    """Dispatch a task to an agent."""
    repo_path = Path.cwd()
    config = load_config(repo_path)

    if dangerous and not container:
        console.print(
            "[red]Error: --dangerous requires --container for safety[/red]"
        )
        sys.exit(1)

    if not issue_number and not task:
        console.print("[red]Error: Provide either issue number or --task[/red]")
        sys.exit(1)

    # Get worktree path
    worktree_path = config.get_worktree_path(agent_num)

    if not worktree_path.exists():
        console.print(
            f"[red]Error: Agent {agent_num} not set up. Run: agenttree setup {agent_num}[/red]"
        )
        sys.exit(1)

    # Initialize managers
    wt_manager = WorktreeManager(repo_path, config)
    tmux_manager = TmuxManager(config)
    gh_manager = GitHubManager()
    agents_repo = AgentsRepository(repo_path)

    # Ensure agents repo exists
    agents_repo.ensure_repo()

    # Dispatch worktree (reset to main)
    try:
        wt_manager.dispatch(agent_num, force=force)
    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    # Create TASK.md
    task_file = worktree_path / "TASK.md"

    if issue_number:
        try:
            issue = get_issue(issue_number)
            gh_manager.create_task_file(issue, task_file)
            gh_manager.assign_issue_to_agent(issue_number, agent_num)

            # Create spec and task log in agents/ repo
            agents_repo.create_spec_file(
                issue_number, issue.title, issue.body, issue.url
            )
            agents_repo.create_task_file(
                agent_num, issue_number, issue.title, issue.body, issue.url
            )

            console.print(f"[green]✓ Created task for issue #{issue_number}[/green]")
            console.print(f"[green]✓ Created spec and task log in agents/ repo[/green]")
        except Exception as e:
            console.print(f"[red]Error fetching issue: {e}[/red]")
            sys.exit(1)
    else:
        gh_manager.create_adhoc_task_file(task or "", task_file)
        console.print("[green]✓ Created ad-hoc task[/green]")

    # Start agent in tmux
    tool_name = tool or config.default_tool

    if container:
        runtime = get_container_runtime()
        if not runtime.is_available():
            console.print(f"[red]Error: No container runtime available[/red]")
            console.print(f"Recommendation: {runtime.get_recommended_action()}")
            sys.exit(1)

        console.print(f"[yellow]Running in container ({runtime.get_runtime_name()})[/yellow]")
        # TODO: Integrate container mode with tmux
        console.print("[yellow]Container mode integration coming soon[/yellow]")
    else:
        tmux_manager.start_agent(agent_num, worktree_path, tool_name)
        console.print(f"[green]✓ Started {tool_name} in tmux session[/green]")

    console.print(f"\nCommands:")
    console.print(f"  agenttree attach {agent_num}  # Attach to session")
    console.print(f"  agenttree status             # View all agents")


@main.command()
def status() -> None:
    """Show status of all agents."""
    repo_path = Path.cwd()
    config = load_config(repo_path)

    wt_manager = WorktreeManager(repo_path, config)
    tmux_manager = TmuxManager(config)

    table = Table(title="Agent Status")
    table.add_column("Agent", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Task", style="green")
    table.add_column("Branch", style="yellow")

    # Check agents 1-9 by default
    for agent_num in range(1, 10):
        worktree_path = config.get_worktree_path(agent_num)

        if not worktree_path.exists():
            continue

        status = wt_manager.get_status(agent_num)
        is_running = tmux_manager.is_running(agent_num)

        # Determine status emoji
        if is_running and status.is_busy:
            status_str = "🔴 Busy"
        elif status.is_busy:
            status_str = "🟡 Has task"
        elif is_running:
            status_str = "🟢 Running"
        else:
            status_str = "⚪ Available"

        # Get task description
        task_desc = ""
        if status.has_task:
            task_file = worktree_path / "TASK.md"
            with open(task_file) as f:
                first_line = f.readline().strip()
                task_desc = first_line.replace("# Task: ", "").replace("# Task", "")[:50]

        table.add_row(f"Agent {agent_num}", status_str, task_desc, status.branch)

    console.print(table)


@main.command()
@click.argument("agent_num", type=int)
def attach(agent_num: int) -> None:
    """Attach to an agent's tmux session."""
    config = load_config()
    tmux_manager = TmuxManager(config)

    try:
        console.print(f"Attaching to agent-{agent_num} (Ctrl+B, D to detach)...")
        tmux_manager.attach(agent_num)
    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@main.command()
@click.argument("agent_num", type=int)
@click.argument("message")
def send(agent_num: int, message: str) -> None:
    """Send a message to an agent."""
    config = load_config()
    tmux_manager = TmuxManager(config)

    if not tmux_manager.is_running(agent_num):
        console.print(f"[red]Error: Agent {agent_num} is not running[/red]")
        sys.exit(1)

    tmux_manager.send_message(agent_num, message)
    console.print(f"[green]✓ Sent message to agent-{agent_num}[/green]")


@main.command()
@click.argument("agent_num", type=int)
def kill(agent_num: int) -> None:
    """Kill an agent's tmux session."""
    config = load_config()
    tmux_manager = TmuxManager(config)

    tmux_manager.stop_agent(agent_num)
    console.print(f"[green]✓ Killed agent-{agent_num}[/green]")


@main.group()
def notes() -> None:
    """Manage agents repository notes and documentation."""
    pass


@notes.command("show")
@click.argument("agent_num", type=int)
def notes_show(agent_num: int) -> None:
    """Show task logs for an agent."""
    repo_path = Path.cwd()
    agents_repo = AgentsRepository(repo_path)

    agent_dir = agents_repo.agents_path / "tasks" / f"agent-{agent_num}"

    if not agent_dir.exists():
        console.print(f"[yellow]No tasks found for agent-{agent_num}[/yellow]")
        return

    task_files = sorted(agent_dir.glob("*.md"), reverse=True)

    if not task_files:
        console.print(f"[yellow]No tasks found for agent-{agent_num}[/yellow]")
        return

    console.print(f"\n[cyan]Tasks for agent-{agent_num}:[/cyan]\n")
    for task_file in task_files:
        console.print(f"  • {task_file.name}")

    console.print(f"\n[dim]View task: cat agents/tasks/agent-{agent_num}/<filename>[/dim]")


@notes.command("search")
@click.argument("query")
def notes_search(query: str) -> None:
    """Search all notes for a query."""
    repo_path = Path.cwd()
    agents_repo = AgentsRepository(repo_path)

    if not agents_repo.agents_path.exists():
        console.print("[yellow]Agents repository not initialized[/yellow]")
        return

    console.print(f"\n[cyan]Searching for '{query}'...[/cyan]\n")

    import subprocess

    # Use ripgrep or grep to search
    try:
        result = subprocess.run(
            ["rg", "-i", query, str(agents_repo.agents_path)],
            capture_output=True,
            text=True,
        )
        if result.stdout:
            console.print(result.stdout)
        else:
            console.print("[yellow]No results found[/yellow]")
    except FileNotFoundError:
        # Fallback to grep
        result = subprocess.run(
            ["grep", "-ri", query, str(agents_repo.agents_path)],
            capture_output=True,
            text=True,
        )
        if result.stdout:
            console.print(result.stdout)
        else:
            console.print("[yellow]No results found[/yellow]")


@notes.command("archive")
@click.argument("agent_num", type=int)
def notes_archive(agent_num: int) -> None:
    """Archive completed tasks for an agent."""
    repo_path = Path.cwd()
    agents_repo = AgentsRepository(repo_path)

    agents_repo.archive_task(agent_num)
    console.print(f"[green]✓ Archived completed task for agent-{agent_num}[/green]")


if __name__ == "__main__":
    main()

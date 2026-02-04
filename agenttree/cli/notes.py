"""Notes management commands."""

import subprocess
from pathlib import Path

import click

from agenttree.agents_repo import AgentsRepository
from agenttree.cli.common import console


@click.group()
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

    console.print(f"\n[dim]View task: cat _agenttree/tasks/agent-{agent_num}/<filename>[/dim]")


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

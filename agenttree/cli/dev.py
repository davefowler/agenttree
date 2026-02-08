"""Development commands (test, lint, sync)."""

import subprocess
import sys

import click

from agenttree.cli._utils import console, load_config


@click.command()
@click.argument("extra_args", nargs=-1)
def test(extra_args: tuple[str, ...]) -> None:
    """Run the project's test commands.

    Uses commands.test from .agenttree.yaml config.
    Runs all commands and reports all errors (doesn't stop on first failure).
    """
    config = load_config()
    test_cmd = config.commands.get("test")

    if not test_cmd:
        console.print("[red]Error: test command not configured[/red]")
        console.print("\nAdd to .agenttree.yaml:")
        console.print("  commands:")
        console.print("    test: pytest")
        sys.exit(1)

    # Normalize to list
    commands = test_cmd if isinstance(test_cmd, list) else [test_cmd]

    failed = []
    for cmd in commands:
        # Append extra arguments to each command
        if extra_args:
            cmd = f"{cmd} {' '.join(extra_args)}"

        console.print(f"[dim]Running: {cmd}[/dim]")
        result = subprocess.run(cmd, shell=True)

        if result.returncode != 0:
            failed.append(cmd)

    if failed:
        console.print(f"\n[red]Failed commands ({len(failed)}/{len(commands)}):[/red]")
        for cmd in failed:
            console.print(f"  - {cmd}")
        sys.exit(1)

    console.print(f"\n[green]All {len(commands)} test command(s) passed[/green]")


@click.command()
@click.argument("extra_args", nargs=-1)
def lint(extra_args: tuple[str, ...]) -> None:
    """Run the project's lint commands.

    Uses commands.lint from .agenttree.yaml config.
    Runs all commands and reports all errors (doesn't stop on first failure).
    """
    config = load_config()
    lint_cmd = config.commands.get("lint")

    if not lint_cmd:
        console.print("[red]Error: lint command not configured[/red]")
        console.print("\nAdd to .agenttree.yaml:")
        console.print("  commands:")
        console.print("    lint: ruff check .")
        sys.exit(1)

    # Normalize to list
    commands = lint_cmd if isinstance(lint_cmd, list) else [lint_cmd]

    failed = []
    for cmd in commands:
        # Append extra arguments to each command
        if extra_args:
            cmd = f"{cmd} {' '.join(extra_args)}"

        console.print(f"[dim]Running: {cmd}[/dim]")
        result = subprocess.run(cmd, shell=True)

        if result.returncode != 0:
            failed.append(cmd)

    if failed:
        console.print(f"\n[red]Failed commands ({len(failed)}/{len(commands)}):[/red]")
        for cmd in failed:
            console.print(f"  - {cmd}")
        sys.exit(1)

    console.print(f"\n[green]All {len(commands)} lint command(s) passed[/green]")


@click.command("sync")
def sync_command() -> None:
    """Force sync with agents repository.

    This command:
    1. Pushes any pending branches to remote
    2. Creates PRs for issues at implementation_review that don't have PRs
    3. Detects PRs that were merged externally and advances issues to accepted

    Sync happens automatically on most agenttree commands, but use this
    to force it immediately (e.g., right after an agent finishes).

    Example:
        agenttree sync
    """
    from agenttree.agents_repo import sync_agents_repo
    from agenttree.manager_hooks import run_post_manager_hooks
    from agenttree.issues import get_agenttree_path

    console.print("[dim]Syncing agents repository...[/dim]")
    agents_path = get_agenttree_path()
    success = sync_agents_repo(agents_path)

    if success:
        console.print("[green]✓ Sync complete[/green]")
    else:
        console.print("[yellow]Sync completed with warnings[/yellow]")

    # Run manager hooks (stall detection, CI checks, etc.)
    console.print("[dim]Running manager hooks...[/dim]")
    run_post_manager_hooks(agents_path)

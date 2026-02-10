"""Centralized API for high-level agent operations.

This module consolidates operations that coordinate between tmux, container, and config
systems. It provides a single source of truth for operations like stopping agents
and cleaning up containers.

Functions moved here from state.py to eliminate duplication and inconsistencies.
"""

import time
from typing import Optional

from agenttree.config import load_config
from agenttree.container import get_container_runtime
from agenttree.tmux import kill_session, session_exists


def stop_agent(issue_id: str, role: str = "developer", quiet: bool = False) -> bool:
    """Stop an active agent - kills tmux and stops container.

    Uses config methods to ensure consistent naming across the system.

    Args:
        issue_id: Issue ID to stop
        role: Agent role (default: "developer")
        quiet: If True, suppress output messages

    Returns:
        True if something was stopped, False if nothing to stop
    """
    config = load_config()
    stopped_something = False

    if not quiet:
        from rich.console import Console
        console = Console()

    # 1. Kill serve session (if it exists) - runs on host, not in container
    try:
        serve_session_name = f"{config.project}-serve-{issue_id}"
        if session_exists(serve_session_name):
            kill_session(serve_session_name)
            stopped_something = True
            if not quiet:
                console.print(f"[dim]  Stopped serve session: {serve_session_name}[/dim]")
    except Exception as e:
        if not quiet:
            console.print(f"[yellow]  Warning: Could not stop serve session: {e}[/yellow]")

    # 2. Kill tmux session if it exists
    try:
        session_name = config.get_issue_tmux_session(issue_id, role)
        if session_exists(session_name):
            kill_session(session_name)
            stopped_something = True
            if not quiet:
                console.print(f"[dim]  Stopped tmux session: {session_name}[/dim]")
    except Exception as e:
        if not quiet:
            console.print(f"[yellow]  Warning: Could not stop tmux session: {e}[/yellow]")

    # 3. Stop container by name (fast and reliable)
    try:
        runtime = get_container_runtime()
        if runtime.runtime:
            # Use config method for consistent container naming
            container_name = config.get_issue_container_name(issue_id)

            if runtime.stop(container_name):
                stopped_something = True
                if not quiet:
                    console.print(f"[dim]  Stopped container: {container_name}[/dim]")

            # Remove container (Apple Containers do NOT auto-remove, Docker needs explicit rm too)
            if runtime.delete(container_name):
                stopped_something = True
    except Exception as e:
        if not quiet:
            console.print(f"[yellow]  Warning: Could not stop container: {e}[/yellow]")

    if stopped_something and not quiet:
        console.print(f"[green]✓ Agent stopped for issue #{issue_id}[/green]")

    return stopped_something


def stop_all_agents_for_issue(issue_id: str, quiet: bool = False) -> int:
    """Stop all agents for an issue (across all roles).

    Args:
        issue_id: Issue ID
        quiet: If True, suppress output messages

    Returns:
        Number of agents stopped
    """
    # Use lazy import to avoid circular dependency
    from agenttree.state import get_active_agents_for_issue

    agents = get_active_agents_for_issue(issue_id)
    count = 0
    for agent in agents:
        if stop_agent(issue_id, agent.role, quiet):
            count += 1
    return count


def cleanup_orphaned_containers(quiet: bool = False) -> int:
    """Stop containers that don't have a corresponding tmux session.

    This handles the case where tmux sessions are killed but containers keep running.
    Looks for containers named with agenttree pattern and stops any that don't have
    a matching tmux session. Uses the container runtime abstraction instead of raw
    subprocess calls.

    Args:
        quiet: If True, suppress output messages

    Returns:
        Number of containers stopped
    """
    if not quiet:
        from rich.console import Console
        console = Console()

    runtime = get_container_runtime()
    if not runtime.runtime:
        return 0

    config = load_config()
    stopped = 0

    # Get list of all containers using runtime abstraction
    containers = runtime.list_all()

    # Check each container to see if it matches our naming pattern
    # Pattern: agenttree-{project}-{issue_id}
    import re
    pattern = rf"^agenttree-{re.escape(config.project)}-(\d+)$"

    for container in containers:
        name = container.get("name", "") or ""
        if isinstance(name, list):
            name = name[0] if name else ""
        name = name.strip("/")  # Docker adds leading slash

        match = re.match(pattern, name)
        if not match:
            continue

        issue_id = match.group(1)

        # Check if there's a tmux session for this container (developer is default role)
        session_name = config.get_issue_tmux_session(issue_id, "developer")

        if not session_exists(session_name):
            # Orphaned container - stop and remove it
            container_id = container.get("id", "") or name

            try:
                runtime.stop(container_id)
                runtime.delete(container_id)
                stopped += 1
                if not quiet:
                    console.print(f"[dim]Cleaned up orphaned container: {name}[/dim]")
            except Exception as e:
                # Container cleanup can fail if already removed - continue with others
                if not quiet:
                    console.print(f"[yellow]Warning: Could not cleanup container {name}: {e}[/yellow]")

    if not quiet and stopped > 0:
        console.print(f"[green]✓ Cleaned up {stopped} orphaned container(s)[/green]")

    return stopped


def cleanup_all_agenttree_containers(quiet: bool = False) -> int:
    """Remove ALL agenttree containers (by name prefix OR image name).

    Uses the container runtime abstraction which handles differences
    between Apple Container, Docker, and Podman.

    Args:
        quiet: If True, suppress output messages

    Returns:
        Number of containers removed
    """
    if not quiet:
        from rich.console import Console
        console = Console()

    runtime = get_container_runtime()
    if not runtime.runtime:
        return 0

    config = load_config()
    project_prefix = f"agenttree-{config.project}-"

    # Get all containers and filter for agenttree ones
    containers = runtime.list_all()
    removed = 0

    for c in containers:
        name = c.get("name", "") or c.get("id", "")
        image = c.get("image", "")

        # Match by name prefix OR by agenttree image (catches legacy unnamed containers)
        is_ours = (
            name.startswith(project_prefix) or
            name.startswith("agenttree-") or
            "agenttree" in image
        )

        if is_ours and name:
            runtime.stop(name)
            if runtime.delete(name):
                removed += 1
                if not quiet:
                    console.print(f"[dim]Removed: {name}[/dim]")

    if not quiet and removed:
        console.print(f"[green]✓ Removed {removed} container(s)[/green]")

    return removed


def cleanup_all_with_retry(max_passes: int = 3, delay_s: float = 2.0, quiet: bool = False) -> None:
    """Perform multi-pass cleanup of all agenttree containers with retry logic.

    Sometimes containers need multiple passes to fully clean up due to timing
    issues or dependency ordering. This function performs multiple cleanup
    passes with configurable delay between them.

    Args:
        max_passes: Number of cleanup passes to perform
        delay_s: Delay in seconds between passes
        quiet: If True, suppress output messages
    """
    for i in range(max_passes):
        cleanup_all_agenttree_containers(quiet)
        # Sleep between passes, but not after the last pass
        if i < max_passes - 1:
            time.sleep(delay_s)

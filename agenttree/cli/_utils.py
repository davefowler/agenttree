"""Shared utilities for CLI modules."""

import sys

from rich.console import Console

# Shared Rich console instance for all CLI modules
console = Console()

# Re-export commonly used functions for consistent import paths
from agenttree.config import load_config, Config
from agenttree.issues import (
    get_issue as get_issue_func,
    get_issue_dir,
)

def normalize_issue_id(issue_id: str) -> int:
    """Parse issue ID string to int."""
    from agenttree.ids import parse_issue_id
    return parse_issue_id(issue_id)


def format_role_label(role: str) -> str:
    """Format role label for display (empty string if developer)."""
    return f" ({role})" if role != "developer" else ""


def get_manager_session_name(config: Config) -> str:
    """Get tmux session name for the manager agent."""
    return f"{config.project}-manager-000"


def require_manager_running(config: Config, hint: bool = True) -> str:
    """Require that the manager session is running.

    Args:
        config: Config object
        hint: Whether to show a hint about how to start the manager

    Returns:
        Session name if manager is running

    Exits:
        With code 1 if manager is not running
    """
    from agenttree.tmux import session_exists

    session_name = get_manager_session_name(config)
    if not session_exists(session_name):
        console.print("[red]Error: Manager not running[/red]")
        if hint:
            console.print("[yellow]Start it with: agenttree start 0[/yellow]")
        sys.exit(1)
    return session_name


def get_manager_session_if_running(config: Config) -> str | None:
    """Get manager session name if it's running.

    Args:
        config: Config object

    Returns:
        Session name if manager is running, None otherwise
    """
    from agenttree.tmux import session_exists

    session_name = get_manager_session_name(config)
    if session_exists(session_name):
        return session_name
    return None


__all__ = [
    "console",
    "load_config",
    "Config",
    "get_issue_func",
    "get_issue_dir",
    "normalize_issue_id",
    "format_role_label",
    "get_manager_session_name",
    "require_manager_running",
    "get_manager_session_if_running",
]

"""Shared utilities for CLI modules."""

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


__all__ = [
    "console",
    "load_config",
    "Config",
    "get_issue_func",
    "get_issue_dir",
    "normalize_issue_id",
    "format_role_label",
    "get_manager_session_name",
]

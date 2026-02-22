"""Shared utilities for CLI modules."""

import os

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


def infer_issue_id() -> int | None:
    """Infer issue_id from environment, or None if not in an agent context.

    Checks the AGENTTREE_ISSUE_ID environment variable set by containers.
    Returns None when running on the host with no env var set.

    Important: Does NOT default to 0. Being on the host doesn't mean
    "I'm the manager." It means "I'm not in any agent's context."
    """
    env_id = os.environ.get("AGENTTREE_ISSUE_ID")
    if env_id:
        from agenttree.ids import parse_issue_id
        return parse_issue_id(env_id)
    return None


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
    "infer_issue_id",
]

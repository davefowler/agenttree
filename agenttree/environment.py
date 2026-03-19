"""Environment detection utilities for AgentTree.

This module provides functions to detect the runtime environment.
In the new architecture, everything runs in a single container (or on host).
Sub-agents are `claude -p` subprocesses, not separate containers.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING

from agenttree.config import DEFAULT_ROLE

if TYPE_CHECKING:
    from agenttree.issues import Issue


def is_running_in_container() -> bool:
    """Check if we're running inside the agenttree container.

    In the new architecture, there's ONE container for the whole system.
    This checks for AGENTTREE_CONTAINER env var set when launching the container.

    Returns:
        True if running in a container, False otherwise
    """
    return (
        os.environ.get("AGENTTREE_CONTAINER") == "1"
        or os.environ.get("CONTAINER_RUNTIME") is not None
    )


def is_agent_subprocess() -> bool:
    """Check if we're running as a claude -p subprocess (not interactive).

    Agent subprocesses have AGENTTREE_ISSUE_ID set but no terminal.

    Returns:
        True if running as an agent subprocess
    """
    return os.environ.get("AGENTTREE_ISSUE_ID") is not None


def get_code_directory(issue: "Issue | None", issue_dir: Path) -> Path:
    """Get the correct working directory for code operations.

    In the new model, agents run directly in their worktree (no /workspace mount).
    On host, use the issue's worktree_dir if set, otherwise fall back to issue_dir.
    """
    if issue and issue.worktree_dir:
        return Path(issue.worktree_dir)

    return issue_dir


def get_current_role() -> str:
    """Get the current agent role.

    Returns:
        Role name (e.g., "developer", "messenger", "reviewer")
    """
    role = os.environ.get("AGENTTREE_ROLE")
    if role:
        return role

    # Default: developer if agent subprocess, messenger if host
    if is_agent_subprocess():
        return DEFAULT_ROLE
    return "messenger"


def can_agent_operate_in_stage(stage_role: str) -> bool:
    """Check if the current agent can operate in a stage with the given role.

    Args:
        stage_role: The role from the stage config

    Returns:
        True if the current agent can operate in this stage
    """
    current_role = get_current_role()

    # Messenger/manager can operate anywhere
    if current_role in ("manager", "messenger"):
        return True

    return current_role == stage_role

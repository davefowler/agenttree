"""Environment detection utilities for AgentTree.

This module provides functions to detect the runtime environment,
including container detection and agent role determination.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agenttree.issues import Issue


def is_running_in_container() -> bool:
    """Check if we're running inside a container.

    Checks for AGENTTREE_CONTAINER env var (set by agenttree when launching)
    as well as common container indicators.

    Returns:
        True if running in a container, False otherwise
    """
    # Check for agenttree-specific env var first (most reliable)
    if os.environ.get("AGENTTREE_CONTAINER") == "1":
        return True
    # Fall back to common container indicators
    return (
        os.path.exists("/.dockerenv") or
        os.path.exists("/run/.containerenv") or
        os.environ.get("CONTAINER_RUNTIME") is not None
    )


def get_code_directory(issue: "Issue | None", issue_dir: Path) -> Path:
    """Get the correct working directory for code operations.

    Inside containers, code is always mounted at /workspace regardless of
    the issue's worktree_dir (which is a host path). On the host, use the
    issue's worktree_dir if set, otherwise fall back to issue_dir.

    Args:
        issue: The issue object (may be None)
        issue_dir: The issue's _agenttree/issues/ directory (fallback)

    Returns:
        Path to the directory containing the code
    """
    if is_running_in_container():
        return Path("/workspace")

    if issue and issue.worktree_dir:
        return Path(issue.worktree_dir)

    return issue_dir


def get_current_role() -> str:
    """Get the current agent role.

    The role is determined by the AGENTTREE_ROLE env var.
    If not set, defaults to "developer" for containers or "manager" for host.

    Returns:
        Role name (e.g., "developer", "manager", "reviewer")
    """
    # Check for explicit role
    role = os.environ.get("AGENTTREE_ROLE")
    if role:
        return role

    # Default: "developer" if in container, "manager" if on host
    if is_running_in_container():
        return "developer"
    return "manager"


def can_agent_operate_in_stage(stage_role: str) -> bool:
    """Check if the current agent can operate in a stage with the given role.

    Agents can only operate in stages where the stage's role matches their identity.
    - Default agents (role="developer") can only operate in role="developer" stages
    - Custom agents (role="reviewer") can only operate in role="reviewer" stages
    - Manager can operate in any stage (it's human-driven)

    Args:
        stage_role: The role value from the stage config (e.g., "developer", "manager", "reviewer")

    Returns:
        True if the current agent can operate in this stage, False otherwise
    """
    current_role = get_current_role()

    # Manager (human) can operate anywhere
    if current_role == "manager":
        return True

    # Agents can only operate in their own role stages
    return current_role == stage_role

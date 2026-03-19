"""State management for active agents.

Tracks active agents via process state (PID-based) instead of tmux sessions.
The messenger (interactive claude session) is the only tmux-based agent.

ActiveAgent is the public interface - other modules should use this,
not the internal process tracking directly.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from agenttree.config import DEFAULT_ROLE, load_config

if TYPE_CHECKING:
    from agenttree import process

logger = logging.getLogger(__name__)


@dataclass
class ActiveAgent:
    """Information about an active agent for an issue."""

    issue_id: int
    role: str
    pid: int
    worktree: Path
    branch: str
    port: int
    log_file: str
    started: str  # ISO format timestamp

    # Keep tmux_session for backward compat (messenger uses it)
    tmux_session: str = ""
    # Keep container for backward compat (always empty now)
    container: str = ""

    @property
    def state_key(self) -> str:
        """Key for state storage: issue_id:role."""
        return f"{self.issue_id}:{self.role}"


def _agent_from_process(proc: "process.AgentProcess") -> ActiveAgent:
    """Convert an AgentProcess to an ActiveAgent."""
    return ActiveAgent(
        issue_id=proc.issue_id,
        role=proc.role,
        pid=proc.pid,
        worktree=Path(proc.worktree),
        branch=proc.branch,
        port=proc.port,
        log_file=proc.log_file,
        started=proc.started,
    )


def get_active_agent(issue_id: int, role: str = DEFAULT_ROLE) -> ActiveAgent | None:
    """Get active agent for an issue and role.

    Checks process state first, then falls back to tmux (for messenger).

    Args:
        issue_id: Issue ID
        role: Agent role (default: "developer")

    Returns:
        ActiveAgent or None if no active agent
    """
    from agenttree.process import get_agent

    agent = get_agent(issue_id, role)
    if agent:
        return _agent_from_process(agent)

    # For issue 0 / messenger, check tmux
    if issue_id == 0 or role == "messenger":
        return _get_tmux_agent(issue_id, role)

    return None


def _get_tmux_agent(issue_id: int, role: str) -> ActiveAgent | None:
    """Check if a tmux-based agent (messenger) is running."""
    from agenttree.tmux import session_exists
    from agenttree.ids import format_issue_id

    try:
        config = load_config()
        project = config.project
    except (FileNotFoundError, KeyError, AttributeError):
        project = "agenttree"

    session_name = f"{project}-{role}-{format_issue_id(issue_id)}"
    if not session_exists(session_name):
        return None

    return ActiveAgent(
        issue_id=issue_id,
        role=role,
        pid=0,  # tmux-managed, no direct PID
        worktree=Path.cwd(),
        branch="",
        port=0,
        log_file="",
        started=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        tmux_session=session_name,
    )


def get_active_agents_for_issue(issue_id: int) -> list[ActiveAgent]:
    """Get all active agents for an issue (across all roles)."""
    from agenttree.process import get_agents_for_issue

    agents = get_agents_for_issue(issue_id)
    return [_agent_from_process(a) for a in agents]


def list_active_agents() -> list[ActiveAgent]:
    """Get all active agents."""
    from agenttree.process import list_agents

    agents = list_agents()
    return [_agent_from_process(a) for a in agents if a.issue_id != 0]


def unregister_agent(issue_id: int, role: str = DEFAULT_ROLE) -> ActiveAgent | None:
    """Unregister an active agent by stopping its process.

    Args:
        issue_id: Issue ID
        role: Agent role

    Returns:
        The ActiveAgent if found, or None
    """
    from agenttree.process import stop_agent_process, get_agent

    agent = get_agent(issue_id, role)
    result = None
    if agent:
        result = _agent_from_process(agent)
    stop_agent_process(issue_id, role)
    return result


def unregister_all_agents_for_issue(issue_id: int) -> list[ActiveAgent]:
    """Unregister all agents for an issue."""
    agents = get_active_agents_for_issue(issue_id)
    from agenttree.process import stop_all_for_issue
    stop_all_for_issue(issue_id)
    return agents


def get_issue_names(issue_id: int, project: str = "agenttree", role: str = DEFAULT_ROLE) -> dict[str, str]:
    """Get standardized names for issue-bound resources."""
    from agenttree.ids import format_issue_id, worktree_dir_name
    config = load_config()
    return {
        "container": "",  # No containers anymore
        "worktree": worktree_dir_name(issue_id),
        "branch": f"issue-{format_issue_id(issue_id)}",
        "tmux_session": "",  # Sub-agents don't use tmux
    }


def create_agent_for_issue(
    issue_id: int,
    worktree_path: Path,
    port: int,
    project: str = "agenttree",
    role: str = DEFAULT_ROLE,
) -> ActiveAgent:
    """Create an ActiveAgent object for an issue.

    Note: This doesn't start the agent. The agent becomes "running"
    when start_agent() is called in process.py.
    """
    names = get_issue_names(issue_id, project, role)

    return ActiveAgent(
        issue_id=issue_id,
        role=role,
        pid=0,  # Not started yet
        worktree=worktree_path,
        branch=names["branch"],
        port=port,
        log_file="",
        started=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

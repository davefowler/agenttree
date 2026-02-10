"""State management for active agents.

Derives active agent state from tmux sessions instead of a state file.
This eliminates staleness issues when containers/sessions die unexpectedly.

Tmux session naming convention: {project}-{role}-{issue_id}
Examples:
  - agenttree-developer-042 -> issue 042, role "developer"
  - agenttree-reviewer-042  -> issue 042, role "reviewer"
"""

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agenttree.config import load_config


@dataclass
class ActiveAgent:
    """Information about an active agent for an issue."""

    issue_id: str
    role: str  # Agent role (e.g., "developer", "reviewer")
    container: str
    worktree: Path
    branch: str
    port: int
    tmux_session: str
    started: str  # ISO format timestamp (approximate, from tmux)

    @property
    def state_key(self) -> str:
        """Key for state storage: issue_id:role."""
        return f"{self.issue_id}:{self.role}"


def _parse_tmux_session_name(session_name: str, project: str) -> Optional[tuple[str, str]]:
    """Parse a tmux session name to extract issue_id and role.

    Args:
        session_name: Tmux session name (e.g., "agenttree-developer-042")
        project: Project name prefix to match

    Returns:
        Tuple of (issue_id, role) or None if not a matching session
    """
    # Pattern: {project}-{role}-{issue_id}
    pattern = rf"^{re.escape(project)}-(\w+)-(\d+)$"
    match = re.match(pattern, session_name)
    if match:
        role = match.group(1)
        issue_id = match.group(2)
        return (issue_id, role)
    return None


def _get_tmux_sessions() -> list[tuple[str, str]]:
    """Get all tmux sessions with their creation times.

    Returns:
        List of (session_name, created_time) tuples
    """
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}|#{session_created}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []

        stdout = result.stdout.strip()
        if not stdout:
            return []

        sessions = []
        for line in stdout.split("\n"):
            if "|" in line:
                name, created = line.split("|", 1)
                sessions.append((name, created))
        return sessions
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _build_agent_from_session(
    issue_id: str,
    role: str,
    session_name: str,
    created_timestamp: str,
    project: str,
) -> ActiveAgent:
    """Build an ActiveAgent from tmux session info.

    Args:
        issue_id: Issue ID
        role: Role type (developer, reviewer, etc.)
        session_name: Tmux session name
        created_timestamp: Unix timestamp when session was created
        project: Project name

    Returns:
        ActiveAgent with derived fields
    """
    # Get issue data to find worktree/branch
    from agenttree.issues import get_issue
    issue = get_issue(issue_id)

    worktree = Path(issue.worktree_dir) if issue and issue.worktree_dir else Path(f".worktrees/issue-{issue_id}")
    branch = issue.branch if issue and issue.branch else f"issue-{issue_id}"

    # Port is deterministic from issue ID
    config = load_config()
    port = config.get_port_for_issue(issue_id) or 9000 + (int(issue_id) % 1000)

    # Convert unix timestamp to ISO format
    try:
        created_dt = datetime.fromtimestamp(int(created_timestamp), tz=timezone.utc)
        started = created_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Container name follows convention (actual UUID looked up when needed)
    container = f"{project}-{role}-{issue_id}"

    return ActiveAgent(
        issue_id=issue_id,
        role=role,
        container=container,
        worktree=worktree,
        branch=branch,
        port=port,
        tmux_session=session_name,
        started=started,
    )


def get_active_agent(issue_id: str, role: str = "developer") -> Optional[ActiveAgent]:
    """Get active agent for an issue and role by checking tmux sessions.

    Args:
        issue_id: Issue ID (e.g., "023")
        role: Agent role (default: "developer")

    Returns:
        ActiveAgent or None if no active agent
    """
    try:
        config = load_config()
        project = config.project
    except (FileNotFoundError, KeyError, AttributeError):
        project = "agenttree"

    expected_session = f"{project}-{role}-{issue_id}"

    for session_name, created in _get_tmux_sessions():
        if session_name == expected_session:
            return _build_agent_from_session(issue_id, role, session_name, created, project)

    return None


def get_active_agents_for_issue(issue_id: str) -> list[ActiveAgent]:
    """Get all active agents for an issue (across all roles).

    Args:
        issue_id: Issue ID (e.g., "023")

    Returns:
        List of ActiveAgent objects for this issue
    """
    try:
        config = load_config()
        project = config.project
    except (FileNotFoundError, KeyError, AttributeError):
        project = "agenttree"

    agents = []
    for session_name, created in _get_tmux_sessions():
        parsed = _parse_tmux_session_name(session_name, project)
        if parsed and parsed[0] == issue_id:
            sid, role = parsed
            agents.append(_build_agent_from_session(sid, role, session_name, created, project))

    return agents


def list_active_agents() -> list[ActiveAgent]:
    """Get all active agents by scanning tmux sessions.

    Returns:
        List of ActiveAgent objects
    """
    try:
        config = load_config()
        project = config.project
    except (FileNotFoundError, KeyError, AttributeError):
        project = "agenttree"

    agents = []
    for session_name, created in _get_tmux_sessions():
        parsed = _parse_tmux_session_name(session_name, project)
        if parsed:
            issue_id, role = parsed
            agents.append(_build_agent_from_session(issue_id, role, session_name, created, project))

    return agents






def unregister_agent(issue_id: str, role: str = "developer") -> Optional[ActiveAgent]:
    """Unregister an active agent by stopping its tmux session.

    With dynamic state, unregistration = killing the tmux session.
    This function stops the agent and returns its info.

    Args:
        issue_id: Issue ID to unregister
        role: Agent role (default: "developer")

    Returns:
        The ActiveAgent if found, or None
    """
    # Get agent info before stopping
    agent = get_active_agent(issue_id, role)
    if agent:
        # Actually stop the agent (kills tmux session = unregistration)
        from agenttree.api import stop_agent
        stop_agent(issue_id, role, quiet=True)
    return agent


def unregister_all_agents_for_issue(issue_id: str) -> list[ActiveAgent]:
    """Unregister all agents for an issue (across all roles).

    Stops all agents (across all roles) and returns their info.

    Args:
        issue_id: Issue ID

    Returns:
        List of ActiveAgent objects that were stopped
    """
    agents = get_active_agents_for_issue(issue_id)
    for agent in agents:
        from agenttree.api import stop_agent
        stop_agent(issue_id, agent.role, quiet=True)
    return agents




def get_issue_names(issue_id: str, slug: str, project: str = "agenttree", role: str = "developer") -> dict:
    """Get standardized names for issue-bound resources.

    Args:
        issue_id: Issue ID (e.g., "023")
        slug: Issue slug (e.g., "fix-login-bug")
        project: Project name
        role: Agent role (default: "developer")

    Returns:
        Dictionary with container, worktree, branch, tmux_session names
    """
    # Truncate slug for filesystem friendliness
    short_slug = slug[:30] if len(slug) > 30 else slug

    config = load_config()
    return {
        "container": config.get_issue_container_name(issue_id),
        "worktree": f"issue-{issue_id}-{short_slug}",
        "branch": f"issue-{issue_id}-{short_slug}",
        "tmux_session": config.get_issue_tmux_session(issue_id, role),
    }



def create_agent_for_issue(
    issue_id: str,
    slug: str,
    worktree_path: Path,
    port: int,
    project: str = "agenttree",
    role: str = "developer",
) -> ActiveAgent:
    """Create an ActiveAgent object for an issue.

    Note: With dynamic state, this doesn't register anything. The agent
    becomes "registered" when its tmux session is created.

    Args:
        issue_id: Issue ID
        slug: Issue slug
        worktree_path: Path to worktree
        port: Allocated port
        project: Project name
        role: Agent role (default: "developer")

    Returns:
        ActiveAgent object (not yet running until tmux session created)
    """
    names = get_issue_names(issue_id, slug, project, role)

    return ActiveAgent(
        issue_id=issue_id,
        role=role,
        container=names["container"],
        worktree=worktree_path,
        branch=names["branch"],
        port=port,
        tmux_session=names["tmux_session"],
        started=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

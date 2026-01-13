"""State management for active agents.

Tracks which issues have active agents (container + worktree + tmux session)
and manages dynamic port allocation.

Uses file locking to prevent race conditions when multiple processes access
the state file concurrently (e.g., starting multiple agents simultaneously).
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

import yaml
from filelock import FileLock


@dataclass
class ActiveAgent:
    """Information about an active agent for an issue."""

    issue_id: str
    container: str
    worktree: Path
    branch: str
    port: int
    tmux_session: str
    started: str  # ISO format timestamp

    def to_dict(self) -> dict:
        """Convert to dictionary for YAML serialization."""
        return {
            "issue_id": self.issue_id,
            "container": self.container,
            "worktree": str(self.worktree),
            "branch": self.branch,
            "port": self.port,
            "tmux_session": self.tmux_session,
            "started": self.started,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ActiveAgent":
        """Create from dictionary."""
        return cls(
            issue_id=data["issue_id"],
            container=data["container"],
            worktree=Path(data["worktree"]),
            branch=data["branch"],
            port=data["port"],
            tmux_session=data["tmux_session"],
            started=data["started"],
        )


def get_state_path() -> Path:
    """Get path to state file."""
    return Path.cwd() / "_agenttree" / "state.yaml"


def get_state_lock_path() -> Path:
    """Get path to state lock file.

    The lock file is a sibling of the state file, used by filelock
    to coordinate concurrent access.
    """
    return get_state_path().parent / "state.yaml.lock"


# Lock timeout in seconds - prevents deadlocks if a process crashes while holding lock
_LOCK_TIMEOUT = 5.0


@contextmanager
def state_lock() -> Generator[None, None, None]:
    """Context manager for exclusive access to state file.

    Use this for atomic read-modify-write operations to prevent race conditions.

    Raises:
        Timeout: If lock cannot be acquired within _LOCK_TIMEOUT seconds

    Example:
        with state_lock():
            state = load_state()
            state["key"] = "value"
            save_state(state)
    """
    lock_path = get_state_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(lock_path, timeout=_LOCK_TIMEOUT)

    with lock:
        yield


def load_state() -> dict:
    """Load state from file.

    Returns:
        State dictionary with 'active_agents' and 'port_pool' keys
    """
    state_path = get_state_path()

    if not state_path.exists():
        return {
            "active_agents": {},
            "port_pool": {
                "base": 3000,
                "allocated": [],
            },
        }

    with open(state_path) as f:
        data = yaml.safe_load(f)

    return data or {
        "active_agents": {},
        "port_pool": {"base": 3000, "allocated": []},
    }


def save_state(state: dict) -> None:
    """Save state to file.

    Args:
        state: State dictionary to save
    """
    state_path = get_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)

    with open(state_path, "w") as f:
        yaml.dump(state, f, default_flow_style=False, sort_keys=False)


def get_active_agent(issue_id: str) -> Optional[ActiveAgent]:
    """Get active agent for an issue.

    Args:
        issue_id: Issue ID (e.g., "023")

    Returns:
        ActiveAgent or None if no active agent
    """
    state = load_state()
    agent_data = state.get("active_agents", {}).get(issue_id)

    if agent_data:
        return ActiveAgent.from_dict(agent_data)

    return None


def list_active_agents() -> list[ActiveAgent]:
    """Get all active agents.

    Returns:
        List of ActiveAgent objects
    """
    state = load_state()
    agents = []

    for agent_data in state.get("active_agents", {}).values():
        agents.append(ActiveAgent.from_dict(agent_data))

    return agents


def register_agent(agent: ActiveAgent) -> None:
    """Register a new active agent.

    Uses file locking to prevent race conditions during concurrent registrations.

    Args:
        agent: ActiveAgent to register
    """
    with state_lock():
        state = load_state()

        if "active_agents" not in state:
            state["active_agents"] = {}

        state["active_agents"][agent.issue_id] = agent.to_dict()

        # Track port allocation
        if "port_pool" not in state:
            state["port_pool"] = {"base": 3000, "allocated": []}

        if agent.port not in state["port_pool"]["allocated"]:
            state["port_pool"]["allocated"].append(agent.port)

        save_state(state)


def unregister_agent(issue_id: str) -> Optional[ActiveAgent]:
    """Unregister an active agent.

    Uses file locking to prevent race conditions during concurrent unregistrations.

    Args:
        issue_id: Issue ID to unregister

    Returns:
        The unregistered ActiveAgent, or None if not found
    """
    with state_lock():
        state = load_state()

        agent_data = state.get("active_agents", {}).pop(issue_id, None)

        if agent_data:
            agent = ActiveAgent.from_dict(agent_data)

            # Free port
            if agent.port in state.get("port_pool", {}).get("allocated", []):
                state["port_pool"]["allocated"].remove(agent.port)

            save_state(state)
            return agent

        return None


def allocate_port(base_port: int = 3000) -> int:
    """Allocate an available port.

    Uses file locking to prevent race conditions when multiple processes
    allocate ports concurrently (e.g., starting multiple agents at once).

    Args:
        base_port: Starting port number

    Returns:
        Allocated port number
    """
    with state_lock():
        state = load_state()

        if "port_pool" not in state:
            state["port_pool"] = {"base": base_port, "allocated": []}

        allocated = set(state["port_pool"].get("allocated", []))

        # Find first available port starting from base + 1
        port = base_port + 1
        while port in allocated:
            port += 1

        state["port_pool"]["allocated"].append(port)
        save_state(state)

        return port


def free_port(port: int) -> None:
    """Free an allocated port.

    Uses file locking to prevent race conditions during concurrent operations.

    Args:
        port: Port number to free
    """
    with state_lock():
        state = load_state()

        allocated = state.get("port_pool", {}).get("allocated", [])
        if port in allocated:
            allocated.remove(port)
            save_state(state)


def get_issue_names(issue_id: str, slug: str, project: str = "agenttree") -> dict:
    """Get standardized names for issue-bound resources.

    Args:
        issue_id: Issue ID (e.g., "023")
        slug: Issue slug (e.g., "fix-login-bug")
        project: Project name

    Returns:
        Dictionary with container, worktree, branch, tmux_session names
    """
    # Truncate slug for filesystem friendliness
    short_slug = slug[:30] if len(slug) > 30 else slug

    return {
        "container": f"{project}-issue-{issue_id}",
        "worktree": f"issue-{issue_id}-{short_slug}",
        "branch": f"issue-{issue_id}-{short_slug}",
        "tmux_session": f"{project}-issue-{issue_id}",
    }


def create_agent_for_issue(
    issue_id: str,
    slug: str,
    worktree_path: Path,
    port: int,
    project: str = "agenttree",
) -> ActiveAgent:
    """Create and register an agent for an issue.

    Args:
        issue_id: Issue ID
        slug: Issue slug
        worktree_path: Path to worktree
        port: Allocated port
        project: Project name

    Returns:
        Created ActiveAgent
    """
    names = get_issue_names(issue_id, slug, project)

    agent = ActiveAgent(
        issue_id=issue_id,
        container=names["container"],
        worktree=worktree_path,
        branch=names["branch"],
        port=port,
        tmux_session=names["tmux_session"],
        started=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    register_agent(agent)
    return agent

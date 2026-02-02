"""State management for active agents.

Tracks which issues have active agents (container + worktree + tmux session)
and manages dynamic port allocation.

Uses file locking to prevent race conditions when multiple processes access
the state file concurrently (e.g., starting multiple agents simultaneously).
"""

import re
import subprocess
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
    host: str  # Agent host type (e.g., "agent", "reviewer")
    container: str
    worktree: Path
    branch: str
    port: int
    tmux_session: str
    started: str  # ISO format timestamp

    @property
    def state_key(self) -> str:
        """Key for state storage: issue_id:host."""
        return f"{self.issue_id}:{self.host}"

    def to_dict(self) -> dict:
        """Convert to dictionary for YAML serialization."""
        return {
            "issue_id": self.issue_id,
            "host": self.host,
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
            host=data.get("host", "agent"),  # Default to "agent" if not specified
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
        State dictionary with 'active_agents' key
    """
    state_path = get_state_path()

    if not state_path.exists():
        return {"active_agents": {}}

    with open(state_path) as f:
        data = yaml.safe_load(f)

    return data or {"active_agents": {}}


def save_state(state: dict) -> None:
    """Save state to file.

    Args:
        state: State dictionary to save
    """
    state_path = get_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)

    with open(state_path, "w") as f:
        yaml.dump(state, f, default_flow_style=False, sort_keys=False)


def get_active_agent(issue_id: str, host: str = "agent") -> Optional[ActiveAgent]:
    """Get active agent for an issue and host.

    Args:
        issue_id: Issue ID (e.g., "023")
        host: Agent host type (default: "agent")

    Returns:
        ActiveAgent or None if no active agent
    """
    state = load_state()
    state_key = f"{issue_id}:{host}"
    agent_data = state.get("active_agents", {}).get(state_key)

    if agent_data:
        return ActiveAgent.from_dict(agent_data)

    return None


def get_active_agents_for_issue(issue_id: str) -> list[ActiveAgent]:
    """Get all active agents for an issue (across all hosts).

    Args:
        issue_id: Issue ID (e.g., "023")

    Returns:
        List of ActiveAgent objects for this issue
    """
    state = load_state()
    agents = []
    prefix = f"{issue_id}:"

    for key, agent_data in state.get("active_agents", {}).items():
        if key.startswith(prefix):
            agents.append(ActiveAgent.from_dict(agent_data))

    return agents


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

        state["active_agents"][agent.state_key] = agent.to_dict()

        # Note: Port tracking removed - ports are now deterministic from issue ID
        # via get_port_for_issue()

        save_state(state)


def update_agent_container_id(issue_id: str, container_id: str, host: str = "agent") -> None:
    """Update an agent's container ID (for Apple Containers UUID tracking).

    Apple Containers use UUIDs instead of names. This function updates the
    stored container ID after the container has started and we can look up
    its UUID.

    Args:
        issue_id: Issue ID
        container_id: Container UUID
        host: Agent host type (default: "agent")
    """
    with state_lock():
        state = load_state()

        if "active_agents" not in state:
            return

        state_key = f"{issue_id}:{host}"
        if state_key not in state["active_agents"]:
            return

        state["active_agents"][state_key]["container"] = container_id
        save_state(state)


def unregister_agent(issue_id: str, host: str = "agent") -> Optional[ActiveAgent]:
    """Unregister an active agent.

    Uses file locking to prevent race conditions during concurrent unregistrations.

    Args:
        issue_id: Issue ID to unregister
        host: Agent host type (default: "agent")

    Returns:
        The unregistered ActiveAgent, or None if not found
    """
    with state_lock():
        state = load_state()

        state_key = f"{issue_id}:{host}"
        agent_data = state.get("active_agents", {}).pop(state_key, None)

        if agent_data:
            agent = ActiveAgent.from_dict(agent_data)
            # Note: Port freeing removed - ports are deterministic from issue ID
            save_state(state)
            return agent

        return None


def unregister_all_agents_for_issue(issue_id: str) -> list[ActiveAgent]:
    """Unregister all agents for an issue (across all hosts).

    Args:
        issue_id: Issue ID to unregister

    Returns:
        List of unregistered ActiveAgent objects
    """
    with state_lock():
        state = load_state()
        unregistered = []
        prefix = f"{issue_id}:"

        keys_to_remove = [k for k in state.get("active_agents", {}).keys() if k.startswith(prefix)]
        for key in keys_to_remove:
            agent_data = state["active_agents"].pop(key)
            unregistered.append(ActiveAgent.from_dict(agent_data))

        if unregistered:
            save_state(state)

        return unregistered


def stop_agent(issue_id: str, host: str = "agent", quiet: bool = False) -> bool:
    """Stop an active agent - kills tmux, stops container, unregisters from state.

    This is the canonical way to stop an agent. Used by:
    - CLI: agenttree stop <id>
    - Web API: POST /api/issues/{id}/stop
    - Hooks: cleanup_agent

    Args:
        issue_id: Issue ID to stop
        host: Agent host type (default: "agent")
        quiet: If True, suppress output messages

    Returns:
        True if agent was stopped, False if no agent was found
    """
    agent = get_active_agent(issue_id, host)
    if not agent:
        return False

    if not quiet:
        from rich.console import Console
        console = Console()
        console.print(f"[dim]Stopping agent for issue #{issue_id}...[/dim]")

    # 1. Kill tmux session
    try:
        from agenttree.tmux import kill_session, session_exists
        if session_exists(agent.tmux_session):
            kill_session(agent.tmux_session)
            if not quiet:
                console.print(f"[dim]  Stopped tmux session: {agent.tmux_session}[/dim]")
    except Exception as e:
        if not quiet:
            console.print(f"[yellow]  Warning: Could not stop tmux session: {e}[/yellow]")

    # 2. Stop container (if running)
    try:
        from agenttree.container import get_container_runtime, find_container_by_worktree
        runtime = get_container_runtime()
        if runtime.runtime and agent.container:
            container_id = agent.container

            # For Apple Containers, we need the UUID, not the name
            # If the stored ID looks like a name (not a UUID), try to find the UUID
            if runtime.runtime == "container" and not _is_uuid(container_id):
                worktree_path = Path(agent.worktree)
                if not worktree_path.is_absolute():
                    worktree_path = Path.cwd() / worktree_path
                found_uuid = find_container_by_worktree(worktree_path)
                if found_uuid:
                    container_id = found_uuid

            result = subprocess.run(
                [runtime.runtime, "stop", container_id],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and not quiet:
                short_id = container_id[:12] if len(container_id) > 12 else container_id
                console.print(f"[dim]  Stopped container: {short_id}[/dim]")

            # Remove container (only for Docker/Podman - Apple Containers auto-removes)
            if runtime.runtime != "container":
                subprocess.run(
                    [runtime.runtime, "rm", container_id],
                    capture_output=True,
                    text=True,
                    check=False,
                )
    except Exception as e:
        if not quiet:
            console.print(f"[yellow]  Warning: Could not stop container: {e}[/yellow]")

    # 3. Unregister from state
    unregister_agent(issue_id, host)

    if not quiet:
        console.print(f"[green]✓ Agent stopped for issue #{issue_id}[/green]")

    return True


def stop_all_agents_for_issue(issue_id: str, quiet: bool = False) -> int:
    """Stop all agents for an issue (across all hosts).

    Args:
        issue_id: Issue ID
        quiet: If True, suppress output messages

    Returns:
        Number of agents stopped
    """
    agents = get_active_agents_for_issue(issue_id)
    count = 0
    for agent in agents:
        if stop_agent(issue_id, agent.host, quiet):
            count += 1
    return count


def _is_uuid(s: str) -> bool:
    """Check if string looks like a UUID."""
    return bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', s, re.I))


def get_issue_names(issue_id: str, slug: str, project: str = "agenttree", host: str = "agent") -> dict:
    """Get standardized names for issue-bound resources.

    Args:
        issue_id: Issue ID (e.g., "023")
        slug: Issue slug (e.g., "fix-login-bug")
        project: Project name
        host: Agent host type (default: "agent")

    Returns:
        Dictionary with container, worktree, branch, tmux_session names
    """
    # Truncate slug for filesystem friendliness
    short_slug = slug[:30] if len(slug) > 30 else slug

    return {
        "container": f"{project}-{host}-{issue_id}",
        "worktree": f"issue-{issue_id}-{short_slug}",
        "branch": f"issue-{issue_id}-{short_slug}",
        "tmux_session": f"{project}-{host}-{issue_id}",
    }


def get_port_for_issue(issue_id: str, base_port: int = 9000) -> int:
    """Get deterministic port for an issue.

    Derives port from issue number: base_port + (issue_num % 1000).
    This eliminates the need for dynamic port allocation and port_pool state.

    Args:
        issue_id: Issue ID (e.g., "023" or "1045")
        base_port: Base port number (default 9000)

    Returns:
        Port number for this issue

    Note:
        Issues 1 and 1001 would get the same port. This is acceptable because:
        - Having 1000+ issues is rare
        - Both would need active agents simultaneously (even rarer)
        - The conflict would be immediately obvious
    """
    issue_num = int(issue_id)
    return base_port + (issue_num % 1000)


def create_agent_for_issue(
    issue_id: str,
    slug: str,
    worktree_path: Path,
    port: int,
    project: str = "agenttree",
    host: str = "agent",
) -> ActiveAgent:
    """Create and register an agent for an issue.

    Args:
        issue_id: Issue ID
        slug: Issue slug
        worktree_path: Path to worktree
        port: Allocated port
        project: Project name
        host: Agent host type (default: "agent")

    Returns:
        Created ActiveAgent
    """
    names = get_issue_names(issue_id, slug, project, host)

    agent = ActiveAgent(
        issue_id=issue_id,
        host=host,
        container=names["container"],
        worktree=worktree_path,
        branch=names["branch"],
        port=port,
        tmux_session=names["tmux_session"],
        started=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    register_agent(agent)
    return agent

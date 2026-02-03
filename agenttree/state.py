"""State management for active agents.

Derives active agent state from tmux sessions instead of a state file.
This eliminates staleness issues when containers/sessions die unexpectedly.

Tmux session naming convention: {project}-{host}-{issue_id}
Examples:
  - agenttree-agent-042  -> issue 042, host "agent"
  - agenttree-review-042 -> issue 042, host "review"
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
    host: str  # Agent host type (e.g., "agent", "review")
    container: str
    worktree: Path
    branch: str
    port: int
    tmux_session: str
    started: str  # ISO format timestamp (approximate, from tmux)

    @property
    def state_key(self) -> str:
        """Key for state storage: issue_id:host."""
        return f"{self.issue_id}:{self.host}"


def _parse_tmux_session_name(session_name: str, project: str) -> Optional[tuple[str, str]]:
    """Parse a tmux session name to extract issue_id and host.

    Args:
        session_name: Tmux session name (e.g., "agenttree-agent-042")
        project: Project name prefix to match

    Returns:
        Tuple of (issue_id, host) or None if not a matching session
    """
    # Pattern: {project}-{host}-{issue_id}
    pattern = rf"^{re.escape(project)}-(\w+)-(\d+)$"
    match = re.match(pattern, session_name)
    if match:
        host = match.group(1)
        issue_id = match.group(2)
        return (issue_id, host)
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
    host: str,
    session_name: str,
    created_timestamp: str,
    project: str,
) -> ActiveAgent:
    """Build an ActiveAgent from tmux session info.

    Args:
        issue_id: Issue ID
        host: Host type (agent, review, etc.)
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
    port = get_port_for_issue(issue_id)

    # Convert unix timestamp to ISO format
    try:
        created_dt = datetime.fromtimestamp(int(created_timestamp), tz=timezone.utc)
        started = created_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Container name follows convention (actual UUID looked up when needed)
    container = f"{project}-{host}-{issue_id}"

    return ActiveAgent(
        issue_id=issue_id,
        host=host,
        container=container,
        worktree=worktree,
        branch=branch,
        port=port,
        tmux_session=session_name,
        started=started,
    )


def get_active_agent(issue_id: str, host: str = "agent") -> Optional[ActiveAgent]:
    """Get active agent for an issue and host by checking tmux sessions.

    Args:
        issue_id: Issue ID (e.g., "023")
        host: Agent host type (default: "agent")

    Returns:
        ActiveAgent or None if no active agent
    """
    try:
        config = load_config()
        project = config.project
    except (FileNotFoundError, KeyError, AttributeError):
        project = "agenttree"

    expected_session = f"{project}-{host}-{issue_id}"

    for session_name, created in _get_tmux_sessions():
        if session_name == expected_session:
            return _build_agent_from_session(issue_id, host, session_name, created, project)

    return None


def get_active_agents_for_issue(issue_id: str) -> list[ActiveAgent]:
    """Get all active agents for an issue (across all hosts).

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

<<<<<<< HEAD
    for key, agent_data in state.get("active_agents", {}).items():
        # Match both new format (062:agent) and old format (062)
        if key.startswith(prefix) or key == issue_id:
            agents.append(ActiveAgent.from_dict(agent_data))
=======
    agents = []
    for session_name, created in _get_tmux_sessions():
        parsed = _parse_tmux_session_name(session_name, project)
        if parsed and parsed[0] == issue_id:
            sid, host = parsed
            agents.append(_build_agent_from_session(sid, host, session_name, created, project))
>>>>>>> origin/main

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
            issue_id, host = parsed
            agents.append(_build_agent_from_session(issue_id, host, session_name, created, project))

    return agents


def register_agent(agent: ActiveAgent) -> None:
    """Register a new active agent.

    With dynamic state, registration happens automatically when the tmux
    session is created. This function is a no-op kept for API compatibility.

    Args:
        agent: ActiveAgent to register (ignored)
    """
    # No-op: tmux session creation IS registration
    pass


def update_agent_container_id(issue_id: str, container_id: str, host: str = "agent") -> None:
    """Update an agent's container ID.

    With dynamic state, we don't persist container IDs. They're looked up
    when needed via find_container_by_worktree(). This is a no-op.

    Args:
        issue_id: Issue ID
        container_id: Container UUID (ignored)
        host: Agent host type (ignored)
    """
    # No-op: container IDs are looked up dynamically when needed
    pass


def unregister_agent(issue_id: str, host: str = "agent") -> Optional[ActiveAgent]:
    """Unregister an active agent by stopping its tmux session.

    With dynamic state, unregistration = killing the tmux session.
    This function stops the agent and returns its info.

    Args:
        issue_id: Issue ID to unregister
        host: Agent host type (default: "agent")

    Returns:
        The ActiveAgent if found, or None
    """
    # Get agent info before stopping
    agent = get_active_agent(issue_id, host)
    if agent:
        # Actually stop the agent (kills tmux session = unregistration)
        stop_agent(issue_id, host, quiet=True)
    return agent


def unregister_all_agents_for_issue(issue_id: str) -> list[ActiveAgent]:
    """Unregister all agents for an issue (across all hosts).

    Stops all agents (across all hosts) and returns their info.

    Args:
        issue_id: Issue ID

    Returns:
        List of ActiveAgent objects that were stopped
    """
    agents = get_active_agents_for_issue(issue_id)
    for agent in agents:
        stop_agent(issue_id, agent.host, quiet=True)
    return agents


def stop_agent(issue_id: str, host: str = "agent", quiet: bool = False) -> bool:
    """Stop an active agent - kills tmux and stops container.

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

    # 2. Stop container (look up by worktree mount)
    try:
        from agenttree.container import get_container_runtime, find_container_by_worktree

        runtime = get_container_runtime()
        if runtime.runtime:
            worktree_path = Path(agent.worktree)
            if not worktree_path.is_absolute():
                worktree_path = Path.cwd() / worktree_path

            container_id = find_container_by_worktree(worktree_path)
            if container_id:
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

    Args:
        issue_id: Issue ID (e.g., "023" or "1045")
        base_port: Base port number (default 9000)

    Returns:
        Port number for this issue
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
    """Create an ActiveAgent object for an issue.

    Note: With dynamic state, this doesn't register anything. The agent
    becomes "registered" when its tmux session is created.

    Args:
        issue_id: Issue ID
        slug: Issue slug
        worktree_path: Path to worktree
        port: Allocated port
        project: Project name
        host: Agent host type (default: "agent")

    Returns:
        ActiveAgent object (not yet running until tmux session created)
    """
    names = get_issue_names(issue_id, slug, project, host)

    return ActiveAgent(
        issue_id=issue_id,
        host=host,
        container=names["container"],
        worktree=worktree_path,
        branch=names["branch"],
        port=port,
        tmux_session=names["tmux_session"],
        started=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# Legacy compatibility - these functions are no longer needed but kept for imports
def load_state() -> dict:
    """Legacy function - returns empty state dict."""
    return {"active_agents": {}}


def save_state(state: dict) -> None:
    """Legacy function - no-op."""
    pass


def get_state_path() -> Path:
    """Legacy function - returns path that won't be used."""
    return Path.cwd() / "_agenttree" / "state.yaml"

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
    port = get_port_for_issue(issue_id)

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


def register_agent(agent: ActiveAgent) -> None:
    """Register a new active agent.

    With dynamic state, registration happens automatically when the tmux
    session is created. This function is a no-op kept for API compatibility.

    Args:
        agent: ActiveAgent to register (ignored)
    """
    # No-op: tmux session creation IS registration
    pass


def update_agent_container_id(issue_id: str, container_id: str, role: str = "developer") -> None:
    """Update an agent's container ID.

    With dynamic state, we don't persist container IDs. They're looked up
    when needed via find_container_by_worktree(). This is a no-op.

    Args:
        issue_id: Issue ID
        container_id: Container UUID (ignored)
        role: Agent role (ignored)
    """
    # No-op: container IDs are looked up dynamically when needed
    pass


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
        stop_agent(issue_id, agent.role, quiet=True)
    return agents


def stop_agent(issue_id: str, role: str = "developer", quiet: bool = False) -> bool:
    """Stop an active agent - kills tmux and stops container.

    Args:
        issue_id: Issue ID to stop
        role: Agent role (default: "developer")
        quiet: If True, suppress output messages

    Returns:
        True if something was stopped, False if nothing to stop
    """
    config = load_config()
    stopped_something = False
    
    if not quiet:
        from rich.console import Console
        console = Console()

    # 1. Kill tmux session if it exists
    try:
        from agenttree.tmux import kill_session, session_exists
        session_name = f"{config.project}-{role}-{issue_id}"
        if session_exists(session_name):
            kill_session(session_name)
            stopped_something = True
            if not quiet:
                console.print(f"[dim]  Stopped tmux session: {session_name}[/dim]")
    except Exception as e:
        if not quiet:
            console.print(f"[yellow]  Warning: Could not stop tmux session: {e}[/yellow]")

    # 2. Stop container by name (fast and reliable)
    try:
        from agenttree.container import get_container_runtime

        runtime = get_container_runtime()
        if runtime.runtime:
            # Use container name directly - pattern: agenttree-{project}-{issue_id}
            container_name = f"agenttree-{config.project}-{issue_id}"
            
            if runtime.stop(container_name):
                stopped_something = True
                if not quiet:
                    console.print(f"[dim]  Stopped container: {container_name}[/dim]")

            # Remove container (Apple Containers do NOT auto-remove, Docker needs explicit rm too)
            if runtime.delete(container_name):
                stopped_something = True
    except Exception as e:
        if not quiet:
            console.print(f"[yellow]  Warning: Could not stop container: {e}[/yellow]")

    if stopped_something and not quiet:
        console.print(f"[green]✓ Agent stopped for issue #{issue_id}[/green]")

    return stopped_something


def stop_all_agents_for_issue(issue_id: str, quiet: bool = False) -> int:
    """Stop all agents for an issue (across all roles).

    Args:
        issue_id: Issue ID
        quiet: If True, suppress output messages

    Returns:
        Number of agents stopped
    """
    agents = get_active_agents_for_issue(issue_id)
    count = 0
    for agent in agents:
        if stop_agent(issue_id, agent.role, quiet):
            count += 1
    return count


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

    return {
        "container": f"{project}-{role}-{issue_id}",
        "worktree": f"issue-{issue_id}-{short_slug}",
        "branch": f"issue-{issue_id}-{short_slug}",
        "tmux_session": f"{project}-{role}-{issue_id}",
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


def cleanup_orphaned_containers(quiet: bool = False) -> int:
    """Stop containers that don't have a corresponding tmux session.
    
    This handles the case where tmux sessions are killed but containers keep running.
    Looks for containers named like {project}-{role}-{issue_id} and stops any
    that don't have a matching tmux session.
    
    Args:
        quiet: If True, suppress output messages
        
    Returns:
        Number of containers stopped
    """
    from agenttree.container import get_container_runtime
    from agenttree.tmux import session_exists
    
    if not quiet:
        from rich.console import Console
        console = Console()
    
    runtime = get_container_runtime()
    if not runtime.runtime:
        return 0
        
    config = load_config()
    stopped = 0
    
    # Get list of running containers
    try:
        import json
        result = subprocess.run(
            [runtime.runtime, "list", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return 0
            
        containers = json.loads(result.stdout) if result.stdout.strip() else []
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        return 0
    
    # Check each container to see if it matches our naming pattern
    # Pattern: agenttree-{project}-{issue_id}
    import re
    pattern = rf"^agenttree-{re.escape(config.project)}-(\d+)$"
    
    for container in containers:
        # Handle Apple Container's nested JSON structure
        container_config = container.get("configuration", {})
        name = container_config.get("name") or container.get("name") or ""
        if isinstance(name, list):
            name = name[0] if name else ""
        name = name.strip("/")  # Docker adds leading slash
        
        match = re.match(pattern, name)
        if not match:
            continue
            
        issue_id = match.group(1)
        
        # Check if there's a tmux session for this container (developer is default role)
        session_name = f"{config.project}-developer-{issue_id}"
        
        if not session_exists(session_name):
            # Orphaned container - stop and remove it
            container_id = container_config.get("id") or container.get("uuid") or container.get("id") or name
            
            try:
                subprocess.run(
                    [runtime.runtime, "stop", container_id],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                subprocess.run(
                    [runtime.runtime, "delete", container_id],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                stopped += 1
                if not quiet:
                    console.print(f"[dim]Cleaned up orphaned container: {name}[/dim]")
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
    
    if not quiet and stopped > 0:
        console.print(f"[green]✓ Cleaned up {stopped} orphaned container(s)[/green]")
    
    return stopped


def cleanup_all_agenttree_containers(quiet: bool = False) -> int:
    """Remove ALL agenttree containers (by name prefix OR image name).
    
    Uses the container runtime abstraction which handles differences
    between Apple Container, Docker, and Podman.
    
    Args:
        quiet: If True, suppress output messages
        
    Returns:
        Number of containers removed
    """
    from agenttree.container import get_container_runtime
    
    if not quiet:
        from rich.console import Console
        console = Console()
    
    runtime = get_container_runtime()
    if not runtime.runtime:
        return 0
    
    config = load_config()
    project_prefix = f"agenttree-{config.project}-"
    
    # Get all containers and filter for agenttree ones
    containers = runtime.list_all()
    removed = 0
    
    for c in containers:
        name = c.get("name", "") or c.get("id", "")
        image = c.get("image", "")
        
        # Match by name prefix OR by agenttree image (catches legacy unnamed containers)
        is_ours = (
            name.startswith(project_prefix) or 
            name.startswith("agenttree-") or 
            "agenttree" in image
        )
        
        if is_ours and name:
            runtime.stop(name)
            if runtime.delete(name):
                removed += 1
                if not quiet:
                    console.print(f"[dim]Removed: {name}[/dim]")
    
    if not quiet and removed:
        console.print(f"[green]✓ Removed {removed} container(s)[/green]")
    
    return removed

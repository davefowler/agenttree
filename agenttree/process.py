"""Process-based agent runner for AgentTree.

Instead of running each agent in a separate container with tmux,
agents run as `claude -p --dangerously-skip-permissions` subprocesses
directly in their worktree directories. This is simpler, faster, and
eliminates all container debugging nightmares.

State is tracked via a JSON file (.agenttree-processes.json) in the
repo root, keyed by issue_id:role. Dead processes are detected by
checking if the PID is still alive.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("agenttree.process")

# State file location (in repo root)
STATE_FILENAME = ".agenttree-processes.json"


@dataclass
class AgentProcess:
    """A running agent subprocess."""

    issue_id: int
    role: str
    pid: int
    worktree: str
    branch: str
    port: int
    log_file: str
    started: str  # ISO format timestamp
    model: str = ""

    @property
    def state_key(self) -> str:
        return f"{self.issue_id}:{self.role}"


def _state_file_path() -> Path:
    """Get path to the process state file."""
    return Path.cwd() / STATE_FILENAME


def _load_state() -> dict[str, dict[str, Any]]:
    """Load process state from disk."""
    path = _state_file_path()
    if not path.exists():
        return {}
    try:
        result: dict[str, dict[str, Any]] = json.loads(path.read_text())
        return result
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict[str, dict[str, Any]]) -> None:
    """Save process state to disk."""
    path = _state_file_path()
    path.write_text(json.dumps(state, indent=2) + "\n")


def is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running.
    
    Note: pid=0 is special on Linux (sends to process group), so we
    explicitly return False for it to avoid false positives.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # Signal 0 = check existence
        return True
    except (OSError, ProcessLookupError):
        return False


def register_agent(agent: AgentProcess) -> None:
    """Register a running agent in the state file."""
    state = _load_state()
    state[agent.state_key] = asdict(agent)
    _save_state(state)


def unregister_agent(issue_id: int, role: str) -> AgentProcess | None:
    """Remove an agent from the state file. Returns the agent if found."""
    key = f"{issue_id}:{role}"
    state = _load_state()
    data = state.pop(key, None)
    if data:
        _save_state(state)
        return AgentProcess(**data)
    return None


def get_agent(issue_id: int, role: str) -> AgentProcess | None:
    """Get a registered agent. Returns None if not registered or dead."""
    key = f"{issue_id}:{role}"
    state = _load_state()
    data = state.get(key)
    if not data:
        return None
    agent = AgentProcess(**data)
    if not is_pid_alive(agent.pid):
        # Clean up dead entry
        state.pop(key, None)
        _save_state(state)
        return None
    return agent


def get_agents_for_issue(issue_id: int) -> list[AgentProcess]:
    """Get all living agents for an issue."""
    state = _load_state()
    agents = []
    prefix = f"{issue_id}:"
    dead_keys = []
    for key, data in state.items():
        if key.startswith(prefix):
            agent = AgentProcess(**data)
            if is_pid_alive(agent.pid):
                agents.append(agent)
            else:
                dead_keys.append(key)
    # Clean up dead entries
    if dead_keys:
        for k in dead_keys:
            state.pop(k, None)
        _save_state(state)
    return agents


def list_agents() -> list[AgentProcess]:
    """Get all living agents."""
    state = _load_state()
    agents = []
    dead_keys = []
    for key, data in state.items():
        agent = AgentProcess(**data)
        if is_pid_alive(agent.pid):
            agents.append(agent)
        else:
            dead_keys.append(key)
    # Clean up dead entries
    if dead_keys:
        for k in dead_keys:
            state.pop(k, None)
        _save_state(state)
    return agents


def start_agent(
    issue_id: int,
    role: str,
    worktree_path: Path,
    branch: str,
    port: int,
    prompt: str,
    model: str = "sonnet",
    tool: str = "claude",
) -> AgentProcess:
    """Start a claude -p subprocess for an issue.

    Args:
        issue_id: Issue ID
        role: Agent role (e.g., "developer")
        worktree_path: Path to the worktree (cwd for the subprocess)
        branch: Git branch name
        port: Assigned port
        prompt: The full prompt to send to claude -p
        model: Model to use
        tool: CLI tool name (default: "claude")

    Returns:
        AgentProcess with the running subprocess info
    """
    # Create log file for output capture
    log_dir = worktree_path / ".agenttree"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"agent-{role}.log"

    # Build claude command
    cmd = [tool, "-p", "--dangerously-skip-permissions"]
    if model:
        cmd.extend(["--model", model])

    # Open log file for writing - subprocess inherits this fd
    log_handle = open(log_file, "w")

    try:
        # Start subprocess
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(worktree_path),
            # Don't let parent signals kill the child
            preexec_fn=os.setpgrp,
        )
    finally:
        # Close parent's copy of the fd - subprocess keeps writing via its inherited copy
        log_handle.close()

    # Write prompt to stdin and close it
    if proc.stdin:
        proc.stdin.write(prompt.encode("utf-8"))
        proc.stdin.close()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    agent = AgentProcess(
        issue_id=issue_id,
        role=role,
        pid=proc.pid,
        worktree=str(worktree_path),
        branch=branch,
        port=port,
        log_file=str(log_file),
        started=now,
        model=model,
    )

    register_agent(agent)
    log.info("Started agent PID %d for issue #%d (%s)", proc.pid, issue_id, role)
    return agent


def stop_agent_process(issue_id: int, role: str) -> bool:
    """Stop an agent by killing its process.

    Returns True if something was stopped.
    """
    agent = get_agent(issue_id, role)
    if not agent:
        # Check state file even if PID is dead (cleanup)
        removed = unregister_agent(issue_id, role)
        return removed is not None

    # Kill the process group to also kill any child processes
    try:
        os.killpg(os.getpgid(agent.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass

    # Give it a moment to die
    for _ in range(10):
        if not is_pid_alive(agent.pid):
            break
        time.sleep(0.1)

    # Force kill if still alive
    if is_pid_alive(agent.pid):
        try:
            os.killpg(os.getpgid(agent.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass

    unregister_agent(issue_id, role)
    log.info("Stopped agent PID %d for issue #%d (%s)", agent.pid, issue_id, role)
    return True


def stop_all_for_issue(issue_id: int) -> int:
    """Stop all agents for an issue. Returns count stopped."""
    agents = get_agents_for_issue(issue_id)
    count = 0
    for agent in agents:
        if stop_agent_process(agent.issue_id, agent.role):
            count += 1
    # Also try default role in case state was stale
    from agenttree.config import DEFAULT_ROLE
    if not any(a.role == DEFAULT_ROLE for a in agents):
        if stop_agent_process(issue_id, DEFAULT_ROLE):
            count += 1
    return count


def get_agent_output(issue_id: int, role: str, lines: int = 50) -> str:
    """Read recent output from an agent's log file.

    Args:
        issue_id: Issue ID
        role: Agent role
        lines: Number of lines to return from the end

    Returns:
        Recent output text, or empty string if no log
    """
    agent = get_agent(issue_id, role)
    if not agent:
        # Try to find log file even if agent is dead
        from agenttree.config import load_config
        config = load_config()
        worktree_path = config.get_issue_worktree_path(issue_id)
        log_file = worktree_path / ".agenttree" / f"agent-{role}.log"
        if not log_file.exists():
            return ""
    else:
        log_file = Path(agent.log_file)

    if not log_file.exists():
        return ""

    try:
        # Read last N lines efficiently
        with open(log_file, "r") as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:])
    except OSError:
        return ""


def write_agent_notification(issue_id: int, message: str) -> bool:
    """Write a notification file for an agent to read on next `agenttree next`.
    
    Since subprocess-based agents can't receive messages mid-flight,
    notifications are written to a file that the agent reads when it
    next calls `agenttree next`.
    
    Args:
        issue_id: Issue ID
        message: Notification message
        
    Returns:
        True if notification was written successfully
    """
    from agenttree.config import load_config
    
    try:
        config = load_config()
        worktree_path = config.get_issue_worktree_path(issue_id)
        
        notification_dir = worktree_path / ".agenttree"
        notification_dir.mkdir(exist_ok=True)
        notification_file = notification_dir / "pending_notification.txt"
        
        # Append to existing notifications (one per line)
        with open(notification_file, "a") as f:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            f.write(f"[{timestamp}] {message}\n")
        
        log.info("Wrote notification for issue #%d: %s", issue_id, message[:50])
        return True
    except Exception as e:
        log.warning("Failed to write notification for issue #%d: %s", issue_id, e)
        return False


def read_agent_notifications(issue_id: int) -> list[str]:
    """Read and clear pending notifications for an agent.
    
    Called by `agenttree next` to show any notifications that arrived
    while the agent was working.
    
    Args:
        issue_id: Issue ID
        
    Returns:
        List of notification messages (empty if none)
    """
    from agenttree.config import load_config
    
    try:
        config = load_config()
        worktree_path = config.get_issue_worktree_path(issue_id)
        notification_file = worktree_path / ".agenttree" / "pending_notification.txt"
        
        if not notification_file.exists():
            return []
        
        notifications = notification_file.read_text().strip().split("\n")
        notifications = [n for n in notifications if n.strip()]
        
        # Clear the file after reading
        notification_file.unlink()
        
        return notifications
    except Exception as e:
        log.warning("Failed to read notifications for issue #%d: %s", issue_id, e)
        return []


def build_agent_prompt(
    issue_id: int,
    *,
    has_merge_conflicts: bool = False,
    is_restart: bool = False,
) -> str:
    """Build the prompt that gets piped to `claude -p`.

    The prompt tells the agent what issue to work on and to use
    `agenttree next` to get stage instructions.
    """
    if has_merge_conflicts:
        return (
            f"You are an AI agent working on issue #{issue_id}. "
            f"IMPORTANT: Your branch was rebased onto latest main and there are MERGE CONFLICTS. "
            f"Run 'git status' to see conflicted files and resolve them FIRST before any other work. "
            f"After resolving conflicts and committing, run: agenttree next\n"
            f"When you complete a stage, run 'agenttree next' again to advance to the next stage. "
            f"Keep working through stages until you hit a human review stage or finish."
        )
    elif is_restart:
        return (
            f"SESSION RESTARTED - Issue #{issue_id}. "
            f"Your branch was rebased onto latest main to get CLI updates. "
            f"Any uncommitted work was auto-committed. "
            f"Run 'agenttree next' to see your current stage and resume work.\n"
            f"When you complete a stage, run 'agenttree next' again to advance to the next stage. "
            f"Keep working through stages until you hit a human review stage or finish."
        )
    else:
        return (
            f"You are an AI agent working on issue #{issue_id}. "
            f"Run 'agenttree next' to see your workflow instructions and current stage.\n"
            f"When you complete a stage, run 'agenttree next' again to advance to the next stage. "
            f"Keep working through stages until you hit a human review stage or finish."
        )

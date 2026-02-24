"""Agent manager for tracking tmux sessions."""

import subprocess
from typing import Optional

from agenttree.config import load_config
from agenttree.worktree import WorktreeManager

# Load config at module level
_config = load_config()


class AgentManager:
    """Manages agent tmux session checks."""

    def __init__(self, worktree_manager: Optional[WorktreeManager] = None):
        self.worktree_manager = worktree_manager
        self._active_sessions: Optional[set[str]] = None

    def _get_active_sessions(self) -> set[str]:
        """Get all active tmux session names in one call."""
        if self._active_sessions is not None:
            return self._active_sessions

        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                self._active_sessions = set(result.stdout.strip().split("\n"))
            else:
                self._active_sessions = set()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            self._active_sessions = set()

        return self._active_sessions

    def clear_session_cache(self) -> None:
        """Clear the cached session list (call at start of each request)."""
        self._active_sessions = None

    def _check_issue_tmux_session(self, issue_id: int) -> bool:
        """Check if tmux session exists for an issue-bound agent.

        Note: Manager is agent 0, so _check_issue_tmux_session(0) checks manager.
        Uses config.get_issue_session_patterns() for consistent naming.
        """
        active = self._get_active_sessions()
        patterns = _config.get_issue_session_patterns(issue_id)
        return any(name in active for name in patterns)


# Global agent manager singleton - initialized at import time
agent_manager = AgentManager()

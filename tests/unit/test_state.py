"""Tests for agenttree.state module.

Note: State is now derived dynamically from tmux sessions.
register_agent(), unregister_agent(), save_state() are no-ops.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agenttree.state import (
    unregister_agent,
    get_active_agent,
    list_active_agents,
    ActiveAgent,
    _parse_tmux_session_name,
)
from agenttree.api import stop_agent




class TestDynamicState:
    """Tests for dynamic state derived from tmux sessions."""

    def test_parse_tmux_session_name_valid(self):
        """Should parse valid session names."""
        result = _parse_tmux_session_name("agenttree-developer-042", "agenttree")
        assert result == (42, "developer")

        result = _parse_tmux_session_name("agenttree-review-123", "agenttree")
        assert result == (123, "review")

        result = _parse_tmux_session_name("myproject-developer-001", "myproject")
        assert result == (1, "developer")

    def test_parse_tmux_session_name_invalid(self):
        """Should return None for non-matching session names."""
        # Wrong project
        assert _parse_tmux_session_name("other-agent-042", "agenttree") is None

        # No issue ID
        assert _parse_tmux_session_name("agenttree-agent", "agenttree") is None

        # Random session
        assert _parse_tmux_session_name("random-session", "agenttree") is None


    @patch("agenttree.issues.get_issue")
    @patch("agenttree.state._get_tmux_sessions")
    @patch("agenttree.state.load_config")
    def test_get_active_agent_finds_session(self, mock_config, mock_sessions, mock_get_issue):
        """get_active_agent should find matching tmux session."""
        mock_config.return_value = MagicMock(project="agenttree")
        mock_sessions.return_value = [
            ("agenttree-developer-042", "1704067200"),  # Unix timestamp
        ]
        mock_issue = MagicMock()
        mock_issue.worktree_dir = "/tmp/worktree"
        mock_issue.branch = "issue-042"
        mock_get_issue.return_value = mock_issue

        agent = get_active_agent(42, "developer")

        assert agent is not None
        assert agent.issue_id == 42
        assert agent.role == "developer"
        assert agent.tmux_session == "agenttree-developer-042"

    @patch("agenttree.state._get_tmux_sessions")
    @patch("agenttree.state.load_config")
    def test_get_active_agent_returns_none_when_no_session(self, mock_config, mock_sessions):
        """get_active_agent should return None when no matching session."""
        mock_config.return_value = MagicMock(project="agenttree")
        mock_sessions.return_value = [
            ("agenttree-developer-001", "1704067200"),
        ]

        agent = get_active_agent(42, "developer")

        assert agent is None

    @patch("agenttree.issues.get_issue")
    @patch("agenttree.state._get_tmux_sessions")
    @patch("agenttree.state.load_config")
    def test_list_active_agents(self, mock_config, mock_sessions, mock_get_issue):
        """list_active_agents should return all agents from tmux sessions."""
        mock_config.return_value = MagicMock(project="agenttree")
        mock_sessions.return_value = [
            ("agenttree-developer-042", "1704067200"),
            ("agenttree-review-042", "1704067300"),
            ("agenttree-developer-043", "1704067400"),
            ("other-session", "1704067500"),  # Not matching
        ]
        mock_issue = MagicMock()
        mock_issue.worktree_dir = "/tmp/worktree"
        mock_issue.branch = "issue-042"
        mock_get_issue.return_value = mock_issue

        agents = list_active_agents()

        assert len(agents) == 3
        issue_ids = {a.issue_id for a in agents}
        assert 42 in issue_ids
        assert 43 in issue_ids


class TestStopAgentServeSession:
    """Tests for serve session cleanup in stop_agent()."""

    def test_stop_agent_kills_serve_session(self):
        """stop_agent should kill the serve session before the agent session."""
        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.get_issue_tmux_session.return_value = "myproject-developer-042"

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", return_value=True), \
             patch("agenttree.tmux.kill_session") as mock_kill, \
             patch("agenttree.container.get_container_runtime") as mock_runtime:
            mock_runtime.return_value.runtime = None
            result = stop_agent(42, quiet=True)

        assert result is True
        # Serve session should be killed
        mock_kill.assert_any_call("myproject-serve-042")
        # Agent session should also be killed
        mock_kill.assert_any_call("myproject-developer-042")

    def test_stop_agent_skips_serve_when_no_session(self):
        """stop_agent should skip serve cleanup when session doesn't exist."""
        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.get_issue_tmux_session.return_value = "myproject-developer-042"

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", side_effect=lambda name: name == "myproject-developer-042"), \
             patch("agenttree.tmux.kill_session") as mock_kill, \
             patch("agenttree.container.get_container_runtime") as mock_runtime:
            mock_runtime.return_value.runtime = None
            result = stop_agent(42, quiet=True)

        assert result is True
        # Only agent session should be killed, not serve session
        mock_kill.assert_called_once_with("myproject-developer-042")

    def test_stop_agent_serve_failure_does_not_block(self):
        """If serve session cleanup fails, agent stop should continue."""
        def session_exists_side_effect(name):
            if name == "myproject-serve-042":
                raise subprocess.CalledProcessError(1, "tmux")
            return True

        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.get_issue_tmux_session.return_value = "myproject-developer-042"

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", side_effect=session_exists_side_effect), \
             patch("agenttree.tmux.kill_session") as mock_kill, \
             patch("agenttree.container.get_container_runtime") as mock_runtime:
            mock_runtime.return_value.runtime = None
            result = stop_agent(42, quiet=True)

        assert result is True
        # Agent session should still be killed despite serve failure
        mock_kill.assert_called_once_with("myproject-developer-042")



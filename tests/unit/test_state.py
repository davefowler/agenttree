"""Tests for agenttree.state module.

Note: State is now derived dynamically from tmux sessions.
register_agent(), unregister_agent(), save_state() are no-ops.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agenttree.state import (
    load_state,
    save_state,
    get_port_for_issue,
    register_agent,
    unregister_agent,
    get_active_agent,
    list_active_agents,
    stop_agent,
    ActiveAgent,
    _parse_tmux_session_name,
)


class TestDeterministicPorts:
    """Tests for deterministic port allocation from issue ID."""

    def test_get_port_for_issue_basic(self):
        """Port should be base + issue_id % 1000."""
        assert get_port_for_issue("001", base_port=9000) == 9001
        assert get_port_for_issue("023", base_port=9000) == 9023
        assert get_port_for_issue("100", base_port=9000) == 9100
        assert get_port_for_issue("999", base_port=9000) == 9999

    def test_get_port_for_issue_modulo_wrapping(self):
        """Issues over 1000 should wrap around."""
        # Issue 1001 should get same port as issue 1
        assert get_port_for_issue("1001", base_port=9000) == 9001
        assert get_port_for_issue("1023", base_port=9000) == 9023
        assert get_port_for_issue("2045", base_port=9000) == 9045

    def test_get_port_for_issue_custom_base(self):
        """Should work with different base ports."""
        assert get_port_for_issue("023", base_port=3000) == 3023
        assert get_port_for_issue("023", base_port=8000) == 8023
        assert get_port_for_issue("023", base_port=10000) == 10023

    def test_get_port_for_issue_string_parsing(self):
        """Should handle both padded and unpadded issue IDs."""
        # Leading zeros shouldn't matter
        assert get_port_for_issue("023", base_port=9000) == 9023
        assert get_port_for_issue("23", base_port=9000) == 9023

    def test_port_determinism(self):
        """Same issue ID should always return same port."""
        for _ in range(100):
            assert get_port_for_issue("042", base_port=9000) == 9042


class TestDynamicState:
    """Tests for dynamic state derived from tmux sessions."""

    def test_parse_tmux_session_name_valid(self):
        """Should parse valid session names."""
        result = _parse_tmux_session_name("agenttree-developer-042", "agenttree")
        assert result == ("042", "developer")

        result = _parse_tmux_session_name("agenttree-review-123", "agenttree")
        assert result == ("123", "review")

        result = _parse_tmux_session_name("myproject-developer-001", "myproject")
        assert result == ("001", "developer")

    def test_parse_tmux_session_name_invalid(self):
        """Should return None for non-matching session names."""
        # Wrong project
        assert _parse_tmux_session_name("other-agent-042", "agenttree") is None

        # No issue ID
        assert _parse_tmux_session_name("agenttree-agent", "agenttree") is None

        # Random session
        assert _parse_tmux_session_name("random-session", "agenttree") is None

    def test_register_agent_is_noop(self):
        """register_agent should be a no-op (tmux creation is registration)."""
        agent = ActiveAgent(
            issue_id="042",
            role="developer",
            container="test-container",
            worktree=Path("/tmp/worktree"),
            branch="test-branch",
            port=9042,
            tmux_session="test-session",
            started="2024-01-01T00:00:00Z",
        )
        # Should not raise
        register_agent(agent)

    def test_save_state_is_noop(self):
        """save_state should be a no-op."""
        # Should not raise
        save_state({"active_agents": {"test": "data"}})

    def test_load_state_returns_empty_default(self):
        """load_state should return empty default state."""
        state = load_state()
        assert "active_agents" in state
        assert state["active_agents"] == {}

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

        agent = get_active_agent("042", "developer")

        assert agent is not None
        assert agent.issue_id == "042"
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

        agent = get_active_agent("042", "developer")

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
        assert "042" in issue_ids
        assert "043" in issue_ids


class TestStopAgentServeSession:
    """Tests for serve session cleanup in stop_agent()."""

    def test_stop_agent_kills_serve_session(self):
        """stop_agent should kill the serve session before the agent session."""
        mock_config = MagicMock()
        mock_config.project = "myproject"

        with patch("agenttree.state.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", return_value=True), \
             patch("agenttree.tmux.kill_session") as mock_kill, \
             patch("agenttree.container.get_container_runtime") as mock_runtime:
            mock_runtime.return_value.runtime = None
            result = stop_agent("042", quiet=True)

        assert result is True
        # Serve session should be killed
        mock_kill.assert_any_call("myproject-serve-042")
        # Agent session should also be killed
        mock_kill.assert_any_call("myproject-developer-042")

    def test_stop_agent_skips_serve_when_no_session(self):
        """stop_agent should skip serve cleanup when session doesn't exist."""
        mock_config = MagicMock()
        mock_config.project = "myproject"

        with patch("agenttree.state.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", side_effect=lambda name: name == "myproject-developer-042"), \
             patch("agenttree.tmux.kill_session") as mock_kill, \
             patch("agenttree.container.get_container_runtime") as mock_runtime:
            mock_runtime.return_value.runtime = None
            result = stop_agent("042", quiet=True)

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

        with patch("agenttree.state.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", side_effect=session_exists_side_effect), \
             patch("agenttree.tmux.kill_session") as mock_kill, \
             patch("agenttree.container.get_container_runtime") as mock_runtime:
            mock_runtime.return_value.runtime = None
            result = stop_agent("042", quiet=True)

        assert result is True
        # Agent session should still be killed despite serve failure
        mock_kill.assert_called_once_with("myproject-developer-042")


class TestLegacyStatePath:
    """Tests for legacy state path function."""

    def test_get_state_path_returns_path(self):
        """get_state_path should return a Path object."""
        from agenttree.state import get_state_path
        path = get_state_path()
        assert isinstance(path, Path)
        assert path.name == "state.yaml"

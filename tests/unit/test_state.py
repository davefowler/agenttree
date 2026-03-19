"""Tests for agenttree.state module.

State is now derived from process tracking (PID-based) instead of tmux sessions.
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agenttree.state import (
    get_active_agent,
    list_active_agents,
    ActiveAgent,
    create_agent_for_issue,
    get_issue_names,
)
from agenttree.process import (
    AgentProcess,
    register_agent,
    unregister_agent,
    get_agent,
    list_agents,
    is_pid_alive,
    _load_state,
    _save_state,
    _state_file_path,
)


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    """Set up a temp state file."""
    monkeypatch.chdir(tmp_path)
    return tmp_path / ".agenttree-processes.json"


@pytest.fixture
def mock_config(monkeypatch):
    """Mock load_config for state module."""
    config = MagicMock()
    config.project = "testproject"
    config.get_port_for_issue.return_value = 9042
    config.get_issue_worktree_path.return_value = Path("/tmp/worktrees/issue-042")
    monkeypatch.setattr("agenttree.state.load_config", lambda: config)
    monkeypatch.setattr("agenttree.process.load_config", lambda: config, raising=False)
    return config


class TestProcessState:
    """Tests for process-based state tracking."""

    def test_register_and_get_agent(self, state_file):
        """Should register and retrieve an agent."""
        agent = AgentProcess(
            issue_id=42,
            role="developer",
            pid=99999,
            worktree="/tmp/wt",
            branch="issue-042",
            port=9042,
            log_file="/tmp/wt/.agenttree/agent-developer.log",
            started="2024-01-01T00:00:00Z",
        )
        register_agent(agent)

        # State file should exist
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert "42:developer" in state

    def test_unregister_agent(self, state_file):
        """Should remove an agent from state."""
        agent = AgentProcess(
            issue_id=42,
            role="developer",
            pid=99999,
            worktree="/tmp/wt",
            branch="issue-042",
            port=9042,
            log_file="/tmp/log",
            started="2024-01-01T00:00:00Z",
        )
        register_agent(agent)
        removed = unregister_agent(42, "developer")
        assert removed is not None
        assert removed.issue_id == 42

        # Should be gone
        state = json.loads(state_file.read_text())
        assert "42:developer" not in state

    def test_get_agent_returns_none_for_dead_pid(self, state_file):
        """Should return None and clean up if PID is dead."""
        agent = AgentProcess(
            issue_id=42,
            role="developer",
            pid=99999999,  # Very unlikely to be alive
            worktree="/tmp/wt",
            branch="issue-042",
            port=9042,
            log_file="/tmp/log",
            started="2024-01-01T00:00:00Z",
        )
        register_agent(agent)

        result = get_agent(42, "developer")
        assert result is None  # Dead PID cleaned up

    def test_list_agents_cleans_dead(self, state_file):
        """list_agents should clean up dead PIDs."""
        _save_state({
            "42:developer": {
                "issue_id": 42,
                "role": "developer",
                "pid": 99999999,
                "worktree": "/tmp/wt",
                "branch": "issue-042",
                "port": 9042,
                "log_file": "/tmp/log",
                "started": "2024-01-01T00:00:00Z",
            }
        })

        agents = list_agents()
        assert len(agents) == 0  # Dead PID cleaned up


class TestActiveAgentInterface:
    """Tests for the ActiveAgent public interface."""

    def test_create_agent_for_issue(self, mock_config):
        """create_agent_for_issue should return an ActiveAgent."""
        agent = create_agent_for_issue(
            issue_id=42,
            worktree_path=Path("/tmp/wt"),
            port=9042,
            project="testproject",
            role="developer",
        )

        assert isinstance(agent, ActiveAgent)
        assert agent.issue_id == 42
        assert agent.role == "developer"
        assert agent.port == 9042
        assert agent.pid == 0  # Not started yet

    def test_get_issue_names(self, mock_config):
        """get_issue_names should return resource names."""
        names = get_issue_names(42, "testproject", "developer")
        assert names["branch"] == "issue-042"
        assert names["worktree"] == "issue-042"
        assert names["container"] == ""  # No containers anymore
        assert names["tmux_session"] == ""  # Sub-agents don't use tmux


class TestStopAgent:
    """Tests for stop_agent in the new model."""

    @patch("agenttree.process.stop_agent_process")
    @patch("agenttree.tmux.session_exists", return_value=False)
    @patch("agenttree.config.load_config")
    def test_stop_agent_kills_process(self, mock_config, mock_session, mock_stop):
        """stop_agent should kill the process."""
        from agenttree.api import stop_agent

        mock_config.return_value = MagicMock(project="myproject")
        mock_stop.return_value = True

        result = stop_agent(42, quiet=True)
        assert result is True
        mock_stop.assert_called_once_with(42, "developer")

    @patch("agenttree.process.stop_agent_process")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.config.load_config")
    def test_stop_agent_also_kills_serve_session(self, mock_config, mock_session, mock_stop):
        """stop_agent should also kill the serve session if running."""
        from agenttree.api import stop_agent

        mock_config.return_value = MagicMock(project="myproject")
        mock_stop.return_value = True
        mock_session.return_value = True

        with patch("agenttree.tmux.kill_session") as mock_kill:
            result = stop_agent(42, quiet=True)

        assert result is True
        mock_kill.assert_any_call("myproject-serve-042")

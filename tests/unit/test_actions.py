"""Tests for agenttree.actions module."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from agenttree.actions import (
    register_action,
    get_action,
    list_actions,
    ACTION_REGISTRY,
    get_default_event_config,
    check_stalled_agents,
)


class TestActionRegistry:
    """Tests for action registration and lookup."""

    def test_register_action_decorator(self) -> None:
        """@register_action adds function to registry."""
        # Use a unique name to avoid conflicts
        @register_action("test_unique_action_123")
        def my_test_action(agents_dir: Path, **kwargs) -> None:
            pass
        
        assert "test_unique_action_123" in ACTION_REGISTRY
        assert ACTION_REGISTRY["test_unique_action_123"] is my_test_action

    def test_get_action_returns_registered(self) -> None:
        """get_action returns registered action."""
        # Built-in actions should be registered
        action = get_action("sync")
        assert action is not None
        assert callable(action)

    def test_get_action_returns_none_for_unknown(self) -> None:
        """get_action returns None for unknown action."""
        action = get_action("definitely_not_a_real_action_xyz")
        assert action is None

    def test_list_actions_returns_sorted_names(self) -> None:
        """list_actions returns sorted list of action names."""
        actions = list_actions()
        assert isinstance(actions, list)
        assert actions == sorted(actions)
        # Should have built-in actions
        assert "sync" in actions
        assert "start_manager" in actions


class TestBuiltinActions:
    """Tests for built-in action functions."""

    @patch("agenttree.config.load_config")
    @patch("agenttree.tmux.session_exists")
    @patch("subprocess.Popen")
    def test_start_manager_skips_if_running(
        self,
        mock_popen: MagicMock,
        mock_session_exists: MagicMock,
        mock_load_config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """start_manager skips if session already exists."""
        mock_config = MagicMock()
        mock_config.project = "test"
        mock_load_config.return_value = mock_config
        mock_session_exists.return_value = True
        
        action = get_action("start_manager")
        assert action is not None
        action(tmp_path)
        
        # Should not start subprocess
        mock_popen.assert_not_called()

    @patch("agenttree.config.load_config")
    @patch("agenttree.tmux.session_exists")
    @patch("subprocess.Popen")
    def test_start_manager_starts_if_not_running(
        self,
        mock_popen: MagicMock,
        mock_session_exists: MagicMock,
        mock_load_config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """start_manager starts subprocess if session doesn't exist."""
        mock_config = MagicMock()
        mock_config.project = "test"
        mock_load_config.return_value = mock_config
        mock_session_exists.return_value = False
        
        action = get_action("start_manager")
        assert action is not None
        action(tmp_path)
        
        # Should start subprocess
        mock_popen.assert_called_once()

    @patch("agenttree.hooks.is_running_in_container")
    @patch("subprocess.run")
    def test_sync_skips_in_container(
        self,
        mock_run: MagicMock,
        mock_in_container: MagicMock,
        tmp_path: Path,
    ) -> None:
        """sync action skips when running in container."""
        mock_in_container.return_value = True
        
        action = get_action("sync")
        assert action is not None
        action(tmp_path)
        
        # Should not run git commands
        mock_run.assert_not_called()

    @patch("agenttree.agents_repo.check_ci_status")
    def test_check_ci_status_delegates(
        self, mock_check: MagicMock, tmp_path: Path
    ) -> None:
        """check_ci_status delegates to agents_repo function."""
        mock_check.return_value = 2
        
        action = get_action("check_ci_status")
        assert action is not None
        action(tmp_path)
        
        mock_check.assert_called_once_with(tmp_path)

    @patch("agenttree.agents_repo.check_merged_prs")
    def test_check_merged_prs_delegates(
        self, mock_check: MagicMock, tmp_path: Path
    ) -> None:
        """check_merged_prs delegates to agents_repo function."""
        mock_check.return_value = 1
        
        action = get_action("check_merged_prs")
        assert action is not None
        action(tmp_path)
        
        mock_check.assert_called_once_with(tmp_path)


class TestDefaultEventConfigs:
    """Tests for default event configurations."""

    def test_startup_has_defaults(self) -> None:
        """startup event has default config."""
        config = get_default_event_config("startup")
        assert config is not None
        assert isinstance(config, list)
        assert "start_manager" in config
        assert "auto_start_agents" in config

    def test_shutdown_has_defaults(self) -> None:
        """shutdown event has default config."""
        config = get_default_event_config("shutdown")
        assert config is not None
        assert isinstance(config, list)
        assert "sync" in config
        assert "stop_all_agents" in config

    def test_heartbeat_has_defaults(self) -> None:
        """heartbeat event has default config with interval."""
        config = get_default_event_config("heartbeat")
        assert config is not None
        assert isinstance(config, dict)
        assert config["interval_s"] == 10
        assert "actions" in config
        assert len(config["actions"]) > 0

    def test_unknown_event_returns_none(self) -> None:
        """Unknown event returns None."""
        config = get_default_event_config("not_a_real_event")
        assert config is None


class TestCleanupResources:
    """Tests for cleanup_resources action."""

    def test_writes_to_log_file(self, tmp_path: Path) -> None:
        """cleanup_resources writes timestamp to log file."""
        action = get_action("cleanup_resources")
        assert action is not None
        
        log_file = "logs/cleanup.log"
        action(tmp_path, log_file=log_file)
        
        log_path = tmp_path / "logs" / "cleanup.log"
        assert log_path.exists()
        content = log_path.read_text()
        assert "cleanup_resources executed" in content

    def test_no_log_without_log_file(self, tmp_path: Path) -> None:
        """cleanup_resources does nothing without log_file."""
        action = get_action("cleanup_resources")
        assert action is not None
        
        action(tmp_path)  # No log_file param
        
        # Should not create any files
        assert not (tmp_path / "logs").exists()


class TestCheckStalledAgentsReNotification:
    """Tests for stall re-notification logic in check_stalled_agents."""

    def _make_stalled_yaml(self, path: Path, agents: list[dict], dead: list | None = None) -> None:
        """Write a stalled.yaml with given agent data."""
        data = {
            "updated_at": "2026-01-01T00:00:00+00:00",
            "threshold_min": 15,
            "dead_agents": dead or [],
            "stalled_agents": agents,
        }
        (path / "stalled.yaml").write_text(yaml.dump(data, default_flow_style=False))

    def _issue_updated_ago(self, minutes: int) -> str:
        """Return ISO timestamp for `minutes` ago."""
        t = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return t.strftime("%Y-%m-%dT%H:%M:%SZ")

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.is_claude_running", return_value=True)
    @patch("agenttree.tmux.session_exists", return_value=True)
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_first_stall_notifies(
        self, mock_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_claude: MagicMock,
        mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """First time an agent is detected stalled, manager should be notified."""
        issue = MagicMock(id="042", title="Test", stage="implement.code",
                          updated=self._issue_updated_ago(20))
        mock_list.return_value = [issue]
        mock_config.return_value.get_manager_tmux_session.return_value = "mgr"
        mock_config.return_value.get_issue_tmux_session.return_value = "at-042"
        mock_config.return_value.is_parking_lot.return_value = False

        check_stalled_agents(tmp_path, threshold_min=15)

        # Should have notified agent (nudge) and manager (stall report)
        assert mock_send.call_count == 2
        # First call is to agent
        agent_call = mock_send.call_args_list[0]
        assert agent_call[0][0] == "at-042"
        assert "You appear stalled" in agent_call[0][1]
        # Second call is to manager
        mgr_call = mock_send.call_args_list[1]
        assert mgr_call[0][0] == "mgr"
        assert "042" in mgr_call[0][1]

        # stalled.yaml should have notified_at_minutes
        data = yaml.safe_load((tmp_path / "stalled.yaml").read_text())
        assert data["stalled_agents"][0]["notified_at_minutes"] >= 19  # ~20 min

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.is_claude_running", return_value=True)
    @patch("agenttree.tmux.session_exists", return_value=True)
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_same_stall_not_renotified_too_soon(
        self, mock_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_claude: MagicMock,
        mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """If stall hasn't grown by threshold_min since last notification, don't re-notify."""
        # Agent stalled at 25 min, previously notified at 20 min (only 5 min growth, threshold 15)
        self._make_stalled_yaml(tmp_path, [
            {"id": "042", "title": "Test", "stage": "implement.code",
             "stalled_minutes": 20, "notified_at_minutes": 20},
        ])

        issue = MagicMock(id="042", title="Test", stage="implement.code",
                          updated=self._issue_updated_ago(25))
        mock_list.return_value = [issue]
        mock_config.return_value.get_manager_tmux_session.return_value = "mgr"
        mock_config.return_value.get_issue_tmux_session.return_value = "at-042"
        mock_config.return_value.is_parking_lot.return_value = False

        check_stalled_agents(tmp_path, threshold_min=15)

        # Agent still gets nudged, but manager is NOT re-notified (25 - 20 = 5 < 15)
        assert mock_send.call_count == 1
        # Only the agent gets nudged, not the manager
        agent_call = mock_send.call_args_list[0]
        assert agent_call[0][0] == "at-042"
        assert "You appear stalled" in agent_call[0][1]

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.is_claude_running", return_value=True)
    @patch("agenttree.tmux.session_exists", return_value=True)
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_stall_renotifies_after_threshold_growth(
        self, mock_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_claude: MagicMock,
        mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """If stall grows by another threshold_min, re-notify with STILL STALLED."""
        # Previously notified at 20 min
        self._make_stalled_yaml(tmp_path, [
            {"id": "042", "title": "Test", "stage": "implement.code",
             "stalled_minutes": 20, "notified_at_minutes": 20},
        ])

        # Agent now stalled at 36 min (16 more than 20, threshold is 15 → re-notify)
        issue = MagicMock(id="042", title="Test", stage="implement.code",
                          updated=self._issue_updated_ago(36))
        mock_list.return_value = [issue]
        mock_config.return_value.get_manager_tmux_session.return_value = "mgr"
        mock_config.return_value.get_issue_tmux_session.return_value = "at-042"
        mock_config.return_value.is_parking_lot.return_value = False

        check_stalled_agents(tmp_path, threshold_min=15)

        # Should have notified agent (nudge) and manager (re-notification)
        assert mock_send.call_count == 2
        # First call is to agent
        agent_call = mock_send.call_args_list[0]
        assert agent_call[0][0] == "at-042"
        assert "You appear stalled" in agent_call[0][1]
        # Second call is to manager with STILL STALLED
        mgr_call = mock_send.call_args_list[1]
        assert mgr_call[0][0] == "mgr"
        assert "STILL STALLED" in mgr_call[0][1]

        # notified_at_minutes should be updated to ~36
        data = yaml.safe_load((tmp_path / "stalled.yaml").read_text())
        assert data["stalled_agents"][0]["notified_at_minutes"] >= 35

"""Tests for agenttree.actions module."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
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


class TestCheckStalledAgents:
    """Tests for simplified, role-aware stall detection."""

    def _timestamp_ago(self, minutes: int) -> str:
        """Return ISO timestamp for `minutes` ago."""
        t = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return t.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _make_issue(self, issue_id: str = "042", stage: str = "implement.code",
                    minutes_ago: int = 20) -> MagicMock:
        """Create a mock issue with history."""
        history_entry = MagicMock()
        history_entry.timestamp = self._timestamp_ago(minutes_ago)
        issue = MagicMock(
            id=issue_id, title="Test Issue", stage=stage,
            history=[history_entry],
        )
        return issue

    def _make_config(self) -> MagicMock:
        """Create a mock config."""
        cfg = MagicMock()
        cfg.get_manager_tmux_session.return_value = "mgr"
        cfg.is_parking_lot.return_value = False
        cfg.is_human_review.return_value = False
        cfg.role_for.return_value = "developer"
        cfg.get_issue_tmux_session.return_value = "at-042"
        return cfg

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_first_stall_notifies_manager(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """First stall detection sends informational message to manager."""
        mock_load_config.return_value = self._make_config()
        mock_list.return_value = [self._make_issue(minutes_ago=15)]
        # Agent dead, manager running
        mock_exists.side_effect = lambda name: name == "mgr"

        check_stalled_agents(tmp_path, threshold_min=10)

        # Should notify manager
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "042" in msg
        assert "agenttree status --active-only" in msg

        # State should track notification count
        state = yaml.safe_load((tmp_path / ".heartbeat_state.yaml").read_text())
        assert state["stall_notifications"]["042"]["count"] == 1

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_not_renotified_too_soon(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Don't re-notify if not enough time has passed for next notification."""
        mock_load_config.return_value = self._make_config()
        # Issue at 15 min, threshold=10 → first notify at 10, second at 20
        mock_list.return_value = [self._make_issue(minutes_ago=15)]
        # Agent dead, manager running
        mock_exists.side_effect = lambda name: name == "mgr"

        # Pre-seed state: already notified once
        state = {
            "stall_notifications": {
                "042": {"stage": "implement.code", "count": 1, "last_at": self._timestamp_ago(5)},
            },
        }
        (tmp_path / ".heartbeat_state.yaml").write_text(yaml.dump(state))

        check_stalled_agents(tmp_path, threshold_min=10)

        # Should NOT notify (15 min < 20 min = threshold * (1+1))
        mock_send.assert_not_called()

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_renotifies_at_next_threshold(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Re-notifies when elapsed time reaches next threshold multiple."""
        mock_load_config.return_value = self._make_config()
        # Issue at 25 min, threshold=10 → second notify at 20 min
        mock_list.return_value = [self._make_issue(minutes_ago=25)]
        # Agent dead, manager running
        mock_exists.side_effect = lambda name: name == "mgr"

        # Pre-seed state: already notified once
        state = {
            "stall_notifications": {
                "042": {"stage": "implement.code", "count": 1, "last_at": self._timestamp_ago(15)},
            },
        }
        (tmp_path / ".heartbeat_state.yaml").write_text(yaml.dump(state))

        check_stalled_agents(tmp_path, threshold_min=10)

        # Should notify (25 min >= 20 min = threshold * (1+1))
        mock_send.assert_called_once()

        # Count should be 2
        state = yaml.safe_load((tmp_path / ".heartbeat_state.yaml").read_text())
        assert state["stall_notifications"]["042"]["count"] == 2

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_stops_after_max_notifications(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Stops notifying after max_notifications reached."""
        mock_load_config.return_value = self._make_config()
        mock_list.return_value = [self._make_issue(minutes_ago=60)]
        # Agent dead, manager running
        mock_exists.side_effect = lambda name: name == "mgr"

        # Pre-seed state: already notified 3 times (max)
        state = {
            "stall_notifications": {
                "042": {"stage": "implement.code", "count": 3, "last_at": self._timestamp_ago(10)},
            },
        }
        (tmp_path / ".heartbeat_state.yaml").write_text(yaml.dump(state))

        check_stalled_agents(tmp_path, threshold_min=10, max_notifications=3)

        # Should NOT notify (already at max)
        mock_send.assert_not_called()

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_resets_on_stage_change(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Notification count resets when issue changes stage."""
        mock_load_config.return_value = self._make_config()
        # Issue now at plan.draft (changed from implement.code)
        mock_list.return_value = [self._make_issue(stage="plan.draft", minutes_ago=15)]
        # Agent dead, manager running
        mock_exists.side_effect = lambda name: name == "mgr"

        # Pre-seed state: had 3 notifications for old stage
        state = {
            "stall_notifications": {
                "042": {"stage": "implement.code", "count": 3, "last_at": self._timestamp_ago(10)},
            },
        }
        (tmp_path / ".heartbeat_state.yaml").write_text(yaml.dump(state))

        check_stalled_agents(tmp_path, threshold_min=10)

        # Should notify (stage changed, count reset to 0)
        mock_send.assert_called_once()

        state = yaml.safe_load((tmp_path / ".heartbeat_state.yaml").read_text())
        assert state["stall_notifications"]["042"]["stage"] == "plan.draft"
        assert state["stall_notifications"]["042"]["count"] == 1

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_skips_parking_lot_stages(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Issues in parking lot stages are skipped."""
        cfg = self._make_config()
        cfg.is_parking_lot.return_value = True
        mock_load_config.return_value = cfg
        mock_list.return_value = [self._make_issue(stage="backlog", minutes_ago=100)]
        mock_exists.side_effect = lambda name: name == "mgr"

        check_stalled_agents(tmp_path, threshold_min=10)

        mock_send.assert_not_called()

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_skips_manager_stages(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Issues in manager (human review) stages are skipped."""
        cfg = self._make_config()
        cfg.role_for.return_value = "manager"
        mock_load_config.return_value = cfg
        mock_list.return_value = [self._make_issue(stage="implement.review", minutes_ago=100)]
        mock_exists.side_effect = lambda name: name == "mgr"

        check_stalled_agents(tmp_path, threshold_min=10)

        mock_send.assert_not_called()

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_role_aware_session_check(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Uses config.role_for() to determine correct session to check."""
        cfg = self._make_config()
        cfg.role_for.return_value = "review"
        mock_load_config.return_value = cfg
        mock_list.return_value = [self._make_issue(stage="implement.independent_review", minutes_ago=15)]
        mock_exists.side_effect = lambda name: name == "mgr"

        check_stalled_agents(tmp_path, threshold_min=10)

        # Should have checked session for "review" role
        cfg.get_issue_tmux_session.assert_called_with("042", "review")

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists", return_value=True)
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_running_agent_starts_count_at_one(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Running agents start notification count at 1 to avoid rapid-fire."""
        mock_load_config.return_value = self._make_config()
        # Agent running (session_exists=True for all), at 25 min
        mock_list.return_value = [self._make_issue(minutes_ago=25)]

        check_stalled_agents(tmp_path, threshold_min=10)

        # Should notify (25 >= threshold*2=20, count bumped from 0→1, next_at=20)
        mock_send.assert_called_once()

        # Count should be 2 (started at 1 for running agent, incremented to 2)
        state = yaml.safe_load((tmp_path / ".heartbeat_state.yaml").read_text())
        assert state["stall_notifications"]["042"]["count"] == 2

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists", return_value=True)
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_running_agent_not_rapid_fire(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Running agent at 25m with count=2 waits until 30m for next notify."""
        mock_load_config.return_value = self._make_config()
        mock_list.return_value = [self._make_issue(minutes_ago=25)]

        # Pre-seed: already notified twice
        state = {
            "stall_notifications": {
                "042": {"stage": "implement.code", "count": 2, "last_at": self._timestamp_ago(5)},
            },
        }
        (tmp_path / ".heartbeat_state.yaml").write_text(yaml.dump(state))

        check_stalled_agents(tmp_path, threshold_min=10)

        # Should NOT notify (25 < threshold*3=30)
        mock_send.assert_not_called()

    @patch("agenttree.events.save_event_state")
    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_shared_event_state_modifies_in_place_skips_save(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        mock_save: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When _event_state is passed, modifies it in-place and skips save."""
        mock_load_config.return_value = self._make_config()
        mock_list.return_value = [self._make_issue(minutes_ago=15)]
        mock_exists.side_effect = lambda name: name == "mgr"

        shared_state: dict[str, Any] = {}
        check_stalled_agents(tmp_path, threshold_min=10, _event_state=shared_state)

        # Should have notified manager
        mock_send.assert_called_once()

        # Should have modified the shared dict in-place
        assert "stall_notifications" in shared_state
        assert shared_state["stall_notifications"]["042"]["count"] == 1

        # Should NOT have called save_event_state (dispatcher does it)
        mock_save.assert_not_called()

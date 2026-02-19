"""Tests for agenttree.events module."""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from agenttree.events import (
    STARTUP,
    SHUTDOWN,
    HEARTBEAT,
    load_event_state,
    save_event_state,
    check_action_rate_limit,
    update_action_state,
    parse_action_entry,
    fire_event,
    get_heartbeat_interval,
)


class TestLoadSaveEventState:
    """Tests for event state persistence."""

    def test_load_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        """Load returns empty dict when state file doesn't exist."""
        state = load_event_state(tmp_path)
        assert state == {}

    def test_save_creates_state_file(self, tmp_path: Path) -> None:
        """Save creates state file with provided data."""
        state = {"sync": {"last_run_at": "2024-01-01T00:00:00Z"}}
        save_event_state(tmp_path, state)
        
        state_file = tmp_path / ".heartbeat_state.yaml"
        assert state_file.exists()
        
        loaded = yaml.safe_load(state_file.read_text())
        assert loaded == state

    def test_load_returns_saved_state(self, tmp_path: Path) -> None:
        """Load returns previously saved state."""
        original = {"action1": {"last_run_at": "2024-01-01T00:00:00Z"}}
        save_event_state(tmp_path, original)
        
        loaded = load_event_state(tmp_path)
        assert loaded == original


class TestCheckActionRateLimit:
    """Tests for rate limiting logic."""

    def test_no_rate_limit_allows_run(self) -> None:
        """Action without rate limits should always run."""
        should_run, reason = check_action_rate_limit(
            "sync", {}, {}, heartbeat_count=1
        )
        assert should_run is True
        assert reason == "Running"

    def test_time_based_rate_limit_blocks(self) -> None:
        """Action should be blocked if run too recently."""
        from datetime import datetime, timezone
        
        # Last run was 30 seconds ago, min interval is 60s
        now = datetime.now(timezone.utc)
        last_run = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        state = {"check_ci": {"last_run_at": last_run}}
        config = {"min_interval_s": 60}
        
        should_run, reason = check_action_rate_limit("check_ci", config, state)
        assert should_run is False
        assert "Rate limited" in reason

    def test_count_based_rate_limit_blocks(self) -> None:
        """Action should be blocked on non-Nth heartbeat."""
        should_run, reason = check_action_rate_limit(
            "expensive_action",
            {"every_n": 5},
            {},
            heartbeat_count=3,
        )
        assert should_run is False
        assert "runs every 5" in reason

    def test_count_based_rate_limit_allows_on_nth(self) -> None:
        """Action should run on Nth heartbeat."""
        should_run, reason = check_action_rate_limit(
            "expensive_action",
            {"every_n": 5},
            {},
            heartbeat_count=5,
        )
        assert should_run is True

    def test_legacy_run_every_n_syncs(self) -> None:
        """Legacy run_every_n_syncs should work for backwards compatibility."""
        should_run, reason = check_action_rate_limit(
            "old_action",
            {"run_every_n_syncs": 3},
            {},
            heartbeat_count=6,
        )
        assert should_run is True
        
        should_run, reason = check_action_rate_limit(
            "old_action",
            {"run_every_n_syncs": 3},
            {},
            heartbeat_count=7,
        )
        assert should_run is False


class TestUpdateActionState:
    """Tests for action state updates."""

    def test_creates_state_on_first_run(self) -> None:
        """Creates action state entry on first run."""
        state: dict = {}
        update_action_state("new_action", state)

        assert "new_action" in state
        assert "last_run_at" in state["new_action"]

    def test_updates_last_run_at(self) -> None:
        """Updates last_run_at on subsequent runs."""
        state: dict = {"action": {"last_run_at": "2024-01-01T00:00:00Z"}}
        update_action_state("action", state)
        assert state["action"]["last_run_at"] != "2024-01-01T00:00:00Z"


class TestParseActionEntry:
    """Tests for action entry parsing."""

    def test_string_action(self) -> None:
        """Simple string becomes action name with empty config."""
        name, config = parse_action_entry("sync")
        assert name == "sync"
        assert config == {}

    def test_dict_action_with_empty_value(self) -> None:
        """Dict with empty value parses correctly."""
        name, config = parse_action_entry({"push_pending_branches": {}})
        assert name == "push_pending_branches"
        assert config == {}

    def test_dict_action_with_config(self) -> None:
        """Dict with config values parses correctly."""
        name, config = parse_action_entry({"check_ci_status": {"min_interval_s": 60}})
        assert name == "check_ci_status"
        assert config == {"min_interval_s": 60}

    def test_dict_action_with_none_value(self) -> None:
        """Dict with None value parses correctly."""
        name, config = parse_action_entry({"cleanup": None})
        assert name == "cleanup"
        assert config == {}


class TestFireEvent:
    """Tests for fire_event function."""

    @patch("agenttree.config.load_config")
    @patch("agenttree.actions.get_action")
    def test_fires_startup_event(
        self, mock_get_action: MagicMock, mock_load_config: MagicMock, tmp_path: Path
    ) -> None:
        """Startup event fires configured actions."""
        # Setup mock config
        mock_config = MagicMock()
        mock_config.model_dump.return_value = {
            "on": {
                "startup": ["start_manager", "auto_start_agents"]
            }
        }
        mock_load_config.return_value = mock_config
        
        # Setup mock action
        mock_action = MagicMock()
        mock_get_action.return_value = mock_action
        
        # Fire event
        results = fire_event(STARTUP, tmp_path, verbose=False)
        
        assert results["success"] is True
        assert results["actions_run"] == 2
        assert mock_action.call_count == 2

    @patch("agenttree.config.load_config")
    @patch("agenttree.actions.get_action")
    def test_handles_unknown_action(
        self, mock_get_action: MagicMock, mock_load_config: MagicMock, tmp_path: Path
    ) -> None:
        """Unknown actions are logged but don't crash."""
        mock_config = MagicMock()
        mock_config.model_dump.return_value = {
            "on": {"startup": ["unknown_action"]}
        }
        mock_load_config.return_value = mock_config
        mock_get_action.return_value = None  # Action not found
        
        results = fire_event(STARTUP, tmp_path)
        
        assert "Unknown action: unknown_action" in results["errors"]

    @patch("agenttree.config.load_config")
    @patch("agenttree.actions.get_action")
    def test_optional_action_failure_doesnt_fail_event(
        self, mock_get_action: MagicMock, mock_load_config: MagicMock, tmp_path: Path
    ) -> None:
        """Optional action failures don't set success=False."""
        mock_config = MagicMock()
        mock_config.model_dump.return_value = {
            "on": {"startup": [{"failing_action": {"optional": True}}]}
        }
        mock_load_config.return_value = mock_config
        
        mock_action = MagicMock(side_effect=Exception("Test failure"))
        mock_get_action.return_value = mock_action
        
        results = fire_event(STARTUP, tmp_path)
        
        # Optional failure shouldn't fail the whole event
        assert results["success"] is True
        assert len(results["errors"]) == 1


class TestGetHeartbeatInterval:
    """Tests for heartbeat interval configuration."""

    @patch("agenttree.config.load_config")
    def test_returns_configured_interval(self, mock_load_config: MagicMock) -> None:
        """Returns interval from config."""
        mock_config = MagicMock()
        mock_config.model_dump.return_value = {
            "on": {"heartbeat": {"interval_s": 30}}
        }
        mock_load_config.return_value = mock_config
        
        interval = get_heartbeat_interval()
        assert interval == 30

    @patch("agenttree.config.load_config")
    def test_returns_default_on_missing_config(self, mock_load_config: MagicMock) -> None:
        """Returns default 10s when not configured."""
        mock_config = MagicMock()
        mock_config.model_dump.return_value = {}
        mock_config.refresh_interval = 10
        mock_load_config.return_value = mock_config
        
        interval = get_heartbeat_interval()
        assert interval == 10

    @patch("agenttree.config.load_config")
    def test_returns_default_on_error(self, mock_load_config: MagicMock) -> None:
        """Returns default 10s on config load error."""
        mock_load_config.side_effect = Exception("Config error")
        interval = get_heartbeat_interval()
        assert interval == 10

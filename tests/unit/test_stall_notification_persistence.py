"""Integration tests for stall notification persistence through fire_event.

Tests verify that stall notification counts survive the full execution
path: fire_event → check_stalled_agents → state save → state reload.

This catches the race condition where fire_event's save_event_state overwrites
stall counts because check_stalled_agents used an independent state copy.
The fix (commit e50c4e9) passes _event_state so changes happen in-place.
These tests ensure that fix keeps working.
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

import pytest
import yaml

from agenttree.events import fire_event, load_event_state, HEARTBEAT


def _timestamp_ago(minutes: int) -> str:
    t = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_issue(issue_id: int = 42, stage: str = "implement.code",
                minutes_ago: int = 20) -> MagicMock:
    history_entry = MagicMock()
    history_entry.timestamp = _timestamp_ago(minutes_ago)
    return MagicMock(
        id=issue_id, title="Test Issue", stage=stage,
        history=[history_entry],
    )


def _make_config() -> MagicMock:
    cfg = MagicMock()
    cfg.project = "test"
    cfg.get_manager_tmux_session.return_value = "mgr"
    cfg.is_parking_lot.return_value = False
    cfg.is_human_review.return_value = False
    cfg.role_for.return_value = "developer"
    cfg.get_issue_tmux_session.return_value = "at-042"
    cfg.model_dump.return_value = {}
    return cfg


def _heartbeat_config_with_stall_check_only() -> dict[str, Any]:
    """Config that runs ONLY check_stalled_agents (skips sync, git, etc.)."""
    return {
        "heartbeat": {
            "interval_s": 10,
            "actions": [
                {"check_stalled_agents": {"min_interval_s": 0}},
            ],
        },
    }


class TestStallNotificationPersistenceThroughFireEvent:
    """Verify stall counts persist when check_stalled_agents runs via fire_event.

    This is the critical test class. The web server calls fire_event, not
    check_stalled_agents directly. If the state sharing between fire_event
    and check_stalled_agents breaks, these tests catch it.
    """

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_stall_counts_persist_to_disk_after_fire_event(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Stall notification counts written by check_stalled_agents survive
        fire_event's save_event_state call."""
        cfg = _make_config()
        cfg.model_dump.return_value = {"on": _heartbeat_config_with_stall_check_only()}
        mock_load_config.return_value = cfg
        mock_list.return_value = [_make_issue(issue_id=99, minutes_ago=15)]
        mock_exists.side_effect = lambda name: name == "mgr"

        fire_event(HEARTBEAT, tmp_path, heartbeat_count=1)

        mock_send.assert_called_once()

        state = load_event_state(tmp_path)
        sn = state.get("stall_notifications", {})
        assert 99 in sn, f"Issue 99 missing from stall_notifications: {sn.keys()}"
        assert sn[99]["count"] == 1
        assert sn[99]["stage"] == "implement.code"

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_stall_counts_accumulate_across_multiple_fire_events(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Stall counts increment correctly across separate fire_event calls,
        simulating multiple heartbeat cycles."""
        cfg = _make_config()
        cfg.model_dump.return_value = {"on": _heartbeat_config_with_stall_check_only()}
        mock_load_config.return_value = cfg
        mock_exists.side_effect = lambda name: name == "mgr"

        # Heartbeat 1: issue at 15min (threshold=10, dead agent → count 0→1)
        mock_list.return_value = [_make_issue(issue_id=99, minutes_ago=15)]
        fire_event(HEARTBEAT, tmp_path, heartbeat_count=1)

        state = load_event_state(tmp_path)
        assert state["stall_notifications"][99]["count"] == 1

        # Heartbeat 2: issue at 25min (next_at=20 → count 1→2)
        mock_list.return_value = [_make_issue(issue_id=99, minutes_ago=25)]
        fire_event(HEARTBEAT, tmp_path, heartbeat_count=2)

        state = load_event_state(tmp_path)
        assert state["stall_notifications"][99]["count"] == 2

        # Heartbeat 3: issue at 35min (next_at=30 → count 2→3)
        mock_list.return_value = [_make_issue(issue_id=99, minutes_ago=35)]
        fire_event(HEARTBEAT, tmp_path, heartbeat_count=3)

        state = load_event_state(tmp_path)
        assert state["stall_notifications"][99]["count"] == 3

        # Should have sent 3 notifications total
        assert mock_send.call_count == 3

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_stops_alerting_after_max_notifications_across_fire_events(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """After max_notifications (3) reached via fire_event, no more alerts.

        This is THE regression test for the flooding bug. If this passes,
        the manager won't get spammed with identical stall alerts."""
        cfg = _make_config()
        cfg.model_dump.return_value = {"on": _heartbeat_config_with_stall_check_only()}
        mock_load_config.return_value = cfg
        mock_exists.side_effect = lambda name: name == "mgr"

        # Run 3 heartbeats to reach max count
        for i, mins in enumerate([15, 25, 35], start=1):
            mock_list.return_value = [_make_issue(issue_id=99, minutes_ago=mins)]
            fire_event(HEARTBEAT, tmp_path, heartbeat_count=i)

        assert mock_send.call_count == 3

        # Heartbeat 4: issue still stalled at 45min, but count=3 (max)
        mock_send.reset_mock()
        mock_list.return_value = [_make_issue(issue_id=99, minutes_ago=45)]
        fire_event(HEARTBEAT, tmp_path, heartbeat_count=4)

        mock_send.assert_not_called()

        # Heartbeat 5-10: keep going, should never alert again
        for i in range(5, 11):
            mock_list.return_value = [_make_issue(issue_id=99, minutes_ago=45 + i * 10)]
            fire_event(HEARTBEAT, tmp_path, heartbeat_count=i)

        mock_send.assert_not_called()

        # Count should still be 3
        state = load_event_state(tmp_path)
        assert state["stall_notifications"][99]["count"] == 3

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_other_actions_dont_clobber_stall_state(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Running other actions alongside check_stalled_agents doesn't
        overwrite stall notification state."""
        cfg = _make_config()
        cfg.model_dump.return_value = {"on": {
            "heartbeat": {
                "interval_s": 10,
                "actions": [
                    {"cleanup_resources": {"min_interval_s": 0}},
                    {"check_stalled_agents": {"min_interval_s": 0}},
                    {"cleanup_resources": {"min_interval_s": 0}},
                ],
            },
        }}
        mock_load_config.return_value = cfg
        mock_list.return_value = [_make_issue(issue_id=99, minutes_ago=15)]
        mock_exists.side_effect = lambda name: name == "mgr"

        fire_event(HEARTBEAT, tmp_path, heartbeat_count=1)

        state = load_event_state(tmp_path)
        sn = state.get("stall_notifications", {})
        assert 99 in sn
        assert sn[99]["count"] == 1

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_intermediate_heartbeats_preserve_stall_state(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Heartbeats where check_stalled_agents is rate-limited still
        preserve the existing stall notification state on disk."""
        cfg = _make_config()
        cfg.model_dump.return_value = {"on": {
            "heartbeat": {
                "interval_s": 10,
                "actions": [
                    {"check_stalled_agents": {"min_interval_s": 0}},
                ],
            },
        }}
        mock_load_config.return_value = cfg
        mock_exists.side_effect = lambda name: name == "mgr"

        # Heartbeat 1: stall detected, count=1
        mock_list.return_value = [_make_issue(issue_id=99, minutes_ago=15)]
        fire_event(HEARTBEAT, tmp_path, heartbeat_count=1)

        state = load_event_state(tmp_path)
        assert state["stall_notifications"][99]["count"] == 1

        # Now simulate heartbeats where check_stalled_agents is rate-limited
        # by running fire_event with an empty action list (no stall check)
        cfg_empty = _make_config()
        cfg_empty.model_dump.return_value = {"on": {
            "heartbeat": {
                "interval_s": 10,
                "actions": [
                    {"cleanup_resources": {"min_interval_s": 0}},
                ],
            },
        }}
        mock_load_config.return_value = cfg_empty

        for i in range(2, 6):
            fire_event(HEARTBEAT, tmp_path, heartbeat_count=i)

        # Stall state should survive the intermediate heartbeats
        state = load_event_state(tmp_path)
        assert "stall_notifications" in state
        assert 99 in state["stall_notifications"]
        assert state["stall_notifications"][99]["count"] == 1

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_multiple_issues_tracked_independently(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Multiple stalled issues each get independent notification counts."""
        cfg = _make_config()
        cfg.model_dump.return_value = {"on": _heartbeat_config_with_stall_check_only()}
        cfg.get_issue_tmux_session.side_effect = lambda iid, role: f"at-{iid}"
        mock_load_config.return_value = cfg
        mock_exists.side_effect = lambda name: name == "mgr"

        issues = [
            _make_issue(issue_id=10, minutes_ago=15),
            _make_issue(issue_id=20, minutes_ago=15),
            _make_issue(issue_id=30, minutes_ago=15),
        ]
        mock_list.return_value = issues

        fire_event(HEARTBEAT, tmp_path, heartbeat_count=1)

        state = load_event_state(tmp_path)
        sn = state["stall_notifications"]
        for iid in [10, 20, 30]:
            assert iid in sn, f"Issue {iid} missing from stall_notifications"
            assert sn[iid]["count"] == 1

    @patch("agenttree.tmux.send_message", return_value="sent")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.config.load_config")
    def test_stage_change_resets_count_through_fire_event(
        self, mock_load_config: MagicMock, mock_list: MagicMock,
        mock_exists: MagicMock, mock_send: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Stage change resets notification count even through fire_event path."""
        cfg = _make_config()
        cfg.model_dump.return_value = {"on": _heartbeat_config_with_stall_check_only()}
        mock_load_config.return_value = cfg
        mock_exists.side_effect = lambda name: name == "mgr"

        # Reach max count at implement.code
        for i, mins in enumerate([15, 25, 35], start=1):
            mock_list.return_value = [_make_issue(issue_id=99, stage="implement.code", minutes_ago=mins)]
            fire_event(HEARTBEAT, tmp_path, heartbeat_count=i)

        state = load_event_state(tmp_path)
        assert state["stall_notifications"][99]["count"] == 3
        assert state["stall_notifications"][99]["stage"] == "implement.code"

        # Stage changes to plan.draft — count should reset
        mock_send.reset_mock()
        mock_list.return_value = [_make_issue(issue_id=99, stage="plan.draft", minutes_ago=15)]
        fire_event(HEARTBEAT, tmp_path, heartbeat_count=4)

        mock_send.assert_called_once()
        state = load_event_state(tmp_path)
        assert state["stall_notifications"][99]["count"] == 1
        assert state["stall_notifications"][99]["stage"] == "plan.draft"


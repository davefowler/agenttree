"""Unit tests for manager agent stall detection.

Tests the stall detection functionality including:
- Detecting stalled agents based on last_advanced_at
- Skipping human review stages
- Respecting configurable thresholds
- Logging stall interventions
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import yaml


class TestGetStalledAgents:
    """Test stall detection logic."""

    @patch("agenttree.state.get_active_agent")
    def test_detects_stalled_agent(self, mock_get_active_agent, tmp_path: Path):
        """Agent in implement.code with last_advanced_at 25 min ago should be detected."""
        from agenttree.manager_agent import get_stalled_agents

        # Mock get_active_agent to return a truthy value (indicating agent is running)
        mock_get_active_agent.return_value = MagicMock()

        # Set up issue directory
        issues_dir = tmp_path / "issues"
        issue_dir = issues_dir / "042-test-issue"
        issue_dir.mkdir(parents=True)

        # Create issue.yaml
        issue_yaml = issue_dir / "issue.yaml"
        issue_yaml.write_text(yaml.dump({
            "id": "042",
            "title": "Test Issue",
            "stage": "implement",
            "substage": "code",
        }))

        # Create session file with last_advanced_at 25 min ago
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(minutes=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
        session_file = issue_dir / ".agent_session.yaml"
        session_file.write_text(yaml.dump({
            "session_id": "abc123",
            "issue_id": "042",
            "started_at": old_time,
            "last_stage": "implement",
            "last_substage": "code",
            "last_advanced_at": old_time,
            "oriented": True,
        }))

        stalled = get_stalled_agents(tmp_path, threshold_min=20)

        assert len(stalled) == 1
        assert stalled[0]["issue_id"] == "042"
        assert stalled[0]["stage"] == "implement.code"

    @patch("agenttree.state.get_active_agent")
    def test_skips_recent_agent(self, mock_get_active_agent, tmp_path: Path):
        """Agent with last_advanced_at 10 min ago should NOT be detected."""
        from agenttree.manager_agent import get_stalled_agents

        # Mock get_active_agent to return a truthy value (indicating agent is running)
        mock_get_active_agent.return_value = MagicMock()

        # Set up issue directory
        issues_dir = tmp_path / "issues"
        issue_dir = issues_dir / "042-test-issue"
        issue_dir.mkdir(parents=True)

        # Create issue.yaml
        issue_yaml = issue_dir / "issue.yaml"
        issue_yaml.write_text(yaml.dump({
            "id": "042",
            "title": "Test Issue",
            "stage": "implement",
            "substage": "code",
        }))

        # Create session file with last_advanced_at 10 min ago (not stalled)
        now = datetime.now(timezone.utc)
        recent_time = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        session_file = issue_dir / ".agent_session.yaml"
        session_file.write_text(yaml.dump({
            "session_id": "abc123",
            "issue_id": "042",
            "started_at": recent_time,
            "last_stage": "implement",
            "last_substage": "code",
            "last_advanced_at": recent_time,
            "oriented": True,
        }))

        stalled = get_stalled_agents(tmp_path, threshold_min=20)

        assert len(stalled) == 0

    @patch("agenttree.state.get_active_agent")
    def test_skips_human_review_stages(self, mock_get_active_agent, tmp_path: Path):
        """Agent at plan_review stage (even if 2 hours old) should NOT be detected."""
        from agenttree.manager_agent import get_stalled_agents

        # Mock get_active_agent to return a truthy value (indicating agent is running)
        mock_get_active_agent.return_value = MagicMock()

        # Set up issue directory
        issues_dir = tmp_path / "issues"
        issue_dir = issues_dir / "042-test-issue"
        issue_dir.mkdir(parents=True)

        # Create issue.yaml in human review stage
        issue_yaml = issue_dir / "issue.yaml"
        issue_yaml.write_text(yaml.dump({
            "id": "042",
            "title": "Test Issue",
            "stage": "plan_review",
        }))

        # Create session file with last_advanced_at 2 hours ago
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        session_file = issue_dir / ".agent_session.yaml"
        session_file.write_text(yaml.dump({
            "session_id": "abc123",
            "issue_id": "042",
            "started_at": old_time,
            "last_stage": "plan_review",
            "last_substage": None,
            "last_advanced_at": old_time,
            "oriented": True,
        }))

        stalled = get_stalled_agents(tmp_path, threshold_min=20)

        # Should not be detected because plan_review is a human review stage
        assert len(stalled) == 0

    @patch("agenttree.state.get_active_agent")
    def test_configurable_threshold(self, mock_get_active_agent, tmp_path: Path):
        """Threshold from config should be respected."""
        from agenttree.manager_agent import get_stalled_agents

        # Mock get_active_agent to return a truthy value (indicating agent is running)
        mock_get_active_agent.return_value = MagicMock()

        # Set up issue directory
        issues_dir = tmp_path / "issues"
        issue_dir = issues_dir / "042-test-issue"
        issue_dir.mkdir(parents=True)

        # Create issue.yaml
        issue_yaml = issue_dir / "issue.yaml"
        issue_yaml.write_text(yaml.dump({
            "id": "042",
            "title": "Test Issue",
            "stage": "implement",
            "substage": "code",
        }))

        # Create session file with last_advanced_at 15 min ago
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
        session_file = issue_dir / ".agent_session.yaml"
        session_file.write_text(yaml.dump({
            "session_id": "abc123",
            "issue_id": "042",
            "started_at": old_time,
            "last_stage": "implement",
            "last_substage": "code",
            "last_advanced_at": old_time,
            "oriented": True,
        }))

        # With 20 min threshold, should not be stalled
        stalled_20 = get_stalled_agents(tmp_path, threshold_min=20)
        assert len(stalled_20) == 0

        # With 10 min threshold, should be stalled
        stalled_10 = get_stalled_agents(tmp_path, threshold_min=10)
        assert len(stalled_10) == 1


class TestLogStall:
    """Test stall logging functionality."""

    def test_logs_stall_to_yaml(self, tmp_path: Path):
        """Stall should be recorded in manager_logs/stalls.yaml."""
        from agenttree.manager_agent import log_stall

        log_stall(
            agents_dir=tmp_path,
            issue_id="042",
            stage="implement.code",
            nudge_message="You seem stuck. Try running agenttree next.",
            escalated=False,
        )

        # Check log file was created
        log_file = tmp_path / "manager_logs" / "stalls.yaml"
        assert log_file.exists()

        # Check content
        with open(log_file) as f:
            data = yaml.safe_load(f)

        assert "stalls" in data
        assert len(data["stalls"]) == 1
        stall = data["stalls"][0]
        assert stall["issue_id"] == "042"
        assert stall["stage"] == "implement.code"
        assert stall["nudge_sent"] == "You seem stuck. Try running agenttree next."
        assert stall["escalation_needed"] is False
        assert "detected_at" in stall


class TestStallNotification:
    """Test stall notification cooldown logic."""

    def test_should_notify_first_time(self, tmp_path: Path):
        """First notification for an issue/stage should always fire."""
        from agenttree.manager_agent import should_notify_stall

        assert should_notify_stall(tmp_path, "042", "implement.code") is True

    def test_should_not_notify_within_cooldown(self, tmp_path: Path):
        """Should skip notification if recently notified."""
        from agenttree.manager_agent import should_notify_stall, mark_stall_notified

        mark_stall_notified(tmp_path, "042", "implement.code")
        assert should_notify_stall(tmp_path, "042", "implement.code", cooldown_min=10) is False

    def test_should_notify_after_cooldown_expires(self, tmp_path: Path):
        """Should notify again after cooldown period has passed."""
        from agenttree.manager_agent import should_notify_stall

        # Write a stale timestamp (20 min ago)
        logs_dir = tmp_path / "controller_logs"
        logs_dir.mkdir(parents=True)
        state_file = logs_dir / "stall_notifications.yaml"
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        state_file.write_text(yaml.dump({"042:implement.code": old_time}))

        assert should_notify_stall(tmp_path, "042", "implement.code", cooldown_min=10) is True

    def test_should_notify_different_stage(self, tmp_path: Path):
        """Notification for a different stage should fire even if another was recent."""
        from agenttree.manager_agent import should_notify_stall, mark_stall_notified

        mark_stall_notified(tmp_path, "042", "implement.code")
        assert should_notify_stall(tmp_path, "042", "implement.debug") is True

    def test_mark_stall_creates_state_file(self, tmp_path: Path):
        """mark_stall_notified should create state file and directory."""
        from agenttree.manager_agent import mark_stall_notified

        mark_stall_notified(tmp_path, "042", "implement.code")

        state_file = tmp_path / "controller_logs" / "stall_notifications.yaml"
        assert state_file.exists()
        with open(state_file) as f:
            data = yaml.safe_load(f)
        assert "042:implement.code" in data

    def test_mark_stall_preserves_other_entries(self, tmp_path: Path):
        """mark_stall_notified should preserve existing entries."""
        from agenttree.manager_agent import mark_stall_notified

        mark_stall_notified(tmp_path, "042", "implement.code")
        mark_stall_notified(tmp_path, "043", "research.explore")

        state_file = tmp_path / "controller_logs" / "stall_notifications.yaml"
        with open(state_file) as f:
            data = yaml.safe_load(f)
        assert "042:implement.code" in data
        assert "043:research.explore" in data

    def test_should_notify_with_malformed_timestamp(self, tmp_path: Path):
        """Malformed timestamp in state file should not block notification."""
        from agenttree.manager_agent import should_notify_stall

        logs_dir = tmp_path / "controller_logs"
        logs_dir.mkdir(parents=True)
        state_file = logs_dir / "stall_notifications.yaml"
        state_file.write_text(yaml.dump({"042:implement.code": "not-a-date"}))

        assert should_notify_stall(tmp_path, "042", "implement.code") is True



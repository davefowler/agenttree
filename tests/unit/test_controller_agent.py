"""Unit tests for controller agent stall detection.

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
        from agenttree.controller_agent import get_stalled_agents

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
        from agenttree.controller_agent import get_stalled_agents

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
        from agenttree.controller_agent import get_stalled_agents

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
        from agenttree.controller_agent import get_stalled_agents

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
        """Stall should be recorded in controller_logs/stalls.yaml."""
        from agenttree.controller_agent import log_stall

        log_stall(
            agents_dir=tmp_path,
            issue_id="042",
            stage="implement.code",
            nudge_message="You seem stuck. Try running agenttree next.",
            escalated=False,
        )

        # Check log file was created
        log_file = tmp_path / "controller_logs" / "stalls.yaml"
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


class TestStallsCommand:
    """Test the agenttree stalls CLI command."""

    def test_stalls_command_lists_stalled(self, tmp_path: Path):
        """agenttree stalls should show stalled agents."""
        from click.testing import CliRunner
        from agenttree.cli import main

        # Set up issue directory
        issues_dir = tmp_path / "_agenttree" / "issues"
        issue_dir = issues_dir / "042-test-issue"
        issue_dir.mkdir(parents=True)

        # Create issue.yaml
        issue_yaml = issue_dir / "issue.yaml"
        issue_yaml.write_text(yaml.dump({
            "id": "042",
            "title": "Test Issue",
            "stage": "implement",
            "substage": "code",
            "assigned_agent": "agent-1",
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

        runner = CliRunner()
        with patch("agenttree.cli.Path.cwd", return_value=tmp_path):
            result = runner.invoke(main, ["stalls"])

        assert result.exit_code == 0
        assert "042" in result.output or "stalled" in result.output.lower()

    def test_stalls_command_empty_when_none(self, tmp_path: Path):
        """agenttree stalls should show nothing when no stalls."""
        from click.testing import CliRunner
        from agenttree.cli import main

        # Set up empty issues directory
        issues_dir = tmp_path / "_agenttree" / "issues"
        issues_dir.mkdir(parents=True)

        runner = CliRunner()
        with patch("agenttree.cli.Path.cwd", return_value=tmp_path):
            result = runner.invoke(main, ["stalls"])

        assert result.exit_code == 0
        assert "no stalled" in result.output.lower() or result.output.strip() == ""

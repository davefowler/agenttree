"""Unit tests for manager agent stall detection.

Tests the stall detection functionality including:
- Detecting stalled agents based on last_advanced_at
- Skipping human review stages
- Respecting configurable thresholds
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
            "stage": "implement.code",
        }))

        # Create session file with last_advanced_at 25 min ago
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(minutes=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
        session_file = issue_dir / ".agent_session.yaml"
        session_file.write_text(yaml.dump({
            "session_id": "abc123",
            "issue_id": "042",
            "started_at": old_time,
            "last_stage": "implement.code",
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
            "stage": "implement.code",
        }))

        # Create session file with last_advanced_at 10 min ago (not stalled)
        now = datetime.now(timezone.utc)
        recent_time = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        session_file = issue_dir / ".agent_session.yaml"
        session_file.write_text(yaml.dump({
            "session_id": "abc123",
            "issue_id": "042",
            "started_at": recent_time,
            "last_stage": "implement.code",
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
            "stage": "plan.review",
        }))

        # Create session file with last_advanced_at 2 hours ago
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        session_file = issue_dir / ".agent_session.yaml"
        session_file.write_text(yaml.dump({
            "session_id": "abc123",
            "issue_id": "042",
            "started_at": old_time,
            "last_stage": "plan.review",
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
            "stage": "implement.code",
        }))

        # Create session file with last_advanced_at 15 min ago
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
        session_file = issue_dir / ".agent_session.yaml"
        session_file.write_text(yaml.dump({
            "session_id": "abc123",
            "issue_id": "042",
            "started_at": old_time,
            "last_stage": "implement.code",
            "last_advanced_at": old_time,
            "oriented": True,
        }))

        # With 20 min threshold, should not be stalled
        stalled_20 = get_stalled_agents(tmp_path, threshold_min=20)
        assert len(stalled_20) == 0

        # With 10 min threshold, should be stalled
        stalled_10 = get_stalled_agents(tmp_path, threshold_min=10)
        assert len(stalled_10) == 1

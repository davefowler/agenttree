"""Tests for reject functionality."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner


@pytest.fixture
def cli_runner():
    """Create a Click test runner."""
    return CliRunner()


@pytest.fixture
def mock_config():
    """Create a mock config with stage definitions."""
    from agenttree.config import Config, StageConfig, SubstageConfig

    config = Config(
        project="testproject",
        stages={
            "backlog": StageConfig(name="backlog"),
            "explore": StageConfig(name="explore", substages={
                "define": SubstageConfig(name="define", output="problem.md"),
                "research": SubstageConfig(name="research", output="research.md"),
            }),
            "plan": StageConfig(name="plan", substages={
                "draft": SubstageConfig(name="draft", output="spec.md"),
                "assess": SubstageConfig(name="assess", output="spec_review.md"),
                "revise": SubstageConfig(name="revise", output="spec.md"),
                "review": SubstageConfig(name="review", human_review=True),
            }),
            "implement": StageConfig(name="implement", substages={
                "code": SubstageConfig(name="code"),
                "code_review": SubstageConfig(name="code_review", output="review.md"),
                "address_review": SubstageConfig(name="address_review"),
                "wrapup": SubstageConfig(name="wrapup"),
                "feedback": SubstageConfig(name="feedback", output="feedback.md"),
                "review": SubstageConfig(name="review", human_review=True),
            }),
            "accepted": StageConfig(name="accepted", is_parking_lot=True),
            "not_doing": StageConfig(name="not_doing", is_parking_lot=True, redirect_only=True),
        },
    )
    return config


@pytest.fixture
def temp_issue_dir(tmp_path):
    """Create a temporary issue directory with sample files."""
    issues_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
    issues_dir.mkdir(parents=True)

    # Create issue.yaml at implement.review stage (hierarchical format)
    issue_data = {
        "id": "42",
        "slug": "test-issue",
        "title": "Test Issue",
        "stage": "implement.review",
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
        "history": [],
        "labels": [],
        "priority": "medium",
        "pr_number": 123,
        "pr_url": "https://github.com/org/repo/pull/123",
    }
    yaml_path = issues_dir / "issue.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(issue_data, f)

    # Create output files
    (issues_dir / "problem.md").write_text("# Problem\nTest problem")
    (issues_dir / "research.md").write_text("# Research\nTest research")
    (issues_dir / "spec.md").write_text("# Spec\nTest spec")
    (issues_dir / "spec_review.md").write_text("# Review\nTest review")
    (issues_dir / "review.md").write_text("# Code Review\nTest code review")

    return issues_dir


class TestRejectValidation:
    """Tests for reject command validation."""

    def test_rejects_from_implementation_review_to_implement(self, cli_runner, mock_config, temp_issue_dir):
        """Should move from implement.review to implement.code stage."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.agents_repo.sync_agents_repo"):
                            with patch("agenttree.state.get_active_agent", return_value=None):
                                result = cli_runner.invoke(main, ["reject", "42"])

        assert result.exit_code == 0
        assert "implement.code" in result.output.lower()
        # Check the issue.yaml was updated
        yaml_path = temp_issue_dir / "issue.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["stage"] == "implement.code"

    def test_rejects_from_plan_review_to_plan_revise(self, cli_runner, mock_config, temp_issue_dir):
        """Should move from plan.review to plan.revise stage."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="plan.review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        # Update temp issue to plan.review
        yaml_path = temp_issue_dir / "issue.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        data["stage"] = "plan.review"
        with open(yaml_path, "w") as f:
            yaml.dump(data, f)

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.agents_repo.sync_agents_repo"):
                            with patch("agenttree.state.get_active_agent", return_value=None):
                                result = cli_runner.invoke(main, ["reject", "42"])

        assert result.exit_code == 0
        assert "plan.revise" in result.output.lower()
        # Check the issue.yaml was updated
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["stage"] == "plan.revise"

    def test_rejects_non_review_stage(self, cli_runner, mock_config):
        """Should error when not at a review stage."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test",
            title="Test",
            stage="implement.code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["reject", "42"])

        assert result.exit_code == 1
        assert "not a human review stage" in result.output.lower() or "review stage" in result.output.lower()

    def test_rejects_in_container(self, cli_runner, mock_config):
        """Should block when running inside a container."""
        from agenttree.cli import main

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.is_running_in_container", return_value=True):
                result = cli_runner.invoke(main, ["reject", "42"])

        assert result.exit_code == 1
        assert "container" in result.output.lower()


class TestRejectWithMessage:
    """Tests for reject command with feedback message."""

    def test_reject_with_message(self, cli_runner, mock_config, temp_issue_dir):
        """Should send feedback message to agent."""
        from agenttree.cli import main
        from agenttree.issues import Issue
        from agenttree.state import ActiveAgent

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        mock_agent = MagicMock(spec=ActiveAgent)
        mock_agent.tmux_session = "testproject-issue-42"
        mock_agent.issue_id = "42"

        message_sent = []

        def capture_send(session, msg, interrupt=False):
            message_sent.append(msg)
            return "sent"

        mock_tmux_manager = MagicMock()
        mock_tmux_manager.is_issue_running.return_value = True
        mock_tmux_manager.send_message_to_issue.side_effect = capture_send

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.agents_repo.sync_agents_repo"):
                            with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                                with patch("agenttree.cli.workflow.TmuxManager", return_value=mock_tmux_manager):
                                    result = cli_runner.invoke(main, ["reject", "42", "--message", "Please fix the tests"])

        assert result.exit_code == 0
        assert len(message_sent) == 1
        assert "Please fix the tests" in message_sent[0]


class TestRejectStateUpdates:
    """Tests for reject state updates."""

    def test_updates_stage(self, cli_runner, mock_config, temp_issue_dir):
        """Should update issue.yaml stage correctly (hierarchical dot-path format)."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.agents_repo.sync_agents_repo"):
                            with patch("agenttree.state.get_active_agent", return_value=None):
                                result = cli_runner.invoke(main, ["reject", "42"])

        assert result.exit_code == 0
        yaml_path = temp_issue_dir / "issue.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["stage"] == "implement.code"

    def test_adds_reject_history_entry(self, cli_runner, mock_config, temp_issue_dir):
        """Should add history entry with type='reject'."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.agents_repo.sync_agents_repo"):
                            with patch("agenttree.state.get_active_agent", return_value=None):
                                result = cli_runner.invoke(main, ["reject", "42"])

        assert result.exit_code == 0
        yaml_path = temp_issue_dir / "issue.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert len(data["history"]) >= 1
        last_entry = data["history"][-1]
        assert last_entry["type"] == "reject"
        assert last_entry["stage"] == "implement.code"

    def test_preserves_pr_metadata(self, cli_runner, mock_config, temp_issue_dir):
        """Should NOT clear PR metadata (unlike rollback)."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
            pr_number=123,
            pr_url="https://github.com/org/repo/pull/123",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.agents_repo.sync_agents_repo"):
                            with patch("agenttree.state.get_active_agent", return_value=None):
                                result = cli_runner.invoke(main, ["reject", "42"])

        assert result.exit_code == 0
        yaml_path = temp_issue_dir / "issue.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        # PR metadata should be preserved
        assert data.get("pr_number") == 123
        assert data.get("pr_url") == "https://github.com/org/repo/pull/123"


class TestRejectAgentNotification:
    """Tests for agent notification during reject."""

    def test_notifies_running_agent(self, cli_runner, mock_config, temp_issue_dir):
        """Should send message if agent is running."""
        from agenttree.cli import main
        from agenttree.issues import Issue
        from agenttree.state import ActiveAgent

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        mock_agent = MagicMock(spec=ActiveAgent)
        mock_agent.tmux_session = "testproject-issue-42"
        mock_agent.issue_id = "42"

        message_sent = []

        mock_tmux_manager = MagicMock()
        mock_tmux_manager.is_issue_running.return_value = True
        mock_tmux_manager.send_message_to_issue.side_effect = lambda s, m, interrupt=False: message_sent.append(m) or "sent"

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.agents_repo.sync_agents_repo"):
                            with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                                with patch("agenttree.cli.workflow.TmuxManager", return_value=mock_tmux_manager):
                                    result = cli_runner.invoke(main, ["reject", "42"])

        assert result.exit_code == 0
        assert len(message_sent) == 1
        assert "rejected" in message_sent[0].lower() or "agenttree next" in message_sent[0].lower()

    def test_handles_agent_not_running(self, cli_runner, mock_config, temp_issue_dir):
        """Should not error if agent is not running."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.agents_repo.sync_agents_repo"):
                            with patch("agenttree.state.get_active_agent", return_value=None):
                                result = cli_runner.invoke(main, ["reject", "42"])

        # Should succeed even without active agent
        assert result.exit_code == 0
        assert "implement.code" in result.output.lower()

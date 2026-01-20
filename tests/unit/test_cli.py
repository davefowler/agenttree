"""Tests for CLI commands."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner():
    """Create a Click test runner."""
    return CliRunner()


@pytest.fixture
def mock_config():
    """Create a mock config."""
    config = MagicMock()
    config.project = "testproject"
    config.get_tmux_session_name.return_value = "agent-42"
    return config


class TestSendCommand:
    """Tests for the send command."""

    def test_send_no_active_agent(self, cli_runner, mock_config):
        """Should error when no active agent for issue."""
        from agenttree.cli import main

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.state.get_active_agent", return_value=None):
                with patch("agenttree.cli.get_issue_func", return_value=None):
                    result = cli_runner.invoke(main, ["send", "42", "hello"])

        assert result.exit_code == 1
        assert "No active agent" in result.output

    def test_send_agent_not_running(self, cli_runner, mock_config):
        """Should error when agent tmux session not running."""
        from agenttree.cli import main

        mock_agent = MagicMock()
        mock_agent.tmux_session = "agent-42"
        mock_agent.issue_id = "42"

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                with patch("agenttree.cli.TmuxManager") as mock_tm_class:
                    mock_tm = MagicMock()
                    mock_tm.is_issue_running.return_value = False
                    mock_tm_class.return_value = mock_tm

                    result = cli_runner.invoke(main, ["send", "42", "hello"])

        assert result.exit_code == 1
        assert "not running" in result.output

    def test_send_success(self, cli_runner, mock_config):
        """Should send message successfully."""
        from agenttree.cli import main

        mock_agent = MagicMock()
        mock_agent.tmux_session = "agent-42"
        mock_agent.issue_id = "42"

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                with patch("agenttree.cli.TmuxManager") as mock_tm_class:
                    mock_tm = MagicMock()
                    mock_tm.is_issue_running.return_value = True
                    mock_tm_class.return_value = mock_tm

                    result = cli_runner.invoke(main, ["send", "42", "hello"])

        assert result.exit_code == 0
        assert "Sent message" in result.output
        mock_tm.send_message_to_issue.assert_called_once_with("agent-42", "hello")


class TestKillCommand:
    """Tests for the kill command."""

    def test_kill_no_active_agent(self, cli_runner, mock_config):
        """Should error when no active agent for issue."""
        from agenttree.cli import main

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.state.get_active_agent", return_value=None):
                with patch("agenttree.cli.get_issue_func", return_value=None):
                    result = cli_runner.invoke(main, ["kill", "42"])

        assert result.exit_code == 1
        assert "No active agent" in result.output

    def test_kill_success(self, cli_runner, mock_config):
        """Should kill agent session successfully."""
        from agenttree.cli import main

        mock_agent = MagicMock()
        mock_agent.tmux_session = "agent-42"
        mock_agent.issue_id = "42"

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                with patch("agenttree.state.unregister_agent") as mock_unregister:
                    with patch("agenttree.cli.TmuxManager") as mock_tm_class:
                        mock_tm = MagicMock()
                        mock_tm_class.return_value = mock_tm

                        result = cli_runner.invoke(main, ["kill", "42"])

        assert result.exit_code == 0
        assert "Killed" in result.output or "killed" in result.output.lower()
        mock_tm.stop_issue_agent.assert_called_once_with("agent-42")
        mock_unregister.assert_called_once()


class TestAttachCommand:
    """Tests for the attach command."""

    def test_attach_no_active_agent(self, cli_runner, mock_config):
        """Should error when no active agent for issue."""
        from agenttree.cli import main

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.state.get_active_agent", return_value=None):
                with patch("agenttree.cli.get_issue_func", return_value=None):
                    result = cli_runner.invoke(main, ["attach", "42"])

        assert result.exit_code == 1
        assert "No active agent" in result.output


class TestIssueListCommand:
    """Tests for the issue list command."""

    def test_issue_list_empty(self, cli_runner, mock_config, tmp_path):
        """Should show message when no issues."""
        from agenttree.cli import main

        mock_config.agents_dir = tmp_path / "_agenttree"
        mock_config.agents_dir.mkdir()
        (mock_config.agents_dir / "issues").mkdir()

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.list_issues_func", return_value=[]):
                result = cli_runner.invoke(main, ["issue", "list"])

        assert result.exit_code == 0

    def test_issue_list_with_issues(self, cli_runner, mock_config, tmp_path):
        """Should list issues."""
        from agenttree.cli import main
        from agenttree.issues import Priority

        mock_config.agents_dir = tmp_path / "_agenttree"
        mock_config.agents_dir.mkdir()
        (mock_config.agents_dir / "issues").mkdir()

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "Test Issue"
        mock_issue.stage = "backlog"  # Stages are just strings
        mock_issue.substage = None
        mock_issue.priority = Priority.MEDIUM  # Priority is an enum
        mock_issue.assigned_agent = None

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.list_issues_func", return_value=[mock_issue]):
                result = cli_runner.invoke(main, ["issue", "list"])

        assert result.exit_code == 0


class TestApproveCommand:
    """Tests for the approve command."""

    def test_approve_issue_not_found(self, cli_runner, mock_config):
        """Should error when issue not found."""
        from agenttree.cli import main

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=None):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["approve", "999"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_approve_issue_not_review_stage(self, cli_runner, mock_config):
        """Should error when issue is not in a review stage."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "Test Issue"
        mock_issue.stage = "implement"  # Not a review stage
        mock_issue.is_review = False

        # Mock stage config to indicate not a review stage
        mock_config.get_stage.return_value = MagicMock(human_review=False, host="agent")
        mock_config.get_human_review_stages.return_value = ["plan_review", "implementation_review"]

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["approve", "42"])

        assert result.exit_code == 1
        assert "not" in result.output.lower() and "review" in result.output.lower()

    def test_approve_blocks_in_container(self, cli_runner, mock_config):
        """Should block approve command when running in container."""
        from agenttree.cli import main

        with patch("agenttree.cli.is_running_in_container", return_value=True):
            result = cli_runner.invoke(main, ["approve", "42"])

        assert result.exit_code == 1
        assert "container" in result.output.lower()


class TestIssueCreateCommand:
    """Tests for the issue create command."""

    def test_issue_create_missing_title(self, cli_runner, mock_config):
        """Should error when title is missing."""
        from agenttree.cli import main

        result = cli_runner.invoke(main, ["issue", "create"])

        assert result.exit_code != 0

    def test_issue_create_short_title(self, cli_runner, mock_config):
        """Should error when title is too short."""
        from agenttree.cli import main

        problem = "This is a detailed problem statement that is at least 50 characters long."
        result = cli_runner.invoke(main, ["issue", "create", "Short", "--problem", problem])

        assert result.exit_code == 1
        assert "at least 10 characters" in result.output

    def test_issue_create_short_problem(self, cli_runner, mock_config):
        """Should error when problem is too short."""
        from agenttree.cli import main

        result = cli_runner.invoke(main, ["issue", "create", "A valid issue title here", "--problem", "Too short"])

        assert result.exit_code == 1
        assert "at least 50 characters" in result.output

    def test_issue_create_success(self, cli_runner, mock_config, tmp_path):
        """Should create issue successfully."""
        from agenttree.cli import main

        mock_config.agents_dir = tmp_path / "_agenttree"
        mock_config.agents_dir.mkdir()
        (mock_config.agents_dir / "issues").mkdir()
        (mock_config.agents_dir / "skills").mkdir()

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "A valid issue title here"
        mock_issue.slug = "a-valid-issue-title-here"
        mock_issue.stage = "spec"
        mock_issue.dependencies = None

        problem = "This is a detailed problem statement that is at least 50 characters long for the test."

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.create_issue_func", return_value=mock_issue):
                result = cli_runner.invoke(main, ["issue", "create", "A valid issue title here", "--problem", problem])

        assert result.exit_code == 0
        assert "Created issue" in result.output


class TestStatusCommand:
    """Tests for the status command."""

    def test_status_no_active_issues(self, cli_runner, mock_config):
        """Should show message when no active issues."""
        from agenttree.cli import main

        # All issues are in backlog, so none are active
        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "Test Issue"
        mock_issue.stage = "backlog"
        mock_issue.assigned_agent = None

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.list_issues_func", return_value=[mock_issue]):
                result = cli_runner.invoke(main, ["status"])

        assert result.exit_code == 0
        assert "No active issues" in result.output

    def test_status_with_active_issues(self, cli_runner, mock_config):
        """Should show table when there are active issues."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "Test Issue"
        mock_issue.stage = "implement"  # Active stage
        mock_issue.substage = None
        mock_issue.assigned_agent = 1

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.list_issues_func", return_value=[mock_issue]):
                result = cli_runner.invoke(main, ["status"])

        assert result.exit_code == 0
        assert "Active Issues" in result.output


class TestMainHelp:
    """Tests for main help command."""

    def test_help(self, cli_runner):
        """Should show help."""
        from agenttree.cli import main

        result = cli_runner.invoke(main, ["--help"])

        assert result.exit_code == 0
        assert "Usage:" in result.output

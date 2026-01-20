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


class TestShutdownCommand:
    """Tests for the shutdown command."""

    def test_shutdown_help(self, cli_runner):
        """Should show help for shutdown command."""
        from agenttree.cli import main

        result = cli_runner.invoke(main, ["shutdown", "--help"])

        assert result.exit_code == 0
        assert "backlog" in result.output
        assert "not_doing" in result.output
        assert "accepted" in result.output

    def test_shutdown_blocks_in_container(self, cli_runner, mock_config):
        """Should block shutdown command when running in container."""
        from agenttree.cli import main

        with patch("agenttree.cli.is_running_in_container", return_value=True):
            result = cli_runner.invoke(main, ["shutdown", "42", "backlog"])

        assert result.exit_code == 1
        assert "container" in result.output.lower()

    def test_shutdown_issue_not_found(self, cli_runner, mock_config):
        """Should error when issue not found."""
        from agenttree.cli import main

        with patch("agenttree.cli.is_running_in_container", return_value=False):
            with patch("agenttree.cli.get_issue_func", return_value=None):
                result = cli_runner.invoke(main, ["shutdown", "999", "backlog"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_shutdown_already_at_target_stage(self, cli_runner, mock_config):
        """Should return early when issue is already at target stage."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "backlog"

        with patch("agenttree.cli.is_running_in_container", return_value=False):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                result = cli_runner.invoke(main, ["shutdown", "42", "backlog"])

        assert result.exit_code == 0
        assert "already in backlog" in result.output.lower()

    def test_shutdown_stops_agent_before_worktree_operations(self, cli_runner, mock_config, tmp_path):
        """Should stop agent before handling worktree to avoid race conditions."""
        from agenttree.cli import main

        # Track order of operations
        operations = []

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "implement"
        mock_issue.worktree_dir = str(tmp_path / "worktree")
        mock_issue.branch = "issue-42"

        # Create the worktree directory
        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()

        mock_agent = MagicMock()
        mock_agent.tmux_session = "agent-42"
        mock_agent.issue_id = "42"

        def mock_stop_agent(*args, **kwargs):
            operations.append("stop_agent")

        def mock_subprocess_run(cmd, **kwargs):
            if "status" in cmd:
                operations.append("git_status")
                return MagicMock(stdout="", returncode=0)
            elif "log" in cmd:
                operations.append("git_log")
                return MagicMock(stdout="", returncode=0)
            return MagicMock(returncode=0)

        with patch("agenttree.cli.is_running_in_container", return_value=False):
            with patch("agenttree.cli.load_config", return_value=mock_config):
                with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                        with patch("agenttree.state.unregister_agent"):
                            with patch("agenttree.cli.TmuxManager") as mock_tm:
                                mock_tm.return_value.stop_issue_agent = mock_stop_agent
                                with patch("subprocess.run", side_effect=mock_subprocess_run):
                                    with patch("agenttree.cli.update_issue_stage", return_value=mock_issue):
                                        with patch("agenttree.cli.delete_session"):
                                            with patch("agenttree.cli.update_issue_metadata"):
                                                with patch("agenttree.worktree.remove_worktree"):
                                                    result = cli_runner.invoke(main, ["shutdown", "42", "not_doing", "-f"])

        # Agent should be stopped before any git operations
        assert operations.index("stop_agent") < operations.index("git_status")

    def test_shutdown_unpushed_commits_no_upstream(self, cli_runner, mock_config, tmp_path):
        """Should detect unpushed commits even when branch has no upstream."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "implement"
        mock_issue.worktree_dir = str(tmp_path / "worktree")
        mock_issue.branch = "issue-42"

        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()

        def mock_subprocess_run(cmd, **kwargs):
            if "status" in cmd:
                return MagicMock(stdout="", returncode=0)
            elif "@{u}" in cmd:
                # Simulate no upstream - return error
                return MagicMock(stdout="", stderr="fatal: no upstream", returncode=128)
            elif "origin/main" in cmd:
                # Fallback check shows unpushed commits
                return MagicMock(stdout="abc123 Test commit\n", returncode=0)
            return MagicMock(returncode=0)

        with patch("agenttree.cli.is_running_in_container", return_value=False):
            with patch("agenttree.cli.load_config", return_value=mock_config):
                with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("subprocess.run", side_effect=mock_subprocess_run):
                            # Don't use -f so we get the warning
                            result = cli_runner.invoke(main, ["shutdown", "42", "not_doing"], input="n\n")

        # Should warn about no upstream and unpushed commits
        assert "no upstream" in result.output.lower() or "unpushed" in result.output.lower()

    def test_shutdown_with_uncommitted_changes_error_mode(self, cli_runner, mock_config, tmp_path):
        """Should error when there are uncommitted changes and changes=error."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "implement"
        mock_issue.worktree_dir = str(tmp_path / "worktree")
        mock_issue.branch = "issue-42"

        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()

        def mock_subprocess_run(cmd, **kwargs):
            if "status" in cmd:
                # Has uncommitted changes
                return MagicMock(stdout="M  file.py\n", returncode=0)
            return MagicMock(returncode=0)

        with patch("agenttree.cli.is_running_in_container", return_value=False):
            with patch("agenttree.cli.load_config", return_value=mock_config):
                with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("subprocess.run", side_effect=mock_subprocess_run):
                            # accepted stage defaults to changes=error
                            result = cli_runner.invoke(main, ["shutdown", "42", "accepted"])

        assert result.exit_code == 1
        assert "uncommitted changes" in result.output.lower()

    def test_shutdown_with_uncommitted_changes_discard_aborted(self, cli_runner, mock_config, tmp_path):
        """Should abort when user declines to discard changes."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "implement"
        mock_issue.worktree_dir = str(tmp_path / "worktree")
        mock_issue.branch = "issue-42"

        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()

        def mock_subprocess_run(cmd, **kwargs):
            if "status" in cmd:
                return MagicMock(stdout="M  file.py\n", returncode=0)
            return MagicMock(returncode=0)

        with patch("agenttree.cli.is_running_in_container", return_value=False):
            with patch("agenttree.cli.load_config", return_value=mock_config):
                with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("subprocess.run", side_effect=mock_subprocess_run):
                            # not_doing defaults to discard, user says no
                            result = cli_runner.invoke(main, ["shutdown", "42", "not_doing"], input="n\n")

        assert result.exit_code == 0
        assert "aborted" in result.output.lower()

    def test_shutdown_force_skips_confirmation(self, cli_runner, mock_config, tmp_path):
        """Should skip confirmation prompts when --force is used."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "implement"
        mock_issue.worktree_dir = str(tmp_path / "worktree")
        mock_issue.branch = "issue-42"

        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()

        subprocess_calls = []

        def mock_subprocess_run(cmd, **kwargs):
            subprocess_calls.append(cmd)
            if "status" in cmd:
                return MagicMock(stdout="M  file.py\n", returncode=0)
            elif "checkout" in cmd or "clean" in cmd:
                return MagicMock(returncode=0)
            elif "log" in cmd:
                return MagicMock(stdout="", returncode=0)
            elif "branch" in cmd:
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        with patch("agenttree.cli.is_running_in_container", return_value=False):
            with patch("agenttree.cli.load_config", return_value=mock_config):
                with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("subprocess.run", side_effect=mock_subprocess_run):
                            with patch("agenttree.cli.update_issue_stage", return_value=mock_issue):
                                with patch("agenttree.cli.delete_session"):
                                    with patch("agenttree.cli.update_issue_metadata"):
                                        with patch("agenttree.worktree.remove_worktree"):
                                            result = cli_runner.invoke(main, ["shutdown", "42", "not_doing", "-f"])

        assert result.exit_code == 0
        # Should have called git checkout and clean (discard changes)
        checkout_called = any("checkout" in str(cmd) for cmd in subprocess_calls)
        assert checkout_called

    def test_shutdown_stash_changes(self, cli_runner, mock_config, tmp_path):
        """Should stash changes when using backlog stage."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "implement"
        mock_issue.worktree_dir = str(tmp_path / "worktree")
        mock_issue.branch = "issue-42"

        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()

        subprocess_calls = []

        def mock_subprocess_run(cmd, **kwargs):
            subprocess_calls.append(cmd)
            if "status" in cmd:
                return MagicMock(stdout="M  file.py\n", returncode=0)
            elif "stash" in cmd:
                return MagicMock(returncode=0)
            elif "log" in cmd:
                return MagicMock(stdout="", returncode=0)
            return MagicMock(returncode=0)

        with patch("agenttree.cli.is_running_in_container", return_value=False):
            with patch("agenttree.cli.load_config", return_value=mock_config):
                with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("subprocess.run", side_effect=mock_subprocess_run):
                            with patch("agenttree.cli.update_issue_stage", return_value=mock_issue):
                                with patch("agenttree.cli.delete_session"):
                                    with patch("agenttree.cli.update_issue_metadata"):
                                        # backlog defaults to stash
                                        result = cli_runner.invoke(main, ["shutdown", "42", "backlog"])

        assert result.exit_code == 0
        # Should have called git stash
        stash_called = any("stash" in str(cmd) for cmd in subprocess_calls)
        assert stash_called

    def test_shutdown_handles_subprocess_error(self, cli_runner, mock_config, tmp_path):
        """Should handle subprocess errors gracefully."""
        from agenttree.cli import main
        import subprocess

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "implement"
        mock_issue.worktree_dir = str(tmp_path / "worktree")
        mock_issue.branch = "issue-42"

        worktree_path = tmp_path / "worktree"
        worktree_path.mkdir()

        def mock_subprocess_run(cmd, **kwargs):
            if "status" in cmd:
                return MagicMock(stdout="M  file.py\n", returncode=0)
            elif "stash" in cmd:
                if kwargs.get("check"):
                    raise subprocess.CalledProcessError(1, cmd, stderr="stash failed")
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        with patch("agenttree.cli.is_running_in_container", return_value=False):
            with patch("agenttree.cli.load_config", return_value=mock_config):
                with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("subprocess.run", side_effect=mock_subprocess_run):
                            result = cli_runner.invoke(main, ["shutdown", "42", "backlog"])

        assert result.exit_code == 1
        assert "error" in result.output.lower()

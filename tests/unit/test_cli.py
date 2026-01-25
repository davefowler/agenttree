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
                    mock_tm.send_message_to_issue.return_value = "sent"
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
                # Use --no-start to skip auto-starting agent (which requires more mocking)
                result = cli_runner.invoke(main, ["issue", "create", "A valid issue title here", "--problem", problem, "--no-start"])

        assert result.exit_code == 0
        assert "Created issue" in result.output

    def test_issue_create_auto_starts_agent(self, cli_runner, mock_config, tmp_path):
        """Should auto-start agent by default when creating issue."""
        from agenttree.cli import main

        mock_config.agents_dir = tmp_path / "_agenttree"
        mock_config.agents_dir.mkdir()
        (mock_config.agents_dir / "issues").mkdir()
        (mock_config.agents_dir / "skills").mkdir()

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "A valid issue title here"
        mock_issue.slug = "a-valid-issue-title-here"
        mock_issue.stage = "define"
        mock_issue.dependencies = None

        problem = "This is a detailed problem statement that is at least 50 characters long for the test."

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.create_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.start_agent") as mock_start_agent:
                    result = cli_runner.invoke(main, ["issue", "create", "A valid issue title here", "--problem", problem])

        assert "Auto-starting agent" in result.output
        # start_agent is invoked via ctx.invoke, so check it was called
        mock_start_agent.assert_called_once()

    def test_issue_create_skips_auto_start_with_unmet_deps(self, cli_runner, mock_config, tmp_path):
        """Should skip auto-start when issue has unmet dependencies."""
        from agenttree.cli import main

        mock_config.agents_dir = tmp_path / "_agenttree"
        mock_config.agents_dir.mkdir()
        (mock_config.agents_dir / "issues").mkdir()
        (mock_config.agents_dir / "skills").mkdir()

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "A valid issue title here"
        mock_issue.slug = "a-valid-issue-title-here"
        mock_issue.stage = "backlog"
        mock_issue.dependencies = ["053"]

        # Mock a dependency that is not yet accepted
        mock_dep_issue = MagicMock()
        mock_dep_issue.stage = "implement"  # Not accepted yet

        problem = "This is a detailed problem statement that is at least 50 characters long for the test."

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.create_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.get_issue_func", return_value=mock_dep_issue):
                    with patch("agenttree.cli.start_agent") as mock_start_agent:
                        result = cli_runner.invoke(main, ["issue", "create", "A valid issue title here", "--problem", problem, "--depends-on", "053"])

        assert result.exit_code == 0
        assert "blocked by dependencies" in result.output
        mock_start_agent.assert_not_called()

    def test_issue_create_skips_auto_start_with_explicit_backlog_stage(self, cli_runner, mock_config, tmp_path):
        """Should skip auto-start when issue is explicitly created in backlog stage."""
        from agenttree.cli import main

        mock_config.agents_dir = tmp_path / "_agenttree"
        mock_config.agents_dir.mkdir()
        (mock_config.agents_dir / "issues").mkdir()
        (mock_config.agents_dir / "skills").mkdir()

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "A valid issue title here"
        mock_issue.slug = "a-valid-issue-title-here"
        mock_issue.stage = "backlog"
        mock_issue.dependencies = None

        problem = "This is a detailed problem statement that is at least 50 characters long for the test."

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.create_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.start_agent") as mock_start_agent:
                    result = cli_runner.invoke(main, ["issue", "create", "A valid issue title here", "--problem", problem, "--stage", "backlog"])

        assert result.exit_code == 0
        # Should show "Next steps" message, not auto-start
        assert "Next steps" in result.output
        assert "agenttree start" in result.output
        mock_start_agent.assert_not_called()


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


class TestSandboxCommand:
    """Tests for the sandbox command."""

    def test_sandbox_help(self, cli_runner):
        """Should show help for sandbox command."""
        from agenttree.cli import main

        result = cli_runner.invoke(main, ["sandbox", "--help"])

        assert result.exit_code == 0
        assert "sandbox" in result.output.lower()
        assert "--list" in result.output
        assert "--kill" in result.output
        assert "--git" in result.output

    def test_sandbox_list_no_active(self, cli_runner, mock_config):
        """Should show message when no active sandboxes."""
        from agenttree.cli import main

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.tmux.list_sessions", return_value=[]):
                result = cli_runner.invoke(main, ["sandbox", "--list"])

        assert result.exit_code == 0
        assert "No active sandboxes" in result.output

    def test_sandbox_list_with_active(self, cli_runner, mock_config):
        """Should list active sandboxes correctly."""
        from agenttree.cli import main
        from agenttree.tmux import TmuxSession

        # Create mock TmuxSession objects
        mock_sessions = [
            TmuxSession(name="testproject-sandbox-default", windows=1, attached=False),
            TmuxSession(name="testproject-sandbox-experiments", windows=1, attached=True),
            TmuxSession(name="other-project-agent-1", windows=1, attached=False),  # Should be filtered out
        ]

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.tmux.list_sessions", return_value=mock_sessions):
                result = cli_runner.invoke(main, ["sandbox", "--list"])

        assert result.exit_code == 0
        assert "Active Sandboxes" in result.output
        assert "default" in result.output
        assert "experiments" in result.output
        # The non-sandbox session should not appear
        assert "other-project" not in result.output

    def test_sandbox_kill_existing(self, cli_runner, mock_config):
        """Should kill an existing sandbox."""
        from agenttree.cli import main

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=True):
                with patch("agenttree.tmux.kill_session") as mock_kill:
                    result = cli_runner.invoke(main, ["sandbox", "mysandbox", "--kill"])

        assert result.exit_code == 0
        assert "Killed" in result.output
        mock_kill.assert_called_once_with("testproject-sandbox-mysandbox")

    def test_sandbox_kill_not_running(self, cli_runner, mock_config):
        """Should handle killing a non-existent sandbox gracefully."""
        from agenttree.cli import main

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=False):
                result = cli_runner.invoke(main, ["sandbox", "nosandbox", "--kill"])

        assert result.exit_code == 0
        assert "not running" in result.output

    def test_sandbox_attach_existing(self, cli_runner, mock_config):
        """Should attach to an existing sandbox."""
        from agenttree.cli import main

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=True):
                with patch("agenttree.tmux.attach_session") as mock_attach:
                    result = cli_runner.invoke(main, ["sandbox", "existing"])

        assert result.exit_code == 0
        assert "Attaching" in result.output
        mock_attach.assert_called_once_with("testproject-sandbox-existing")

    def test_sandbox_no_runtime_available(self, cli_runner, mock_config):
        """Should error when no container runtime is available."""
        from agenttree.cli import main

        mock_runtime = MagicMock()
        mock_runtime.is_available.return_value = False
        mock_runtime.get_recommended_action.return_value = "Install Docker"

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=False):
                with patch("agenttree.container.get_container_runtime", return_value=mock_runtime):
                    result = cli_runner.invoke(main, ["sandbox"])

        assert result.exit_code == 1
        assert "No container runtime" in result.output


class TestRollbackCommand:
    """Tests for the rollback command."""

    def test_rollback_issue_not_found(self, cli_runner, mock_config):
        """Should error when issue not found."""
        from agenttree.cli import main

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=None):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["rollback", "999", "research"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_rollback_invalid_stage(self, cli_runner, mock_config):
        """Should error when target stage is invalid."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "implement"

        mock_config.get_stage_names.return_value = [
            "backlog", "define", "research", "plan", "implement", "accepted"
        ]

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["rollback", "42", "invalid_stage"])

        assert result.exit_code == 1
        assert "Invalid stage" in result.output

    def test_rollback_target_not_before_current(self, cli_runner, mock_config):
        """Should error when target stage is not before current stage."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "research"

        mock_config.get_stage_names.return_value = [
            "backlog", "define", "research", "plan", "implement", "accepted"
        ]

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["rollback", "42", "implement"])

        assert result.exit_code == 1
        assert "not before" in result.output.lower()

    def test_rollback_to_terminal_stage(self, cli_runner, mock_config):
        """Should error when trying to rollback to a terminal stage."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "implement"

        mock_config.get_stage_names.return_value = [
            "backlog", "define", "research", "plan", "implement", "accepted"
        ]
        mock_stage_config = MagicMock()
        mock_stage_config.terminal = True
        mock_config.get_stage.return_value = mock_stage_config

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    # Note: "accepted" is normally at the end, this tests terminal check
                    result = cli_runner.invoke(main, ["rollback", "42", "backlog"])

        assert result.exit_code == 1
        assert "terminal stage" in result.output.lower()

    def test_rollback_blocked_in_container(self, cli_runner, mock_config):
        """Should error when run inside a container."""
        from agenttree.cli import main

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.is_running_in_container", return_value=True):
                result = cli_runner.invoke(main, ["rollback", "42", "research"])

        assert result.exit_code == 1
        assert "container" in result.output.lower()

    def test_rollback_cancelled(self, cli_runner, mock_config, tmp_path):
        """Should abort when user cancels confirmation."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "Test Issue"
        mock_issue.stage = "implement"
        mock_issue.substage = None

        mock_config.get_stage_names.return_value = [
            "backlog", "define", "research", "plan", "implement", "accepted"
        ]
        mock_stage_config = MagicMock()
        mock_stage_config.terminal = False
        mock_stage_config.substage_order.return_value = []
        mock_stage_config.output = None
        mock_stage_config.substages = {}
        mock_config.get_stage.return_value = mock_stage_config

        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
        issue_dir.mkdir(parents=True)

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.cli.is_running_in_container", return_value=False):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            # User answers 'n' to confirmation
                            result = cli_runner.invoke(main, ["rollback", "42", "research"], input="n\n")

        assert "Cancelled" in result.output

    def test_rollback_success_with_yes_flag(self, cli_runner, mock_config, tmp_path):
        """Should succeed with --yes flag and update state."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "Test Issue"
        mock_issue.stage = "implement"
        mock_issue.substage = "code"

        mock_config.get_stage_names.return_value = [
            "backlog", "define", "research", "plan", "implement", "accepted"
        ]
        mock_stage_config = MagicMock()
        mock_stage_config.terminal = False
        mock_stage_config.substage_order.return_value = ["explore", "document"]
        mock_stage_config.output = "research.md"
        mock_stage_config.substages = {}
        mock_config.get_stage.return_value = mock_stage_config

        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
        issue_dir.mkdir(parents=True)

        # Create issue.yaml
        import yaml
        issue_yaml = {
            "id": "42",
            "slug": "test-issue",
            "title": "Test Issue",
            "created": "2024-01-01T00:00:00Z",
            "updated": "2024-01-01T00:00:00Z",
            "stage": "implement",
            "substage": "code",
            "history": [],
        }
        with open(issue_dir / "issue.yaml", "w") as f:
            yaml.dump(issue_yaml, f)

        # Create a file that should be archived
        (issue_dir / "spec.md").write_text("# Spec")

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.cli.is_running_in_container", return_value=False):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            with patch("agenttree.cli.delete_session"):
                                with patch("agenttree.agents_repo.sync_agents_repo"):
                                    with patch("agenttree.issues.get_agenttree_path", return_value=tmp_path):
                                        result = cli_runner.invoke(main, ["rollback", "42", "research", "--yes"])

        assert result.exit_code == 0
        assert "rolled back" in result.output.lower()

        # Verify issue.yaml was updated
        with open(issue_dir / "issue.yaml") as f:
            updated_data = yaml.safe_load(f)
        assert updated_data["stage"] == "research"
        assert updated_data["substage"] == "explore"
        assert len(updated_data["history"]) == 1
        assert updated_data["history"][0]["type"] == "rollback"

    def test_rollback_archives_files(self, cli_runner, mock_config, tmp_path):
        """Should archive output files from rolled back stages."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "Test Issue"
        mock_issue.stage = "implement"
        mock_issue.substage = "code"

        mock_config.get_stage_names.return_value = [
            "backlog", "define", "research", "plan", "implement", "accepted"
        ]

        # Set up stage configs with output files
        def get_stage_side_effect(name):
            stage_config = MagicMock()
            stage_config.terminal = False
            stage_config.substage_order.return_value = []
            stage_config.substages = {}
            if name == "plan":
                stage_config.output = "spec.md"
            elif name == "implement":
                stage_config.output = None
                review_substage = MagicMock()
                review_substage.output = "review.md"
                stage_config.substages = {"code_review": review_substage}
            else:
                stage_config.output = None
            return stage_config

        mock_config.get_stage.side_effect = get_stage_side_effect

        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
        issue_dir.mkdir(parents=True)

        # Create issue.yaml
        import yaml
        issue_yaml = {
            "id": "42",
            "slug": "test-issue",
            "title": "Test Issue",
            "created": "2024-01-01T00:00:00Z",
            "updated": "2024-01-01T00:00:00Z",
            "stage": "implement",
            "substage": "code",
            "history": [],
        }
        with open(issue_dir / "issue.yaml", "w") as f:
            yaml.dump(issue_yaml, f)

        # Create files that should be archived
        (issue_dir / "spec.md").write_text("# Spec")
        (issue_dir / "review.md").write_text("# Review")

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.cli.is_running_in_container", return_value=False):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            with patch("agenttree.cli.delete_session"):
                                with patch("agenttree.agents_repo.sync_agents_repo"):
                                    with patch("agenttree.issues.get_agenttree_path", return_value=tmp_path):
                                        result = cli_runner.invoke(main, ["rollback", "42", "research", "--yes"])

        assert result.exit_code == 0

        # Verify files were moved to archive
        archive_dirs = list((issue_dir / "archive").iterdir())
        assert len(archive_dirs) == 1
        rollback_dir = archive_dirs[0]
        assert rollback_dir.name.startswith("rollback_")
        assert (rollback_dir / "spec.md").exists()
        assert (rollback_dir / "review.md").exists()

        # Verify original files are gone
        assert not (issue_dir / "spec.md").exists()
        assert not (issue_dir / "review.md").exists()

    def test_rollback_with_active_agent(self, cli_runner, mock_config, tmp_path):
        """Should unregister active agent during rollback."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "Test Issue"
        mock_issue.stage = "implement"
        mock_issue.substage = "code"

        mock_agent = MagicMock()
        mock_agent.issue_id = "42"
        mock_agent.worktree = tmp_path / "worktree"
        mock_agent.worktree.mkdir(parents=True)

        mock_config.get_stage_names.return_value = [
            "backlog", "define", "research", "plan", "implement", "accepted"
        ]
        mock_stage_config = MagicMock()
        mock_stage_config.terminal = False
        mock_stage_config.substage_order.return_value = []
        mock_stage_config.output = None
        mock_stage_config.substages = {}
        mock_config.get_stage.return_value = mock_stage_config

        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
        issue_dir.mkdir(parents=True)

        # Create issue.yaml
        import yaml
        issue_yaml = {
            "id": "42",
            "slug": "test-issue",
            "title": "Test Issue",
            "created": "2024-01-01T00:00:00Z",
            "updated": "2024-01-01T00:00:00Z",
            "stage": "implement",
            "substage": "code",
            "history": [],
        }
        with open(issue_dir / "issue.yaml", "w") as f:
            yaml.dump(issue_yaml, f)

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.cli.is_running_in_container", return_value=False):
                        with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                            with patch("agenttree.state.unregister_agent") as mock_unregister:
                                with patch("agenttree.cli.delete_session"):
                                    with patch("agenttree.agents_repo.sync_agents_repo"):
                                        with patch("agenttree.issues.get_agenttree_path", return_value=tmp_path):
                                            result = cli_runner.invoke(main, ["rollback", "42", "research", "--yes"])

        assert result.exit_code == 0
        mock_unregister.assert_called_once_with("42")

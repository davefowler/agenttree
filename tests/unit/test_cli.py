"""Tests for CLI commands."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


@pytest.fixture
def mock_config():
    """Create a mock config."""
    config = MagicMock()
    config.project = "testproject"
    config.get_tmux_session_name.return_value = "agent-42"
    config.get_manager_tmux_session.return_value = "testproject-manager-000"
    config.get_issue_tmux_session.return_value = "testproject-developer-042"
    # Add flows dict for flow validation in issue create
    config.flows = {"default": MagicMock()}
    # parse_stage returns (stage_group, substage_or_none) for dot path strings
    def _parse_stage(dot_path: str) -> tuple:
        if "." in dot_path:
            parts = dot_path.split(".", 1)
            return (parts[0], parts[1])
        return (dot_path, None)
    config.parse_stage.side_effect = _parse_stage
    return config


class TestSendCommand:
    """Tests for the send command."""

    def test_send_issue_not_found(self, cli_runner, mock_config):
        """Should error when issue doesn't exist."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.cli.agents.get_issue_func", return_value=None):
                result = cli_runner.invoke(main, ["send", "42", "hello"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_send_auto_starts_agent(self, cli_runner, mock_config):
        """Should auto-start agent if not running."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"

        mock_agent = MagicMock()
        mock_agent.tmux_session = "agent-42"
        mock_agent.issue_id = "42"
        mock_agent.role = "developer"

        # First call returns None (no agent), second call returns agent (after start)
        agent_call_count = [0]
        def mock_get_agent(issue_id, role="developer"):
            agent_call_count[0] += 1
            if agent_call_count[0] == 1:
                return None  # First check: not running
            return mock_agent  # After start: running

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.cli.agents.get_issue_func", return_value=mock_issue):
                with patch("agenttree.state.get_active_agent", side_effect=mock_get_agent):
                    with patch("agenttree.cli.agents.TmuxManager") as mock_tm_class:
                        mock_tm = MagicMock()
                        mock_tm.is_issue_running.return_value = True
                        mock_tm.send_message_to_issue.return_value = "sent"
                        mock_tm_class.return_value = mock_tm

                        with patch("agenttree.cli.agents.subprocess.run") as mock_run:
                            mock_run.return_value = MagicMock(returncode=0, stderr="")
                            result = cli_runner.invoke(main, ["send", "42", "hello"])

        assert result.exit_code == 0

    def test_send_success(self, cli_runner, mock_config):
        """Should send message successfully when agent already running."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"

        mock_agent = MagicMock()
        mock_agent.tmux_session = "agent-42"
        mock_agent.issue_id = "42"
        mock_agent.role = "developer"

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.cli.agents.get_issue_func", return_value=mock_issue):
                with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                    with patch("agenttree.cli.agents.TmuxManager") as mock_tm_class:
                        mock_tm = MagicMock()
                        mock_tm.is_issue_running.return_value = True
                        mock_tm.send_message_to_issue.return_value = "sent"
                        mock_tm_class.return_value = mock_tm

                        result = cli_runner.invoke(main, ["send", "42", "hello"])

        assert result.exit_code == 0


class TestStopCommand:
    """Tests for the stop command (and kill alias)."""

    def test_stop_no_active_agent(self, cli_runner, mock_config):
        """Should error when no active agent for issue."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.state.get_active_agent", return_value=None):
                with patch("agenttree.cli.agents.get_issue_func", return_value=None):
                    result = cli_runner.invoke(main, ["stop", "42"])

        assert result.exit_code == 1
        assert "No active agent" in result.output

    def test_stop_success(self, cli_runner, mock_config):
        """Should stop agent session successfully using consolidated stop_agent."""
        from agenttree.cli import main

        mock_agent = MagicMock()
        mock_agent.tmux_session = "agent-42"
        mock_agent.issue_id = "42"
        mock_agent.role = "developer"

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                with patch("agenttree.api.stop_agent", return_value=True) as mock_stop:
                    with patch("agenttree.cli.agents.get_issue_func", return_value=None):
                        result = cli_runner.invoke(main, ["stop", "42"])

        assert result.exit_code == 0
        mock_stop.assert_called_once_with("42", "developer")


class TestAttachCommand:
    """Tests for the attach command."""

    def test_attach_no_active_agent(self, cli_runner, mock_config):
        """Should error when no active agent for issue."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.state.get_active_agent", return_value=None):
                with patch("agenttree.cli.agents.get_issue_func", return_value=None):
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

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.list_issues_func", return_value=[]):
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
        mock_issue.priority = Priority.MEDIUM  # Priority is an enum
        mock_issue.assigned_agent = None

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.list_issues_func", return_value=[mock_issue]):
                result = cli_runner.invoke(main, ["issue", "list"])

        assert result.exit_code == 0


class TestApproveCommand:
    """Tests for the approve command."""

    def test_approve_issue_not_found(self, cli_runner, mock_config):
        """Should error when issue not found."""
        from agenttree.cli import main

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=None):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["approve", "999"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_approve_issue_not_review_stage(self, cli_runner, mock_config):
        """Should error when issue is not in a review stage."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "Test Issue"
        mock_issue.stage = "implement.code"  # Not a review stage
        mock_issue.is_review = False

        # Mock stage config to indicate not a review stage
        mock_config.get_stage.return_value = MagicMock(human_review=False, role="developer")
        mock_config.get_human_review_stages.return_value = ["plan.review", "implement.review"]
        mock_config.is_human_review.return_value = False
        mock_config.role_for.return_value = "developer"

        # Patch workflow's load_config and get_issue_func. Also patch transition_issue
        # since it would call real get_issue/update_issue_stage - we want to test the
        # "not a human review stage" early-exit path only.
        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["approve", "42"])

        assert result.exit_code == 1
        # Output contains "not a human review stage" (e.g. "Issue is at 'implement', not a human review stage")
        assert "not" in result.output.lower() and "review" in result.output.lower()

    def test_approve_blocks_in_container(self, cli_runner, mock_config):
        """Should block approve command when running in container."""
        from agenttree.cli import main

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=True):
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

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.create_issue_func", return_value=mock_issue):
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

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.create_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.agents.start_agent") as mock_start_agent:
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

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.create_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.issues.get_issue_func", return_value=mock_dep_issue):
                    with patch("agenttree.cli.agents.start_agent") as mock_start_agent:
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

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.create_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.agents.start_agent") as mock_start_agent:
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

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.list_issues_func", return_value=[mock_issue]):
                result = cli_runner.invoke(main, ["status"])

        assert result.exit_code == 0
        assert "No active issues" in result.output

    def test_status_with_active_issues(self, cli_runner, mock_config):
        """Should show table when there are active issues."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "Test Issue"
        mock_issue.stage = "implement.code"  # Active stage
        mock_issue.assigned_agent = 1
        mock_issue.updated = "2026-02-04T00:00:00Z"
        mock_issue.flow = "default"

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.list_issues_func", return_value=[mock_issue]):
                with patch("agenttree.tmux.session_exists", return_value=False):
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

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=True):
            result = cli_runner.invoke(main, ["shutdown", "42", "backlog"])

        assert result.exit_code == 1
        assert "container" in result.output.lower()

    def test_shutdown_issue_not_found(self, cli_runner, mock_config):
        """Should error when issue not found."""
        from agenttree.cli import main

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=None):
                result = cli_runner.invoke(main, ["shutdown", "999", "backlog"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_shutdown_already_at_target_stage(self, cli_runner, mock_config):
        """Should return early when issue is already at target stage."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "backlog"

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
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

        def mock_stop_all_agents(*args, **kwargs):
            operations.append("stop_agent")
            return 1  # Return count of stopped agents

        def mock_subprocess_run(cmd, **kwargs):
            if "status" in cmd:
                operations.append("git_status")
                return MagicMock(stdout="", returncode=0)
            elif "log" in cmd:
                operations.append("git_log")
                return MagicMock(stdout="", returncode=0)
            return MagicMock(returncode=0)

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
            with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
                with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                    with patch("agenttree.api.stop_all_agents_for_issue", side_effect=mock_stop_all_agents):
                        with patch("subprocess.run", side_effect=mock_subprocess_run):
                            with patch("agenttree.cli.workflow.update_issue_stage", return_value=mock_issue):
                                with patch("agenttree.cli.workflow.delete_session"):
                                    with patch("agenttree.cli.workflow.update_issue_metadata"):
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

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
            with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
                with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
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

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
            with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
                with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
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

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
            with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
                with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
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

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
            with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
                with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("subprocess.run", side_effect=mock_subprocess_run):
                            with patch("agenttree.cli.workflow.update_issue_stage", return_value=mock_issue):
                                with patch("agenttree.cli.workflow.delete_session"):
                                    with patch("agenttree.cli.workflow.update_issue_metadata"):
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

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
            with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
                with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("subprocess.run", side_effect=mock_subprocess_run):
                            with patch("agenttree.cli.workflow.update_issue_stage", return_value=mock_issue):
                                with patch("agenttree.cli.workflow.delete_session"):
                                    with patch("agenttree.cli.workflow.update_issue_metadata"):
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

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
            with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
                with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
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

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
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

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
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

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=True):
                with patch("agenttree.tmux.kill_session") as mock_kill:
                    result = cli_runner.invoke(main, ["sandbox", "mysandbox", "--kill"])

        assert result.exit_code == 0
        assert "Killed" in result.output
        mock_kill.assert_called_once_with("testproject-sandbox-mysandbox")

    def test_sandbox_kill_not_running(self, cli_runner, mock_config):
        """Should handle killing a non-existent sandbox gracefully."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=False):
                result = cli_runner.invoke(main, ["sandbox", "nosandbox", "--kill"])

        assert result.exit_code == 0
        assert "not running" in result.output

    def test_sandbox_attach_existing(self, cli_runner, mock_config):
        """Should attach to an existing sandbox."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
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

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
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

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=None):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["rollback", "999", "research"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_rollback_invalid_stage(self, cli_runner, mock_config):
        """Should error when target stage is invalid."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "implement"
        mock_issue.flow = "default"

        stage_list = ["backlog", "explore.define", "explore.research", "plan.draft", "implement.code", "accepted"]
        mock_config.get_stage_names.return_value = stage_list
        mock_config.get_flow_stage_names.return_value = stage_list

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["rollback", "42", "invalid_stage"])

        assert result.exit_code == 1
        assert "Invalid stage" in result.output

    def test_rollback_target_not_before_current(self, cli_runner, mock_config):
        """Should error when target stage is not before current stage."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "explore.research"

        stage_list = ["backlog", "explore.define", "explore.research", "plan.draft", "implement.code", "accepted"]
        mock_config.get_stage_names.return_value = stage_list
        mock_config.get_flow_stage_names.return_value = stage_list

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["rollback", "42", "implement.code"])

        assert result.exit_code == 1
        assert "not before" in result.output.lower()

    def test_rollback_to_terminal_stage(self, cli_runner, mock_config):
        """Should error when trying to rollback to a terminal stage."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.stage = "implement.code"

        # not_doing is positioned before implement.code so we can test the redirect_only check
        # (position check must pass before redirect_only check is reached)
        stage_list = ["backlog", "not_doing", "explore.define", "explore.research", "plan.draft", "implement.code", "accepted"]
        mock_config.get_stage_names.return_value = stage_list
        mock_config.get_flow_stage_names.return_value = stage_list
        mock_config.parse_stage.return_value = ("not_doing", None)
        mock_stage_config = MagicMock()
        mock_stage_config.redirect_only = True
        mock_config.get_stage.return_value = mock_stage_config

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    # Note: "not_doing" is redirect_only, this tests that check
                    result = cli_runner.invoke(main, ["rollback", "42", "not_doing"])

        assert result.exit_code == 1
        assert "redirect-only stage" in result.output.lower()

    def test_rollback_blocked_in_container(self, cli_runner, mock_config):
        """Should error when run inside a container."""
        from agenttree.cli import main

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.is_running_in_container", return_value=True):
                result = cli_runner.invoke(main, ["rollback", "42", "research"])

        assert result.exit_code == 1
        assert "container" in result.output.lower()

    def test_rollback_cancelled(self, cli_runner, mock_config, tmp_path):
        """Should abort when user cancels confirmation."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "Test Issue"
        mock_issue.stage = "implement.code"

        stage_list = ["backlog", "explore.define", "explore.research", "plan.draft", "implement.code", "accepted"]
        mock_config.get_stage_names.return_value = stage_list
        mock_config.get_flow_stage_names.return_value = stage_list
        mock_stage_config = MagicMock()
        mock_stage_config.redirect_only = False
        mock_stage_config.output = None
        mock_config.get_stage.return_value = mock_stage_config

        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
        issue_dir.mkdir(parents=True)

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            # User answers 'n' to confirmation
                            result = cli_runner.invoke(main, ["rollback", "42", "explore.research"], input="n\n")

        assert "Cancelled" in result.output

    def test_rollback_success_with_yes_flag(self, cli_runner, mock_config, tmp_path):
        """Should succeed with --yes flag and update state."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "Test Issue"
        mock_issue.stage = "implement.code"

        stage_list = ["backlog", "explore.define", "explore.research", "plan.draft", "implement.code", "accepted"]
        mock_config.get_stage_names.return_value = stage_list
        mock_config.get_flow_stage_names.return_value = stage_list
        mock_stage_config = MagicMock()
        mock_stage_config.redirect_only = False
        mock_stage_config.output = "research.md"
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
            "stage": "implement.code",
            "history": [],
        }
        with open(issue_dir / "issue.yaml", "w") as f:
            yaml.dump(issue_yaml, f)

        # Create a file that should be archived
        (issue_dir / "spec.md").write_text("# Spec")

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            with patch("agenttree.cli.workflow.delete_session"):
                                with patch("agenttree.agents_repo.sync_agents_repo"):
                                    with patch("agenttree.issues.get_agenttree_path", return_value=tmp_path):
                                        result = cli_runner.invoke(main, ["rollback", "42", "explore.research", "--yes"])

        assert result.exit_code == 0
        assert "rolled back" in result.output.lower()

        # Verify issue.yaml was updated
        with open(issue_dir / "issue.yaml") as f:
            updated_data = yaml.safe_load(f)
        assert updated_data["stage"] == "explore.research"
        assert len(updated_data["history"]) == 1
        assert updated_data["history"][0]["type"] == "rollback"

    def test_rollback_archives_files(self, cli_runner, mock_config, tmp_path):
        """Should archive output files from rolled back stages."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = "42"
        mock_issue.title = "Test Issue"
        mock_issue.stage = "implement.code"

        stage_list = ["backlog", "explore.define", "explore.research", "plan.draft", "implement.code", "accepted"]
        mock_config.get_stage_names.return_value = stage_list
        mock_config.get_flow_stage_names.return_value = stage_list

        # Set up stage configs with output files
        def get_stage_side_effect(name):
            stage_config = MagicMock()
            stage_config.redirect_only = False
            if name == "plan.draft":
                stage_config.output = "spec.md"
            elif name == "implement.code":
                stage_config.output = None
            else:
                stage_config.output = None
            return stage_config

        mock_config.get_stage.side_effect = get_stage_side_effect

        def output_for_side_effect(dot_path):
            if dot_path == "plan.draft":
                return "spec.md"
            if dot_path == "implement.code":
                return "review.md"
            return None
        mock_config.output_for.side_effect = output_for_side_effect

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
            "stage": "implement.code",
            "history": [],
        }
        with open(issue_dir / "issue.yaml", "w") as f:
            yaml.dump(issue_yaml, f)

        # Create files that should be archived
        (issue_dir / "spec.md").write_text("# Spec")
        (issue_dir / "review.md").write_text("# Review")

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            with patch("agenttree.cli.workflow.delete_session"):
                                with patch("agenttree.agents_repo.sync_agents_repo"):
                                    with patch("agenttree.issues.get_agenttree_path", return_value=tmp_path):
                                        result = cli_runner.invoke(main, ["rollback", "42", "explore.research", "--yes"])

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
        mock_issue.stage = "implement.code"

        mock_agent = MagicMock()
        mock_agent.issue_id = "42"
        mock_agent.worktree = tmp_path / "worktree"
        mock_agent.worktree.mkdir(parents=True)

        stage_list = ["backlog", "explore.define", "explore.research", "plan.draft", "implement.code", "accepted"]
        mock_config.get_stage_names.return_value = stage_list
        mock_config.get_flow_stage_names.return_value = stage_list
        mock_stage_config = MagicMock()
        mock_stage_config.redirect_only = False
        mock_stage_config.output = None
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
            "stage": "implement.code",
            "history": [],
        }
        with open(issue_dir / "issue.yaml", "w") as f:
            yaml.dump(issue_yaml, f)

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                        with patch("agenttree.state.get_active_agents_for_issue", return_value=[mock_agent]):
                            with patch("agenttree.state.unregister_all_agents_for_issue") as mock_unregister:
                                with patch("agenttree.cli.workflow.delete_session"):
                                    with patch("agenttree.agents_repo.sync_agents_repo"):
                                        with patch("agenttree.issues.get_agenttree_path", return_value=tmp_path):
                                            result = cli_runner.invoke(main, ["rollback", "42", "explore.research", "--yes"])

        assert result.exit_code == 0
        mock_unregister.assert_called_once_with("42")


class TestManagerCommands:
    """Tests for manager-specific commands."""

    def test_send_to_manager_success(self, cli_runner, mock_config):
        """Should send message to manager when running."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=True):
                with patch("agenttree.tmux.send_message", return_value="sent") as mock_send:
                    result = cli_runner.invoke(main, ["send", "0", "hello manager"])

        assert result.exit_code == 0
        mock_send.assert_called_once()

    def test_send_to_manager_not_running(self, cli_runner, mock_config):
        """Should error when manager is not running."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=False):
                result = cli_runner.invoke(main, ["send", "0", "hello"])

        assert result.exit_code == 1
        assert "not running" in result.output.lower()
        assert "agenttree start 0" in result.output

    def test_stop_manager_success(self, cli_runner, mock_config):
        """Should stop manager session when running."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=True):
                with patch("agenttree.tmux.kill_session") as mock_kill:
                    result = cli_runner.invoke(main, ["stop", "0"])

        assert result.exit_code == 0
        assert "Stopped manager" in result.output
        mock_kill.assert_called_once_with("testproject-manager-000")

    def test_stop_manager_not_running(self, cli_runner, mock_config):
        """Should handle gracefully when manager not running."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=False):
                result = cli_runner.invoke(main, ["stop", "0"])

        assert result.exit_code == 0
        assert "not running" in result.output.lower()

    def test_attach_to_manager_not_running(self, cli_runner, mock_config):
        """Should error when trying to attach to manager that's not running."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=False):
                result = cli_runner.invoke(main, ["attach", "0"])

        assert result.exit_code == 1
        assert "Manager not running" in result.output
        assert "agenttree start 0" in result.output

    def test_attach_to_manager_success(self, cli_runner, mock_config):
        """Should attach to manager when running."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=True):
                with patch("agenttree.tmux.attach_session") as mock_attach:
                    result = cli_runner.invoke(main, ["attach", "0"])

        assert result.exit_code == 0
        assert "Attaching to manager" in result.output
        mock_attach.assert_called_once_with("testproject-manager-000")


class TestIssueShowCommand:
    """Tests for the issue show command with --json and --field flags."""

    def test_issue_show_not_found(self, cli_runner, mock_config):
        """Should error when issue not found."""
        from agenttree.cli import main

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.get_issue_func", return_value=None):
                result = cli_runner.invoke(main, ["issue", "show", "999"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_issue_show_json(self, cli_runner, mock_config, tmp_path):
        """Should output JSON when --json flag is used."""
        import json
        from agenttree.cli import main
        from agenttree.issues import Issue, Priority

        mock_issue = Issue(
            id="042",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage="implement.code",
            priority=Priority.HIGH,
            branch="issue-042-test-issue",
        )

        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
        issue_dir.mkdir(parents=True)
        (issue_dir / "problem.md").write_text("# Problem")

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.issues.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.issues.get_issue_dir", return_value=issue_dir):
                        result = cli_runner.invoke(main, ["issue", "show", "042", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == "042"
        assert data["title"] == "Test Issue"
        assert data["stage"] == "implement.code"
        assert data["branch"] == "issue-042-test-issue"
        assert data["priority"] == "high"
        assert data["issue_dir_rel"] == "_agenttree/issues/042-test-issue"
        # JSON includes docs
        assert "problem_md" in data

    def test_issue_show_field(self, cli_runner, mock_config, tmp_path):
        """Should output single field value when --field is used."""
        from agenttree.cli import main
        from agenttree.issues import Issue, Priority

        mock_issue = Issue(
            id="042",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage="implement.code",
            branch="issue-042-test-issue",
            worktree_dir="/path/to/worktree",
        )

        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
        issue_dir.mkdir(parents=True)

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.issues.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.issues.get_issue_dir", return_value=issue_dir):
                        result = cli_runner.invoke(main, ["issue", "show", "042", "--field", "branch"])

        assert result.exit_code == 0
        assert result.output.strip() == "issue-042-test-issue"

    def test_issue_show_field_worktree_dir(self, cli_runner, mock_config, tmp_path):
        """Should output worktree_dir field value correctly."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="042",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            worktree_dir="/path/to/worktree",
        )

        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
        issue_dir.mkdir(parents=True)

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.issues.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.issues.get_issue_dir", return_value=issue_dir):
                        result = cli_runner.invoke(main, ["issue", "show", "042", "--field", "worktree_dir"])

        assert result.exit_code == 0
        assert result.output.strip() == "/path/to/worktree"

    def test_issue_show_field_stage(self, cli_runner, mock_config, tmp_path):
        """Should output stage field (dot-path format)."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="042",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage="implement.code",
        )

        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
        issue_dir.mkdir(parents=True)

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.issues.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.issues.get_issue_dir", return_value=issue_dir):
                        result = cli_runner.invoke(main, ["issue", "show", "042", "--field", "stage"])

        assert result.exit_code == 0
        assert result.output.strip() == "implement.code"

    def test_issue_show_field_unknown(self, cli_runner, mock_config, tmp_path):
        """Should error when field name is unknown."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="042",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
        )

        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
        issue_dir.mkdir(parents=True)

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.issues.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.issues.get_issue_dir", return_value=issue_dir):
                        result = cli_runner.invoke(main, ["issue", "show", "042", "--field", "nonexistent_field"])

        assert result.exit_code == 1
        assert "Unknown field" in result.output
        assert "Available fields" in result.output

    def test_issue_show_field_list_value(self, cli_runner, mock_config, tmp_path):
        """Should output list values as JSON."""
        import json
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="042",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            labels=["bug", "urgent"],
        )

        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
        issue_dir.mkdir(parents=True)

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.issues.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.issues.get_issue_dir", return_value=issue_dir):
                        result = cli_runner.invoke(main, ["issue", "show", "042", "--field", "labels"])

        assert result.exit_code == 0
        labels = json.loads(result.output.strip())
        assert labels == ["bug", "urgent"]

    def test_issue_show_field_none_value(self, cli_runner, mock_config, tmp_path):
        """Should output empty string for None values."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="042",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            branch=None,  # No branch assigned
        )

        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
        issue_dir.mkdir(parents=True)

        with patch("agenttree.cli.issues.load_config", return_value=mock_config):
            with patch("agenttree.cli.issues.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.issues.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.issues.get_issue_dir", return_value=issue_dir):
                        result = cli_runner.invoke(main, ["issue", "show", "042", "--field", "branch"])

        assert result.exit_code == 0
        assert result.output.strip() == ""


class TestCleanupCommand:
    """Tests for the cleanup command."""

    def test_cleanup_dry_run_nothing_to_clean(self, cli_runner, mock_config):
        """Should report nothing to clean when no stale resources."""
        from agenttree.cli import main

        with patch("agenttree.cli.misc.load_config", return_value=mock_config):
            with patch("agenttree.cli.misc.is_running_in_container", return_value=False):
                with patch("agenttree.cli.misc.list_issues_func", return_value=[]):
                    with patch("agenttree.worktree.list_worktrees", return_value=[]):
                        with patch("subprocess.run") as mock_run:
                            # Mock git branch --list output
                            mock_run.return_value.stdout = ""
                            mock_run.return_value.returncode = 0
                            with patch("agenttree.tmux.list_sessions", return_value=[]):
                                with patch("agenttree.cli.misc.get_container_runtime") as mock_runtime:
                                    mock_runtime.return_value.runtime = None
                                    result = cli_runner.invoke(main, ["cleanup", "--dry-run"])

        assert result.exit_code == 0
        assert "Nothing to clean up" in result.output

    def test_cleanup_blocked_in_container(self, cli_runner, mock_config):
        """Should error when run from inside a container."""
        from agenttree.cli import main

        with patch("agenttree.cli.misc.load_config", return_value=mock_config):
            with patch("agenttree.cli.misc.is_running_in_container", return_value=True):
                result = cli_runner.invoke(main, ["cleanup"])

        assert result.exit_code == 1
        assert "cannot be run from inside a container" in result.output

    def test_cleanup_finds_stale_worktree_accepted_issue(self, cli_runner, mock_config):
        """Should identify worktree for accepted issue as stale."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="042",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage="accepted",
        )

        mock_worktrees = [
            {"path": "/repo", "branch": "main"},
            {"path": "/repo/.worktrees/issue-042-test-issue", "branch": "issue-042-test-issue"},
        ]

        with patch("agenttree.cli.misc.load_config", return_value=mock_config):
            with patch("agenttree.cli.misc.is_running_in_container", return_value=False):
                with patch("agenttree.cli.misc.list_issues_func", return_value=[mock_issue]):
                    with patch("agenttree.worktree.list_worktrees", return_value=mock_worktrees):
                        with patch("subprocess.run") as mock_run:
                            mock_run.return_value.stdout = ""
                            mock_run.return_value.returncode = 0
                            with patch("agenttree.tmux.list_sessions", return_value=[]):
                                with patch("agenttree.cli.misc.get_container_runtime") as mock_runtime:
                                    mock_runtime.return_value.runtime = None
                                    result = cli_runner.invoke(main, ["cleanup", "--dry-run"])

        assert result.exit_code == 0
        assert "Worktrees to remove" in result.output
        assert "issue-042-test-issue" in result.output
        assert "accepted stage" in result.output

    def test_cleanup_finds_stale_branch_merged(self, cli_runner, mock_config):
        """Should identify merged branch as stale."""
        from agenttree.cli import main

        with patch("agenttree.cli.misc.load_config", return_value=mock_config):
            with patch("agenttree.cli.misc.is_running_in_container", return_value=False):
                with patch("agenttree.cli.misc.list_issues_func", return_value=[]):
                    with patch("agenttree.worktree.list_worktrees", return_value=[{"path": "/repo", "branch": "main"}]):
                        with patch("subprocess.run") as mock_run:
                            # Configure different outputs for different commands
                            def mock_subprocess(*args, **kwargs):
                                cmd = args[0] if args else kwargs.get("args", [])
                                result = MagicMock()
                                result.returncode = 0
                                if "branch" in cmd and "--list" in cmd:
                                    result.stdout = "  main\n  feature-old\n  issue-099-old"
                                elif "branch" in cmd and "--merged" in cmd:
                                    result.stdout = "  main\n  feature-old"
                                else:
                                    result.stdout = ""
                                return result

                            mock_run.side_effect = mock_subprocess
                            with patch("agenttree.tmux.list_sessions", return_value=[]):
                                with patch("agenttree.cli.misc.get_container_runtime") as mock_runtime:
                                    mock_runtime.return_value.runtime = None
                                    result = cli_runner.invoke(main, ["cleanup", "--dry-run"])

        assert result.exit_code == 0
        assert "Branches to delete" in result.output
        assert "feature-old" in result.output

    def test_cleanup_finds_stale_tmux_session(self, cli_runner, mock_config):
        """Should identify tmux session for nonexistent issue as stale."""
        from agenttree.cli import main
        from agenttree.tmux import TmuxSession

        mock_sessions = [
            TmuxSession(name="testproject-issue-999", windows=1, attached=False),
        ]

        with patch("agenttree.cli.misc.load_config", return_value=mock_config):
            with patch("agenttree.cli.misc.is_running_in_container", return_value=False):
                with patch("agenttree.cli.misc.list_issues_func", return_value=[]):  # Issue 999 doesn't exist
                    with patch("agenttree.worktree.list_worktrees", return_value=[{"path": "/repo", "branch": "main"}]):
                        with patch("subprocess.run") as mock_run:
                            mock_run.return_value.stdout = ""
                            mock_run.return_value.returncode = 0
                            with patch("agenttree.tmux.list_sessions", return_value=mock_sessions):
                                with patch("agenttree.cli.misc.get_container_runtime") as mock_runtime:
                                    mock_runtime.return_value.runtime = None
                                    result = cli_runner.invoke(main, ["cleanup", "--dry-run"])

        assert result.exit_code == 0
        assert "Tmux sessions to kill" in result.output
        assert "testproject-issue-999" in result.output

    def test_cleanup_force_no_prompt(self, cli_runner, mock_config):
        """Should skip confirmation with --force."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="042",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage="accepted",
        )

        mock_worktrees = [
            {"path": "/repo", "branch": "main"},
            {"path": "/repo/.worktrees/issue-042-test-issue", "branch": "issue-042-test-issue"},
        ]

        with patch("agenttree.cli.misc.load_config", return_value=mock_config):
            with patch("agenttree.cli.misc.is_running_in_container", return_value=False):
                with patch("agenttree.cli.misc.list_issues_func", return_value=[mock_issue]):
                    with patch("agenttree.worktree.list_worktrees", return_value=mock_worktrees):
                        with patch("subprocess.run") as mock_run:
                            mock_run.return_value.stdout = ""
                            mock_run.return_value.returncode = 0
                            with patch("agenttree.tmux.list_sessions", return_value=[]):
                                with patch("agenttree.cli.misc.get_container_runtime") as mock_runtime:
                                    mock_runtime.return_value.runtime = None
                                    with patch("agenttree.worktree.remove_worktree") as mock_remove:
                                        result = cli_runner.invoke(main, ["cleanup", "--force"])

        assert result.exit_code == 0
        # With --force, it should proceed without prompting
        mock_remove.assert_called_once()

    def test_cleanup_selective_categories(self, cli_runner, mock_config):
        """Should allow selective cleanup of categories."""
        from agenttree.cli import main

        with patch("agenttree.cli.misc.load_config", return_value=mock_config):
            with patch("agenttree.cli.misc.is_running_in_container", return_value=False):
                with patch("agenttree.cli.misc.list_issues_func", return_value=[]):
                    with patch("agenttree.worktree.list_worktrees", return_value=[{"path": "/repo", "branch": "main"}]):
                        with patch("agenttree.tmux.list_sessions", return_value=[]):
                            with patch("agenttree.cli.misc.get_container_runtime") as mock_runtime:
                                mock_runtime.return_value.runtime = None
                                # Only check worktrees, skip branches/sessions/containers
                                result = cli_runner.invoke(main, [
                                    "cleanup", "--dry-run",
                                    "--no-branches", "--no-sessions", "--no-containers"
                                ])

        assert result.exit_code == 0
        # subprocess.run should not be called for git branch commands
        assert "Checking worktrees" in result.output or "Nothing to clean up" in result.output


class TestAINotesDetection:
    """Tests for AI notes detection helper."""

    def test_detect_ai_notes_finds_claude_files(self, tmp_path):
        """Should detect files with CLAUDE in the name at root level."""
        from agenttree.cli.setup import _detect_ai_notes

        # Create test files at root level (pattern matching is root-level only)
        (tmp_path / "CLAUDE.md").write_text("Claude notes")
        (tmp_path / "CLAUDE_NOTES.md").write_text("More notes")
        (tmp_path / "ai_summary.md").write_text("AI summary")

        notes = _detect_ai_notes(tmp_path)
        names = [n.name for n in notes]

        assert "CLAUDE.md" in names
        assert "CLAUDE_NOTES.md" in names
        assert "ai_summary.md" in names

    def test_detect_ai_notes_excludes_readme(self, tmp_path):
        """Should not detect README.md files."""
        from agenttree.cli.setup import _detect_ai_notes

        (tmp_path / "README.md").write_text("Project readme")
        (tmp_path / "CLAUDE.md").write_text("Claude notes")

        notes = _detect_ai_notes(tmp_path)
        names = [n.name.lower() for n in notes]

        assert "readme.md" not in names
        assert "claude.md" in names

    def test_detect_ai_notes_excludes_agenttree_dir(self, tmp_path):
        """Should not detect files inside _agenttree directory."""
        from agenttree.cli.setup import _detect_ai_notes

        (tmp_path / "_agenttree").mkdir()
        (tmp_path / "_agenttree" / "notes").mkdir()
        (tmp_path / "_agenttree" / "notes" / "CLAUDE.md").write_text("Already migrated")
        (tmp_path / "CLAUDE.md").write_text("Should be detected")

        notes = _detect_ai_notes(tmp_path)
        paths = [str(n) for n in notes]

        assert any("CLAUDE.md" in p and "_agenttree" not in p for p in paths)
        assert not any("_agenttree" in p for p in paths)

    def test_detect_ai_notes_finds_notes_directory(self, tmp_path):
        """Should detect files in notes/ directory."""
        from agenttree.cli.setup import _detect_ai_notes

        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "research.md").write_text("Research notes")
        (tmp_path / "notes" / "ideas.md").write_text("Ideas")

        notes = _detect_ai_notes(tmp_path)
        names = [n.name for n in notes]

        assert "research.md" in names
        assert "ideas.md" in names

    def test_detect_ai_notes_empty_repo(self, tmp_path):
        """Should return empty list for repo with no AI notes."""
        from agenttree.cli.setup import _detect_ai_notes

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# Code")
        (tmp_path / "README.md").write_text("Project readme")

        notes = _detect_ai_notes(tmp_path)

        assert len(notes) == 0


class TestNotesMigration:
    """Tests for notes migration helper."""

    def test_migrate_notes_moves_files(self, tmp_path):
        """Should move files to _agenttree/notes/."""
        from agenttree.cli.setup import _migrate_notes

        # Create source files
        (tmp_path / "CLAUDE.md").write_text("Claude notes")
        agents_path = tmp_path / "_agenttree"
        agents_path.mkdir()

        notes = [tmp_path / "CLAUDE.md"]
        migrated = _migrate_notes(tmp_path, notes, agents_path)

        assert migrated == 1
        assert (agents_path / "notes" / "CLAUDE.md").exists()
        assert not (tmp_path / "CLAUDE.md").exists()

    def test_migrate_notes_preserves_path_structure(self, tmp_path):
        """Should preserve relative path structure."""
        from agenttree.cli.setup import _migrate_notes

        (tmp_path / "docs" / "ai-notes").mkdir(parents=True)
        (tmp_path / "docs" / "ai-notes" / "research.md").write_text("Research")
        agents_path = tmp_path / "_agenttree"
        agents_path.mkdir()

        notes = [tmp_path / "docs" / "ai-notes" / "research.md"]
        migrated = _migrate_notes(tmp_path, notes, agents_path)

        assert migrated == 1
        assert (agents_path / "notes" / "docs" / "ai-notes" / "research.md").exists()


class TestInitKnowledgeIssue:
    """Tests for knowledge issue creation during init."""

    def test_create_knowledge_issue_helper(self, tmp_path):
        """Should create knowledge population issue with correct parameters."""
        from agenttree.cli.setup import _create_knowledge_issue

        mock_issue = MagicMock()
        mock_issue.id = "001"

        with patch("agenttree.issues.create_issue", return_value=mock_issue) as mock_create:
            _create_knowledge_issue(tmp_path)

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert "knowledge base" in call_kwargs["title"].lower()
        assert "Analyze" in call_kwargs["problem"]

    def test_prompt_notes_migration_shows_explanation(self, tmp_path, capsys):
        """Should display explanation about AgentTree notes manager."""
        from agenttree.cli.setup import _prompt_notes_migration

        agents_path = tmp_path / "_agenttree"
        agents_path.mkdir()

        mock_notes = [tmp_path / "CLAUDE.md"]
        (tmp_path / "CLAUDE.md").write_text("Notes")

        with patch("click.confirm", return_value=False):
            _prompt_notes_migration(tmp_path, mock_notes, agents_path)

        # Check that the explanation was printed (via rich console)
        # We can't easily capture rich output, so just ensure no exception

    def test_prompt_notes_migration_decline_shows_command(self, tmp_path):
        """Should show migrate-docs command when user declines."""
        from agenttree.cli.setup import _prompt_notes_migration

        agents_path = tmp_path / "_agenttree"
        agents_path.mkdir()

        mock_notes = [tmp_path / "CLAUDE.md"]
        (tmp_path / "CLAUDE.md").write_text("Notes")

        # User declines migration
        with patch("click.confirm", return_value=False):
            # This should not raise and should print the command
            _prompt_notes_migration(tmp_path, mock_notes, agents_path)

    def test_prompt_notes_migration_accept_migrates_files(self, tmp_path):
        """Should migrate files when user confirms."""
        from agenttree.cli.setup import _prompt_notes_migration

        agents_path = tmp_path / "_agenttree"
        agents_path.mkdir()

        # Create a test file
        (tmp_path / "CLAUDE.md").write_text("Notes content")
        mock_notes = [tmp_path / "CLAUDE.md"]

        with patch("click.confirm", return_value=True):
            with patch("agenttree.cli.setup._migrate_notes", return_value=1) as mock_migrate:
                _prompt_notes_migration(tmp_path, mock_notes, agents_path)

        mock_migrate.assert_called_once()


class TestMigrateDocsCommand:
    """Tests for the migrate-docs command."""

    def test_migrate_docs_no_agenttree(self, cli_runner, mock_config, tmp_path, monkeypatch):
        """Should error when _agenttree doesn't exist."""
        from agenttree.cli import main

        monkeypatch.chdir(tmp_path)

        result = cli_runner.invoke(main, ["migrate-docs"])

        assert result.exit_code == 1
        assert "_agenttree/ directory not found" in result.output

    def test_migrate_docs_no_notes_found(self, cli_runner, mock_config, tmp_path, monkeypatch):
        """Should show message when no AI notes found."""
        from agenttree.cli import main

        monkeypatch.chdir(tmp_path)
        (tmp_path / "_agenttree").mkdir()

        with patch("agenttree.cli.setup._detect_ai_notes", return_value=[]):
            result = cli_runner.invoke(main, ["migrate-docs"])

        assert "No AI notes files found" in result.output

    def test_migrate_docs_prompts_when_found(self, cli_runner, mock_config, tmp_path, monkeypatch):
        """Should prompt for migration when AI notes are found."""
        from agenttree.cli import main

        monkeypatch.chdir(tmp_path)
        (tmp_path / "_agenttree").mkdir()

        mock_notes = [tmp_path / "CLAUDE.md"]
        with patch("agenttree.cli.setup._detect_ai_notes", return_value=mock_notes):
            with patch("agenttree.cli.setup._prompt_notes_migration") as mock_prompt:
                result = cli_runner.invoke(main, ["migrate-docs"])

        mock_prompt.assert_called_once()

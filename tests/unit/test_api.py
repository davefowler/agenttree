"""Tests for agenttree.api module."""

from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

from agenttree.api import (
    start_issue,
    start_controller,
    send_message,
    IssueNotFoundError,
    AgentStartError,
    AgentAlreadyRunningError,
    PreflightError,
    MessengerNotRunningError,
)


class TestStartAgent:
    """Tests for start_issue() function."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock()
        config.project = "testproj"
        config.default_tool = "claude"
        config.port_range = "8000-8099"
        config.get_issue_worktree_path.return_value = Path("/tmp/worktrees/042-test-issue")
        config.model_for.return_value = "claude-sonnet-4-20250514"
        config.get_port_for_issue.return_value = 8042
        config.is_resumable_stage.return_value = False
        config.commands = {}
        return config

    @pytest.fixture
    def mock_issue(self):
        """Create a mock issue."""
        issue = MagicMock()
        issue.id = "042"
        issue.slug = "test-issue"
        issue.title = "Test Issue"
        issue.stage = "explore.define"
        return issue

    @pytest.fixture
    def mock_agent(self):
        """Create a mock active agent."""
        agent = MagicMock()
        agent.issue_id = "042"
        agent.role = "developer"
        agent.pid = 12345
        agent.worktree = Path("/tmp/worktrees/042-test-issue")
        agent.port = 8042
        agent.log_file = "/tmp/worktrees/042-test-issue/.agenttree/agent-developer.log"
        agent.started = "2024-01-01T00:00:00Z"
        return agent

    def test_start_issue_creates_worktree_and_starts_process(
        self, mock_config, mock_issue, mock_agent, tmp_path, monkeypatch
    ):
        """Happy path: returns ActiveAgent."""
        monkeypatch.chdir(tmp_path)

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.log_file = "/tmp/worktrees/042-test-issue/.agenttree/agent-developer.log"
        mock_proc.started = "2024-01-01T00:00:00Z"

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[]):
                with patch("agenttree.issues.get_issue", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("agenttree.state.get_issue_names", return_value={
                            "branch": "issue-042-test-issue",
                            "session": "testproj-issue-042",
                        }):
                            with patch("agenttree.worktree.create_worktree"):
                                with patch("agenttree.worktree.sync_local_agenttree_config"):
                                    with patch("agenttree.issues.create_session"):
                                        with patch("agenttree.issues.update_issue_metadata"):
                                            with patch("agenttree.process.start_agent", return_value=mock_proc):
                                                with patch("agenttree.process.stop_agent_process"):
                                                    with patch("subprocess.run") as mock_run:
                                                        mock_run.return_value = MagicMock(returncode=1)
                                                        result = start_issue("042", quiet=True)

        assert result.issue_id == mock_issue.id

    def test_start_issue_issue_not_found_raises(self, mock_config, tmp_path, monkeypatch):
        """IssueNotFoundError when issue doesn't exist."""
        monkeypatch.chdir(tmp_path)

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[]):
                with patch("agenttree.issues.get_issue", return_value=None):
                    with pytest.raises(IssueNotFoundError) as exc_info:
                        start_issue("999", quiet=True)

        assert exc_info.value.issue_id == 999

    def test_start_issue_already_running_without_force_raises(
        self, mock_config, mock_issue, mock_agent, tmp_path, monkeypatch
    ):
        """AgentAlreadyRunningError without --force."""
        monkeypatch.chdir(tmp_path)

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[]):
                with patch("agenttree.issues.get_issue", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                        with pytest.raises(AgentAlreadyRunningError) as exc_info:
                            start_issue("042", quiet=True)

        assert exc_info.value.issue_id == "042"

    def test_start_issue_force_restarts_existing(
        self, mock_config, mock_issue, mock_agent, tmp_path, monkeypatch
    ):
        """With force=True, restarts agent."""
        monkeypatch.chdir(tmp_path)

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.log_file = "/tmp/worktrees/042-test-issue/.agenttree/agent-developer.log"
        mock_proc.started = "2024-01-01T00:00:00Z"

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[]):
                with patch("agenttree.issues.get_issue", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                        with patch("agenttree.process.stop_agent_process") as mock_stop:
                            with patch("agenttree.state.get_issue_names", return_value={
                                "branch": "issue-042-test-issue",
                                "session": "testproj-issue-042",
                            }):
                                with patch("agenttree.worktree.create_worktree"):
                                    with patch("agenttree.worktree.sync_local_agenttree_config"):
                                        with patch("agenttree.issues.create_session"):
                                            with patch("agenttree.issues.update_issue_metadata"):
                                                with patch("agenttree.process.start_agent", return_value=mock_proc):
                                                    with patch("subprocess.run") as mock_run:
                                                        mock_run.return_value = MagicMock(returncode=1)
                                                        result = start_issue("042", force=True, quiet=True)

        assert result.issue_id == mock_issue.id
        mock_stop.assert_called_once()

    def test_start_issue_syncs_local_agenttree_config_into_worktree(
        self, mock_config, mock_issue, mock_agent, tmp_path, monkeypatch
    ):
        """Issue start should copy local workflow config into the worktree."""
        monkeypatch.chdir(tmp_path)

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.log_file = "/tmp/worktrees/042-test-issue/.agenttree/agent-developer.log"
        mock_proc.started = "2024-01-01T00:00:00Z"

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[]):
                with patch("agenttree.issues.get_issue", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("agenttree.state.get_issue_names", return_value={
                            "branch": "issue-042-test-issue",
                            "session": "testproj-issue-042",
                        }):
                            with patch("agenttree.worktree.create_worktree"):
                                with patch("agenttree.worktree.sync_local_agenttree_config") as mock_sync:
                                    with patch("agenttree.issues.create_session"):
                                        with patch("agenttree.issues.update_issue_metadata"):
                                            with patch("agenttree.process.start_agent", return_value=mock_proc):
                                                with patch("subprocess.run") as mock_run:
                                                    mock_run.return_value = MagicMock(returncode=1)
                                                    start_issue("042", quiet=True)

        mock_sync.assert_called_once_with(
            tmp_path,
            mock_config.get_issue_worktree_path.return_value,
        )

    def test_start_issue_preflight_failure(self, mock_config, tmp_path, monkeypatch):
        """PreflightError when checks fail."""
        monkeypatch.chdir(tmp_path)

        mock_result = MagicMock()
        mock_result.passed = False
        mock_result.name = "git_clean"
        mock_result.message = "Uncommitted changes"

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[mock_result]):
                with pytest.raises(PreflightError) as exc_info:
                    start_issue("042", quiet=True)

        assert "git_clean" in str(exc_info.value)

    def test_start_issue_quiet_suppresses_output(
        self, mock_config, mock_issue, mock_agent, tmp_path, monkeypatch, capsys
    ):
        """No console output when quiet=True."""
        monkeypatch.chdir(tmp_path)

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.log_file = "/tmp/worktrees/042-test-issue/.agenttree/agent-developer.log"
        mock_proc.started = "2024-01-01T00:00:00Z"

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[]):
                with patch("agenttree.issues.get_issue", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("agenttree.state.get_issue_names", return_value={
                            "branch": "issue-042-test-issue",
                            "session": "testproj-issue-042",
                        }):
                            with patch("agenttree.worktree.create_worktree"):
                                with patch("agenttree.worktree.sync_local_agenttree_config"):
                                    with patch("agenttree.issues.create_session"):
                                        with patch("agenttree.issues.update_issue_metadata"):
                                            with patch("agenttree.process.start_agent", return_value=mock_proc):
                                                with patch("subprocess.run") as mock_run:
                                                    mock_run.return_value = MagicMock(returncode=1)
                                                    start_issue("042", quiet=True)

        captured = capsys.readouterr()
        assert captured.out == ""


class TestSendMessage:
    """Tests for send_message() function."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock()
        config.project = "testproj"
        return config

    @pytest.fixture
    def mock_issue(self):
        """Create a mock issue."""
        issue = MagicMock()
        issue.id = "042"
        return issue

    @pytest.fixture
    def mock_agent(self):
        """Create a mock active agent."""
        agent = MagicMock()
        agent.issue_id = "042"
        agent.role = "developer"
        agent.pid = 12345
        return agent

    def test_send_message_agent_running(self, mock_config, mock_issue, mock_agent):
        """Returns 'sent' when sub-agent is running (can't send mid-flight)."""
        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", return_value=mock_issue):
                with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                    result = send_message("042", "hello", quiet=True)

        assert result == "sent"

    def test_send_message_auto_starts_agent(self, mock_config, mock_issue):
        """Starts agent if not running and auto_start=True."""
        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", return_value=mock_issue):
                with patch("agenttree.state.get_active_agent", return_value=None):
                    with patch("agenttree.api.start_issue") as mock_start:
                        result = send_message("042", "hello", quiet=True)

        assert result == "restarted"
        mock_start.assert_called_once()

    def test_send_message_no_auto_start(self, mock_config, mock_issue):
        """Returns 'no_agent' if agent not running and auto_start=False."""
        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", return_value=mock_issue):
                with patch("agenttree.state.get_active_agent", return_value=None):
                    result = send_message("042", "hello", auto_start=False, quiet=True)

        assert result == "no_agent"

    def test_send_message_issue_not_found(self, mock_config):
        """IssueNotFoundError when issue doesn't exist."""
        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", return_value=None):
                with pytest.raises(IssueNotFoundError) as exc_info:
                    send_message("999", "hello", quiet=True)

        assert exc_info.value.issue_id == 999


class TestStartController:
    """Tests for start_controller() function (alias for start_messenger)."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        from agenttree.config import RoleConfig
        config = MagicMock()
        config.project = "testproj"
        config.default_tool = "claude"
        config.default_model = "opus"
        manager_role = RoleConfig(name="messenger", tool="claude", model="sonnet")
        config.roles = {"messenger": manager_role}
        config.get_role_tmux_session.return_value = "testproj-controller-000"
        return config

    def test_start_controller_creates_session(self, mock_config, tmp_path, monkeypatch):
        """Creates tmux session on host."""
        monkeypatch.chdir(tmp_path)

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=False):
                with patch("agenttree.tmux.TmuxManager") as mock_tm_class:
                    mock_tm = MagicMock()
                    mock_tm_class.return_value = mock_tm

                    start_controller(quiet=True)

        mock_tm.start_host_role.assert_called_once()
        call_args = mock_tm.start_host_role.call_args
        assert call_args.kwargs["session_name"] == "testproj-controller-000"

    def test_start_controller_not_in_container(self, mock_config, tmp_path, monkeypatch):
        """Runs directly without container."""
        monkeypatch.chdir(tmp_path)

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=False):
                with patch("agenttree.tmux.TmuxManager") as mock_tm_class:
                    mock_tm = MagicMock()
                    mock_tm_class.return_value = mock_tm

                    start_controller(quiet=True)

        # Verify start_host_role was called (not start_issue_agent_in_container)
        mock_tm.start_host_role.assert_called_once()
        mock_tm.start_issue_agent_in_container.assert_not_called()

    def test_start_controller_already_running_raises(self, mock_config, tmp_path, monkeypatch):
        """AgentAlreadyRunningError if already running without force."""
        monkeypatch.chdir(tmp_path)

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=True):
                with pytest.raises(AgentAlreadyRunningError) as exc_info:
                    start_controller(quiet=True)

        assert exc_info.value.issue_id == "messenger"

    def test_start_controller_force_restarts(self, mock_config, tmp_path, monkeypatch):
        """With force=True, restarts controller."""
        monkeypatch.chdir(tmp_path)

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=True):
                with patch("agenttree.tmux.kill_session") as mock_kill:
                    with patch("agenttree.tmux.TmuxManager") as mock_tm_class:
                        mock_tm = MagicMock()
                        mock_tm_class.return_value = mock_tm

                        start_controller(force=True, quiet=True)

        mock_kill.assert_called_once_with("testproj-controller-000")
        mock_tm.start_host_role.assert_called_once()


class TestControllerMessages:
    """Tests for sending messages to messenger (issue 0)."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock()
        config.project = "testproj"
        config.get_role_tmux_session.return_value = "testproj-controller-000"
        config.get_manager_tmux_session.return_value = "testproj-controller-000"
        return config

    def test_send_to_messenger_success(self, mock_config):
        """Message sent to messenger successfully."""
        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=True):
                with patch("agenttree.tmux.send_message", return_value="sent") as mock_send:
                    result = send_message("0", "hello controller", quiet=True)

        assert result == "sent"
        mock_send.assert_called_once_with("testproj-controller-000", "hello controller", interrupt=False)

    def test_send_to_messenger_not_running(self, mock_config):
        """MessengerNotRunningError if messenger not running."""
        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=False):
                with pytest.raises(MessengerNotRunningError):
                    send_message("0", "hello", quiet=True)


# =============================================================================
# Tests for Stop/Cleanup Functions
# =============================================================================


class TestStopAgent:
    """Tests for stop_agent function."""

    def test_stop_agent_kills_process_and_serve_session(self):
        """stop_agent kills serve tmux session and stops process."""
        from agenttree.api import stop_agent

        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.commands = {}

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.process.stop_agent_process", return_value=True) as mock_stop_proc, \
             patch("agenttree.ids.serve_session_name", return_value="myproject-serve-042"), \
             patch("agenttree.tmux.session_exists", return_value=False), \
             patch("agenttree.tmux.kill_session") as mock_kill:

            result = stop_agent(42, "developer", quiet=True)

        assert result is True
        mock_stop_proc.assert_called_once_with(42, "developer")
        mock_kill.assert_not_called()  # serve session doesn't exist

    def test_stop_agent_kills_serve_session_if_exists(self):
        """stop_agent kills serve tmux session when it exists."""
        from agenttree.api import stop_agent

        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.commands = {}

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.process.stop_agent_process", return_value=True), \
             patch("agenttree.ids.serve_session_name", return_value="myproject-serve-042"), \
             patch("agenttree.tmux.session_exists", return_value=True), \
             patch("agenttree.tmux.kill_session") as mock_kill:

            result = stop_agent(42, "developer", quiet=True)

        assert result is True
        mock_kill.assert_called_once_with("myproject-serve-042")

    def test_stop_agent_handles_no_process(self):
        """stop_agent returns False when nothing to stop."""
        from agenttree.api import stop_agent

        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.commands = {}

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.process.stop_agent_process", return_value=False), \
             patch("agenttree.ids.serve_session_name", return_value="myproject-serve-042"), \
             patch("agenttree.tmux.session_exists", return_value=False), \
             patch("agenttree.tmux.kill_session") as mock_kill:

            result = stop_agent(42, "developer", quiet=True)

        assert result is False
        mock_kill.assert_not_called()

    def test_stop_agent_calls_stop_agent_process(self):
        """stop_agent uses agenttree.process.stop_agent_process, not tmux/container."""
        from agenttree.api import stop_agent

        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.commands = {}

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.process.stop_agent_process", return_value=True) as mock_stop_proc, \
             patch("agenttree.ids.serve_session_name", return_value="myproject-serve-042"), \
             patch("agenttree.tmux.session_exists", return_value=False):

            stop_agent(42, "developer", quiet=True)

        mock_stop_proc.assert_called_once_with(42, "developer")


class TestStopAllAgentsForIssue:
    """Tests for stop_all_agents_for_issue function."""

    def test_stop_all_agents_for_issue(self):
        """stop_all_agents_for_issue delegates to process.stop_all_for_issue."""
        from agenttree.api import stop_all_agents_for_issue

        with patch("agenttree.process.stop_all_for_issue", return_value=2) as mock_stop:
            result = stop_all_agents_for_issue("042", quiet=True)

        assert result == 2
        mock_stop.assert_called_once_with("042")


class TestCleanupOrphanedContainers:
    """Tests for cleanup_orphaned_containers - now a no-op."""

    def test_cleanup_orphaned_containers_is_noop(self):
        """cleanup_orphaned_containers returns 0 (no-op)."""
        from agenttree.api import cleanup_orphaned_containers

        result = cleanup_orphaned_containers(quiet=True)

        assert result == 0

    def test_cleanup_orphaned_skips_active(self):
        """cleanup_orphaned_containers is a no-op regardless of state."""
        from agenttree.api import cleanup_orphaned_containers

        result = cleanup_orphaned_containers(quiet=False)

        assert result == 0


class TestCleanupAllContainers:
    """Tests for cleanup_all_agenttree_containers - now a no-op."""

    def test_cleanup_all_containers_is_noop(self):
        """cleanup_all_agenttree_containers returns 0 (no-op)."""
        from agenttree.api import cleanup_all_agenttree_containers

        result = cleanup_all_agenttree_containers(quiet=True)

        assert result == 0


class TestCleanupAllWithRetry:
    """Tests for cleanup_all_with_retry - now a no-op."""

    def test_cleanup_all_with_retry_is_noop(self):
        """cleanup_all_with_retry is a no-op."""
        from agenttree.api import cleanup_all_with_retry

        # Should not raise
        cleanup_all_with_retry(max_passes=3, delay_s=1.0, quiet=True)

    def test_cleanup_all_with_retry_single_pass(self):
        """cleanup_all_with_retry is a no-op for single pass too."""
        from agenttree.api import cleanup_all_with_retry

        cleanup_all_with_retry(max_passes=1, delay_s=2.0, quiet=True)


class TestTransitionIssue:
    """Tests for transition_issue() function."""

    @pytest.fixture
    def mock_issue(self):
        issue = MagicMock()
        issue.id = "42"
        issue.stage = "plan.review"
        issue.slug = "test-issue"
        return issue

    def test_transition_success(self, mock_issue):
        """Normal transition: exit hooks -> stage update -> enter hooks -> ensure agent."""
        from agenttree.api import transition_issue

        updated_issue = MagicMock()
        updated_issue.stage = "implement.code"

        with patch("agenttree.issues.get_issue", return_value=mock_issue), \
             patch("agenttree.hooks.execute_exit_hooks") as mock_exit, \
             patch("agenttree.issues.update_issue_stage", return_value=updated_issue) as mock_update, \
             patch("agenttree.hooks.execute_enter_hooks") as mock_enter, \
             patch("agenttree.api._ensure_stage_agent") as mock_ensure:

            result = transition_issue("42", "implement.code")

        assert result == updated_issue
        mock_exit.assert_called_once_with(mock_issue, "plan.review", skip_pr_approval=False)
        mock_update.assert_called_once_with(42, "implement.code")
        mock_enter.assert_called_once_with(updated_issue, "implement.code")
        mock_ensure.assert_called_once_with(42, "implement.code")

    def test_transition_exit_hook_redirect(self, mock_issue):
        """Exit hook StageRedirect changes the target stage."""
        from agenttree.api import transition_issue
        from agenttree.hooks import StageRedirect

        updated_issue = MagicMock()
        updated_issue.stage = "explore.define"

        with patch("agenttree.issues.get_issue", return_value=mock_issue), \
             patch("agenttree.hooks.execute_exit_hooks", side_effect=StageRedirect("explore.define", "needs more work")), \
             patch("agenttree.issues.update_issue_stage", return_value=updated_issue) as mock_update, \
             patch("agenttree.hooks.execute_enter_hooks"), \
             patch("agenttree.api._ensure_stage_agent") as mock_ensure:

            result = transition_issue("42", "implement.code")

        # Should have updated to the redirected stage, not original target
        mock_update.assert_called_once_with(42, "explore.define")
        assert result == updated_issue
        mock_ensure.assert_called_once_with(42, "explore.define")

    def test_transition_enter_hook_redirect(self, mock_issue):
        """Enter hook StageRedirect updates stage and ensures agent for redirect target."""
        from agenttree.api import transition_issue
        from agenttree.hooks import StageRedirect

        updated_issue = MagicMock()
        redirected_issue = MagicMock()
        redirected_issue.stage = "implement.code"

        with patch("agenttree.issues.get_issue", return_value=mock_issue), \
             patch("agenttree.hooks.execute_exit_hooks"), \
             patch("agenttree.issues.update_issue_stage", side_effect=[updated_issue, redirected_issue]), \
             patch("agenttree.hooks.execute_enter_hooks", side_effect=StageRedirect("implement.code", "merge conflict")), \
             patch("agenttree.api._ensure_stage_agent") as mock_ensure:

            result = transition_issue("42", "accepted")

        assert result == redirected_issue
        mock_ensure.assert_called_once_with(42, "implement.code")

    def test_transition_validation_error_propagates(self, mock_issue):
        """ValidationError from exit hooks propagates to caller."""
        from agenttree.api import transition_issue
        from agenttree.hooks import ValidationError

        with patch("agenttree.issues.get_issue", return_value=mock_issue), \
             patch("agenttree.hooks.execute_exit_hooks", side_effect=ValidationError("Tests failed")):

            with pytest.raises(ValidationError, match="Tests failed"):
                transition_issue("42", "implement")

    def test_transition_issue_not_found(self):
        """RuntimeError if issue doesn't exist."""
        from agenttree.api import transition_issue

        with patch("agenttree.issues.get_issue", return_value=None):
            with pytest.raises(RuntimeError, match="not found"):
                transition_issue("999", "implement")

    def test_transition_enter_hook_failure_rolls_back_and_raises(self, mock_issue):
        """Non-redirect enter hook errors rollback stage and raise RuntimeError."""
        from agenttree.api import transition_issue

        updated_issue = MagicMock()
        updated_issue.stage = "accepted"
        rolled_back_issue = MagicMock()
        rolled_back_issue.stage = "plan.review"

        with patch("agenttree.issues.get_issue", return_value=mock_issue), \
             patch("agenttree.hooks.execute_exit_hooks"), \
             patch("agenttree.issues.update_issue_stage", side_effect=[updated_issue, rolled_back_issue]) as mock_update, \
             patch("agenttree.hooks.execute_enter_hooks", side_effect=RuntimeError("merge failed")), \
             patch("agenttree.api._ensure_stage_agent") as mock_ensure:

            with pytest.raises(RuntimeError, match="Enter hooks failed"):
                transition_issue("42", "accepted")

        assert mock_update.call_count == 2
        assert mock_update.call_args_list[0].args == (42, "accepted")
        assert mock_update.call_args_list[1].args == (42, "plan.review")
        mock_ensure.assert_called_once_with(42, "plan.review")


class TestNotifyAgent:
    """Tests for _notify_agent() function."""

    def test_notify_sends_to_messenger_via_tmux(self):
        """Sends message to messenger (issue 0) via tmux."""
        from agenttree.api import _notify_agent

        mock_config = MagicMock()
        mock_config.get_role_tmux_session.return_value = "testproj-messenger-000"
        mock_config.get_manager_tmux_session.return_value = "testproj-messenger-000"

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", return_value=True), \
             patch("agenttree.tmux.send_message") as mock_send:

            _notify_agent(0, "Test message")

        mock_send.assert_called_once_with("testproj-messenger-000", "Test message", interrupt=False)

    def test_notify_sends_with_interrupt_to_messenger(self):
        """Sends message with interrupt=True when specified (messenger only)."""
        from agenttree.api import _notify_agent

        mock_config = MagicMock()
        mock_config.get_role_tmux_session.return_value = "testproj-messenger-000"
        mock_config.get_manager_tmux_session.return_value = "testproj-messenger-000"

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", return_value=True), \
             patch("agenttree.tmux.send_message") as mock_send:

            _notify_agent(0, "Test message", interrupt=True)

        mock_send.assert_called_once_with("testproj-messenger-000", "Test message", interrupt=True)

    def test_notify_sub_agent_is_noop(self):
        """Does nothing for sub-agents (non-zero issue_id)."""
        from agenttree.api import _notify_agent

        with patch("agenttree.tmux.send_message") as mock_send:
            _notify_agent(42, "Test message")  # Should not send via tmux

        mock_send.assert_not_called()

    def test_notify_messenger_no_session_is_noop(self):
        """Does nothing if messenger tmux session doesn't exist."""
        from agenttree.api import _notify_agent

        mock_config = MagicMock()
        mock_config.get_role_tmux_session.return_value = "testproj-messenger-000"
        mock_config.get_manager_tmux_session.return_value = "testproj-messenger-000"

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", return_value=False), \
             patch("agenttree.tmux.send_message") as mock_send:

            _notify_agent(0, "Test message")

        mock_send.assert_not_called()

    def test_notify_never_raises(self):
        """Never raises even if operations fail."""
        from agenttree.api import _notify_agent

        with patch("agenttree.config.load_config", side_effect=Exception("boom")):
            _notify_agent(0, "Test message")  # Should not raise

    def test_notify_sub_agent_never_raises(self):
        """Never raises for sub-agents either."""
        from agenttree.api import _notify_agent

        _notify_agent(42, "Test message")  # Should not raise


class TestStartRole:
    """Tests for start_role() function."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config for role tests."""
        config = MagicMock()
        config.project = "testproj"
        config.default_tool = "claude"
        config.default_model = "sonnet"
        config.get_role_tmux_session.return_value = "testproj-messenger-000"
        return config

    @pytest.fixture
    def mock_role(self):
        """Create a mock role config."""
        role = MagicMock()
        role.tool = "claude"
        role.model = "opus"
        role.skill_file = "messenger.md"
        return role

    def test_start_role_creates_tmux_session(
        self, mock_config, mock_role, tmp_path, monkeypatch
    ):
        """start_role creates tmux session via TmuxManager.start_host_role."""
        from agenttree.api import start_role

        monkeypatch.chdir(tmp_path)
        mock_config.roles = {"messenger": mock_role}

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", return_value=False), \
             patch("agenttree.tmux.TmuxManager") as mock_tm_class:
            mock_tm = MagicMock()
            mock_tm_class.return_value = mock_tm

            start_role("messenger", quiet=True)

        mock_tm.start_host_role.assert_called_once()

    def test_start_role_already_running_raises(
        self, mock_config, mock_role, tmp_path, monkeypatch
    ):
        """AgentAlreadyRunningError if session already running."""
        from agenttree.api import start_role

        monkeypatch.chdir(tmp_path)
        mock_config.roles = {"messenger": mock_role}

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", return_value=True):

            with pytest.raises(AgentAlreadyRunningError):
                start_role("messenger", quiet=True)

    def test_start_role_force_restarts(
        self, mock_config, mock_role, tmp_path, monkeypatch
    ):
        """force=True kills existing session and restarts."""
        from agenttree.api import start_role

        monkeypatch.chdir(tmp_path)
        mock_config.roles = {"messenger": mock_role}

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", return_value=True), \
             patch("agenttree.tmux.kill_session") as mock_kill, \
             patch("agenttree.tmux.TmuxManager") as mock_tm_class:
            mock_tm = MagicMock()
            mock_tm_class.return_value = mock_tm

            start_role("messenger", force=True, quiet=True)

        mock_kill.assert_called_once_with("testproj-messenger-000")
        mock_tm.start_host_role.assert_called_once()

    def test_start_role_messenger_in_host_tmux_roles(self):
        """HOST_TMUX_ROLES contains 'messenger'."""
        from agenttree.api import HOST_TMUX_ROLES

        assert "messenger" in HOST_TMUX_ROLES

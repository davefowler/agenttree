"""Tests for agenttree.api module."""

from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

from agenttree.api import (
    start_agent,
    start_controller,
    send_message,
    IssueNotFoundError,
    AgentStartError,
    AgentAlreadyRunningError,
    PreflightError,
    ContainerUnavailableError,
    ControllerNotRunningError,
)


class TestStartAgent:
    """Tests for start_agent() function."""

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
        agent.host = "agent"
        agent.tmux_session = "testproj-issue-042"
        agent.worktree_path = Path("/tmp/worktrees/042-test-issue")
        agent.port = 8042
        return agent

    def test_start_agent_creates_worktree_and_starts_tmux(
        self, mock_config, mock_issue, mock_agent, tmp_path, monkeypatch
    ):
        """Happy path: returns ActiveAgent."""
        monkeypatch.chdir(tmp_path)

        mock_runtime = MagicMock()
        mock_runtime.is_available.return_value = True
        mock_runtime.get_runtime_name.return_value = "docker"

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[]):
                with patch("agenttree.issues.get_issue", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("agenttree.tmux.TmuxManager") as mock_tm_class:
                            mock_tm = MagicMock()
                            mock_tm.start_issue_agent_in_container.return_value = True
                            mock_tm_class.return_value = mock_tm

                            with patch("agenttree.state.create_agent_for_issue", return_value=mock_agent):
                                with patch("agenttree.container.get_container_runtime", return_value=mock_runtime):
                                    with patch("agenttree.worktree.create_worktree"):
                                        with patch("agenttree.state.get_issue_names", return_value={
                                            "branch": "issue-042-test-issue",
                                            "session": "testproj-issue-042",
                                        }):
                                                with patch("agenttree.issues.create_session"):
                                                    with patch("agenttree.issues.update_issue_metadata"):
                                                        with patch("subprocess.run") as mock_run:
                                                            mock_run.return_value = MagicMock(returncode=1)
                                                            result = start_agent("042", quiet=True)

        assert result == mock_agent

    def test_start_agent_issue_not_found_raises(self, mock_config, tmp_path, monkeypatch):
        """IssueNotFoundError when issue doesn't exist."""
        monkeypatch.chdir(tmp_path)

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[]):
                with patch("agenttree.issues.get_issue", return_value=None):
                    with pytest.raises(IssueNotFoundError) as exc_info:
                        start_agent("999", quiet=True)

        assert exc_info.value.issue_id == 999

    def test_start_agent_already_running_without_force_raises(
        self, mock_config, mock_issue, mock_agent, tmp_path, monkeypatch
    ):
        """AgentAlreadyRunningError without --force."""
        monkeypatch.chdir(tmp_path)

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[]):
                with patch("agenttree.issues.get_issue", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                        with pytest.raises(AgentAlreadyRunningError) as exc_info:
                            start_agent("042", quiet=True)

        assert exc_info.value.issue_id == "042"

    def test_start_agent_force_restarts_existing(
        self, mock_config, mock_issue, mock_agent, tmp_path, monkeypatch
    ):
        """With force=True, restarts agent."""
        monkeypatch.chdir(tmp_path)

        mock_runtime = MagicMock()
        mock_runtime.is_available.return_value = True
        mock_runtime.get_runtime_name.return_value = "docker"

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[]):
                with patch("agenttree.issues.get_issue", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                        with patch("agenttree.tmux.TmuxManager") as mock_tm_class:
                            mock_tm = MagicMock()
                            mock_tm.start_issue_agent_in_container.return_value = True
                            mock_tm_class.return_value = mock_tm

                            with patch("agenttree.state.create_agent_for_issue", return_value=mock_agent):
                                with patch("agenttree.container.get_container_runtime", return_value=mock_runtime):
                                    with patch("agenttree.worktree.create_worktree"):
                                        with patch("agenttree.state.get_issue_names", return_value={
                                            "branch": "issue-042-test-issue",
                                            "session": "testproj-issue-042",
                                        }):
                                                with patch("agenttree.issues.create_session"):
                                                    with patch("agenttree.issues.update_issue_metadata"):
                                                        with patch("subprocess.run") as mock_run:
                                                            mock_run.return_value = MagicMock(returncode=1)
                                                            result = start_agent("042", force=True, quiet=True)

        assert result == mock_agent

    def test_start_agent_preflight_failure(self, mock_config, tmp_path, monkeypatch):
        """PreflightError when checks fail."""
        monkeypatch.chdir(tmp_path)

        mock_result = MagicMock()
        mock_result.passed = False
        mock_result.name = "git_clean"
        mock_result.message = "Uncommitted changes"

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[mock_result]):
                with pytest.raises(PreflightError) as exc_info:
                    start_agent("042", quiet=True)

        assert "git_clean" in str(exc_info.value)

    def test_start_agent_container_not_available(
        self, mock_config, mock_issue, tmp_path, monkeypatch
    ):
        """ContainerUnavailableError when no runtime."""
        monkeypatch.chdir(tmp_path)

        mock_runtime = MagicMock()
        mock_runtime.is_available.return_value = False
        mock_runtime.get_recommended_action.return_value = "Install Docker"

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[]):
                with patch("agenttree.issues.get_issue", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("agenttree.tmux.TmuxManager"):
                            with patch("agenttree.state.create_agent_for_issue") as mock_create:
                                mock_create.return_value = MagicMock()
                                with patch("agenttree.container.get_container_runtime", return_value=mock_runtime):
                                    with patch("agenttree.worktree.create_worktree"):
                                        with patch("agenttree.state.get_issue_names", return_value={
                                            "branch": "issue-042-test-issue",
                                            "session": "testproj-issue-042",
                                        }):
                                                with patch("agenttree.issues.create_session"):
                                                    with patch("agenttree.issues.update_issue_metadata"):
                                                        with patch("subprocess.run") as mock_run:
                                                            mock_run.return_value = MagicMock(returncode=1)
                                                            with pytest.raises(ContainerUnavailableError) as exc_info:
                                                                start_agent("042", quiet=True)

        assert "Install Docker" in str(exc_info.value)

    def test_start_agent_quiet_suppresses_output(
        self, mock_config, mock_issue, mock_agent, tmp_path, monkeypatch, capsys
    ):
        """No console output when quiet=True."""
        monkeypatch.chdir(tmp_path)

        mock_runtime = MagicMock()
        mock_runtime.is_available.return_value = True
        mock_runtime.get_runtime_name.return_value = "docker"

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.preflight.run_preflight", return_value=[]):
                with patch("agenttree.issues.get_issue", return_value=mock_issue):
                    with patch("agenttree.state.get_active_agent", return_value=None):
                        with patch("agenttree.tmux.TmuxManager") as mock_tm_class:
                            mock_tm = MagicMock()
                            mock_tm.start_issue_agent_in_container.return_value = True
                            mock_tm_class.return_value = mock_tm

                            with patch("agenttree.state.create_agent_for_issue", return_value=mock_agent):
                                with patch("agenttree.container.get_container_runtime", return_value=mock_runtime):
                                    with patch("agenttree.worktree.create_worktree"):
                                        with patch("agenttree.state.get_issue_names", return_value={
                                            "branch": "issue-042-test-issue",
                                            "session": "testproj-issue-042",
                                        }):
                                                with patch("agenttree.issues.create_session"):
                                                    with patch("agenttree.issues.update_issue_metadata"):
                                                        with patch("subprocess.run") as mock_run:
                                                            mock_run.return_value = MagicMock(returncode=1)
                                                            start_agent("042", quiet=True)

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
        agent.host = "agent"
        agent.tmux_session = "testproj-issue-042"
        return agent

    def test_send_message_success(self, mock_config, mock_issue, mock_agent):
        """Returns 'sent' when agent running."""
        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", return_value=mock_issue):
                with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                    with patch("agenttree.tmux.TmuxManager") as mock_tm_class:
                        mock_tm = MagicMock()
                        mock_tm.is_issue_running.return_value = True
                        mock_tm.send_message_to_issue.return_value = "sent"
                        mock_tm_class.return_value = mock_tm

                        result = send_message("042", "hello", quiet=True)

        assert result == "sent"
        mock_tm.send_message_to_issue.assert_called_once_with("testproj-issue-042", "hello", interrupt=False)

    def test_send_message_auto_starts_agent(self, mock_config, mock_issue, mock_agent):
        """Starts agent if not running and auto_start=True."""
        call_count = [0]

        def mock_get_agent(issue_id, host="developer"):
            call_count[0] += 1
            if call_count[0] == 1:
                return None
            return mock_agent

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", return_value=mock_issue):
                with patch("agenttree.state.get_active_agent", side_effect=mock_get_agent):
                    with patch("agenttree.tmux.TmuxManager") as mock_tm_class:
                        mock_tm = MagicMock()
                        mock_tm.is_issue_running.return_value = True
                        mock_tm.send_message_to_issue.return_value = "sent"
                        mock_tm_class.return_value = mock_tm

                        with patch("agenttree.api.start_agent", return_value=mock_agent):
                            result = send_message("042", "hello", quiet=True)

        assert result == "sent"

    def test_send_message_no_auto_start(self, mock_config, mock_issue):
        """Returns error if agent not running and auto_start=False."""
        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", return_value=mock_issue):
                with patch("agenttree.state.get_active_agent", return_value=None):
                    with patch("agenttree.tmux.TmuxManager") as mock_tm_class:
                        mock_tm = MagicMock()
                        mock_tm.is_issue_running.return_value = False
                        mock_tm_class.return_value = mock_tm

                        result = send_message("042", "hello", auto_start=False, quiet=True)

        assert result == "no_agent"

    def test_send_message_retry_on_claude_exit(self, mock_config, mock_issue, mock_agent):
        """Restarts and retries if Claude CLI exited."""
        send_call_count = [0]

        def mock_send(session, message, interrupt=False):
            send_call_count[0] += 1
            if send_call_count[0] == 1:
                return "claude_exited"
            return "sent"

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", return_value=mock_issue):
                with patch("agenttree.state.get_active_agent", return_value=mock_agent):
                    with patch("agenttree.tmux.TmuxManager") as mock_tm_class:
                        mock_tm = MagicMock()
                        mock_tm.is_issue_running.return_value = True
                        mock_tm.send_message_to_issue.side_effect = mock_send
                        mock_tm_class.return_value = mock_tm

                        with patch("agenttree.api.start_agent", return_value=mock_agent):
                            result = send_message("042", "hello", quiet=True)

        assert result == "restarted"
        assert send_call_count[0] == 2

    def test_send_message_issue_not_found(self, mock_config):
        """IssueNotFoundError when issue doesn't exist."""
        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", return_value=None):
                with pytest.raises(IssueNotFoundError) as exc_info:
                    send_message("999", "hello", quiet=True)

        assert exc_info.value.issue_id == 999


class TestStartController:
    """Tests for start_controller() function."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock()
        config.project = "testproj"
        config.default_tool = "claude"
        config.get_manager_tmux_session.return_value = "testproj-controller-000"
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

        mock_tm.start_manager.assert_called_once()
        call_args = mock_tm.start_manager.call_args
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

        # Verify start_manager was called (not start_issue_agent_in_container)
        mock_tm.start_manager.assert_called_once()
        mock_tm.start_issue_agent_in_container.assert_not_called()

    def test_start_controller_already_running_raises(self, mock_config, tmp_path, monkeypatch):
        """AgentAlreadyRunningError if already running without force."""
        monkeypatch.chdir(tmp_path)

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=True):
                with pytest.raises(AgentAlreadyRunningError) as exc_info:
                    start_controller(quiet=True)

        assert exc_info.value.issue_id == "0"

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
        mock_tm.start_manager.assert_called_once()


class TestControllerMessages:
    """Tests for sending messages to controller."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock()
        config.project = "testproj"
        config.get_manager_tmux_session.return_value = "testproj-controller-000"
        return config

    def test_send_to_controller_success(self, mock_config):
        """Message sent to controller successfully."""
        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=True):
                with patch("agenttree.tmux.send_message", return_value="sent") as mock_send:
                    result = send_message("0", "hello controller", quiet=True)

        assert result == "sent"
        mock_send.assert_called_once_with("testproj-controller-000", "hello controller", interrupt=False)

    def test_send_to_controller_not_running(self, mock_config):
        """ControllerNotRunningError if controller not running."""
        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=False):
                with pytest.raises(ControllerNotRunningError):
                    send_message("0", "hello", quiet=True)


# =============================================================================
# Tests for Stop/Cleanup Functions (from state.py consolidation)
# =============================================================================


class TestStopAgent:
    """Tests for stop_agent function."""

    def test_stop_agent_kills_tmux_and_container(self):
        """stop_agent should kill tmux session and stop/delete container using config names."""
        from agenttree.api import stop_agent

        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.get_issue_tmux_session.return_value = "myproject-developer-042"
        mock_config.get_issue_container_name.return_value = "agenttree-myproject-042"

        mock_runtime = MagicMock()
        mock_runtime.runtime = "container"
        mock_runtime.stop.return_value = True
        mock_runtime.delete.return_value = True

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", return_value=True), \
             patch("agenttree.tmux.kill_session") as mock_kill, \
             patch("agenttree.container.get_container_runtime", return_value=mock_runtime):

            result = stop_agent("042", "developer", quiet=True)

        assert result is True
        # Verify tmux session was killed using config method
        mock_config.get_issue_tmux_session.assert_called_with("042", "developer")
        mock_kill.assert_any_call("myproject-developer-042")

        # Verify container was stopped/deleted using config method
        mock_config.get_issue_container_name.assert_called_with("042")
        mock_runtime.stop.assert_called_with("agenttree-myproject-042")
        mock_runtime.delete.assert_called_with("agenttree-myproject-042")

    def test_stop_agent_handles_no_session(self):
        """stop_agent should gracefully handle when tmux session doesn't exist."""
        from agenttree.api import stop_agent

        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.get_issue_tmux_session.return_value = "myproject-developer-042"
        mock_config.get_issue_container_name.return_value = "agenttree-myproject-042"

        mock_runtime = MagicMock()
        mock_runtime.runtime = "container"
        mock_runtime.stop.return_value = True
        mock_runtime.delete.return_value = True

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", return_value=False), \
             patch("agenttree.tmux.kill_session") as mock_kill, \
             patch("agenttree.container.get_container_runtime", return_value=mock_runtime):

            result = stop_agent("042", "developer", quiet=True)

        # Should still attempt container cleanup
        assert result is True
        # Should not attempt to kill session
        mock_kill.assert_not_called()
        # Should still stop/delete container
        mock_runtime.stop.assert_called_with("agenttree-myproject-042")
        mock_runtime.delete.assert_called_with("agenttree-myproject-042")

    def test_stop_agent_handles_no_container(self):
        """stop_agent should gracefully handle when container doesn't exist."""
        from agenttree.api import stop_agent

        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.get_issue_tmux_session.return_value = "myproject-developer-042"
        mock_config.get_issue_container_name.return_value = "agenttree-myproject-042"

        mock_runtime = MagicMock()
        mock_runtime.runtime = None  # No container runtime

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", return_value=True), \
             patch("agenttree.tmux.kill_session") as mock_kill, \
             patch("agenttree.container.get_container_runtime", return_value=mock_runtime):

            result = stop_agent("042", "developer", quiet=True)

        assert result is True  # Still returns True because tmux was stopped
        # Should kill tmux session
        mock_kill.assert_called_with("myproject-developer-042")
        # Should not attempt container operations
        mock_runtime.stop.assert_not_called()
        mock_runtime.delete.assert_not_called()


class TestStopAllAgentsForIssue:
    """Tests for stop_all_agents_for_issue function."""

    def test_stop_all_agents_for_issue(self):
        """stop_all_agents_for_issue should find all role sessions and stop each."""
        from agenttree.api import stop_all_agents_for_issue

        mock_agents = [
            MagicMock(issue_id="042", role="developer"),
            MagicMock(issue_id="042", role="reviewer"),
        ]

        with patch("agenttree.state.get_active_agents_for_issue", return_value=mock_agents), \
             patch("agenttree.api.stop_agent", return_value=True) as mock_stop:

            result = stop_all_agents_for_issue("042", quiet=True)

        assert result == 2
        mock_stop.assert_has_calls([
            call("042", "developer", True),
            call("042", "reviewer", True),
        ])


class TestCleanupOrphanedContainers:
    """Tests for cleanup_orphaned_containers function."""

    def test_cleanup_orphaned_containers(self):
        """cleanup_orphaned_containers should stop containers without tmux sessions using runtime abstraction."""
        from agenttree.api import cleanup_orphaned_containers

        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.get_issue_tmux_session.side_effect = lambda issue_id, role: f"myproject-{role}-{issue_id:03d}"

        mock_containers = [
            {"name": "agenttree-myproject-042", "id": "container1"},
            {"name": "agenttree-myproject-043", "id": "container2"},
            {"name": "other-container", "id": "container3"},  # Should be ignored
        ]

        mock_runtime = MagicMock()
        mock_runtime.runtime = "container"
        mock_runtime.list_all.return_value = mock_containers

        def session_exists_side_effect(session_name):
            # Only issue 043 has an active tmux session
            return session_name == "myproject-developer-043"

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.container.get_container_runtime", return_value=mock_runtime), \
             patch("agenttree.tmux.session_exists", side_effect=session_exists_side_effect):

            result = cleanup_orphaned_containers(quiet=True)

        assert result == 1  # Only container 042 should be cleaned up
        # Should stop and delete only the orphaned container (using container ID)
        mock_runtime.stop.assert_called_once_with("container1")
        mock_runtime.delete.assert_called_once_with("container1")

    def test_cleanup_orphaned_skips_active(self):
        """cleanup_orphaned_containers should NOT clean up containers with active tmux sessions."""
        from agenttree.api import cleanup_orphaned_containers

        mock_config = MagicMock()
        mock_config.project = "myproject"

        mock_containers = [
            {"name": "agenttree-myproject-042", "id": "container1"},
        ]

        mock_runtime = MagicMock()
        mock_runtime.runtime = "container"
        mock_runtime.list_all.return_value = mock_containers

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.container.get_container_runtime", return_value=mock_runtime), \
             patch("agenttree.tmux.session_exists", return_value=True):  # Session exists

            result = cleanup_orphaned_containers(quiet=True)

        assert result == 0  # No containers cleaned up
        mock_runtime.stop.assert_not_called()
        mock_runtime.delete.assert_not_called()


class TestCleanupAllContainers:
    """Tests for cleanup_all_agenttree_containers function."""

    def test_cleanup_all_containers(self):
        """cleanup_all_agenttree_containers should remove all agenttree containers regardless of session state."""
        from agenttree.api import cleanup_all_agenttree_containers

        mock_config = MagicMock()
        mock_config.project = "myproject"

        mock_containers = [
            {"name": "agenttree-myproject-042", "image": ""},
            {"name": "agenttree-other-043", "image": ""},
            {"name": "other-container", "image": "agenttree:latest"},  # Match by image
            {"name": "unrelated", "image": "nginx"},  # Should be ignored
        ]

        mock_runtime = MagicMock()
        mock_runtime.runtime = "container"
        mock_runtime.list_all.return_value = mock_containers
        mock_runtime.stop.return_value = True
        mock_runtime.delete.return_value = True

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.container.get_container_runtime", return_value=mock_runtime):

            result = cleanup_all_agenttree_containers(quiet=True)

        assert result == 3  # Three agenttree containers
        # Should stop and delete all matching containers
        expected_calls = [
            call("agenttree-myproject-042"),
            call("agenttree-other-043"),
            call("other-container"),
        ]
        mock_runtime.stop.assert_has_calls(expected_calls, any_order=True)
        mock_runtime.delete.assert_has_calls(expected_calls, any_order=True)


class TestCleanupAllWithRetry:
    """Tests for cleanup_all_with_retry function."""

    def test_cleanup_all_with_retry(self):
        """cleanup_all_with_retry should perform multiple passes with configurable delay."""
        from agenttree.api import cleanup_all_with_retry

        with patch("agenttree.api.cleanup_all_agenttree_containers", return_value=2) as mock_cleanup, \
             patch("time.sleep") as mock_sleep:

            cleanup_all_with_retry(max_passes=3, delay_s=1.0, quiet=True)

        # Should call cleanup 3 times
        assert mock_cleanup.call_count == 3
        # Should sleep between passes (2 sleeps for 3 passes)
        mock_sleep.assert_has_calls([call(1.0), call(1.0)])

    def test_cleanup_all_with_retry_single_pass(self):
        """cleanup_all_with_retry should work with single pass (no sleep)."""
        from agenttree.api import cleanup_all_with_retry

        with patch("agenttree.api.cleanup_all_agenttree_containers", return_value=1) as mock_cleanup, \
             patch("time.sleep") as mock_sleep:

            cleanup_all_with_retry(max_passes=1, delay_s=2.0, quiet=True)

        mock_cleanup.assert_called_once()
        mock_sleep.assert_not_called()  # No sleep for single pass


class TestContainerNamingConsistency:
    """Tests to verify API uses consistent container naming from config."""

    def test_container_naming_consistency(self):
        """stop_agent should use same container name as config.get_issue_container_name()."""
        from agenttree.api import stop_agent

        mock_config = MagicMock()
        mock_config.project = "testproject"
        mock_config.get_issue_tmux_session.return_value = "testproject-developer-123"
        mock_config.get_issue_container_name.return_value = "agenttree-testproject-123"

        mock_runtime = MagicMock()
        mock_runtime.runtime = "container"
        mock_runtime.stop.return_value = True
        mock_runtime.delete.return_value = True

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.tmux.session_exists", return_value=False), \
             patch("agenttree.tmux.kill_session"), \
             patch("agenttree.container.get_container_runtime", return_value=mock_runtime):

            stop_agent("123", "developer", quiet=True)

        # Verify both config methods were called with same issue_id
        mock_config.get_issue_container_name.assert_called_with("123")
        # Verify container operations used the config-derived name
        expected_name = "agenttree-testproject-123"
        mock_runtime.stop.assert_called_with(expected_name)
        mock_runtime.delete.assert_called_with(expected_name)


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
        """Normal transition: exit hooks -> stage update -> enter hooks."""
        from agenttree.api import transition_issue

        updated_issue = MagicMock()
        updated_issue.stage = "implement.code"

        with patch("agenttree.issues.get_issue", return_value=mock_issue), \
             patch("agenttree.hooks.execute_exit_hooks") as mock_exit, \
             patch("agenttree.issues.update_issue_stage", return_value=updated_issue) as mock_update, \
             patch("agenttree.hooks.execute_enter_hooks") as mock_enter:

            result = transition_issue("42", "implement.code")

        assert result == updated_issue
        mock_exit.assert_called_once_with(mock_issue, "plan.review", skip_pr_approval=False)
        mock_update.assert_called_once_with(42, "implement.code")
        mock_enter.assert_called_once_with(updated_issue, "implement.code")

    def test_transition_exit_hook_redirect(self, mock_issue):
        """Exit hook StageRedirect changes the target stage."""
        from agenttree.api import transition_issue
        from agenttree.hooks import StageRedirect

        updated_issue = MagicMock()
        updated_issue.stage = "explore.define"

        with patch("agenttree.issues.get_issue", return_value=mock_issue), \
             patch("agenttree.hooks.execute_exit_hooks", side_effect=StageRedirect("explore.define", "needs more work")), \
             patch("agenttree.issues.update_issue_stage", return_value=updated_issue) as mock_update, \
             patch("agenttree.hooks.execute_enter_hooks"):

            result = transition_issue("42", "implement.code")

        # Should have updated to the redirected stage, not original target
        mock_update.assert_called_once_with(42, "explore.define")
        assert result == updated_issue

    def test_transition_enter_hook_redirect(self, mock_issue):
        """Enter hook StageRedirect updates stage and notifies agent."""
        from agenttree.api import transition_issue, _notify_agent
        from agenttree.hooks import StageRedirect

        updated_issue = MagicMock()
        redirected_issue = MagicMock()
        redirected_issue.stage = "implement.code"

        with patch("agenttree.issues.get_issue", return_value=mock_issue), \
             patch("agenttree.hooks.execute_exit_hooks"), \
             patch("agenttree.issues.update_issue_stage", side_effect=[updated_issue, redirected_issue]), \
             patch("agenttree.hooks.execute_enter_hooks", side_effect=StageRedirect("implement.code", "merge conflict")), \
             patch("agenttree.api._notify_agent") as mock_notify:

            result = transition_issue("42", "accepted")

        assert result == redirected_issue
        mock_notify.assert_called_once()
        assert "merge conflict" in mock_notify.call_args[0][1]

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


class TestNotifyAgent:
    """Tests for _notify_agent() function."""

    def test_notify_sends_message(self):
        """Sends message to active agent's tmux session."""
        from agenttree.api import _notify_agent

        agent = MagicMock()
        agent.tmux_session = "testproj-dev-042"

        with patch("agenttree.state.get_active_agent", return_value=agent), \
             patch("agenttree.tmux.session_exists", return_value=True), \
             patch("agenttree.tmux.send_message") as mock_send:

            _notify_agent("42", "Test message")

        mock_send.assert_called_once_with("testproj-dev-042", "Test message", interrupt=False)

    def test_notify_sends_with_interrupt(self):
        """Sends message with interrupt=True when specified."""
        from agenttree.api import _notify_agent

        agent = MagicMock()
        agent.tmux_session = "testproj-dev-042"

        with patch("agenttree.state.get_active_agent", return_value=agent), \
             patch("agenttree.tmux.session_exists", return_value=True), \
             patch("agenttree.tmux.send_message") as mock_send:

            _notify_agent("42", "Test message", interrupt=True)

        mock_send.assert_called_once_with("testproj-dev-042", "Test message", interrupt=True)

    def test_notify_no_agent(self):
        """Does nothing if no active agent."""
        from agenttree.api import _notify_agent

        with patch("agenttree.state.get_active_agent", return_value=None):
            _notify_agent("42", "Test message")  # Should not raise

    def test_notify_never_raises(self):
        """Never raises even if tmux operations fail."""
        from agenttree.api import _notify_agent

        with patch("agenttree.state.get_active_agent", side_effect=Exception("boom")):
            _notify_agent("42", "Test message")  # Should not raise

"""Tests for agenttree.api module."""

from pathlib import Path
from unittest.mock import MagicMock, patch
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
        return config

    @pytest.fixture
    def mock_issue(self):
        """Create a mock issue."""
        issue = MagicMock()
        issue.id = "042"
        issue.slug = "test-issue"
        issue.title = "Test Issue"
        issue.stage = "define"
        issue.substage = None
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
                                            with patch("agenttree.state.get_port_for_issue", return_value=8042):
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

        assert exc_info.value.issue_id == "999"

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
                                            with patch("agenttree.state.get_port_for_issue", return_value=8042):
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
                                            with patch("agenttree.state.get_port_for_issue", return_value=8042):
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
                                            with patch("agenttree.state.get_port_for_issue", return_value=8042):
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

        assert exc_info.value.issue_id == "999"


class TestStartController:
    """Tests for start_controller() function."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock()
        config.project = "testproj"
        config.default_tool = "claude"
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
        return config

    def test_send_to_controller_success(self, mock_config):
        """Message sent to controller successfully."""
        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=True):
                with patch("agenttree.tmux.send_keys") as mock_send:
                    result = send_message("0", "hello controller", quiet=True)

        assert result == "sent"
        mock_send.assert_called_once_with("testproj-controller-000", "hello controller", interrupt=False)

    def test_send_to_controller_not_running(self, mock_config):
        """ControllerNotRunningError if controller not running."""
        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.tmux.session_exists", return_value=False):
                with pytest.raises(ControllerNotRunningError):
                    send_message("0", "hello", quiet=True)

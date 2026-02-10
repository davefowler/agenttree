"""Tests for tmux session management."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from agenttree.tmux import (
    save_tmux_history_to_file,
    session_exists,
    capture_pane,
)


class TestSessionExists:
    """Tests for session_exists function."""

    def test_session_exists_returns_true(self):
        """Should return True when session exists."""
        from agenttree.tmux import session_exists

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)
            result = session_exists("test-session")

        assert result is True
        mock_run.assert_called_once_with(
            ["tmux", "has-session", "-t", "test-session"],
            check=True,
            capture_output=True,
        )

    def test_session_exists_returns_false_when_not_found(self):
        """Should return False when session doesn't exist."""
        from agenttree.tmux import session_exists

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "tmux")
            result = session_exists("missing-session")

        assert result is False


class TestCreateSession:
    """Tests for create_session function."""

    def test_create_session_basic(self, tmp_path):
        """Should create a session in specified directory, killing stale session first."""
        from agenttree.tmux import create_session

        with patch("subprocess.run") as mock_run:
            create_session("test-session", tmp_path)

        # session_exists check + kill (if exists) + new-session
        assert mock_run.call_count == 3
        mock_run.assert_any_call(
            ["tmux", "has-session", "-t", "test-session"],
            check=True,
            capture_output=True,
        )
        mock_run.assert_any_call(
            ["tmux", "new-session", "-d", "-s", "test-session", "-c", str(tmp_path)],
            check=True,
        )

    def test_create_session_with_command(self, tmp_path):
        """Should create session and run start command."""
        from agenttree.tmux import create_session

        with patch("subprocess.run") as mock_run:
            create_session("test-session", tmp_path, start_command="echo hello")

        # session_exists + kill + new-session + send-keys (literal) + send-keys (Enter)
        assert mock_run.call_count == 5


class TestKillSession:
    """Tests for kill_session function."""

    def test_kill_session_success(self):
        """Should kill existing session."""
        from agenttree.tmux import kill_session

        with patch("subprocess.run") as mock_run:
            kill_session("test-session")

        mock_run.assert_called_once_with(
            ["tmux", "kill-session", "-t", "test-session"],
            check=True,
            capture_output=True,
        )

    def test_kill_session_not_found(self):
        """Should not raise when session doesn't exist."""
        from agenttree.tmux import kill_session

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "tmux")
            # Should not raise
            kill_session("missing-session")


class TestSendKeys:
    """Tests for send_keys function."""

    def test_send_keys_with_submit(self):
        """Should send keys with Enter when submit=True."""
        from agenttree.tmux import send_keys

        with patch("subprocess.run") as mock_run:
            with patch("time.sleep"):  # Skip the delay
                send_keys("test-session", "hello", submit=True)

        assert mock_run.call_count == 2
        # First call sends literal text
        mock_run.assert_any_call(
            ["tmux", "send-keys", "-t", "test-session", "-l", "hello"],
            check=True,
        )
        # Second call sends Enter
        mock_run.assert_any_call(
            ["tmux", "send-keys", "-t", "test-session", "Enter"],
            check=True,
        )

    def test_send_keys_without_submit(self):
        """Should send keys without Enter when submit=False."""
        from agenttree.tmux import send_keys

        with patch("subprocess.run") as mock_run:
            send_keys("test-session", "hello", submit=False)

        assert mock_run.call_count == 1
        mock_run.assert_called_once_with(
            ["tmux", "send-keys", "-t", "test-session", "-l", "hello"],
            check=True,
        )


class TestSendMessage:
    """Tests for send_message function."""

    def test_send_message_success(self):
        """Should return 'sent' when message sent successfully."""
        from agenttree.tmux import send_message

        with patch("agenttree.tmux.session_exists", return_value=True):
            with patch("agenttree.tmux.is_claude_running", return_value=True):
                with patch("agenttree.tmux.send_keys") as mock_send:
                    result = send_message("test-session", "hello")

        assert result == "sent"
        mock_send.assert_called_once_with("test-session", "hello", submit=True, interrupt=False)

    def test_send_message_session_not_exists(self):
        """Should return 'no_session' when session doesn't exist."""
        from agenttree.tmux import send_message

        with patch("agenttree.tmux.session_exists", return_value=False):
            result = send_message("missing-session", "hello")

        assert result == "no_session"

    def test_send_message_claude_exited(self):
        """Should return 'claude_exited' when Claude CLI isn't running."""
        from agenttree.tmux import send_message

        with patch("agenttree.tmux.session_exists", return_value=True):
            with patch("agenttree.tmux.is_claude_running", return_value=False):
                result = send_message("test-session", "hello")

        assert result == "claude_exited"

    def test_send_message_send_fails(self):
        """Should return 'error' when send_keys fails."""
        from agenttree.tmux import send_message

        with patch("agenttree.tmux.session_exists", return_value=True):
            with patch("agenttree.tmux.is_claude_running", return_value=True):
                with patch("agenttree.tmux.send_keys") as mock_send:
                    mock_send.side_effect = subprocess.CalledProcessError(1, "tmux")
                    result = send_message("test-session", "hello")

        assert result == "error"

    def test_send_message_skip_claude_check(self):
        """Should skip Claude check when check_claude=False."""
        from agenttree.tmux import send_message

        with patch("agenttree.tmux.session_exists", return_value=True):
            with patch("agenttree.tmux.is_claude_running") as mock_claude:
                with patch("agenttree.tmux.send_keys"):
                    result = send_message("test-session", "hello", check_claude=False)

        assert result == "sent"
        mock_claude.assert_not_called()


class TestCapturePane:
    """Tests for capture_pane function."""

    def test_capture_pane_success(self):
        """Should return captured content."""
        from agenttree.tmux import capture_pane

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout="line1\nline2\nline3\n")
            result = capture_pane("test-session", lines=50)

        assert result == "line1\nline2\nline3\n"
        mock_run.assert_called_once_with(
            ["tmux", "capture-pane", "-t", "test-session", "-p", "-S", "-50"],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_capture_pane_failure(self):
        """Should return empty string on failure."""
        from agenttree.tmux import capture_pane

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "tmux")
            result = capture_pane("missing-session")

        assert result == ""


class TestWaitForPrompt:
    """Tests for wait_for_prompt function."""

    def test_wait_for_prompt_found_immediately(self):
        """Should return True when prompt found."""
        from agenttree.tmux import wait_for_prompt

        with patch("agenttree.tmux.capture_pane") as mock_capture:
            mock_capture.return_value = "some output\n❯ "
            result = wait_for_prompt("test-session", timeout=1.0)

        assert result is True

    def test_wait_for_prompt_found_after_wait(self):
        """Should return True when prompt appears after waiting."""
        from agenttree.tmux import wait_for_prompt

        call_count = [0]

        def capture_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 3:
                return "❯ "
            return "loading..."

        with patch("agenttree.tmux.capture_pane", side_effect=capture_side_effect):
            with patch("time.sleep"):
                result = wait_for_prompt("test-session", timeout=10.0, poll_interval=0.1)

        assert result is True

    def test_wait_for_prompt_timeout(self):
        """Should return False on timeout."""
        from agenttree.tmux import wait_for_prompt

        with patch("agenttree.tmux.capture_pane", return_value="loading..."):
            # Use a very short timeout
            result = wait_for_prompt("test-session", timeout=0.01, poll_interval=0.005)

        assert result is False


class TestListSessions:
    """Tests for list_sessions function."""

    def test_list_sessions_success(self):
        """Should parse session list correctly."""
        from agenttree.tmux import list_sessions, TmuxSession

        mock_output = """agent-1: 1 windows (created Mon Jan  1 10:00:00 2024)
agent-2: 3 windows (created Mon Jan  1 11:00:00 2024) (attached)
test-session: 2 windows (created Mon Jan  1 12:00:00 2024)"""

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout=mock_output)
            result = list_sessions()

        assert len(result) == 3
        assert result[0] == TmuxSession(name="agent-1", windows=1, attached=False)
        assert result[1] == TmuxSession(name="agent-2", windows=3, attached=True)
        assert result[2] == TmuxSession(name="test-session", windows=2, attached=False)

    def test_list_sessions_empty(self):
        """Should return empty list when no sessions."""
        from agenttree.tmux import list_sessions

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout="")
            result = list_sessions()

        assert result == []

    def test_list_sessions_failure(self):
        """Should return empty list on failure."""
        from agenttree.tmux import list_sessions

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "tmux")
            result = list_sessions()

        assert result == []


class TestTmuxManager:
    """Tests for TmuxManager class."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock()
        config.get_tmux_session_name.return_value = "agent-42"
        return config

    def test_get_session_name(self, mock_config):
        """Should delegate to config."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)
        result = manager.get_session_name(42)

        assert result == "agent-42"
        mock_config.get_tmux_session_name.assert_called_once_with(42)

    def test_stop_agent(self, mock_config):
        """Should kill the correct session."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)

        with patch("agenttree.tmux.kill_session") as mock_kill:
            manager.stop_agent(42)

        mock_kill.assert_called_once_with("agent-42")

    def test_send_message(self, mock_config):
        """Should send message to correct session."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)

        with patch("agenttree.tmux.send_keys") as mock_send:
            manager.send_message(42, "hello")

        mock_send.assert_called_once_with("agent-42", "hello")

    def test_attach(self, mock_config):
        """Should attach to correct session."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)

        with patch("agenttree.tmux.session_exists", return_value=True):
            with patch("agenttree.tmux.attach_session") as mock_attach:
                manager.attach(42)

        mock_attach.assert_called_once_with("agent-42")

    def test_is_running(self, mock_config):
        """Should check correct session."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)

        with patch("agenttree.tmux.session_exists", return_value=True) as mock_exists:
            result = manager.is_running(42)

        assert result is True
        mock_exists.assert_called_once_with("agent-42")

    def test_list_agent_sessions(self, mock_config):
        """Should filter sessions by project prefix."""
        from agenttree.tmux import TmuxManager, TmuxSession

        # list_agent_sessions uses config.project to build prefix
        mock_config.project = "myproject"

        manager = TmuxManager(mock_config)

        test_sessions = [
            TmuxSession(name="myproject-agent-1", windows=1, attached=False),
            TmuxSession(name="myproject-agent-2", windows=1, attached=False),
            TmuxSession(name="other-session", windows=1, attached=False),
        ]

        with patch("agenttree.tmux.list_sessions", return_value=test_sessions):
            result = manager.list_agent_sessions()

        assert len(result) == 2
        assert result[0].name == "myproject-agent-1"
        assert result[1].name == "myproject-agent-2"

    def test_stop_issue_agent(self, mock_config):
        """Should kill issue session."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)

        with patch("agenttree.tmux.kill_session") as mock_kill:
            manager.stop_issue_agent("issue-42")

        mock_kill.assert_called_once_with("issue-42")

    def test_send_message_to_issue(self, mock_config):
        """Should send message to issue session and return status."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)

        with patch("agenttree.tmux.send_message", return_value="sent") as mock_send:
            result = manager.send_message_to_issue("issue-42", "hello")

        assert result == "sent"
        mock_send.assert_called_once_with("issue-42", "hello", check_claude=True, interrupt=False)

    def test_is_issue_running(self, mock_config):
        """Should check issue session existence."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)

        with patch("agenttree.tmux.session_exists", return_value=True) as mock_exists:
            result = manager.is_issue_running("issue-42")

        assert result is True
        mock_exists.assert_called_once_with("issue-42")

    def test_list_issue_sessions(self, mock_config):
        """Should filter sessions by project prefix using is_project_session."""
        from agenttree.tmux import TmuxManager, TmuxSession

        # list_issue_sessions uses config.is_project_session to filter
        mock_config.project = "myproject"
        # Configure is_project_session to match project sessions
        mock_config.is_project_session.side_effect = lambda name: name.startswith("myproject-")

        manager = TmuxManager(mock_config)

        test_sessions = [
            TmuxSession(name="myproject-developer-042", windows=1, attached=False),
            TmuxSession(name="myproject-developer-043", windows=1, attached=False),
            TmuxSession(name="other-session", windows=1, attached=False),
        ]

        with patch("agenttree.tmux.list_sessions", return_value=test_sessions):
            result = manager.list_issue_sessions()

        assert len(result) == 2
        assert result[0].name == "myproject-developer-042"
        assert result[1].name == "myproject-developer-043"


class TestStartController:
    """Tests for TmuxManager.start_manager method."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config for testing."""
        config = MagicMock()
        config.project = "testproject"
        tool_config = MagicMock()
        tool_config.command = "claude"
        config.get_tool_config.return_value = tool_config
        return config

    def test_start_manager_creates_session(self, mock_config, tmp_path):
        """Should create a new tmux session for the manager."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)

        with patch("agenttree.tmux.session_exists", return_value=False):
            with patch("agenttree.tmux.create_session") as mock_create:
                with patch("agenttree.tmux.wait_for_prompt", return_value=True):
                    with patch("agenttree.tmux.send_keys") as mock_send:
                        manager.start_manager(
                            session_name="testproject-manager-000",
                            repo_path=tmp_path,
                            tool_name="claude",
                        )

        mock_create.assert_called_once_with("testproject-manager-000", tmp_path, "claude")
        mock_send.assert_called_once()
        # Verify the startup prompt loads manager skill file
        startup_prompt = mock_send.call_args[0][1]
        assert "manager.md" in startup_prompt or "manager" in startup_prompt.lower()

    def test_start_manager_kills_existing_session(self, mock_config, tmp_path):
        """Should kill existing session before creating new one."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)

        with patch("agenttree.tmux.session_exists", return_value=True):
            with patch("agenttree.tmux.kill_session") as mock_kill:
                with patch("agenttree.tmux.create_session"):
                    with patch("agenttree.tmux.wait_for_prompt", return_value=False):
                        manager.start_manager(
                            session_name="testproject-manager-000",
                            repo_path=tmp_path,
                            tool_name="claude",
                        )

        mock_kill.assert_called_once_with("testproject-manager-000")

    def test_start_manager_uses_correct_tool(self, mock_config, tmp_path):
        """Should use the configured AI tool command."""
        from agenttree.tmux import TmuxManager

        # Configure tool to use a custom command
        tool_config = MagicMock()
        tool_config.command = "custom-ai-tool --special-flag"
        mock_config.get_tool_config.return_value = tool_config

        manager = TmuxManager(mock_config)

        with patch("agenttree.tmux.session_exists", return_value=False):
            with patch("agenttree.tmux.create_session") as mock_create:
                with patch("agenttree.tmux.wait_for_prompt", return_value=False):
                    manager.start_manager(
                        session_name="testproject-manager-000",
                        repo_path=tmp_path,
                        tool_name="custom",
                    )

        # Verify the AI command was used
        mock_create.assert_called_once()
        call_args = mock_create.call_args[0]
        assert call_args[2] == "custom-ai-tool --special-flag"


class TestServeSession:
    """Tests for serve session functionality in start_issue_agent_in_container."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config with serve command."""
        config = MagicMock()
        config.project = "myproject"
        config.default_model = "claude-sonnet"
        config.commands = {"serve": "uv run uvicorn app:app --port $PORT"}
        config.get_port_for_agent.return_value = 9135
        tool_config = MagicMock()
        tool_config.command = "claude"
        config.get_tool_config.return_value = tool_config
        return config

    @pytest.fixture
    def mock_container_runtime(self):
        """Create a mock container runtime."""
        runtime = MagicMock()
        runtime.build_run_command.return_value = ["docker", "run", "image"]
        runtime.runtime = None  # No real runtime, skip cleanup_container
        return runtime

    def test_serve_session_naming(self, mock_config, mock_container_runtime, tmp_path):
        """Serve session should be named {project}-serve-{issue_id}."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)

        with patch("agenttree.tmux.session_exists", return_value=False):
            with patch("agenttree.tmux.kill_session") as mock_kill:
                with patch("agenttree.tmux.create_session") as mock_create:
                    with patch("agenttree.tmux.wait_for_prompt", return_value=False):
                        manager.start_issue_agent_in_container(
                            issue_id="135",
                            session_name="myproject-issue-135",
                            worktree_path=tmp_path,
                            tool_name="claude",
                            container_runtime=mock_container_runtime,
                        )

        # Verify serve session was created with correct name
        # Filter by session name containing "-serve-"
        serve_session_calls = [
            call for call in mock_create.call_args_list
            if "-serve-" in call[0][0]
        ]
        assert len(serve_session_calls) == 1
        assert serve_session_calls[0][0][0] == "myproject-serve-135"

    def test_serve_session_starts_with_correct_command(self, mock_config, mock_container_runtime, tmp_path):
        """Serve session should run with PORT=xxxx prefix."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)

        with patch("agenttree.tmux.session_exists", return_value=False):
            with patch("agenttree.tmux.kill_session"):
                with patch("agenttree.tmux.create_session") as mock_create:
                    with patch("agenttree.tmux.wait_for_prompt", return_value=False):
                        manager.start_issue_agent_in_container(
                            issue_id="135",
                            session_name="myproject-issue-135",
                            worktree_path=tmp_path,
                            tool_name="claude",
                            container_runtime=mock_container_runtime,
                        )

        # Find the serve session create call
        serve_calls = [
            call for call in mock_create.call_args_list
            if "serve" in str(call[0][0])
        ]
        assert len(serve_calls) == 1
        # Check the command has PORT=9135 prefix
        serve_command = serve_calls[0][0][2]
        assert "PORT=9135" in serve_command
        assert "uv run uvicorn app:app --port $PORT" in serve_command

    def test_serve_session_skipped_when_no_serve_command(self, mock_config, mock_container_runtime, tmp_path):
        """No serve session should be created when commands.serve is not configured."""
        from agenttree.tmux import TmuxManager

        # Remove serve command from config
        mock_config.commands = {}

        manager = TmuxManager(mock_config)

        with patch("agenttree.tmux.session_exists", return_value=False):
            with patch("agenttree.tmux.kill_session"):
                with patch("agenttree.tmux.create_session") as mock_create:
                    with patch("agenttree.tmux.wait_for_prompt", return_value=False):
                        manager.start_issue_agent_in_container(
                            issue_id="135",
                            session_name="myproject-issue-135",
                            worktree_path=tmp_path,
                            tool_name="claude",
                            container_runtime=mock_container_runtime,
                        )

        # Should only have one create_session call (for agent, not serve)
        assert mock_create.call_count == 1
        # Verify it's the agent session, not serve
        assert "serve" not in str(mock_create.call_args_list[0][0][0])

    def test_existing_serve_session_killed_before_new_one(self, mock_config, mock_container_runtime, tmp_path):
        """Existing serve session should be killed before creating new one."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)

        # Mock session_exists to return True for serve session
        def session_exists_side_effect(name):
            return "serve" in name or name == "myproject-issue-135"

        with patch("agenttree.tmux.session_exists", side_effect=session_exists_side_effect):
            with patch("agenttree.tmux.kill_session") as mock_kill:
                with patch("agenttree.tmux.create_session"):
                    with patch("agenttree.tmux.wait_for_prompt", return_value=False):
                        manager.start_issue_agent_in_container(
                            issue_id="135",
                            session_name="myproject-issue-135",
                            worktree_path=tmp_path,
                            tool_name="claude",
                            container_runtime=mock_container_runtime,
                        )

        # Verify serve session was killed
        serve_kill_calls = [
            call for call in mock_kill.call_args_list
            if "serve" in str(call)
        ]
        assert len(serve_kill_calls) >= 1
        assert serve_kill_calls[0][0][0] == "myproject-serve-135"

    def test_serve_session_failure_does_not_block_agent(self, mock_config, mock_container_runtime, tmp_path):
        """Serve session failure should not prevent agent from starting."""
        from agenttree.tmux import TmuxManager

        manager = TmuxManager(mock_config)

        call_count = [0]

        def create_session_side_effect(*args, **kwargs):
            call_count[0] += 1
            # First call is agent session (succeeds)
            if call_count[0] == 1:
                return
            # Second call is serve session (fails)
            raise subprocess.CalledProcessError(1, "tmux")

        with patch("agenttree.tmux.session_exists", return_value=False):
            with patch("agenttree.tmux.kill_session"):
                with patch("agenttree.tmux.create_session", side_effect=create_session_side_effect):
                    with patch("agenttree.tmux.wait_for_prompt", return_value=False):
                        # Should not raise even if serve session fails
                        manager.start_issue_agent_in_container(
                            issue_id="135",
                            session_name="myproject-issue-135",
                            worktree_path=tmp_path,
                            tool_name="claude",
                            container_runtime=mock_container_runtime,
                        )

        # Agent session should have been created
        assert call_count[0] >= 1


class TestSaveTmuxHistoryToFile:
    """Tests for save_tmux_history_to_file function."""

    def test_save_history_when_session_does_not_exist(self, tmp_path: Path) -> None:
        """Should return False when tmux session doesn't exist."""
        output_file = tmp_path / "history.log"

        with patch("agenttree.tmux.session_exists", return_value=False):
            result = save_tmux_history_to_file("nonexistent-session", output_file, "implement")

        assert result is False
        assert not output_file.exists()

    def test_save_history_when_capture_fails(self, tmp_path: Path) -> None:
        """Should return False when tmux capture-pane fails."""
        output_file = tmp_path / "history.log"

        with patch("agenttree.tmux.session_exists", return_value=True):
            with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "tmux")):
                result = save_tmux_history_to_file("test-session", output_file, "implement")

        assert result is False
        assert not output_file.exists()

    def test_save_history_when_capture_is_empty(self, tmp_path: Path) -> None:
        """Should return False when captured history is empty."""
        output_file = tmp_path / "history.log"
        mock_result = MagicMock()
        mock_result.stdout = "   \n\n  "  # Whitespace only

        with patch("agenttree.tmux.session_exists", return_value=True):
            with patch("subprocess.run", return_value=mock_result):
                result = save_tmux_history_to_file("test-session", output_file, "implement")

        assert result is False
        assert not output_file.exists()

    def test_save_history_creates_file_with_content(self, tmp_path: Path) -> None:
        """Should create file with history content and timestamp header."""
        output_file = tmp_path / "history.log"
        mock_result = MagicMock()
        mock_result.stdout = "$ echo hello\nhello\n$ agenttree next\n"

        with patch("agenttree.tmux.session_exists", return_value=True):
            with patch("subprocess.run", return_value=mock_result):
                result = save_tmux_history_to_file("test-session", output_file, "implement")

        assert result is True
        assert output_file.exists()

        content = output_file.read_text()
        assert "Stage: implement" in content
        assert "Captured:" in content
        assert "$ echo hello" in content
        assert "$ agenttree next" in content

    def test_save_history_appends_to_existing_file(self, tmp_path: Path) -> None:
        """Should append to existing file instead of overwriting."""
        output_file = tmp_path / "history.log"
        output_file.write_text("Previous content\n")

        mock_result = MagicMock()
        mock_result.stdout = "New history content\n"

        with patch("agenttree.tmux.session_exists", return_value=True):
            with patch("subprocess.run", return_value=mock_result):
                result = save_tmux_history_to_file("test-session", output_file, "define")

        assert result is True
        content = output_file.read_text()
        assert "Previous content" in content
        assert "New history content" in content
        assert "Stage: define" in content

    def test_save_history_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if they don't exist."""
        output_file = tmp_path / "nested" / "dir" / "history.log"
        mock_result = MagicMock()
        mock_result.stdout = "History content\n"

        with patch("agenttree.tmux.session_exists", return_value=True):
            with patch("subprocess.run", return_value=mock_result):
                result = save_tmux_history_to_file("test-session", output_file, "plan")

        assert result is True
        assert output_file.exists()
        assert "History content" in output_file.read_text()

    def test_save_history_includes_substage_in_header(self, tmp_path: Path) -> None:
        """Should include substage if provided in stage string."""
        output_file = tmp_path / "history.log"
        mock_result = MagicMock()
        mock_result.stdout = "History content\n"

        with patch("agenttree.tmux.session_exists", return_value=True):
            with patch("subprocess.run", return_value=mock_result):
                result = save_tmux_history_to_file("test-session", output_file, "define.refine")

        assert result is True
        content = output_file.read_text()
        assert "Stage: define.refine" in content

    def test_save_history_uses_full_scrollback_buffer(self, tmp_path: Path) -> None:
        """Should use '-' flag to capture full scrollback buffer."""
        output_file = tmp_path / "history.log"
        mock_result = MagicMock()
        mock_result.stdout = "History content\n"

        with patch("agenttree.tmux.session_exists", return_value=True):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                save_tmux_history_to_file("test-session", output_file, "implement")

        # Verify tmux capture-pane was called with -S - for full history
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "tmux" in call_args
        assert "capture-pane" in call_args
        assert "-S" in call_args
        assert "-" in call_args  # Full scrollback

"""Tests for CLI agent commands (start, stop, etc.)."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner():
    """Create a Click test runner."""
    return CliRunner()


@pytest.fixture
def mock_config():
    """Create a mock config with roles."""
    config = MagicMock()
    config.project = "testproject"
    config.roles = {
        "manager": MagicMock(),
        "architect": MagicMock(),
        "setup": MagicMock(),
        "developer": MagicMock(),
    }
    config.get_role_tmux_session.side_effect = lambda role: f"testproject-{role}-000"
    return config


class TestStartAgentHostRoleRouting:
    """Tests for --role routing to host-level roles in start command."""

    def test_start_with_role_architect_calls_start_role(self, cli_runner, mock_config):
        """When --role architect is passed with an issue ID, should call start_role instead of container path."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.cli.agents.run_preflight") as mock_preflight:
                mock_preflight.return_value = []  # No failed checks
                with patch("agenttree.api.start_role") as mock_start_role:
                    # This should route to start_role because architect is in HOST_TMUX_ROLES
                    result = cli_runner.invoke(main, ["start", "42", "--role", "architect"])

        # start_role should have been called with architect role
        mock_start_role.assert_called_once_with("architect", tool=None, force=False)
        assert result.exit_code == 0

    def test_start_with_role_manager_calls_start_role(self, cli_runner, mock_config):
        """When --role manager is passed with an issue ID, should call start_role instead of container path."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.cli.agents.run_preflight") as mock_preflight:
                mock_preflight.return_value = []  # No failed checks
                with patch("agenttree.api.start_role") as mock_start_role:
                    result = cli_runner.invoke(main, ["start", "42", "--role", "manager"])

        # start_role should have been called with manager role
        mock_start_role.assert_called_once_with("manager", tool=None, force=False)
        assert result.exit_code == 0

    def test_start_with_role_developer_does_not_call_start_role(self, cli_runner, mock_config):
        """When --role developer is passed (not a HOST_TMUX_ROLE), should proceed to container path."""
        from agenttree.cli import main

        mock_issue = MagicMock()
        mock_issue.id = 42
        mock_issue.stage = "implement.code"

        mock_config.is_resumable_stage.return_value = False

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.cli.agents.run_preflight") as mock_preflight:
                mock_preflight.return_value = []  # No failed checks
                with patch("agenttree.api.start_role") as mock_start_role:
                    with patch("agenttree.cli.agents.get_issue_func", return_value=mock_issue):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            # This should NOT route to start_role
                            # It will fail at container startup since we don't mock that path
                            result = cli_runner.invoke(main, ["start", "42", "--role", "developer"])

        # start_role should NOT have been called (developer is not HOST_TMUX_ROLE)
        mock_start_role.assert_not_called()
        # We expect non-zero exit since container path is not fully mocked
        assert result.exit_code != 0

    def test_start_with_role_architect_and_force(self, cli_runner, mock_config):
        """When --role architect --force is passed, should call start_role with force=True."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.cli.agents.run_preflight") as mock_preflight:
                mock_preflight.return_value = []  # No failed checks
                with patch("agenttree.api.start_role") as mock_start_role:
                    result = cli_runner.invoke(main, ["start", "42", "--role", "architect", "--force"])

        mock_start_role.assert_called_once_with("architect", tool=None, force=True)
        assert result.exit_code == 0

    def test_start_role_already_running_error(self, cli_runner, mock_config):
        """When start_role raises AgentAlreadyRunningError, should show appropriate message."""
        from agenttree.cli import main
        from agenttree.api import AgentAlreadyRunningError

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.cli.agents.run_preflight") as mock_preflight:
                mock_preflight.return_value = []  # No failed checks
                with patch("agenttree.api.start_role") as mock_start_role:
                    mock_start_role.side_effect = AgentAlreadyRunningError("architect", "architect")
                    result = cli_runner.invoke(main, ["start", "42", "--role", "architect"])

        assert result.exit_code == 1
        assert "already running" in result.output.lower()
        assert "Use --force" in result.output

    def test_start_setup_skips_preflight(self, cli_runner, mock_config):
        """Setup role should skip preflight so onboarding works in fresh repos."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.cli.agents.run_preflight") as mock_preflight:
                with patch("agenttree.api.start_role") as mock_start_role:
                    result = cli_runner.invoke(main, ["start", "setup"])

        mock_preflight.assert_not_called()
        mock_start_role.assert_called_once_with("setup", tool=None, force=False)
        assert result.exit_code == 0


class TestHostRoleCliCommands:
    """Tests for CLI commands targeting host roles by name."""

    def test_agents_shows_running_host_roles(self, cli_runner, mock_config):
        """agents command should show running host roles like setup."""
        from agenttree.cli import main

        mock_config.roles["setup"].description = "Interactive project setup agent"

        def session_exists_side_effect(session_name: str) -> bool:
            return session_name == "testproject-setup-000"

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.state.list_active_agents", return_value=[]):
                with patch("agenttree.tmux.session_exists", side_effect=session_exists_side_effect):
                    result = cli_runner.invoke(main, ["agents"])

        assert result.exit_code == 0
        assert "Running Host Roles" in result.output
        assert "setup" in result.output

    def test_output_accepts_role_name(self, cli_runner, mock_config):
        """output command should allow host role names like setup."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.cli.agents.require_role_running", return_value="testproject-setup-000"):
                with patch("agenttree.tmux.capture_pane", return_value="setup output"):
                    result = cli_runner.invoke(main, ["output", "setup"])

        assert result.exit_code == 0
        assert "setup output" in result.output

    def test_send_accepts_role_name(self, cli_runner, mock_config):
        """send command should allow host role names like setup."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.cli.agents.require_role_running", return_value="testproject-setup-000"):
                with patch("agenttree.tmux.send_message", return_value="sent") as mock_send:
                    result = cli_runner.invoke(main, ["send", "setup", "hello"])

        mock_send.assert_called_once_with("testproject-setup-000", "hello", interrupt=False)
        assert result.exit_code == 0
        assert "Sent message to setup" in result.output

    def test_stop_accepts_role_name(self, cli_runner, mock_config):
        """stop command should allow host role names like setup."""
        from agenttree.cli import main

        with patch("agenttree.cli.agents.load_config", return_value=mock_config):
            with patch("agenttree.cli.agents.get_role_session_if_running", return_value="testproject-setup-000"):
                with patch("agenttree.tmux.kill_session") as mock_kill:
                    result = cli_runner.invoke(main, ["stop", "setup"])

        mock_kill.assert_called_once_with("testproject-setup-000")
        assert result.exit_code == 0
        assert "Stopped setup" in result.output

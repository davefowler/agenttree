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
    config.roles = {"manager": MagicMock(), "architect": MagicMock(), "developer": MagicMock()}
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

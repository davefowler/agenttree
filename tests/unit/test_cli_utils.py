"""Tests for agenttree/cli/_utils.py."""

from unittest.mock import MagicMock, patch

import pytest

from agenttree.cli._utils import (
    normalize_issue_id,
    format_role_label,
    get_manager_session_name,
    require_manager_running,
    get_manager_session_if_running,
)


class TestNormalizeIssueId:
    """Tests for normalize_issue_id function."""

    def test_normalize_simple(self) -> None:
        """Simple numbers are parsed."""
        assert normalize_issue_id("1") == 1
        assert normalize_issue_id("42") == 42

    def test_normalize_with_leading_zeros(self) -> None:
        """Leading zeros are stripped."""
        assert normalize_issue_id("001") == 1
        assert normalize_issue_id("042") == 42


class TestFormatRoleLabel:
    """Tests for format_role_label function."""

    def test_developer_returns_empty(self) -> None:
        """Developer role returns empty string."""
        assert format_role_label("developer") == ""

    def test_other_roles_formatted(self) -> None:
        """Other roles are formatted with parentheses."""
        assert format_role_label("reviewer") == " (reviewer)"
        assert format_role_label("manager") == " (manager)"


class TestGetManagerSessionName:
    """Tests for get_manager_session_name function."""

    def test_returns_expected_format(self) -> None:
        """Returns session name in expected format."""
        config = MagicMock()
        config.project = "myproject"
        assert get_manager_session_name(config) == "myproject-manager-000"


class TestRequireManagerRunning:
    """Tests for require_manager_running function."""

    @patch("agenttree.tmux.session_exists")
    def test_returns_session_name_when_running(self, mock_session_exists: MagicMock) -> None:
        """Returns session name when manager is running."""
        mock_session_exists.return_value = True
        config = MagicMock()
        config.project = "myproject"

        result = require_manager_running(config)
        assert result == "myproject-manager-000"
        mock_session_exists.assert_called_once_with("myproject-manager-000")

    @patch("agenttree.tmux.session_exists")
    def test_exits_when_not_running(self, mock_session_exists: MagicMock) -> None:
        """Exits with code 1 when manager is not running."""
        mock_session_exists.return_value = False
        config = MagicMock()
        config.project = "myproject"

        with pytest.raises(SystemExit) as excinfo:
            require_manager_running(config)
        assert excinfo.value.code == 1

    @patch("agenttree.tmux.session_exists")
    def test_exits_when_not_running_no_hint(self, mock_session_exists: MagicMock) -> None:
        """Exits with code 1 when manager is not running (no hint)."""
        mock_session_exists.return_value = False
        config = MagicMock()
        config.project = "myproject"

        with pytest.raises(SystemExit) as excinfo:
            require_manager_running(config, hint=False)
        assert excinfo.value.code == 1


class TestGetManagerSessionIfRunning:
    """Tests for get_manager_session_if_running function."""

    @patch("agenttree.tmux.session_exists")
    def test_returns_session_name_when_running(self, mock_session_exists: MagicMock) -> None:
        """Returns session name when manager is running."""
        mock_session_exists.return_value = True
        config = MagicMock()
        config.project = "myproject"

        result = get_manager_session_if_running(config)
        assert result == "myproject-manager-000"

    @patch("agenttree.tmux.session_exists")
    def test_returns_none_when_not_running(self, mock_session_exists: MagicMock) -> None:
        """Returns None when manager is not running (no exit)."""
        mock_session_exists.return_value = False
        config = MagicMock()
        config.project = "myproject"

        result = get_manager_session_if_running(config)
        assert result is None

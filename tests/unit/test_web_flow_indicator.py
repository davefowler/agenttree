"""Tests for flow indicator feature in web UI."""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

# Skip all tests if web dependencies aren't installed
pytest.importorskip("fastapi")

from agenttree.web.models import Issue as WebIssue
from agenttree.web.app import convert_issue_to_web
from agenttree.issues import Priority


class TestWebIssueFlowField:
    """Tests for flow field in WebIssue model."""

    def test_web_issue_defaults_flow_to_default(self):
        """Test that WebIssue defaults flow field to 'default'."""
        issue = WebIssue(
            number=1,
            title="Test",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert issue.flow == "default"

    def test_web_issue_accepts_quick_flow(self):
        """Test that WebIssue accepts 'quick' flow value."""
        issue = WebIssue(
            number=1,
            title="Test",
            flow="quick",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert issue.flow == "quick"


class TestConvertIssueToWebFlow:
    """Tests for flow field in issue conversion."""

    @pytest.fixture
    def mock_core_issue(self):
        """Create a mock core Issue object."""
        mock = Mock()
        mock.id = "001"
        mock.title = "Test Issue"
        mock.stage = "backlog"
        mock.labels = []
        mock.pr_url = None
        mock.pr_number = None
        mock.worktree_dir = None
        mock.created = "2024-01-01T00:00:00Z"
        mock.updated = "2024-01-01T00:00:00Z"
        mock.dependencies = []
        mock.priority = Priority.MEDIUM
        mock.processing = None
        mock.ci_escalated = False
        mock.flow = "default"
        return mock

    @patch("agenttree.web.app.agent_manager")
    @patch("agenttree.web.app._config")
    def test_convert_issue_copies_default_flow(
        self, mock_config, mock_agent_mgr, mock_core_issue
    ):
        """Test that conversion copies 'default' flow from core issue."""
        mock_agent_mgr._check_issue_tmux_session.return_value = False
        mock_config.get_port_for_issue.return_value = None

        web_issue = convert_issue_to_web(mock_core_issue)

        assert web_issue.flow == "default"

    @patch("agenttree.web.app.agent_manager")
    @patch("agenttree.web.app._config")
    def test_convert_issue_copies_quick_flow(
        self, mock_config, mock_agent_mgr, mock_core_issue
    ):
        """Test that conversion copies 'quick' flow from core issue."""
        mock_core_issue.flow = "quick"
        mock_agent_mgr._check_issue_tmux_session.return_value = False
        mock_config.get_port_for_issue.return_value = None

        web_issue = convert_issue_to_web(mock_core_issue)

        assert web_issue.flow == "quick"

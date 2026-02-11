"""Tests for mobile web view endpoints."""

import pytest
from unittest.mock import Mock, patch

# Skip all tests if web dependencies aren't installed
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from starlette.testclient import TestClient

from agenttree.web.app import app
from agenttree.issues import Priority


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_issue():
    """Create a mock issue object."""
    mock = Mock()
    mock.id = "001"
    mock.title = "Test Issue Title"
    mock.stage = "backlog"
    mock.substage = None
    mock.labels = ["bug"]
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


@pytest.fixture
def mock_issue_with_agent():
    """Create a mock issue with an assigned agent."""
    mock = Mock()
    mock.id = "002"
    mock.title = "Issue With Agent"
    mock.stage = "implement"
    mock.substage = "code"
    mock.labels = []
    mock.pr_url = None
    mock.pr_number = None
    mock.worktree_dir = "/tmp/worktree"
    mock.created = "2024-01-01T00:00:00Z"
    mock.updated = "2024-01-01T00:00:00Z"
    mock.dependencies = []
    mock.priority = Priority.MEDIUM
    mock.processing = None
    mock.ci_escalated = False
    mock.flow = "default"
    return mock


class TestMobileEndpoint:
    """Tests for mobile view endpoint."""

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_mobile_returns_html(self, mock_agent_mgr, mock_crud, client):
        """Test mobile endpoint returns HTML."""
        mock_crud.list_issues.return_value = []
        mock_agent_mgr.clear_session_cache = Mock()

        response = client.get("/mobile")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_mobile_with_issues(self, mock_agent_mgr, mock_crud, client, mock_issue):
        """Test mobile view with issues list."""
        mock_crud.list_issues.return_value = [mock_issue]
        mock_crud.get_issue.return_value = mock_issue
        mock_crud.get_issue_dir.return_value = None
        mock_agent_mgr.clear_session_cache = Mock()
        mock_agent_mgr._check_issue_tmux_session = Mock(return_value=False)

        response = client.get("/mobile")

        assert response.status_code == 200
        assert "Test Issue" in response.text

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_mobile_with_issue_param(self, mock_agent_mgr, mock_crud, client, mock_issue):
        """Test mobile with issue parameter selects that issue."""
        mock_crud.list_issues.return_value = [mock_issue]
        mock_crud.get_issue.return_value = mock_issue
        mock_crud.get_issue_dir.return_value = None
        mock_agent_mgr.clear_session_cache = Mock()
        mock_agent_mgr._check_issue_tmux_session = Mock(return_value=False)

        response = client.get("/mobile?issue=001")

        assert response.status_code == 200
        mock_crud.get_issue.assert_called()

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_mobile_with_tab_issues(self, mock_agent_mgr, mock_crud, client, mock_issue):
        """Test mobile with tab=issues shows issues list."""
        mock_crud.list_issues.return_value = [mock_issue]
        mock_crud.get_issue.return_value = mock_issue
        mock_crud.get_issue_dir.return_value = None
        mock_agent_mgr.clear_session_cache = Mock()
        mock_agent_mgr._check_issue_tmux_session = Mock(return_value=False)

        response = client.get("/mobile?tab=issues")

        assert response.status_code == 200
        # The issues tab should be marked as active
        assert 'data-active-tab="issues"' in response.text or 'active-tab' in response.text.lower()

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_mobile_with_tab_detail(self, mock_agent_mgr, mock_crud, client, mock_issue):
        """Test mobile with tab=detail shows issue detail."""
        mock_crud.list_issues.return_value = [mock_issue]
        mock_crud.get_issue.return_value = mock_issue
        mock_crud.get_issue_dir.return_value = None
        mock_agent_mgr.clear_session_cache = Mock()
        mock_agent_mgr._check_issue_tmux_session = Mock(return_value=False)

        response = client.get("/mobile?issue=001&tab=detail")

        assert response.status_code == 200

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_mobile_with_tab_chat(self, mock_agent_mgr, mock_crud, client, mock_issue_with_agent):
        """Test mobile with tab=chat shows chat panel."""
        mock_crud.list_issues.return_value = [mock_issue_with_agent]
        mock_crud.get_issue.return_value = mock_issue_with_agent
        mock_crud.get_issue_dir.return_value = None
        mock_agent_mgr.clear_session_cache = Mock()
        mock_agent_mgr._check_issue_tmux_session = Mock(return_value=True)

        response = client.get("/mobile?issue=002&tab=chat")

        assert response.status_code == 200

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_mobile_includes_bottom_nav(self, mock_agent_mgr, mock_crud, client):
        """Test mobile template includes bottom navigation."""
        mock_crud.list_issues.return_value = []
        mock_agent_mgr.clear_session_cache = Mock()

        response = client.get("/mobile")

        assert response.status_code == 200
        assert "mobile-bottom-nav" in response.text

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_mobile_has_header(self, mock_agent_mgr, mock_crud, client):
        """Test mobile template has header with title."""
        mock_crud.list_issues.return_value = []
        mock_agent_mgr.clear_session_cache = Mock()

        response = client.get("/mobile")

        assert response.status_code == 200
        assert "AgentTree" in response.text

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_mobile_includes_new_issue_button(self, mock_agent_mgr, mock_crud, client):
        """Test mobile template includes + New Issue button."""
        mock_crud.list_issues.return_value = []
        mock_agent_mgr.clear_session_cache = Mock()

        response = client.get("/mobile")

        assert response.status_code == 200
        assert "mobile-fab" in response.text or "new-issue" in response.text.lower()

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_mobile_nonexistent_issue_falls_back(self, mock_agent_mgr, mock_crud, client, mock_issue):
        """Test mobile with nonexistent issue falls back to first issue."""
        mock_crud.list_issues.return_value = [mock_issue]
        mock_crud.get_issue.return_value = None  # Issue 999 not found
        mock_crud.get_issue_dir.return_value = None
        mock_agent_mgr.clear_session_cache = Mock()
        mock_agent_mgr._check_issue_tmux_session = Mock(return_value=False)

        response = client.get("/mobile?issue=999")

        # Should still return 200, not 404
        assert response.status_code == 200

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_mobile_empty_state(self, mock_agent_mgr, mock_crud, client):
        """Test mobile with no issues shows empty state."""
        mock_crud.list_issues.return_value = []
        mock_agent_mgr.clear_session_cache = Mock()

        response = client.get("/mobile")

        assert response.status_code == 200
        # Should show some empty state indication
        assert "no issues" in response.text.lower() or "empty" in response.text.lower()


class TestCreateIssueEndpoint:
    """Tests for create issue API endpoint."""

    @patch("agenttree.web.app.issue_crud")
    def test_create_issue_success(self, mock_crud, client):
        """Test creating issue with description (title auto-generated)."""
        mock_issue = Mock()
        mock_issue.id = "042"
        mock_issue.title = "Auto generated title"
        mock_crud.create_issue.return_value = mock_issue

        response = client.post(
            "/api/issues",
            data={
                "description": "This is a problem description that explains what needs to be done."
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["issue_id"] == "042"

    @patch("agenttree.web.app.issue_crud")
    def test_create_issue_with_title(self, mock_crud, client):
        """Test creating issue with explicit title."""
        mock_issue = Mock()
        mock_issue.id = "042"
        mock_issue.title = "My Custom Title"
        mock_crud.create_issue.return_value = mock_issue

        response = client.post(
            "/api/issues",
            data={
                "title": "My Custom Title",
                "description": "This is a problem description."
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    @patch("agenttree.web.app.issue_crud")
    def test_create_issue_missing_description(self, mock_crud, client):
        """Test creating issue without description fails."""
        response = client.post(
            "/api/issues",
            data={"title": "Some title"}
        )

        assert response.status_code == 400
        assert "description" in response.json()["detail"].lower()

    @patch("agenttree.web.app.issue_crud")
    def test_create_issue_empty_description(self, mock_crud, client):
        """Test creating issue with empty description fails."""
        response = client.post(
            "/api/issues",
            data={"description": "   "}  # whitespace only
        )

        assert response.status_code == 400
        assert "description" in response.json()["detail"].lower()

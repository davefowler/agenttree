"""Tests for web API endpoints."""

import pytest
from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Skip all tests if web dependencies aren't installed
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from starlette.testclient import TestClient

from agenttree.web.app import app, AgentManager, convert_issue_to_web, filter_issues
from agenttree.web.models import StageEnum, Issue as WebIssue
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
    mock.title = "Test Issue"
    mock.stage = "backlog"
    mock.substage = None
    mock.labels = ["bug"]
    mock.assigned_agent = None
    mock.pr_url = None
    mock.pr_number = None
    mock.worktree_dir = None
    mock.created = "2024-01-01T00:00:00Z"
    mock.updated = "2024-01-01T00:00:00Z"
    mock.dependencies = []
    mock.priority = Priority.MEDIUM
    mock.processing = None
    mock.ci_escalated = False
    return mock


@pytest.fixture
def mock_review_issue():
    """Create a mock issue at implementation_review stage."""
    mock = Mock()
    mock.id = "002"
    mock.title = "Review Issue"
    mock.stage = "implementation_review"
    mock.substage = None
    mock.labels = []
    mock.assigned_agent = "1"
    mock.pr_url = "https://github.com/test/repo/pull/123"
    mock.pr_number = 123
    mock.worktree_dir = "/tmp/worktree"
    mock.created = "2024-01-01T00:00:00Z"
    mock.updated = "2024-01-01T00:00:00Z"
    mock.dependencies = []
    mock.priority = Priority.MEDIUM
    mock.processing = None
    mock.ci_escalated = False
    return mock


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check_returns_healthy(self, client):
        """Test health check returns healthy status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "agenttree-web"


class TestRootRedirect:
    """Tests for root redirect."""

    def test_root_redirects_to_kanban(self, client):
        """Test root path redirects to kanban."""
        response = client.get("/", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/kanban"


class TestKanbanEndpoint:
    """Tests for kanban board endpoint."""

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_kanban_returns_html(self, mock_agent_mgr, mock_crud, client):
        """Test kanban endpoint returns HTML."""
        mock_crud.list_issues.return_value = []
        mock_agent_mgr.clear_session_cache = Mock()

        response = client.get("/kanban")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_kanban_with_issue_param(self, mock_agent_mgr, mock_crud, client, mock_issue):
        """Test kanban with issue parameter loads issue detail."""
        mock_crud.list_issues.return_value = [mock_issue]
        mock_crud.get_issue.return_value = mock_issue
        mock_crud.get_issue_dir.return_value = None
        mock_agent_mgr.clear_session_cache = Mock()
        mock_agent_mgr._check_issue_tmux_session = Mock(return_value=False)

        response = client.get("/kanban?issue=001")

        assert response.status_code == 200
        mock_crud.get_issue.assert_called()


class TestFlowEndpoint:
    """Tests for flow view endpoint."""

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_flow_returns_html(self, mock_agent_mgr, mock_crud, client):
        """Test flow endpoint returns HTML."""
        mock_crud.list_issues.return_value = []
        mock_agent_mgr.clear_session_cache = Mock()

        response = client.get("/flow")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_flow_accepts_sort_param(self, mock_agent_mgr, mock_crud, client):
        """Test flow endpoint accepts sort parameter."""
        mock_crud.list_issues.return_value = []
        mock_agent_mgr.clear_session_cache = Mock()

        response = client.get("/flow?sort=updated")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_flow_accepts_filter_param(self, mock_agent_mgr, mock_crud, client):
        """Test flow endpoint accepts filter parameter."""
        mock_crud.list_issues.return_value = []
        mock_agent_mgr.clear_session_cache = Mock()

        response = client.get("/flow?filter=review")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_flow_sort_and_filter_combined(self, mock_agent_mgr, mock_crud, client):
        """Test flow can sort and filter at the same time."""
        mock_crud.list_issues.return_value = []
        mock_agent_mgr.clear_session_cache = Mock()

        response = client.get("/flow?sort=updated&filter=review")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestFlowSortingFunctions:
    """Tests for flow sorting and filtering functions."""

    def test_sort_flow_issues_by_updated(self):
        """Test sorting by updated date."""
        from agenttree.web.app import _sort_flow_issues
        from agenttree.web.models import Issue as WebIssue, StageEnum

        issue1 = WebIssue(
            number=1, title="Older", body="", labels=[], assignees=[],
            stage=StageEnum.BACKLOG, substage=None, assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )
        issue2 = WebIssue(
            number=2, title="Newer", body="", labels=[], assignees=[],
            stage=StageEnum.BACKLOG, substage=None, assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 2),
            dependencies=[], dependents=[],
        )

        result = _sort_flow_issues([issue1, issue2], sort_by="updated")

        # Newer issue should come first
        assert result[0].number == 2
        assert result[1].number == 1

    def test_sort_flow_issues_by_number(self):
        """Test sorting by issue number."""
        from agenttree.web.app import _sort_flow_issues
        from agenttree.web.models import Issue as WebIssue, StageEnum

        issue10 = WebIssue(
            number=10, title="Ten", body="", labels=[], assignees=[],
            stage=StageEnum.BACKLOG, substage=None, assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )
        issue5 = WebIssue(
            number=5, title="Five", body="", labels=[], assignees=[],
            stage=StageEnum.BACKLOG, substage=None, assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )

        result = _sort_flow_issues([issue10, issue5], sort_by="number")

        # Lower number should come first
        assert result[0].number == 5
        assert result[1].number == 10

    def test_sort_flow_issues_by_created(self):
        """Test sorting by created date."""
        from agenttree.web.app import _sort_flow_issues
        from agenttree.web.models import Issue as WebIssue, StageEnum

        issue1 = WebIssue(
            number=1, title="Older", body="", labels=[], assignees=[],
            stage=StageEnum.BACKLOG, substage=None, assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )
        issue2 = WebIssue(
            number=2, title="Newer", body="", labels=[], assignees=[],
            stage=StageEnum.BACKLOG, substage=None, assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 2), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )

        result = _sort_flow_issues([issue1, issue2], sort_by="created")

        # Newer created should come first
        assert result[0].number == 2
        assert result[1].number == 1

    def test_filter_flow_issues_review(self):
        """Test filtering to review stages."""
        from agenttree.web.app import _filter_flow_issues
        from agenttree.web.models import Issue as WebIssue, StageEnum

        review_issue = WebIssue(
            number=1, title="Review", body="", labels=[], assignees=[],
            stage=StageEnum.IMPLEMENTATION_REVIEW, substage=None,
            assigned_agent="1", tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )
        other_issue = WebIssue(
            number=2, title="Other", body="", labels=[], assignees=[],
            stage=StageEnum.IMPLEMENT, substage=None, assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )

        result = _filter_flow_issues([review_issue, other_issue], filter_by="review")

        # Only review issue should remain
        assert len(result) == 1
        assert result[0].number == 1

    def test_filter_flow_issues_running(self):
        """Test filtering to running agents."""
        from agenttree.web.app import _filter_flow_issues
        from agenttree.web.models import Issue as WebIssue, StageEnum

        running_issue = WebIssue(
            number=1, title="Running", body="", labels=[], assignees=[],
            stage=StageEnum.IMPLEMENT, substage=None, assigned_agent="1",
            tmux_active=True, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )
        stopped_issue = WebIssue(
            number=2, title="Stopped", body="", labels=[], assignees=[],
            stage=StageEnum.IMPLEMENT, substage=None, assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )

        result = _filter_flow_issues([running_issue, stopped_issue], filter_by="running")

        # Only running issue should remain
        assert len(result) == 1
        assert result[0].number == 1

    def test_filter_flow_issues_open(self):
        """Test filtering to hide closed issues."""
        from agenttree.web.app import _filter_flow_issues
        from agenttree.web.models import Issue as WebIssue, StageEnum

        open_issue = WebIssue(
            number=1, title="Open", body="", labels=[], assignees=[],
            stage=StageEnum.IMPLEMENT, substage=None, assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )
        accepted_issue = WebIssue(
            number=2, title="Accepted", body="", labels=[], assignees=[],
            stage=StageEnum.ACCEPTED, substage=None, assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )

        result = _filter_flow_issues([open_issue, accepted_issue], filter_by="open")

        # Only open issue should remain
        assert len(result) == 1
        assert result[0].number == 1


class TestAgentStatusEndpoint:
    """Tests for agent status endpoint."""

    @patch("agenttree.web.app.agent_manager")
    def test_agent_status_running(self, mock_agent_mgr, client):
        """Test agent status when tmux session is active."""
        mock_agent_mgr._check_issue_tmux_session.return_value = True

        response = client.get("/api/issues/001/agent-status")

        assert response.status_code == 200
        data = response.json()
        assert data["tmux_active"] is True
        assert data["status"] == "running"

    @patch("agenttree.web.app.agent_manager")
    def test_agent_status_off(self, mock_agent_mgr, client):
        """Test agent status when tmux session is not active."""
        mock_agent_mgr._check_issue_tmux_session.return_value = False

        response = client.get("/api/issues/001/agent-status")

        assert response.status_code == 200
        data = response.json()
        assert data["tmux_active"] is False
        assert data["status"] == "off"


class TestStartIssueEndpoint:
    """Tests for start issue endpoint."""

    @patch("agenttree.api.start_agent")
    def test_start_issue_success(self, mock_start, client):
        """Test starting an agent for an issue."""
        mock_start.return_value = Mock()

        response = client.post("/api/issues/001/start")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "Started agent" in data["status"]

    @patch("agenttree.api.start_agent")
    def test_start_issue_error(self, mock_start, client):
        """Test start issue when start_agent fails."""
        from agenttree.api import AgentStartError
        mock_start.side_effect = AgentStartError("001", "Process failed")

        response = client.post("/api/issues/001/start")

        assert response.status_code == 500


class TestMoveIssueEndpoint:
    """Tests for move issue endpoint."""

    @patch("agenttree.hooks.cleanup_issue_agent")
    @patch("agenttree.web.app.issue_crud")
    def test_move_issue_to_backlog(self, mock_crud, mock_cleanup, client, mock_issue):
        """Test moving issue to backlog succeeds."""
        mock_crud.get_issue.return_value = mock_issue
        mock_crud.update_issue_stage.return_value = mock_issue

        response = client.post(
            "/api/issues/001/move",
            json={"stage": "backlog"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["stage"] == "backlog"

    @patch("agenttree.hooks.cleanup_issue_agent")
    @patch("agenttree.web.app.issue_crud")
    def test_move_issue_to_not_doing(self, mock_crud, mock_cleanup, client, mock_issue):
        """Test moving issue to not_doing succeeds."""
        mock_crud.get_issue.return_value = mock_issue
        mock_crud.update_issue_stage.return_value = mock_issue

        response = client.post(
            "/api/issues/001/move",
            json={"stage": "not_doing"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["stage"] == "not_doing"

    @patch("agenttree.web.app.issue_crud")
    def test_move_issue_to_implement_rejected(self, mock_crud, client, mock_issue):
        """Test moving issue directly to implement is rejected."""
        mock_crud.get_issue.return_value = mock_issue

        response = client.post(
            "/api/issues/001/move",
            json={"stage": "implement"}
        )

        assert response.status_code == 400
        data = response.json()
        assert "only allowed to" in data["detail"].lower()

    @patch("agenttree.web.app.issue_crud")
    def test_move_issue_not_found(self, mock_crud, client):
        """Test moving non-existent issue."""
        mock_crud.get_issue.return_value = None

        response = client.post(
            "/api/issues/999/move",
            json={"stage": "backlog"}
        )

        assert response.status_code == 404


class TestApproveIssueEndpoint:
    """Tests for approve issue endpoint."""

    @patch("agenttree.state.get_active_agent")
    @patch("agenttree.hooks.execute_enter_hooks")
    @patch("agenttree.hooks.execute_exit_hooks")
    @patch("agenttree.config.load_config")
    @patch("agenttree.web.app.issue_crud")
    def test_approve_issue_at_implementation_review(
        self, mock_crud, mock_config, mock_exit, mock_enter, mock_get_agent,
        client, mock_review_issue
    ):
        """Test approving issue at implementation_review stage."""
        mock_crud.get_issue.return_value = mock_review_issue
        mock_crud.update_issue_stage.return_value = mock_review_issue
        mock_get_agent.return_value = None

        # Mock config.get_next_stage
        mock_config.return_value.get_next_stage.return_value = ("accepted", None, True)

        response = client.post("/api/issues/002/approve")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

        # Verify hooks were called
        mock_exit.assert_called_once()
        mock_enter.assert_called_once()
        mock_crud.update_issue_stage.assert_called_once()

    @patch("agenttree.state.get_active_agent")
    @patch("agenttree.hooks.execute_enter_hooks")
    @patch("agenttree.hooks.execute_exit_hooks")
    @patch("agenttree.config.load_config")
    @patch("agenttree.web.app.issue_crud")
    def test_approve_issue_at_plan_review(
        self, mock_crud, mock_config, mock_exit, mock_enter, mock_get_agent,
        client, mock_issue
    ):
        """Test approving issue at plan_review stage."""
        mock_issue.stage = "plan_review"
        mock_crud.get_issue.return_value = mock_issue
        mock_crud.update_issue_stage.return_value = mock_issue
        mock_get_agent.return_value = None

        mock_config.return_value.get_next_stage.return_value = ("implement", None, True)

        response = client.post("/api/issues/001/approve")

        assert response.status_code == 200
        assert response.json()["ok"] is True

    @patch("agenttree.web.app.issue_crud")
    def test_approve_issue_not_at_review_stage(self, mock_crud, client, mock_issue):
        """Test approving issue that's not at review stage."""
        mock_issue.stage = "implement"  # Not a review stage
        mock_crud.get_issue.return_value = mock_issue

        response = client.post("/api/issues/001/approve")

        assert response.status_code == 400
        assert "Not at review stage" in response.json()["detail"]

    @patch("agenttree.web.app.issue_crud")
    def test_approve_issue_not_found(self, mock_crud, client):
        """Test approving non-existent issue."""
        mock_crud.get_issue.return_value = None

        response = client.post("/api/issues/999/approve")

        assert response.status_code == 404

    @patch("agenttree.hooks.execute_exit_hooks")
    @patch("agenttree.config.load_config")
    @patch("agenttree.web.app.issue_crud")
    def test_approve_issue_exit_hook_validation_fails(
        self, mock_crud, mock_config, mock_exit, client, mock_review_issue
    ):
        """Test approve fails when exit hook validation fails."""
        from agenttree.hooks import ValidationError

        mock_crud.get_issue.return_value = mock_review_issue
        mock_config.return_value.get_next_stage.return_value = ("accepted", None, True)
        mock_exit.side_effect = ValidationError("PR not ready")

        response = client.post("/api/issues/002/approve")

        assert response.status_code == 400
        assert "PR not ready" in response.json()["detail"]

    @patch("agenttree.hooks.execute_exit_hooks")
    @patch("agenttree.config.load_config")
    @patch("agenttree.web.app.issue_crud")
    def test_approve_issue_update_fails(
        self, mock_crud, mock_config, mock_exit, client, mock_review_issue
    ):
        """Test approve returns 500 when stage update fails."""
        mock_crud.get_issue.return_value = mock_review_issue
        mock_crud.update_issue_stage.return_value = None  # Update failed
        mock_config.return_value.get_next_stage.return_value = ("accepted", None, True)

        response = client.post("/api/issues/002/approve")

        assert response.status_code == 500
        assert "Failed to update" in response.json()["detail"]

    @patch("agenttree.tmux.send_message")
    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.state.get_active_agent")
    @patch("agenttree.hooks.execute_enter_hooks")
    @patch("agenttree.hooks.execute_exit_hooks")
    @patch("agenttree.config.load_config")
    @patch("agenttree.web.app.issue_crud")
    def test_approve_issue_notifies_agent(
        self, mock_crud, mock_config, mock_exit, mock_enter, mock_get_agent,
        mock_session_exists, mock_send, client, mock_review_issue
    ):
        """Test approve notifies active agent."""
        mock_crud.get_issue.return_value = mock_review_issue
        mock_crud.update_issue_stage.return_value = mock_review_issue
        mock_config.return_value.get_next_stage.return_value = ("accepted", None, True)

        mock_agent = Mock()
        mock_agent.tmux_session = "test-session"
        mock_get_agent.return_value = mock_agent
        mock_session_exists.return_value = True

        response = client.post("/api/issues/002/approve")

        assert response.status_code == 200
        mock_send.assert_called_once()
        assert "approved" in mock_send.call_args[0][1].lower()


class TestRebaseIssueEndpoint:
    """Tests for rebase issue endpoint."""

    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.tmux.send_message")
    @patch("agenttree.hooks.rebase_issue_branch")
    @patch("agenttree.web.app.issue_crud")
    def test_rebase_issue_success(self, mock_crud, mock_rebase, mock_send, mock_session_exists, client, mock_review_issue):
        """Test rebase issue succeeds."""
        mock_crud.get_issue.return_value = mock_review_issue
        mock_rebase.return_value = (True, "Rebased successfully")
        mock_session_exists.return_value = False  # No active session

        response = client.post("/api/issues/002/rebase")

        assert response.status_code == 200
        assert response.json()["ok"] is True

    @patch("agenttree.hooks.rebase_issue_branch")
    @patch("agenttree.web.app.issue_crud")
    def test_rebase_issue_fails(self, mock_crud, mock_rebase, client, mock_review_issue):
        """Test rebase issue when rebase fails."""
        mock_crud.get_issue.return_value = mock_review_issue
        mock_rebase.return_value = (False, "Merge conflicts")

        response = client.post("/api/issues/002/rebase")

        assert response.status_code == 400
        assert "Merge conflicts" in response.json()["detail"]

    @patch("agenttree.web.app.issue_crud")
    def test_rebase_issue_not_found(self, mock_crud, client):
        """Test rebase non-existent issue."""
        mock_crud.get_issue.return_value = None

        response = client.post("/api/issues/999/rebase")

        assert response.status_code == 404


class TestAgentTmuxEndpoint:
    """Tests for agent tmux output endpoint."""

    @patch("subprocess.run")
    @patch("agenttree.web.app.load_config")
    def test_agent_tmux_returns_output(self, mock_config, mock_run, client):
        """Test getting tmux output for agent."""
        mock_config.return_value.project = "test"
        mock_run.return_value = Mock(returncode=0, stdout="Agent output here")

        response = client.get("/agent/001/tmux")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @patch("subprocess.run")
    @patch("agenttree.web.app.load_config")
    def test_agent_tmux_session_not_active(self, mock_config, mock_run, client):
        """Test getting tmux output when session not active."""
        mock_config.return_value.project = "test"
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="session not found")

        response = client.get("/agent/001/tmux")

        assert response.status_code == 200
        assert "not active" in response.text.lower()


class TestSendToAgentEndpoint:
    """Tests for send message to agent endpoint."""

    @patch("agenttree.tmux.session_exists", return_value=False)
    @patch("agenttree.tmux.send_message")
    @patch("agenttree.web.app.load_config")
    def test_send_to_agent(self, mock_config, mock_send, mock_session, client):
        """Test sending message to agent."""
        mock_config.return_value.project = "test"

        response = client.post(
            "/agent/001/send",
            data={"message": "Hello agent"}
        )

        assert response.status_code == 200
        mock_send.assert_called_once()


class TestAgentManager:
    """Tests for AgentManager class."""

    @patch("subprocess.run")
    def test_get_active_sessions(self, mock_run):
        """Test getting active tmux sessions."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="test-issue-001\ntest-issue-002\n"
        )

        manager = AgentManager()
        sessions = manager._get_active_sessions()

        assert "test-issue-001" in sessions
        assert "test-issue-002" in sessions

    @patch("subprocess.run")
    def test_get_active_sessions_no_sessions(self, mock_run):
        """Test getting sessions when tmux has none."""
        mock_run.return_value = Mock(returncode=1, stdout="")

        manager = AgentManager()
        sessions = manager._get_active_sessions()

        assert sessions == set()

    @patch("subprocess.run")
    def test_check_issue_tmux_session(self, mock_run):
        """Test checking if tmux session exists for issue."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="myproject-developer-001\n"
        )

        with patch("agenttree.web.app._config") as mock_config:
            mock_config.get_issue_session_patterns.return_value = [
                "myproject-developer-001",
                "myproject-reviewer-001",
            ]
            manager = AgentManager()
            manager._active_sessions = None  # Reset cache

            exists = manager._check_issue_tmux_session("001")

        assert exists is True

    def test_clear_session_cache(self):
        """Test clearing session cache."""
        manager = AgentManager()
        manager._active_sessions = {"some-session"}

        manager.clear_session_cache()

        assert manager._active_sessions is None


class TestConvertIssueToWeb:
    """Tests for convert_issue_to_web function."""

    @patch("agenttree.web.app.agent_manager")
    def test_convert_basic_issue(self, mock_agent_mgr, mock_issue):
        """Test converting basic issue to web model."""
        mock_agent_mgr._check_issue_tmux_session.return_value = False

        web_issue = convert_issue_to_web(mock_issue)

        assert web_issue.number == 1
        assert web_issue.title == "Test Issue"
        assert web_issue.stage == StageEnum.BACKLOG
        assert web_issue.tmux_active is False

    @patch("agenttree.web.app.agent_manager")
    def test_convert_issue_with_active_tmux(self, mock_agent_mgr, mock_review_issue):
        """Test converting issue with active tmux session."""
        mock_agent_mgr._check_issue_tmux_session.return_value = True

        web_issue = convert_issue_to_web(mock_review_issue)

        assert web_issue.tmux_active is True

    @patch("agenttree.web.app.agent_manager")
    def test_convert_issue_unknown_stage(self, mock_agent_mgr, mock_issue):
        """Test converting issue with unknown stage falls back to backlog."""
        mock_agent_mgr._check_issue_tmux_session.return_value = False
        mock_issue.stage = "unknown_stage"

        web_issue = convert_issue_to_web(mock_issue)

        assert web_issue.stage == StageEnum.BACKLOG


class TestFilterIssues:
    """Tests for filter_issues function."""

    @pytest.fixture
    def sample_web_issues(self):
        """Create sample web issues for testing."""
        return [
            WebIssue(
                number=42,
                title="Add login feature",
                body="",
                labels=["enhancement", "auth"],
                assignees=[],
                stage=StageEnum.IMPLEMENT,
                assigned_agent=None,
                tmux_active=False,
                pr_url=None,
                pr_number=None,
                created_at=datetime(2024, 1, 1),
                updated_at=datetime(2024, 1, 1),
            ),
            WebIssue(
                number=85,
                title="Fix bug in checkout",
                body="",
                labels=["bug", "urgent"],
                assignees=[],
                stage=StageEnum.PLAN_REVIEW,
                assigned_agent=None,
                tmux_active=False,
                pr_url=None,
                pr_number=None,
                created_at=datetime(2024, 1, 2),
                updated_at=datetime(2024, 1, 2),
            ),
            WebIssue(
                number=123,
                title="Update documentation",
                body="",
                labels=["docs"],
                assignees=[],
                stage=StageEnum.ACCEPTED,
                assigned_agent=None,
                tmux_active=False,
                pr_url=None,
                pr_number=None,
                created_at=datetime(2024, 1, 3),
                updated_at=datetime(2024, 1, 3),
            ),
        ]

    def test_filter_issues_by_number(self, sample_web_issues):
        """Test filtering issues by issue number."""
        result = filter_issues(sample_web_issues, "42")

        assert len(result) == 1
        assert result[0].number == 42

    def test_filter_issues_by_title(self, sample_web_issues):
        """Test filtering issues by title."""
        result = filter_issues(sample_web_issues, "login")

        assert len(result) == 1
        assert result[0].title == "Add login feature"

    def test_filter_issues_by_label(self, sample_web_issues):
        """Test filtering issues by label."""
        result = filter_issues(sample_web_issues, "bug")

        assert len(result) == 1
        assert result[0].number == 85

    def test_filter_issues_case_insensitive(self, sample_web_issues):
        """Test that search is case-insensitive."""
        result = filter_issues(sample_web_issues, "LOGIN")

        assert len(result) == 1
        assert result[0].title == "Add login feature"

    def test_empty_search_returns_all(self, sample_web_issues):
        """Test that empty search returns all issues."""
        result = filter_issues(sample_web_issues, "")

        assert len(result) == 3

    def test_none_search_returns_all(self, sample_web_issues):
        """Test that None search returns all issues."""
        result = filter_issues(sample_web_issues, None)

        assert len(result) == 3

    def test_no_matches_returns_empty(self, sample_web_issues):
        """Test that search with no matches returns empty list."""
        result = filter_issues(sample_web_issues, "nonexistent")

        assert len(result) == 0

    def test_filter_issues_includes_old_issues(self, sample_web_issues):
        """Test that search finds accepted/old issues."""
        result = filter_issues(sample_web_issues, "documentation")

        assert len(result) == 1
        assert result[0].stage == StageEnum.ACCEPTED

    def test_filter_issues_whitespace_only_returns_all(self, sample_web_issues):
        """Test that whitespace-only search returns all issues."""
        result = filter_issues(sample_web_issues, "   ")

        assert len(result) == 3


class TestKanbanSearchEndpoint:
    """Tests for kanban board search functionality."""

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_kanban_with_search_param(self, mock_agent_mgr, mock_crud, client, mock_issue):
        """Test kanban with search parameter filters issues."""
        mock_crud.list_issues.return_value = [mock_issue]
        mock_agent_mgr.clear_session_cache = Mock()
        mock_agent_mgr._check_issue_tmux_session = Mock(return_value=False)

        response = client.get("/kanban?search=test")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_kanban_search_preserves_other_params(self, mock_agent_mgr, mock_crud, client, mock_issue):
        """Test kanban search works with other URL params."""
        mock_crud.list_issues.return_value = [mock_issue]
        mock_crud.get_issue.return_value = mock_issue
        mock_crud.get_issue_dir.return_value = None
        mock_agent_mgr.clear_session_cache = Mock()
        mock_agent_mgr._check_issue_tmux_session = Mock(return_value=False)

        response = client.get("/kanban?search=test&issue=001")

        assert response.status_code == 200


class TestFlowSearchEndpoint:
    """Tests for flow view search functionality."""

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_flow_with_search_param(self, mock_agent_mgr, mock_crud, client):
        """Test flow with search parameter filters issues."""
        mock_crud.list_issues.return_value = []
        mock_agent_mgr.clear_session_cache = Mock()

        response = client.get("/flow?search=test")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

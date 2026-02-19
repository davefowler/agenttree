"""Tests for web API endpoints."""

import pytest
from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Skip all tests if web dependencies aren't installed
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from starlette.testclient import TestClient

from agenttree.web.app import app, AgentManager, convert_issue_to_web, filter_issues, FILE_TO_STAGE
from agenttree.web.models import Issue as WebIssue
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
    mock.flow = "default"
    return mock


@pytest.fixture
def mock_review_issue():
    """Create a mock issue at implement.review stage."""
    mock = Mock()
    mock.id = "002"
    mock.title = "Review Issue"
    mock.stage = "implement.review"
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
    mock.flow = "default"
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
        from agenttree.web.models import Issue as WebIssue

        issue1 = WebIssue(
            number=1, title="Older", body="", labels=[], assignees=[],
            stage="backlog", assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )
        issue2 = WebIssue(
            number=2, title="Newer", body="", labels=[], assignees=[],
            stage="backlog", assigned_agent=None,
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
        from agenttree.web.models import Issue as WebIssue

        issue10 = WebIssue(
            number=10, title="Ten", body="", labels=[], assignees=[],
            stage="backlog", assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )
        issue5 = WebIssue(
            number=5, title="Five", body="", labels=[], assignees=[],
            stage="backlog", assigned_agent=None,
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
        from agenttree.web.models import Issue as WebIssue

        issue1 = WebIssue(
            number=1, title="Older", body="", labels=[], assignees=[],
            stage="backlog", assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )
        issue2 = WebIssue(
            number=2, title="Newer", body="", labels=[], assignees=[],
            stage="backlog", assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 2), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )

        result = _sort_flow_issues([issue1, issue2], sort_by="created")

        # Newer created should come first
        assert result[0].number == 2
        assert result[1].number == 1

    @patch("agenttree.config.load_config")
    def test_filter_flow_issues_review(self, mock_load_config):
        """Test filtering to review stages."""
        from agenttree.web.app import _filter_flow_issues
        from agenttree.web.models import Issue as WebIssue

        mock_config = Mock()
        mock_config.is_human_review.side_effect = lambda s: s == "implement.review"
        mock_load_config.return_value = mock_config

        review_issue = WebIssue(
            number=1, title="Review", body="", labels=[], assignees=[],
            stage="implement.review",
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )
        other_issue = WebIssue(
            number=2, title="Other", body="", labels=[], assignees=[],
            stage="implement.code",
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
        from agenttree.web.models import Issue as WebIssue

        running_issue = WebIssue(
            number=1, title="Running", body="", labels=[], assignees=[],
            stage="implement.code", assigned_agent="1",
            tmux_active=True, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )
        stopped_issue = WebIssue(
            number=2, title="Stopped", body="", labels=[], assignees=[],
            stage="implement.code", assigned_agent=None,
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
        from agenttree.web.models import Issue as WebIssue

        open_issue = WebIssue(
            number=1, title="Open", body="", labels=[], assignees=[],
            stage="implement.code", assigned_agent=None,
            tmux_active=False, pr_url=None, pr_number=None,
            created_at=datetime(2024, 1, 1), updated_at=datetime(2024, 1, 1),
            dependencies=[], dependents=[],
        )
        accepted_issue = WebIssue(
            number=2, title="Accepted", body="", labels=[], assignees=[],
            stage="accepted", assigned_agent=None,
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
    @patch("agenttree.api.transition_issue")
    @patch("agenttree.config.load_config")
    @patch("agenttree.web.app.issue_crud")
    def test_approve_issue_at_implementation_review(
        self, mock_crud, mock_config, mock_transition, mock_get_agent,
        client, mock_review_issue
    ):
        """Test approving issue at implementation_review stage."""
        mock_crud.get_issue.return_value = mock_review_issue
        mock_get_agent.return_value = None

        updated = MagicMock()
        updated.stage = "accepted"
        mock_transition.return_value = updated

        # Mock config.get_next_stage
        mock_config.return_value.get_next_stage.return_value = ("accepted", True)

        response = client.post("/api/issues/002/approve")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

        # Verify transition_issue was called
        mock_transition.assert_called_once()

    @patch("agenttree.state.get_active_agent")
    @patch("agenttree.api.transition_issue")
    @patch("agenttree.config.load_config")
    @patch("agenttree.web.app.issue_crud")
    def test_approve_issue_at_plan_review(
        self, mock_crud, mock_config, mock_transition, mock_get_agent,
        client, mock_issue
    ):
        """Test approving issue at plan_review stage."""
        mock_issue.stage = "plan.review"
        mock_crud.get_issue.return_value = mock_issue
        mock_get_agent.return_value = None

        updated = MagicMock()
        updated.stage = "implement"
        mock_transition.return_value = updated

        mock_config.return_value.get_next_stage.return_value = ("implement.code", True)

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

    @patch("agenttree.api.transition_issue")
    @patch("agenttree.config.load_config")
    @patch("agenttree.web.app.issue_crud")
    def test_approve_issue_exit_hook_validation_fails(
        self, mock_crud, mock_config, mock_transition, client, mock_review_issue
    ):
        """Test approve fails when exit hook validation fails."""
        from agenttree.hooks import ValidationError

        mock_crud.get_issue.return_value = mock_review_issue
        mock_config.return_value.get_next_stage.return_value = ("accepted", True)
        mock_transition.side_effect = ValidationError("PR not ready")

        response = client.post("/api/issues/002/approve")

        assert response.status_code == 400
        assert "PR not ready" in response.json()["detail"]

    @patch("agenttree.api.transition_issue")
    @patch("agenttree.config.load_config")
    @patch("agenttree.web.app.issue_crud")
    def test_approve_issue_update_fails(
        self, mock_crud, mock_config, mock_transition, client, mock_review_issue
    ):
        """Test approve returns 500 when transition_issue raises RuntimeError."""
        mock_crud.get_issue.return_value = mock_review_issue
        mock_config.return_value.get_next_stage.return_value = ("accepted", True)
        mock_transition.side_effect = RuntimeError("Failed to update issue #2 to accepted")

        response = client.post("/api/issues/002/approve")

        assert response.status_code == 500

    @patch("agenttree.state.get_active_agent")
    @patch("agenttree.api.transition_issue")
    @patch("agenttree.config.load_config")
    @patch("agenttree.web.app.issue_crud")
    def test_approve_issue_calls_transition(
        self, mock_crud, mock_config, mock_transition, mock_get_agent,
        client, mock_review_issue
    ):
        """Test approve calls transition_issue with correct args."""
        mock_crud.get_issue.return_value = mock_review_issue
        mock_get_agent.return_value = None
        updated = MagicMock()
        updated.stage = "accepted"
        mock_transition.return_value = updated
        mock_config.return_value.get_next_stage.return_value = ("accepted", True)
        mock_config.return_value.allow_self_approval = False

        response = client.post("/api/issues/002/approve")

        assert response.status_code == 200
        mock_transition.assert_called_once_with(
            "2", "accepted",
            skip_pr_approval=False,
            trigger="web",
        )


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

    @patch("agenttree.tmux.session_exists")
    @patch("agenttree.tmux.send_message")
    @patch("agenttree.web.app.load_config")
    def test_send_to_agent(self, mock_config, mock_send, mock_session_exists, client):
        """Test sending message to agent."""
        mock_config.return_value.project = "test"
        mock_session_exists.return_value = True

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
            mock_config.project = "myproject"
            mock_config.get_issue_session_patterns.return_value = [
                "myproject-developer-001",
                "myproject-reviewer-001",
                "myproject-issue-001",
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
        assert web_issue.stage == "backlog"
        assert web_issue.tmux_active is False

    @patch("agenttree.web.app.agent_manager")
    def test_convert_issue_with_active_tmux(self, mock_agent_mgr, mock_review_issue):
        """Test converting issue with active tmux session."""
        mock_agent_mgr._check_issue_tmux_session.return_value = True

        web_issue = convert_issue_to_web(mock_review_issue)

        assert web_issue.tmux_active is True

    @patch("agenttree.web.app.agent_manager")
    def test_convert_issue_unknown_stage(self, mock_agent_mgr, mock_issue):
        """Test converting issue with unknown stage passes it through."""
        mock_agent_mgr._check_issue_tmux_session.return_value = False
        mock_issue.stage = "unknown_stage"

        web_issue = convert_issue_to_web(mock_issue)

        assert web_issue.stage == "unknown_stage"


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
                stage="implement.code",
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
                stage="plan.review",
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
                stage="accepted",
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
        assert result[0].stage == "accepted"

    def test_filter_issues_whitespace_only_returns_all(self, sample_web_issues):
        """Test that whitespace-only search returns all issues."""
        result = filter_issues(sample_web_issues, "   ")

        assert len(result) == 3


class TestKanbanUnrecognizedStage:
    """Test that issues with unrecognized stages appear in backlog."""

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app.agent_manager")
    def test_unrecognized_stage_falls_back_to_backlog(self, mock_agent_mgr, mock_crud):
        """Issues with stage names not in config should appear in backlog."""
        from agenttree.web.app import get_kanban_board
        from agenttree.issues import Issue

        issue = Issue(
            id="162",
            slug="test-issue",
            title="Test Issue",
            stage="implementation_review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )
        mock_crud.list_issues.return_value = [issue]
        mock_agent_mgr._check_issue_tmux_session = Mock(return_value=False)

        board = get_kanban_board()
        backlog_numbers = [i.number for i in board.stages.get("backlog", [])]
        assert 162 in backlog_numbers


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


class TestSettingsPage:
    """Tests for settings page."""

    def test_settings_page_returns_html(self, client):
        """Test GET /settings returns HTML page."""
        response = client.get("/settings")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_settings_page_shows_current_values(self, client):
        """Test settings page displays current config values."""
        response = client.get("/settings")

        assert response.status_code == 200
        # Page should contain form fields for settings
        assert b"default_model" in response.content or b"Default Model" in response.content

    @patch("agenttree.web.app._config")
    def test_settings_page_shows_available_tools(self, mock_config, client):
        """Test settings page shows available tools from config."""
        mock_config.tools = {"claude": Mock(), "aider": Mock()}
        mock_config.default_tool = "claude"
        mock_config.default_model = "opus"
        mock_config.show_issue_yaml = True
        mock_config.save_tmux_history = False
        mock_config.allow_self_approval = False
        mock_config.refresh_interval = 10

        response = client.get("/settings")

        assert response.status_code == 200


class TestFileToStageMapping:
    """Tests for file-to-stage mapping in get_issue_files."""

    def test_file_to_stage_mapping_exists(self):
        """Test that FILE_TO_STAGE mapping maps files to dot-path stages."""
        assert "problem.md" in FILE_TO_STAGE
        assert FILE_TO_STAGE["problem.md"] == "explore.define"
        assert FILE_TO_STAGE["research.md"] == "explore.research"
        assert FILE_TO_STAGE["spec.md"] == "plan.draft"
        assert FILE_TO_STAGE["spec_review.md"] == "plan.assess"
        assert FILE_TO_STAGE["review.md"] == "implement.code_review"
        assert FILE_TO_STAGE["independent_review.md"] == "implement.independent_review"
        assert FILE_TO_STAGE["feedback.md"] == "implement.feedback"

    def test_file_to_stage_unknown_file(self):
        """Test that unknown files are not in FILE_TO_STAGE."""
        assert "unknown.md" not in FILE_TO_STAGE
        assert "issue.yaml" not in FILE_TO_STAGE

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app._config")
    def test_get_issue_files_includes_stage(self, mock_config, mock_crud, tmp_path):
        """Test that get_issue_files includes stage and stage_color fields."""
        from agenttree.web.app import get_issue_files

        # Create test files
        issue_dir = tmp_path / "001-test"
        issue_dir.mkdir()
        (issue_dir / "problem.md").write_text("# Problem")
        (issue_dir / "spec.md").write_text("# Spec")

        mock_crud.get_issue_dir.return_value = issue_dir
        mock_config.show_issue_yaml = False
        mock_config.stage_color.side_effect = lambda dp: {"explore.define": "#f97316", "plan.draft": "#eab308"}.get(dp, "")

        files = get_issue_files("001")

        assert len(files) == 2
        # Check problem.md has stage=explore.define with color from config
        problem_file = next(f for f in files if f["name"] == "problem.md")
        assert problem_file["stage"] == "explore.define"
        assert problem_file["stage_color"] == "#f97316"
        # Check spec.md has stage=plan.draft with color from config
        spec_file = next(f for f in files if f["name"] == "spec.md")
        assert spec_file["stage"] == "plan.draft"
        assert spec_file["stage_color"] == "#eab308"

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app._config")
    def test_get_issue_files_is_passed_true(self, mock_config, mock_crud, tmp_path):
        """Test that is_passed is true for earlier stages."""
        from agenttree.web.app import get_issue_files

        # Create test files
        issue_dir = tmp_path / "001-test"
        issue_dir.mkdir()
        (issue_dir / "problem.md").write_text("# Problem")
        (issue_dir / "spec.md").write_text("# Spec")
        (issue_dir / "review.md").write_text("# Review")

        mock_crud.get_issue_dir.return_value = issue_dir
        mock_config.show_issue_yaml = False
        mock_config.stage_color.return_value = "#aaa"
        mock_config.get_flow_stage_names.return_value = [
            "backlog", "explore.define", "explore.research",
            "plan.draft", "plan.assess", "plan.revise", "plan.review",
            "implement.setup", "implement.code", "implement.code_review",
        ]

        # Current stage is implement.code_review
        files = get_issue_files("001", current_stage="implement.code_review")

        problem_file = next(f for f in files if f["name"] == "problem.md")
        spec_file = next(f for f in files if f["name"] == "spec.md")
        review_file = next(f for f in files if f["name"] == "review.md")

        # problem.md (explore.define) should be passed when at implement.code_review
        assert problem_file["is_passed"] == "true"
        # spec.md (plan.draft) should be passed when at implement.code_review
        assert spec_file["is_passed"] == "true"
        # review.md (implement.code_review) should NOT be passed when at implement.code_review
        assert review_file["is_passed"] == "false"

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app._config")
    def test_get_issue_files_short_name_for_passed(self, mock_config, mock_crud, tmp_path):
        """Test that short_name is truncated for passed stages."""
        from agenttree.web.app import get_issue_files

        # Create test files
        issue_dir = tmp_path / "001-test"
        issue_dir.mkdir()
        (issue_dir / "problem.md").write_text("# Problem")
        (issue_dir / "review.md").write_text("# Review")

        mock_crud.get_issue_dir.return_value = issue_dir
        mock_config.show_issue_yaml = False
        mock_config.stage_color.return_value = "#aaa"
        mock_config.get_flow_stage_names.return_value = [
            "backlog", "explore.define", "explore.research",
            "plan.draft", "plan.assess", "plan.revise", "plan.review",
            "implement.setup", "implement.code", "implement.code_review",
        ]

        # Current stage is implement.code_review
        files = get_issue_files("001", current_stage="implement.code_review")

        problem_file = next(f for f in files if f["name"] == "problem.md")
        review_file = next(f for f in files if f["name"] == "review.md")

        # problem.md is passed, should have truncated short_name
        assert problem_file["short_name"] == "Pro..."
        # review.md is current, should have full display_name as short_name
        assert review_file["short_name"] == "Review"

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app._config")
    def test_get_issue_files_unknown_file_no_stage(self, mock_config, mock_crud, tmp_path):
        """Test that unknown files have empty stage."""
        from agenttree.web.app import get_issue_files

        # Create test file with unknown name
        issue_dir = tmp_path / "001-test"
        issue_dir.mkdir()
        (issue_dir / "custom_notes.md").write_text("# Notes")

        mock_crud.get_issue_dir.return_value = issue_dir
        mock_config.show_issue_yaml = False

        files = get_issue_files("001")

        custom_file = files[0]
        assert custom_file["stage"] == ""
        assert custom_file["stage_color"] == ""
        assert custom_file["is_passed"] == "false"

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app._config")
    def test_get_issue_files_no_current_stage(self, mock_config, mock_crud, tmp_path):
        """Test that files have is_passed=false when no current_stage provided."""
        from agenttree.web.app import get_issue_files

        # Create test files
        issue_dir = tmp_path / "001-test"
        issue_dir.mkdir()
        (issue_dir / "problem.md").write_text("# Problem")

        mock_crud.get_issue_dir.return_value = issue_dir
        mock_config.show_issue_yaml = False
        mock_config.stage_color.return_value = "#aaa"
        mock_config.get_stage_names.return_value = []

        # No current_stage provided
        files = get_issue_files("001")

        problem_file = files[0]
        assert problem_file["is_passed"] == "false"

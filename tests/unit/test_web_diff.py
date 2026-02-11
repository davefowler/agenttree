"""Tests for diff API endpoint."""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path

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
def mock_issue_with_worktree():
    """Create a mock issue with worktree."""
    mock = Mock()
    mock.id = "001"
    mock.title = "Test Issue"
    mock.stage = "implement.review"
    mock.labels = []
    mock.assigned_agent = "1"
    mock.pr_url = "https://github.com/test/repo/pull/123"
    mock.pr_number = 123
    mock.worktree_dir = "/tmp/test-worktree"
    mock.created = "2024-01-01T00:00:00Z"
    mock.updated = "2024-01-01T00:00:00Z"
    mock.dependencies = []
    mock.priority = Priority.MEDIUM
    mock.flow = "default"
    return mock


@pytest.fixture
def mock_issue_no_worktree():
    """Create a mock issue without worktree."""
    mock = Mock()
    mock.id = "002"
    mock.title = "Test Issue No Worktree"
    mock.stage = "backlog"
    mock.labels = []
    mock.assigned_agent = None
    mock.pr_url = None
    mock.pr_number = None
    mock.worktree_dir = None
    mock.created = "2024-01-01T00:00:00Z"
    mock.updated = "2024-01-01T00:00:00Z"
    mock.dependencies = []
    mock.priority = Priority.MEDIUM
    mock.flow = "default"
    return mock


class TestGetDiffEndpoint:
    """Tests for /api/issues/{issue_id}/diff endpoint."""

    @patch("agenttree.web.app.Path.exists")
    @patch("subprocess.run")
    @patch("agenttree.web.app.issue_crud")
    def test_get_diff_returns_diff_output(
        self, mock_crud, mock_run, mock_exists, client, mock_issue_with_worktree
    ):
        """Test endpoint returns git diff output for valid issue with worktree."""
        mock_crud.get_issue.return_value = mock_issue_with_worktree
        mock_exists.return_value = True

        # Mock git diff output
        diff_output = """diff --git a/file.py b/file.py
index 1234567..abcdefg 100644
--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
 def hello():
+    print("Hello world")
     pass
"""
        stat_output = " file.py | 1 +\n 1 file changed, 1 insertion(+)\n"

        mock_run.side_effect = [
            Mock(returncode=0, stdout=diff_output, stderr=""),  # git diff
            Mock(returncode=0, stdout=stat_output, stderr=""),  # git diff --stat
        ]

        response = client.get("/api/issues/001/diff")

        assert response.status_code == 200
        data = response.json()
        assert "diff" in data
        assert data["has_changes"] is True
        assert "file.py" in data["diff"]

    @patch("agenttree.web.app.issue_crud")
    def test_get_diff_no_worktree_returns_empty(
        self, mock_crud, client, mock_issue_no_worktree
    ):
        """Test endpoint returns empty/message when issue has no worktree."""
        mock_crud.get_issue.return_value = mock_issue_no_worktree

        response = client.get("/api/issues/002/diff")

        assert response.status_code == 200
        data = response.json()
        assert data["has_changes"] is False
        assert data["diff"] == ""
        assert "no worktree" in data.get("error", "").lower() or data["diff"] == ""

    @patch("agenttree.web.app.issue_crud")
    def test_get_diff_invalid_issue_returns_404(self, mock_crud, client):
        """Test endpoint returns 404 for non-existent issue."""
        mock_crud.get_issue.return_value = None

        response = client.get("/api/issues/999/diff")

        assert response.status_code == 404

    @patch("agenttree.web.app.Path.exists")
    @patch("subprocess.run")
    @patch("agenttree.web.app.issue_crud")
    def test_get_diff_no_changes_returns_empty(
        self, mock_crud, mock_run, mock_exists, client, mock_issue_with_worktree
    ):
        """Test endpoint handles case where branch has no changes from main."""
        mock_crud.get_issue.return_value = mock_issue_with_worktree
        mock_exists.return_value = True

        # Empty diff output means no changes
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),  # git diff (empty)
            Mock(returncode=0, stdout="", stderr=""),  # git diff --stat (empty)
        ]

        response = client.get("/api/issues/001/diff")

        assert response.status_code == 200
        data = response.json()
        assert data["has_changes"] is False
        assert data["diff"] == ""

    @patch("agenttree.web.app.Path.exists")
    @patch("subprocess.run")
    @patch("agenttree.web.app.issue_crud")
    def test_get_diff_timeout_handling(
        self, mock_crud, mock_run, mock_exists, client, mock_issue_with_worktree
    ):
        """Test endpoint handles git command timeout gracefully."""
        import subprocess

        mock_crud.get_issue.return_value = mock_issue_with_worktree
        mock_exists.return_value = True
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=5)

        response = client.get("/api/issues/001/diff")

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "timed out" in data["error"].lower()

    @patch("agenttree.web.app.Path.exists")
    @patch("subprocess.run")
    @patch("agenttree.web.app.issue_crud")
    def test_get_diff_large_output_truncated(
        self, mock_crud, mock_run, mock_exists, client, mock_issue_with_worktree
    ):
        """Test diff output is truncated at 200KB with warning."""
        mock_crud.get_issue.return_value = mock_issue_with_worktree
        mock_exists.return_value = True

        # Create output larger than 200KB
        large_diff = "+" + "x" * 250_000  # 250KB of content

        mock_run.side_effect = [
            Mock(returncode=0, stdout=large_diff, stderr=""),  # git diff
            Mock(returncode=0, stdout="100 files changed", stderr=""),  # git diff --stat
        ]

        response = client.get("/api/issues/001/diff")

        assert response.status_code == 200
        data = response.json()
        assert data["truncated"] is True
        assert len(data["diff"]) <= 204_800  # 200KB limit

    @patch("agenttree.web.app.Path.exists")
    @patch("agenttree.web.app.issue_crud")
    def test_get_diff_deleted_worktree_handles_gracefully(
        self, mock_crud, mock_exists, client, mock_issue_with_worktree
    ):
        """Test graceful handling when worktree path doesn't exist."""
        mock_crud.get_issue.return_value = mock_issue_with_worktree
        mock_exists.return_value = False  # Worktree doesn't exist

        response = client.get("/api/issues/001/diff")

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert "not found" in data["error"].lower() or "not exist" in data["error"].lower()

"""Unit tests for attachment handling in web API."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from io import BytesIO

# Skip all tests if web dependencies aren't installed
pytest.importorskip("fastapi")
pytest.importorskip("httpx")


class TestCreateIssueApiWithAttachments:
    """Tests for create_issue_api with file uploads."""

    @pytest.fixture
    def mock_issue(self):
        """Create a mock issue for testing."""
        issue = MagicMock()
        issue.id = "999"
        issue.title = "Test Issue"
        return issue

    @pytest.fixture
    def client(self):
        """Create a test client for the web app."""
        from starlette.testclient import TestClient
        from agenttree.web.app import app
        return TestClient(app)

    def test_accepts_files(self, client, mock_issue):
        """Verify endpoint accepts multipart form with files."""
        with patch("agenttree.web.app.issue_crud.create_issue", return_value=mock_issue), \
             patch("agenttree.web.app.start_agent"):

            response = client.post(
                "/api/issues",
                data={"description": "Test description", "title": "Test"},
                files=[("files", ("test.png", b"fake image data", "image/png"))],
            )

            assert response.status_code == 200
            assert response.json()["ok"] is True

    def test_rejects_oversized_file(self, client, mock_issue):
        """Verify 400 error for files > 10MB."""
        # Create a file larger than 10MB
        large_content = b"x" * (11 * 1024 * 1024)  # 11MB

        with patch("agenttree.web.app.issue_crud.create_issue", return_value=mock_issue), \
             patch("agenttree.web.app.start_agent"):

            response = client.post(
                "/api/issues",
                data={"description": "Test description", "title": "Test"},
                files=[("files", ("large.png", large_content, "image/png"))],
            )

            assert response.status_code == 400
            assert "10MB" in response.json()["detail"] or "size" in response.json()["detail"].lower()

    def test_rejects_invalid_file_type(self, client, mock_issue):
        """Verify 400 error for executable files."""
        with patch("agenttree.web.app.issue_crud.create_issue", return_value=mock_issue), \
             patch("agenttree.web.app.start_agent"):

            response = client.post(
                "/api/issues",
                data={"description": "Test description", "title": "Test"},
                files=[("files", ("malware.exe", b"fake exe", "application/octet-stream"))],
            )

            assert response.status_code == 400
            assert "type" in response.json()["detail"].lower() or "allowed" in response.json()["detail"].lower()


class TestGetAttachment:
    """Tests for attachment serving endpoint."""

    @pytest.fixture
    def client(self):
        """Create a test client for the web app."""
        from starlette.testclient import TestClient
        from agenttree.web.app import app
        return TestClient(app)

    @pytest.fixture
    def mock_issue_with_attachment(self, tmp_path):
        """Create a mock issue directory with an attachment."""
        issue_dir = tmp_path / "_agenttree" / "issues" / "999-test-issue"
        attachments_dir = issue_dir / "attachments"
        attachments_dir.mkdir(parents=True)

        # Create a test attachment
        test_file = attachments_dir / "1234567890_screenshot.png"
        test_file.write_bytes(b"fake image content")

        return issue_dir

    def test_returns_file(self, client, mock_issue_with_attachment):
        """Verify attachment serving endpoint returns file content."""
        with patch("agenttree.web.app.get_issue_dir", return_value=mock_issue_with_attachment):
            response = client.get("/api/issues/999/attachments/1234567890_screenshot.png")

            assert response.status_code == 200
            assert response.content == b"fake image content"

    def test_404_for_missing_file(self, client, mock_issue_with_attachment):
        """Verify 404 for non-existent attachments."""
        with patch("agenttree.web.app.get_issue_dir", return_value=mock_issue_with_attachment):
            response = client.get("/api/issues/999/attachments/nonexistent.png")

            assert response.status_code == 404

    def test_404_for_invalid_issue(self, client):
        """Verify 404 for invalid issue ID."""
        with patch("agenttree.web.app.get_issue_dir", return_value=None):
            response = client.get("/api/issues/999/attachments/test.png")

            assert response.status_code == 404

    def test_prevents_path_traversal(self, client, mock_issue_with_attachment):
        """Verify path traversal attempts are blocked."""
        with patch("agenttree.web.app.get_issue_dir", return_value=mock_issue_with_attachment):
            response = client.get("/api/issues/999/attachments/../../../etc/passwd")

            # Should return 404 or 400, not the file content
            assert response.status_code in (400, 404)

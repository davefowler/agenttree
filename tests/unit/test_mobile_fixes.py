"""Tests for mobile UI fix: start agent endpoint error responses."""

import pytest
from unittest.mock import AsyncMock, patch

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from starlette.testclient import TestClient

from agenttree.web.app import app


@pytest.fixture
def client():
    return TestClient(app)


class TestStartIssueErrorResponses:
    """Verify /api/issues/{id}/start returns structured error details."""

    @patch("agenttree.web.routes.issues.asyncio")
    def test_start_nonexistent_issue_returns_404_with_detail(self, mock_asyncio, client):
        """404 response includes a 'detail' field for client display."""
        from agenttree.api import IssueNotFoundError

        mock_asyncio.to_thread = AsyncMock(side_effect=IssueNotFoundError("Issue #999 not found"))

        response = client.post("/api/issues/999/start")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "999" in data["detail"]

    @patch("agenttree.web.routes.issues.asyncio")
    def test_start_failure_returns_500_with_detail(self, mock_asyncio, client):
        """500 response includes a 'detail' field with error message."""
        from agenttree.api import AgentStartError

        mock_asyncio.to_thread = AsyncMock(side_effect=AgentStartError(999, "Container failed to start"))

        response = client.post("/api/issues/999/start")

        assert response.status_code == 500
        data = response.json()
        assert "detail" in data
        assert "Container failed to start" in data["detail"]

    @patch("agenttree.web.routes.issues.asyncio")
    def test_start_success_returns_ok(self, mock_asyncio, client):
        """Successful start returns ok status."""
        mock_asyncio.to_thread = AsyncMock(return_value=None)

        response = client.post("/api/issues/42/start")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    @patch("agenttree.web.routes.issues.asyncio")
    def test_start_generic_error_returns_500_with_detail(self, mock_asyncio, client):
        """Generic exceptions also return detail field."""
        mock_asyncio.to_thread = AsyncMock(side_effect=RuntimeError("Unexpected error"))

        response = client.post("/api/issues/999/start")

        assert response.status_code == 500
        data = response.json()
        assert "detail" in data
        assert "Unexpected error" in data["detail"]

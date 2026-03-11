"""Tests for voice endpoints used by mobile voice mode."""

import pytest
from unittest.mock import AsyncMock, Mock, patch

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

# Requires _agenttree/issues directory and OPENAI_API_KEY — local only
pytestmark = pytest.mark.local_only

from starlette.testclient import TestClient

from agenttree.web.app import app


@pytest.fixture
def client():
    return TestClient(app)


class TestVoiceTokenEndpoint:
    """Tests for /api/voice/token."""

    @patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False)
    def test_token_returns_400_without_api_key(self, client):
        """Token endpoint returns 400 when OPENAI_API_KEY is not set."""
        response = client.get("/api/voice/token")
        assert response.status_code == 400
        assert "OPENAI_API_KEY" in response.json()["detail"]

    @patch("agenttree.web.routes.voice.httpx.AsyncClient")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"}, clear=False)
    def test_token_returns_session_data(self, mock_httpx_class, client):
        """Token endpoint returns session data from OpenAI."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "client_secret": {"value": "eph_test_key"},
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_class.return_value = mock_client

        response = client.get("/api/voice/token")
        assert response.status_code == 200
        data = response.json()
        assert "client_secret" in data
        assert data["client_secret"]["value"] == "eph_test_key"

    @patch("agenttree.web.routes.voice.httpx.AsyncClient")
    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"}, clear=False)
    def test_token_returns_502_on_openai_error(self, mock_httpx_class, client):
        """Token endpoint returns 502 when OpenAI API fails."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx_class.return_value = mock_client

        response = client.get("/api/voice/token")
        assert response.status_code == 502


class TestVoiceToolCallEndpoint:
    """Tests for /api/voice/tool-call."""

    @patch("agenttree.mcp_server.status")
    def test_tool_call_status(self, mock_status, client):
        """Tool call dispatches 'status' correctly."""
        mock_status.return_value = "All agents running"

        response = client.post(
            "/api/voice/tool-call",
            json={"name": "status", "arguments": {}},
        )
        assert response.status_code == 200
        assert response.json()["result"] == "All agents running"
        mock_status.assert_called_once()

    @patch("agenttree.mcp_server.get_issue")
    def test_tool_call_get_issue(self, mock_get_issue, client):
        """Tool call dispatches 'get_issue' with correct args."""
        mock_get_issue.return_value = "Issue #42: Fix bug"

        response = client.post(
            "/api/voice/tool-call",
            json={"name": "get_issue", "arguments": {"issue_id": 42}},
        )
        assert response.status_code == 200
        assert "Issue #42" in response.json()["result"]
        mock_get_issue.assert_called_once_with(42)

    def test_tool_call_unknown_tool(self, client):
        """Unknown tool names return an error message."""
        response = client.post(
            "/api/voice/tool-call",
            json={"name": "nonexistent_tool", "arguments": {}},
        )
        assert response.status_code == 200
        assert "Unknown tool" in response.json()["result"]

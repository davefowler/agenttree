"""Tests for voice widget: navigate tool definition and has_openai_key context passing."""

import pytest
from unittest.mock import patch, MagicMock

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

pytestmark = pytest.mark.local_only

from starlette.testclient import TestClient

from agenttree.web.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestNavigateToolDefinition:
    """Verify the navigate tool is included in voice session tools."""

    def test_navigate_tool_in_voice_route_tools(self) -> None:
        """The navigate tool should be defined in the tools list in voice.py."""
        from agenttree.web.routes import voice as voice_module
        import inspect

        source = inspect.getsource(voice_module.voice_token)
        assert '"navigate"' in source
        assert '"url"' in source

    def test_navigate_tool_call_returns_client_side_message(
        self, client: TestClient
    ) -> None:
        """The navigate tool call endpoint should return a client-side message."""
        response = client.post(
            "/api/voice/tool-call",
            json={"name": "navigate", "arguments": {"url": "/kanban?issue=42"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert "client-side" in data["result"].lower()


class TestHasOpenaiKeyContext:
    """Verify has_openai_key is passed to kanban and flow page contexts."""

    @patch("agenttree.web.app.get_kanban_board")
    def test_kanban_passes_has_openai_key_true(
        self,
        mock_board: MagicMock,
        client: TestClient,
    ) -> None:
        """Kanban page should pass has_openai_key=True when env var is set."""
        mock_board.return_value = {}
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            response = client.get("/kanban")
        assert response.status_code == 200
        assert "voice-widget-btn" in response.text

    @patch("agenttree.web.app.get_kanban_board")
    def test_kanban_hides_voice_without_key(
        self,
        mock_board: MagicMock,
        client: TestClient,
    ) -> None:
        """Kanban page should hide voice widget when OPENAI_API_KEY not set."""
        mock_board.return_value = {}
        with patch.dict("os.environ", {}, clear=True):
            response = client.get("/kanban")
        assert response.status_code == 200
        assert "voice-widget-btn" not in response.text

    @patch("agenttree.web.app._get_flow_issues")
    def test_flow_passes_has_openai_key_true(
        self,
        mock_flow: MagicMock,
        client: TestClient,
    ) -> None:
        """Flow page should pass has_openai_key=True when env var is set."""
        mock_flow.return_value = []
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            response = client.get("/flow")
        assert response.status_code == 200
        assert "voice-widget-btn" in response.text

    @patch("agenttree.web.app._get_flow_issues")
    def test_flow_hides_voice_without_key(
        self,
        mock_flow: MagicMock,
        client: TestClient,
    ) -> None:
        """Flow page should hide voice widget when OPENAI_API_KEY not set."""
        mock_flow.return_value = []
        with patch.dict("os.environ", {}, clear=True):
            response = client.get("/flow")
        assert response.status_code == 200
        assert "voice-widget-btn" not in response.text

"""Tests for agenttree.mcp_server module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agenttree.mcp_server import (
    status,
    get_issue,
    get_agent_output,
    send_message,
    create_issue,
    approve,
    start_agent,
    stop_agent,
    _get_repo_path,
)


@pytest.fixture
def mock_config():
    """Create a mock config."""
    config = MagicMock()
    config.get_issue_session_patterns.return_value = ["proj-issue-042"]
    config.stage_display_name.side_effect = lambda s: s.replace(".", " > ")
    config.is_human_review.return_value = False
    config.is_parking_lot.return_value = False
    return config


@pytest.fixture
def mock_issue():
    """Create a mock issue."""
    issue = MagicMock()
    issue.id = 42
    issue.title = "Fix the widget"
    issue.stage = "implement.code"
    issue.flow = "default"
    issue.priority = MagicMock(value="medium")
    issue.pr_url = None
    issue.branch = "feature-42"
    issue.labels = []
    issue.dependencies = []
    return issue


class TestGetRepoPath:
    def test_uses_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTTREE_REPO_PATH", "/custom/path")
        assert _get_repo_path() == Path("/custom/path")

    def test_defaults_to_cwd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENTTREE_REPO_PATH", raising=False)
        result = _get_repo_path()
        assert result == Path.cwd()


class TestStatus:
    def test_status_no_issues(self, mock_config: MagicMock) -> None:
        with (
            patch("agenttree.config.load_config", return_value=mock_config),
            patch("agenttree.issues.list_issues", return_value=[]),
            patch("agenttree.mcp_server._get_repo_path", return_value=Path("/tmp")),
        ):
            result = status()
            assert result == "No issues found. The board is empty."

    def test_status_with_active_issue(
        self, mock_config: MagicMock, mock_issue: MagicMock
    ) -> None:
        mock_session = MagicMock()
        mock_session.name = "proj-issue-042"

        with (
            patch("agenttree.config.load_config", return_value=mock_config),
            patch("agenttree.issues.list_issues", return_value=[mock_issue]),
            patch("agenttree.mcp_server._get_repo_path", return_value=Path("/tmp")),
            patch(
                "agenttree.tmux.list_sessions",
                return_value=[mock_session],
            ),
        ):
            result = status()
            assert "#42" in result
            assert "Fix the widget" in result
            assert "running" in result

    def test_status_with_review_issue(
        self, mock_config: MagicMock, mock_issue: MagicMock
    ) -> None:
        mock_config.is_human_review.return_value = True
        mock_issue.stage = "implement.review"

        with (
            patch("agenttree.config.load_config", return_value=mock_config),
            patch("agenttree.issues.list_issues", return_value=[mock_issue]),
            patch("agenttree.mcp_server._get_repo_path", return_value=Path("/tmp")),
            patch("agenttree.tmux.list_sessions", return_value=[]),
        ):
            result = status()
            assert "NEEDS YOUR REVIEW" in result
            assert "#42" in result

    def test_status_tmux_not_available(
        self, mock_config: MagicMock, mock_issue: MagicMock
    ) -> None:
        with (
            patch("agenttree.config.load_config", return_value=mock_config),
            patch("agenttree.issues.list_issues", return_value=[mock_issue]),
            patch("agenttree.mcp_server._get_repo_path", return_value=Path("/tmp")),
            patch(
                "agenttree.tmux.list_sessions",
                side_effect=FileNotFoundError("tmux not found"),
            ),
        ):
            result = status()
            assert "stopped" in result
            assert "#42" in result


class TestGetIssue:
    def test_issue_not_found(self, mock_config: MagicMock) -> None:
        with (
            patch("agenttree.config.load_config", return_value=mock_config),
            patch("agenttree.issues.get_issue", return_value=None),
            patch("agenttree.mcp_server._get_repo_path", return_value=Path("/tmp")),
        ):
            result = get_issue(99)
            assert "not found" in result

    def test_issue_found(
        self, mock_config: MagicMock, mock_issue: MagicMock
    ) -> None:
        with (
            patch("agenttree.config.load_config", return_value=mock_config),
            patch("agenttree.issues.get_issue", return_value=mock_issue),
            patch("agenttree.mcp_server._get_repo_path", return_value=Path("/tmp")),
            patch("agenttree.issues.get_issue_dir", return_value=None),
        ):
            result = get_issue(42)
            assert "#42" in result
            assert "Fix the widget" in result
            assert "feature-42" in result

    def test_issue_with_problem_file(
        self, mock_config: MagicMock, mock_issue: MagicMock, tmp_path: Path
    ) -> None:
        problem_file = tmp_path / "problem.md"
        problem_file.write_text("This widget is broken and needs fixing.")

        with (
            patch("agenttree.config.load_config", return_value=mock_config),
            patch("agenttree.issues.get_issue", return_value=mock_issue),
            patch("agenttree.mcp_server._get_repo_path", return_value=Path("/tmp")),
            patch("agenttree.issues.get_issue_dir", return_value=tmp_path),
        ):
            result = get_issue(42)
            assert "broken and needs fixing" in result

    def test_issue_long_description_truncated(
        self, mock_config: MagicMock, mock_issue: MagicMock, tmp_path: Path
    ) -> None:
        problem_file = tmp_path / "problem.md"
        problem_file.write_text("x" * 1000)

        with (
            patch("agenttree.config.load_config", return_value=mock_config),
            patch("agenttree.issues.get_issue", return_value=mock_issue),
            patch("agenttree.mcp_server._get_repo_path", return_value=Path("/tmp")),
            patch("agenttree.issues.get_issue_dir", return_value=tmp_path),
        ):
            result = get_issue(42)
            assert result.endswith("...")
            assert len(result) < 1000


class TestGetAgentOutput:
    def test_no_active_session(self, mock_config: MagicMock) -> None:
        with (
            patch("agenttree.config.load_config", return_value=mock_config),
            patch("agenttree.mcp_server._get_repo_path", return_value=Path("/tmp")),
            patch("agenttree.tmux.session_exists", return_value=False),
        ):
            result = get_agent_output(42)
            assert "No active agent" in result

    def test_with_active_session(self, mock_config: MagicMock) -> None:
        with (
            patch("agenttree.config.load_config", return_value=mock_config),
            patch("agenttree.mcp_server._get_repo_path", return_value=Path("/tmp")),
            patch("agenttree.tmux.session_exists", return_value=True),
            patch(
                "agenttree.tmux.capture_pane",
                return_value="Working on fix...\nDone.",
            ),
        ):
            result = get_agent_output(42)
            assert "Agent output" in result
            assert "Working on fix" in result


class TestSendMessage:
    def test_send_success(self) -> None:
        with patch("agenttree.api.send_message", return_value="sent"):
            result = send_message(42, "Hello agent")
            assert "Message sent" in result

    def test_send_no_agent(self) -> None:
        with patch("agenttree.api.send_message", return_value="no_agent"):
            result = send_message(42, "Hello")
            assert "No agent running" in result

    def test_send_issue_not_found(self) -> None:
        from agenttree.api import IssueNotFoundError

        with patch(
            "agenttree.api.send_message",
            side_effect=IssueNotFoundError("042"),
        ):
            result = send_message(42, "Hello")
            assert "not found" in result


class TestCreateIssue:
    def test_title_too_short(self) -> None:
        result = create_issue("Short", "x" * 60)
        assert "at least 10 characters" in result

    def test_description_too_short(self) -> None:
        result = create_issue("A proper title", "Too short")
        assert "at least 50 characters" in result

    def test_create_success(self, mock_issue: MagicMock) -> None:
        with (
            patch("agenttree.issues.create_issue", return_value=mock_issue),
            patch("agenttree.api.start_agent"),
        ):
            result = create_issue(
                "Fix the broken widget",
                "The widget is broken and needs to be fixed. It crashes on startup with an error.",
            )
            assert "Created issue #42" in result
            assert "Agent started" in result

    def test_create_issue_fails(self) -> None:
        with patch(
            "agenttree.issues.create_issue",
            side_effect=RuntimeError("disk full"),
        ):
            result = create_issue(
                "Fix the broken widget",
                "The widget is broken and needs to be fixed. It crashes on startup with an error.",
            )
            assert "Failed to create" in result
            assert "disk full" in result


class TestApprove:
    def test_issue_not_found(self, mock_config: MagicMock) -> None:
        with (
            patch("agenttree.config.load_config", return_value=mock_config),
            patch("agenttree.issues.get_issue", return_value=None),
            patch("agenttree.mcp_server._get_repo_path", return_value=Path("/tmp")),
        ):
            result = approve(99)
            assert "not found" in result

    def test_not_review_stage(
        self, mock_config: MagicMock, mock_issue: MagicMock
    ) -> None:
        mock_config.is_human_review.return_value = False

        with (
            patch("agenttree.config.load_config", return_value=mock_config),
            patch("agenttree.issues.get_issue", return_value=mock_issue),
            patch("agenttree.mcp_server._get_repo_path", return_value=Path("/tmp")),
        ):
            result = approve(42)
            assert "not a review stage" in result

    def test_approve_success(
        self, mock_config: MagicMock, mock_issue: MagicMock
    ) -> None:
        mock_config.is_human_review.return_value = True
        mock_config.get_next_stage.return_value = ("implement.setup", None)

        with (
            patch("agenttree.config.load_config", return_value=mock_config),
            patch("agenttree.issues.get_issue", return_value=mock_issue),
            patch("agenttree.mcp_server._get_repo_path", return_value=Path("/tmp")),
            patch("agenttree.api.transition_issue"),
        ):
            result = approve(42)
            assert "Approved" in result


class TestStartAgent:
    def test_start_controller(self) -> None:
        with patch("agenttree.api.start_controller"):
            result = start_agent(0)
            assert "Controller started" in result

    def test_start_success(self) -> None:
        with patch("agenttree.api.start_agent"):
            result = start_agent(42)
            assert "Agent started" in result

    def test_issue_not_found(self) -> None:
        from agenttree.api import IssueNotFoundError

        with patch(
            "agenttree.api.start_agent",
            side_effect=IssueNotFoundError("042"),
        ):
            result = start_agent(42)
            assert "not found" in result

    def test_already_running(self) -> None:
        from agenttree.api import AgentAlreadyRunningError

        with patch(
            "agenttree.api.start_agent",
            side_effect=AgentAlreadyRunningError("042"),
        ):
            result = start_agent(42)
            assert "already running" in result


class TestStopAgent:
    def test_stop_success(self) -> None:
        with patch(
            "agenttree.api.stop_all_agents_for_issue", return_value=1
        ):
            result = stop_agent(42)
            assert "Stopped 1 agent" in result

    def test_stop_no_agents(self) -> None:
        with patch(
            "agenttree.api.stop_all_agents_for_issue", return_value=0
        ):
            result = stop_agent(42)
            assert "No active agents" in result

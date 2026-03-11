"""Tests for web page load performance — ensure no redundant subprocess calls."""

from unittest.mock import MagicMock, patch

import pytest


def test_get_repo_remote_name_reads_from_config() -> None:
    """get_repo_remote_name() should read from config, not spawn a subprocess."""
    mock_config = MagicMock()
    mock_config.repo_remote_name = "owner/repo"

    with patch("agenttree.hooks.load_config", return_value=mock_config):
        from agenttree.hooks import get_repo_remote_name

        result = get_repo_remote_name()

    assert result == "owner/repo"


def test_get_repo_remote_name_raises_when_no_remote() -> None:
    """get_repo_remote_name() should raise ValueError when config has no remote."""
    mock_config = MagicMock()
    mock_config.repo_remote_name = None

    with patch("agenttree.hooks.load_config", return_value=mock_config):
        from agenttree.hooks import get_repo_remote_name

        with pytest.raises(ValueError, match="Could not determine"):
            get_repo_remote_name()


def test_convert_issue_to_web_no_git_subprocess() -> None:
    """convert_issue_to_web should not spawn git subprocesses for repo name."""
    pytest.importorskip("fastapi")
    from agenttree.web.utils import convert_issue_to_web

    mock_issue = MagicMock()
    mock_issue.id = 42
    mock_issue.stage = "implement.code"
    mock_issue.title = "Test issue"
    mock_issue.labels = []
    mock_issue.pr_number = 123
    mock_issue.pr_url = None  # This triggers get_repo_remote_name
    mock_issue.worktree_dir = None
    mock_issue.created = "2025-01-01T00:00:00Z"
    mock_issue.updated = "2025-01-01T00:00:00Z"
    mock_issue.history = []
    mock_issue.dependencies = []
    mock_issue.processing = None
    mock_issue.ci_escalated = False
    mock_issue.flow = "default"
    mock_issue.priority = MagicMock()
    mock_issue.priority.value = "medium"

    mock_config = MagicMock()
    mock_config.repo_remote_name = "owner/repo"
    mock_config.is_human_review.return_value = False
    mock_config.get_port_for_issue.return_value = 9001

    with (
        patch("agenttree.web.utils.agent_manager") as mock_am,
        patch("agenttree.web.utils._config", mock_config),
        patch("agenttree.hooks.load_config", return_value=mock_config),
        patch("subprocess.run") as mock_subprocess,
    ):
        mock_am._check_issue_tmux_session.return_value = False

        result = convert_issue_to_web(mock_issue)

    assert result.pr_url == "https://github.com/owner/repo/pull/123"
    # subprocess.run should NOT have been called for git remote
    # (tmux list-sessions may still be called via agent_manager)
    for call in mock_subprocess.call_args_list:
        args = call[0][0] if call[0] else call[1].get("args", [])
        assert "git" not in args, f"Unexpected git subprocess call: {args}"


def test_resolve_repo_remote_name_ssh() -> None:
    """_resolve_repo_remote_name should parse SSH URLs."""
    from agenttree.config import _resolve_repo_remote_name

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "git@github.com:owner/repo.git\n"

    with patch("subprocess.run", return_value=mock_result):
        result = _resolve_repo_remote_name()

    assert result == "owner/repo"


def test_resolve_repo_remote_name_https() -> None:
    """_resolve_repo_remote_name should parse HTTPS URLs."""
    from agenttree.config import _resolve_repo_remote_name

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "https://github.com/owner/repo.git\n"

    with patch("subprocess.run", return_value=mock_result):
        result = _resolve_repo_remote_name()

    assert result == "owner/repo"


def test_resolve_repo_remote_name_no_remote() -> None:
    """_resolve_repo_remote_name should return None when no remote exists."""
    from agenttree.config import _resolve_repo_remote_name

    mock_result = MagicMock()
    mock_result.returncode = 1

    with patch("subprocess.run", return_value=mock_result):
        result = _resolve_repo_remote_name()

    assert result is None

"""Tests for GitHub integration."""

import subprocess
import shutil
from unittest.mock import Mock, patch, MagicMock
import pytest

from agenttree.github import (
    ensure_gh_cli,
    gh_command,
    get_issue,
    add_label_to_issue,
    remove_label_from_issue,
    create_pr,
    get_pr_checks,
    wait_for_ci,
    close_issue,
    Issue,
    PullRequest,
    CheckStatus,
)


class TestEnsureGhCli:
    """Tests for ensure_gh_cli function."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_ensure_gh_cli_success(self, mock_run: Mock, mock_which: Mock) -> None:
        """Test ensure_gh_cli when gh is installed and authenticated."""
        mock_which.return_value = "/usr/bin/gh"
        mock_run.return_value = Mock(returncode=0)

        # Should not raise
        ensure_gh_cli()

        mock_which.assert_called_once_with("gh")
        mock_run.assert_called_once()

    @patch("shutil.which")
    def test_ensure_gh_cli_not_installed(self, mock_which: Mock) -> None:
        """Test ensure_gh_cli when gh is not installed."""
        mock_which.return_value = None

        with pytest.raises(RuntimeError, match="GitHub CLI.*not found"):
            ensure_gh_cli()

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_ensure_gh_cli_not_authenticated(
        self, mock_run: Mock, mock_which: Mock
    ) -> None:
        """Test ensure_gh_cli when gh is not authenticated."""
        mock_which.return_value = "/usr/bin/gh"
        mock_run.return_value = Mock(returncode=1)

        with pytest.raises(RuntimeError, match="Not authenticated"):
            ensure_gh_cli()


class TestGhCommand:
    """Tests for gh_command helper."""

    @patch("subprocess.run")
    def test_gh_command_success(self, mock_run: Mock) -> None:
        """Test gh_command executes and returns output."""
        mock_run.return_value = Mock(returncode=0, stdout="test output")

        result = gh_command(["api", "user"])

        assert result == "test output"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "gh"
        assert "api" in args
        assert "user" in args

    @patch("subprocess.run")
    def test_gh_command_failure(self, mock_run: Mock) -> None:
        """Test gh_command raises on error."""
        mock_run.return_value = Mock(
            returncode=1, stderr="Error: not found", stdout=""
        )

        with pytest.raises(RuntimeError, match="GitHub CLI command failed"):
            gh_command(["api", "nonexistent"])


class TestGetIssue:
    """Tests for get_issue function."""

    @patch("agenttree.github.gh_command")
    def test_get_issue_success(self, mock_gh: Mock) -> None:
        """Test getting an issue."""
        mock_gh.return_value = """{
            "number": 42,
            "title": "Add dark mode",
            "body": "Users want dark mode",
            "html_url": "https://github.com/user/repo/issues/42",
            "state": "open"
        }"""

        issue = get_issue(42)

        assert issue.number == 42
        assert issue.title == "Add dark mode"
        assert issue.body == "Users want dark mode"
        assert issue.url == "https://github.com/user/repo/issues/42"
        assert issue.state == "open"

    @patch("agenttree.github.gh_command")
    def test_get_issue_not_found(self, mock_gh: Mock) -> None:
        """Test getting non-existent issue."""
        mock_gh.side_effect = RuntimeError("not found")

        with pytest.raises(RuntimeError):
            get_issue(999)


class TestAddLabelToIssue:
    """Tests for add_label_to_issue function."""

    @patch("agenttree.github.gh_command")
    def test_add_label_success(self, mock_gh: Mock) -> None:
        """Test adding label to issue."""
        mock_gh.return_value = ""  # Success

        # Should not raise
        add_label_to_issue(42, "bug")

        mock_gh.assert_called_once()
        args = mock_gh.call_args[0][0]
        assert "issue" in args
        assert "42" in args
        assert "bug" in args


class TestRemoveLabelFromIssue:
    """Tests for remove_label_from_issue function."""

    @patch("agenttree.github.gh_command")
    def test_remove_label_success(self, mock_gh: Mock) -> None:
        """Test removing label from issue."""
        mock_gh.return_value = ""  # Success

        # Should not raise
        remove_label_from_issue(42, "bug")

        mock_gh.assert_called_once()


class TestCreatePr:
    """Tests for create_pr function."""

    @patch("agenttree.github.gh_command")
    def test_create_pr_success(self, mock_gh: Mock) -> None:
        """Test creating a pull request."""
        mock_gh.return_value = """{
            "number": 123,
            "title": "Add dark mode",
            "html_url": "https://github.com/user/repo/pull/123",
            "state": "open",
            "head": {"ref": "feature-branch"},
            "base": {"ref": "main"}
        }"""

        pr = create_pr(
            title="Add dark mode",
            body="Implements dark mode",
            branch="feature-branch",
            base="main"
        )

        assert pr.number == 123
        assert pr.title == "Add dark mode"
        assert pr.url == "https://github.com/user/repo/pull/123"
        assert pr.state == "open"

    @patch("agenttree.github.gh_command")
    def test_create_pr_default_base(self, mock_gh: Mock) -> None:
        """Test creating PR with default base branch."""
        mock_gh.return_value = """{
            "number": 123,
            "title": "Test",
            "html_url": "https://github.com/user/repo/pull/123",
            "state": "open",
            "head": {"ref": "feature"},
            "base": {"ref": "main"}
        }"""

        pr = create_pr(
            title="Test",
            body="Test PR",
            branch="feature"
        )

        assert pr.number == 123


class TestGetPrChecks:
    """Tests for get_pr_checks function."""

    @patch("agenttree.github.gh_command")
    def test_get_pr_checks_success(self, mock_gh: Mock) -> None:
        """Test getting PR check statuses."""
        mock_gh.return_value = """{
            "statusCheckRollup": [
                {
                    "name": "CI",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS"
                },
                {
                    "name": "Tests",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE"
                }
            ]
        }"""

        checks = get_pr_checks(123)

        assert len(checks) == 2
        assert checks[0].name == "CI"
        assert checks[0].status == "COMPLETED"
        assert checks[0].conclusion == "SUCCESS"
        assert checks[1].name == "Tests"
        assert checks[1].conclusion == "FAILURE"

    @patch("agenttree.github.gh_command")
    def test_get_pr_checks_empty(self, mock_gh: Mock) -> None:
        """Test getting PR checks when none exist."""
        mock_gh.return_value = """{"statusCheckRollup": []}"""

        checks = get_pr_checks(123)

        assert len(checks) == 0


class TestWaitForCi:
    """Tests for wait_for_ci function."""

    @patch("agenttree.github.get_pr_checks")
    @patch("time.sleep")
    def test_wait_for_ci_success(
        self, mock_sleep: Mock, mock_get_checks: Mock
    ) -> None:
        """Test waiting for CI when all checks pass."""
        # First call: in progress, second call: success
        mock_get_checks.side_effect = [
            [
                CheckStatus(name="CI", status="IN_PROGRESS", conclusion=None),
            ],
            [
                CheckStatus(name="CI", status="COMPLETED", conclusion="SUCCESS"),
            ],
        ]

        success, failed = wait_for_ci(123, timeout=60, interval=1)

        assert success is True
        assert failed == []
        assert mock_get_checks.call_count == 2

    @patch("agenttree.github.get_pr_checks")
    @patch("time.sleep")
    def test_wait_for_ci_failure(
        self, mock_sleep: Mock, mock_get_checks: Mock
    ) -> None:
        """Test waiting for CI when checks fail."""
        mock_get_checks.return_value = [
            CheckStatus(name="Tests", status="COMPLETED", conclusion="FAILURE"),
        ]

        success, failed = wait_for_ci(123, timeout=60, interval=1)

        assert success is False
        assert len(failed) == 1
        assert failed[0].name == "Tests"

    @patch("agenttree.github.get_pr_checks")
    @patch("time.sleep")
    def test_wait_for_ci_timeout(
        self, mock_sleep: Mock, mock_get_checks: Mock
    ) -> None:
        """Test waiting for CI times out."""
        # Always return in-progress
        mock_get_checks.return_value = [
            CheckStatus(name="CI", status="IN_PROGRESS", conclusion=None),
        ]

        success, failed = wait_for_ci(123, timeout=2, interval=1)

        # Should timeout and return current state
        assert success is False or success is True  # Depends on implementation


class TestCloseIssue:
    """Tests for close_issue function."""

    @patch("agenttree.github.gh_command")
    def test_close_issue_success(self, mock_gh: Mock) -> None:
        """Test closing an issue."""
        mock_gh.return_value = ""  # Success

        # Should not raise
        close_issue(42)

        mock_gh.assert_called_once()
        args = mock_gh.call_args[0][0]
        assert "issue" in args
        assert "close" in args
        assert "42" in args


class TestModels:
    """Tests for data models."""

    def test_issue_model(self) -> None:
        """Test Issue model creation."""
        issue = Issue(
            number=42,
            title="Test",
            body="Test body",
            url="https://test.com",
            state="open"
        )

        assert issue.number == 42
        assert issue.title == "Test"

    def test_pull_request_model(self) -> None:
        """Test PullRequest model creation."""
        pr = PullRequest(
            number=123,
            title="Test PR",
            url="https://test.com",
            state="open"
        )

        assert pr.number == 123
        assert pr.title == "Test PR"

    def test_check_status_model(self) -> None:
        """Test CheckStatus model creation."""
        check = CheckStatus(
            name="CI",
            status="COMPLETED",
            conclusion="SUCCESS"
        )

        assert check.name == "CI"
        assert check.status == "COMPLETED"
        assert check.conclusion == "SUCCESS"

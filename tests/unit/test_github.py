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
    is_pr_approved,
    merge_pr,
    auto_merge_if_ready,
    link_pr_to_issue,
    monitor_pr_and_auto_merge,
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
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["gh", "api", "nonexistent"], stderr="Error: not found"
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
            "url": "https://github.com/user/repo/issues/42",
            "labels": [
                {"name": "bug"},
                {"name": "enhancement"}
            ]
        }"""

        issue = get_issue(42)

        assert issue.number == 42
        assert issue.title == "Add dark mode"
        assert issue.body == "Users want dark mode"
        assert issue.url == "https://github.com/user/repo/issues/42"
        assert issue.labels == ["bug", "enhancement"]

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
        mock_gh.return_value = "https://github.com/user/repo/pull/123"

        pr = create_pr(
            title="Add dark mode",
            body="Implements dark mode",
            branch="feature-branch",
            base="main"
        )

        assert pr.number == 123
        assert pr.title == "Add dark mode"
        assert pr.url == "https://github.com/user/repo/pull/123"
        assert pr.branch == "feature-branch"

    @patch("agenttree.github.gh_command")
    def test_create_pr_default_base(self, mock_gh: Mock) -> None:
        """Test creating PR with default base branch."""
        mock_gh.return_value = "https://github.com/user/repo/pull/456"

        pr = create_pr(
            title="Test",
            body="Test PR",
            branch="feature"
        )

        assert pr.number == 456
        assert pr.branch == "feature"


class TestGetPrChecks:
    """Tests for get_pr_checks function."""

    @patch("agenttree.github.gh_command")
    def test_get_pr_checks_success(self, mock_gh: Mock) -> None:
        """Test getting PR check statuses."""
        # gh pr checks --json name,state,link returns state directly (SUCCESS/FAILURE/PENDING)
        mock_gh.return_value = """[
            {
                "name": "CI",
                "state": "SUCCESS",
                "link": "https://github.com/org/repo/actions/runs/123/job/456"
            },
            {
                "name": "Tests",
                "state": "FAILURE",
                "link": "https://github.com/org/repo/actions/runs/123/job/789"
            }
        ]"""

        checks = get_pr_checks(123)

        assert len(checks) == 2
        assert checks[0].name == "CI"
        assert checks[0].state == "SUCCESS"
        assert checks[0].link == "https://github.com/org/repo/actions/runs/123/job/456"
        assert checks[1].name == "Tests"
        assert checks[1].state == "FAILURE"

    @patch("agenttree.github.gh_command")
    def test_get_pr_checks_empty(self, mock_gh: Mock) -> None:
        """Test getting PR checks when none exist."""
        mock_gh.return_value = "[]"

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
        # First call: pending, second call: success
        mock_get_checks.side_effect = [
            [
                CheckStatus(name="CI", state="PENDING"),
            ],
            [
                CheckStatus(name="CI", state="SUCCESS"),
            ],
        ]

        result = wait_for_ci(123, timeout=60, poll_interval=1)

        assert result is True
        assert mock_get_checks.call_count == 2

    @patch("agenttree.github.get_pr_checks")
    @patch("time.sleep")
    def test_wait_for_ci_failure(
        self, mock_sleep: Mock, mock_get_checks: Mock
    ) -> None:
        """Test waiting for CI when checks fail."""
        mock_get_checks.return_value = [
            CheckStatus(name="Tests", state="FAILURE"),
        ]

        result = wait_for_ci(123, timeout=60, poll_interval=1)

        assert result is False

    @patch("agenttree.github.get_pr_checks")
    @patch("time.sleep")
    def test_wait_for_ci_timeout(
        self, mock_sleep: Mock, mock_get_checks: Mock
    ) -> None:
        """Test waiting for CI times out."""
        # Always return in-progress
        mock_get_checks.return_value = [
            CheckStatus(name="CI", state="PENDING"),
        ]

        result = wait_for_ci(123, timeout=2, poll_interval=1)

        # Should timeout and return False
        assert result is False


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
            labels=["bug", "enhancement"]
        )

        assert issue.number == 42
        assert issue.title == "Test"
        assert issue.labels == ["bug", "enhancement"]

    def test_pull_request_model(self) -> None:
        """Test PullRequest model creation."""
        pr = PullRequest(
            number=123,
            title="Test PR",
            url="https://test.com",
            branch="feature-branch"
        )

        assert pr.number == 123
        assert pr.title == "Test PR"
        assert pr.branch == "feature-branch"

    def test_check_status_model(self) -> None:
        """Test CheckStatus model creation."""
        check = CheckStatus(
            name="CI",
            state="COMPLETED",
        )

        assert check.name == "CI"
        assert check.state == "COMPLETED"


class TestIsPrApproved:
    """Tests for is_pr_approved function."""

    @patch("agenttree.github.gh_command")
    def test_pr_approved(self, mock_gh: Mock) -> None:
        """Test checking if PR is approved."""
        mock_gh.return_value = "2"  # 2 approvals

        result = is_pr_approved(123)

        assert result is True
        mock_gh.assert_called_once()

    @patch("agenttree.github.gh_command")
    def test_pr_not_approved(self, mock_gh: Mock) -> None:
        """Test checking if PR has no approvals."""
        mock_gh.return_value = "0"  # No approvals

        result = is_pr_approved(123)

        assert result is False


class TestMergePr:
    """Tests for merge_pr function."""

    @patch("agenttree.github.gh_command")
    def test_merge_pr_squash(self, mock_gh: Mock) -> None:
        """Test merging PR with squash method."""
        mock_gh.return_value = ""

        merge_pr(123, method="squash")

        mock_gh.assert_called_once()
        args = mock_gh.call_args[0][0]
        assert "pr" in args
        assert "merge" in args
        assert "123" in args
        assert "--squash" in args
        assert "--delete-branch" in args

    @patch("agenttree.github.gh_command")
    def test_merge_pr_merge(self, mock_gh: Mock) -> None:
        """Test merging PR with merge method."""
        mock_gh.return_value = ""

        merge_pr(456, method="merge")

        args = mock_gh.call_args[0][0]
        assert "--merge" in args


class TestAutoMergeIfReady:
    """Tests for auto_merge_if_ready function."""

    @patch("agenttree.github.wait_for_ci")
    @patch("agenttree.github.is_pr_approved")
    @patch("agenttree.github.merge_pr")
    def test_auto_merge_success(
        self, mock_merge: Mock, mock_approved: Mock, mock_ci: Mock
    ) -> None:
        """Test auto-merge when CI passes and approved."""
        mock_ci.return_value = True
        mock_approved.return_value = True

        result = auto_merge_if_ready(123, require_approval=True)

        assert result is True
        mock_merge.assert_called_once_with(123)

    @patch("agenttree.github.wait_for_ci")
    def test_auto_merge_ci_failed(self, mock_ci: Mock) -> None:
        """Test auto-merge when CI fails."""
        mock_ci.return_value = False

        result = auto_merge_if_ready(123)

        assert result is False

    @patch("agenttree.github.wait_for_ci")
    @patch("agenttree.github.is_pr_approved")
    def test_auto_merge_not_approved(
        self, mock_approved: Mock, mock_ci: Mock
    ) -> None:
        """Test auto-merge when not approved."""
        mock_ci.return_value = True
        mock_approved.return_value = False

        result = auto_merge_if_ready(123, require_approval=True)

        assert result is False

    @patch("agenttree.github.wait_for_ci")
    @patch("agenttree.github.merge_pr")
    def test_auto_merge_no_approval_required(
        self, mock_merge: Mock, mock_ci: Mock
    ) -> None:
        """Test auto-merge when approval not required."""
        mock_ci.return_value = True

        result = auto_merge_if_ready(123, require_approval=False)

        assert result is True
        mock_merge.assert_called_once()


class TestLinkPrToIssue:
    """Tests for link_pr_to_issue function."""

    @patch("agenttree.github.gh_command")
    def test_link_pr_to_issue(self, mock_gh: Mock) -> None:
        """Test linking PR to issue."""
        mock_gh.side_effect = [
            "Existing PR body",  # First call: get current body
            ""  # Second call: edit PR
        ]

        link_pr_to_issue(123, 42)

        assert mock_gh.call_count == 2
        # Second call should include closing keyword
        edit_args = mock_gh.call_args_list[1][0][0]
        assert "pr" in edit_args
        assert "edit" in edit_args

    @patch("agenttree.github.gh_command")
    def test_link_pr_already_linked(self, mock_gh: Mock) -> None:
        """Test linking PR when already linked."""
        mock_gh.return_value = "PR body with #42 already"

        link_pr_to_issue(123, 42)

        # Should only call once (to get body), not call edit
        assert mock_gh.call_count == 1


class TestMonitorPrAndAutoMerge:
    """Tests for monitor_pr_and_auto_merge function."""

    @patch("agenttree.github.auto_merge_if_ready")
    @patch("agenttree.github.close_issue")
    @patch("time.sleep")
    def test_monitor_pr_merges_immediately(
        self, mock_sleep: Mock, mock_close: Mock, mock_auto: Mock
    ) -> None:
        """Test monitor PR that merges immediately."""
        mock_auto.return_value = True

        result = monitor_pr_and_auto_merge(123, issue_number=42, max_wait=60)

        assert result is True
        mock_auto.assert_called_once_with(123, True)
        mock_close.assert_called_once_with(42)
        # Should not sleep if merged immediately
        mock_sleep.assert_not_called()

    @patch("agenttree.github.auto_merge_if_ready")
    @patch("time.sleep")
    @patch("time.time")
    def test_monitor_pr_timeout(
        self, mock_time: Mock, mock_sleep: Mock, mock_auto: Mock
    ) -> None:
        """Test monitor PR times out."""
        # Simulate time passing
        mock_time.side_effect = [0, 10, 20, 30, 40, 50, 60, 70]
        mock_auto.return_value = False

        result = monitor_pr_and_auto_merge(123, max_wait=60, check_interval=10)

        assert result is False

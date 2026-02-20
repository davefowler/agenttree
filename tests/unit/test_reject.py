"""Tests for reject functionality."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agenttree.issues import Issue


@pytest.fixture
def mock_issue():
    """Create a mock issue at implement.review stage."""
    return Issue(
        id="42",
        slug="test-issue",
        title="Test",
        stage="implement.review",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
        pr_number=123,
        pr_url="https://github.com/org/repo/pull/123",
    )


@pytest.fixture
def mock_issue_plan_review():
    """Create a mock issue at plan.review stage."""
    return Issue(
        id="42",
        slug="test-issue",
        title="Test",
        stage="plan.review",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )


@pytest.fixture
def mock_issue_not_review():
    """Create a mock issue not at a review stage."""
    return Issue(
        id="42",
        slug="test-issue",
        title="Test",
        stage="implement.code",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )


class TestRejectValidation:
    """Tests for reject command validation."""

    def test_rejects_from_implementation_review_to_implement(self, cli_runner, mock_issue):
        """Should move from implement.review to implement.code stage."""
        from agenttree.cli import main

        # Create updated issue that api.reject_issue would return
        updated_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
            with patch("agenttree.api.reject_issue", return_value=updated_issue) as mock_reject:
                result = cli_runner.invoke(main, ["reject", "42"])

        assert result.exit_code == 0
        assert "implement.code" in result.output.lower()
        mock_reject.assert_called_once_with("42", None)

    def test_rejects_from_plan_review_to_plan_revise(self, cli_runner, mock_issue_plan_review):
        """Should move from plan.review to plan.revise stage."""
        from agenttree.cli import main

        updated_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="plan.revise",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
            with patch("agenttree.api.reject_issue", return_value=updated_issue) as mock_reject:
                result = cli_runner.invoke(main, ["reject", "42"])

        assert result.exit_code == 0
        assert "plan.revise" in result.output.lower()
        mock_reject.assert_called_once_with("42", None)

    def test_rejects_non_review_stage(self, cli_runner, mock_issue_not_review):
        """Should error when not at a review stage."""
        from agenttree.cli import main

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
            with patch("agenttree.api.reject_issue") as mock_reject:
                mock_reject.side_effect = ValueError("Issue is at 'implement.code', not a human review stage")
                result = cli_runner.invoke(main, ["reject", "42"])

        assert result.exit_code == 1
        assert "not a human review stage" in result.output.lower()

    def test_rejects_in_container(self, cli_runner):
        """Should error when running in container."""
        from agenttree.cli import main

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=True):
            result = cli_runner.invoke(main, ["reject", "42"])

        assert result.exit_code == 1
        assert "container" in result.output.lower()


class TestRejectWithMessage:
    """Tests for reject command with message."""

    def test_reject_with_message(self, cli_runner, mock_issue):
        """Should send feedback message to agent."""
        from agenttree.cli import main

        updated_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
            with patch("agenttree.api.reject_issue", return_value=updated_issue) as mock_reject:
                result = cli_runner.invoke(main, ["reject", "42", "-m", "Fix the tests"])

        assert result.exit_code == 0
        mock_reject.assert_called_once_with("42", "Fix the tests")


class TestRejectStateUpdates:
    """Tests for reject command state updates (testing the API function)."""

    def test_updates_stage(self, tmp_path):
        """Should update issue.yaml stage correctly."""
        from agenttree.api import reject_issue, REJECT_TARGET_STAGES

        # Setup test issue directory
        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test"
        issue_dir.mkdir(parents=True)
        yaml_path = issue_dir / "issue.yaml"
        yaml_path.write_text(yaml.dump({
            "id": "42",
            "slug": "test",
            "title": "Test",
            "stage": "implement.review",
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "history": [],
        }))

        # Mock dependencies
        mock_config = MagicMock()
        mock_config.is_human_review.return_value = True

        mock_issue = Issue(
            id="42", slug="test", title="Test", stage="implement.review",
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
        )
        mock_updated_issue = Issue(
            id="42", slug="test", title="Test", stage="implement.code",
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", side_effect=[mock_issue, mock_updated_issue]):
                with patch("agenttree.issues.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.issues.get_agenttree_path", return_value=tmp_path / "_agenttree"):
                        with patch("agenttree.agents_repo.sync_agents_repo"):
                            with patch("agenttree.api._notify_agent"):
                                result = reject_issue("42")

        assert result.stage == "implement.code"
        # Verify YAML was updated
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["stage"] == "implement.code"

    def test_adds_reject_history_entry(self, tmp_path):
        """Should add history entry with type='reject'."""
        from agenttree.api import reject_issue

        # Setup test issue directory
        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test"
        issue_dir.mkdir(parents=True)
        yaml_path = issue_dir / "issue.yaml"
        yaml_path.write_text(yaml.dump({
            "id": "42",
            "slug": "test",
            "title": "Test",
            "stage": "implement.review",
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "history": [],
        }))

        mock_config = MagicMock()
        mock_config.is_human_review.return_value = True

        mock_issue = Issue(
            id="42", slug="test", title="Test", stage="implement.review",
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
        )
        mock_updated_issue = Issue(
            id="42", slug="test", title="Test", stage="implement.code",
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", side_effect=[mock_issue, mock_updated_issue]):
                with patch("agenttree.issues.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.issues.get_agenttree_path", return_value=tmp_path / "_agenttree"):
                        with patch("agenttree.agents_repo.sync_agents_repo"):
                            with patch("agenttree.api._notify_agent"):
                                reject_issue("42")

        # Verify history entry
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert len(data["history"]) == 1
        assert data["history"][0]["type"] == "reject"
        assert data["history"][0]["stage"] == "implement.code"

    def test_preserves_pr_metadata(self, tmp_path):
        """Should NOT clear PR metadata (unlike rollback)."""
        from agenttree.api import reject_issue

        # Setup test issue directory with PR metadata
        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test"
        issue_dir.mkdir(parents=True)
        yaml_path = issue_dir / "issue.yaml"
        yaml_path.write_text(yaml.dump({
            "id": "42",
            "slug": "test",
            "title": "Test",
            "stage": "implement.review",
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "history": [],
            "pr_number": 123,
            "pr_url": "https://github.com/org/repo/pull/123",
        }))

        mock_config = MagicMock()
        mock_config.is_human_review.return_value = True

        mock_issue = Issue(
            id="42", slug="test", title="Test", stage="implement.review",
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
            pr_number=123, pr_url="https://github.com/org/repo/pull/123",
        )
        mock_updated_issue = Issue(
            id="42", slug="test", title="Test", stage="implement.code",
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
            pr_number=123, pr_url="https://github.com/org/repo/pull/123",
        )

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", side_effect=[mock_issue, mock_updated_issue]):
                with patch("agenttree.issues.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.issues.get_agenttree_path", return_value=tmp_path / "_agenttree"):
                        with patch("agenttree.agents_repo.sync_agents_repo"):
                            with patch("agenttree.api._notify_agent"):
                                reject_issue("42")

        # Verify PR metadata is preserved
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["pr_number"] == 123
        assert data["pr_url"] == "https://github.com/org/repo/pull/123"


class TestRejectAgentNotification:
    """Tests for agent notification."""

    def test_notifies_running_agent(self, tmp_path):
        """Should call _notify_agent with message."""
        from agenttree.api import reject_issue

        # Setup test issue directory
        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test"
        issue_dir.mkdir(parents=True)
        yaml_path = issue_dir / "issue.yaml"
        yaml_path.write_text(yaml.dump({
            "id": "42",
            "slug": "test",
            "title": "Test",
            "stage": "implement.review",
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "history": [],
        }))

        mock_config = MagicMock()
        mock_config.is_human_review.return_value = True

        mock_issue = Issue(
            id="42", slug="test", title="Test", stage="implement.review",
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
        )
        mock_updated_issue = Issue(
            id="42", slug="test", title="Test", stage="implement.code",
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", side_effect=[mock_issue, mock_updated_issue]):
                with patch("agenttree.issues.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.issues.get_agenttree_path", return_value=tmp_path / "_agenttree"):
                        with patch("agenttree.agents_repo.sync_agents_repo"):
                            with patch("agenttree.api._notify_agent") as mock_notify:
                                reject_issue("42", "Please fix the tests")

        # Verify notification was called with feedback message
        mock_notify.assert_called_once()
        call_args = mock_notify.call_args
        assert "42" == call_args[0][0]
        assert "Please fix the tests" in call_args[0][1]

    def test_handles_agent_not_running(self, tmp_path):
        """Should not error if agent is not running (_notify_agent handles this)."""
        from agenttree.api import reject_issue

        # Setup test issue directory
        issue_dir = tmp_path / "_agenttree" / "issues" / "042-test"
        issue_dir.mkdir(parents=True)
        yaml_path = issue_dir / "issue.yaml"
        yaml_path.write_text(yaml.dump({
            "id": "42",
            "slug": "test",
            "title": "Test",
            "stage": "implement.review",
            "created": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
            "history": [],
        }))

        mock_config = MagicMock()
        mock_config.is_human_review.return_value = True

        mock_issue = Issue(
            id="42", slug="test", title="Test", stage="implement.review",
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
        )
        mock_updated_issue = Issue(
            id="42", slug="test", title="Test", stage="implement.code",
            created="2026-01-01T00:00:00Z", updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", side_effect=[mock_issue, mock_updated_issue]):
                with patch("agenttree.issues.get_issue_dir", return_value=issue_dir):
                    with patch("agenttree.issues.get_agenttree_path", return_value=tmp_path / "_agenttree"):
                        with patch("agenttree.agents_repo.sync_agents_repo"):
                            with patch("agenttree.api._notify_agent"):
                                # Should not raise even if agent not running
                                result = reject_issue("42")

        assert result.stage == "implement.code"

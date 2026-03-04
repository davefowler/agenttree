"""Tests for agenttree.api reset_issue() and reimplement_issue()."""

from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest

from agenttree.api import reset_issue, reimplement_issue, IssueNotFoundError
from agenttree.issues import Issue, HistoryEntry


@pytest.fixture
def issue_dir(tmp_path):
    """Create an issue directory with generated docs."""
    d = tmp_path / "issues" / "042"
    d.mkdir(parents=True)

    # Create generated files
    (d / "problem.md").write_text("# Problem")
    (d / "research.md").write_text("# Research")
    (d / "spec.md").write_text("# Spec")
    (d / "spec_review.md").write_text("# Spec Review")
    (d / "review.md").write_text("# Review")
    (d / "independent_review.md").write_text("# Independent Review")
    (d / "feedback.md").write_text("# Feedback")

    return d


@pytest.fixture
def mock_issue(issue_dir):
    """Create a mock issue with YAML file."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue = Issue(
        id=42,
        slug="test-issue",
        title="Test Issue",
        stage="implement.code",
        flow="default",
        branch="issue-042-test-issue",
        worktree_dir="/tmp/worktrees/042-test-issue",
        pr_number=123,
        pr_url="https://github.com/test/repo/pull/123",
        created=now,
        updated=now,
        ci_escalated=True,
        agent_ensured="implement.code",
        manager_hooks_executed="implement.ci_wait",
        history=[
            HistoryEntry(stage="explore.define", timestamp=now),
            HistoryEntry(stage="explore.research", timestamp=now),
            HistoryEntry(stage="plan.draft", timestamp=now),
            HistoryEntry(stage="plan.review", timestamp=now),
            HistoryEntry(stage="implement.setup", timestamp=now),
            HistoryEntry(stage="implement.code", timestamp=now),
        ],
    )
    yaml_path = issue_dir / "issue.yaml"
    issue._yaml_path = yaml_path
    issue.save()
    return issue


def _patch_reset(mock_issue, issue_dir):
    """Return a context manager that patches all deps for reset/reimplement."""
    from contextlib import contextmanager

    @contextmanager
    def ctx():
        with patch("agenttree.ids.parse_issue_id", return_value=42), \
             patch("agenttree.issues.get_issue", return_value=mock_issue), \
             patch("agenttree.api.stop_all_agents_for_issue"), \
             patch("agenttree.api._remove_issue_worktree"), \
             patch("agenttree.api._delete_issue_branch"), \
             patch("agenttree.issues.get_issue_dir", return_value=issue_dir), \
             patch("agenttree.issues.delete_session"):
            yield

    return ctx()


class TestResetIssue:
    """Tests for reset_issue()."""

    def test_reset_not_found_raises(self):
        with patch("agenttree.ids.parse_issue_id", return_value=999), \
             patch("agenttree.issues.get_issue", return_value=None):
            with pytest.raises(IssueNotFoundError):
                reset_issue(999, quiet=True)

    def test_reset_clears_all_files(self, mock_issue, issue_dir):
        """Reset should remove all generated files except issue.yaml."""
        with _patch_reset(mock_issue, issue_dir):
            reset_issue(42, quiet=True)

        remaining = [f.name for f in issue_dir.iterdir() if not f.name.startswith(".")]
        assert remaining == ["issue.yaml"]

    def test_reset_resets_yaml_state(self, mock_issue, issue_dir):
        """Reset should reset issue.yaml to backlog with clean state."""
        with _patch_reset(mock_issue, issue_dir):
            reset_issue(42, quiet=True)

        reloaded = Issue.from_yaml(issue_dir / "issue.yaml")
        assert reloaded.stage == "backlog"
        assert reloaded.branch is None
        assert reloaded.worktree_dir is None
        assert reloaded.pr_number is None
        assert reloaded.pr_url is None
        assert reloaded.ci_escalated is False
        assert reloaded.agent_ensured is None
        assert reloaded.manager_hooks_executed is None
        assert len(reloaded.history) == 1
        assert reloaded.history[0].type == "reset"

    def test_reset_stops_agents(self, mock_issue, issue_dir):
        """Reset should call stop_all_agents_for_issue."""
        with patch("agenttree.ids.parse_issue_id", return_value=42), \
             patch("agenttree.issues.get_issue", return_value=mock_issue), \
             patch("agenttree.api.stop_all_agents_for_issue") as mock_stop, \
             patch("agenttree.api._remove_issue_worktree"), \
             patch("agenttree.api._delete_issue_branch"), \
             patch("agenttree.issues.get_issue_dir", return_value=issue_dir), \
             patch("agenttree.issues.delete_session"):

            reset_issue(42, quiet=True)

        mock_stop.assert_called_once_with(42, quiet=True)


class TestReimplementIssue:
    """Tests for reimplement_issue()."""

    def test_reimplement_not_found_raises(self):
        with patch("agenttree.ids.parse_issue_id", return_value=999), \
             patch("agenttree.issues.get_issue", return_value=None):
            with pytest.raises(IssueNotFoundError):
                reimplement_issue(999, quiet=True)

    def test_reimplement_keeps_plan_files(self, mock_issue, issue_dir):
        """Reimplement should keep problem.md, research.md, spec.md, spec_review.md."""
        with _patch_reset(mock_issue, issue_dir):
            reimplement_issue(42, quiet=True)

        remaining = sorted(f.name for f in issue_dir.iterdir() if not f.name.startswith("."))
        assert "issue.yaml" in remaining
        assert "problem.md" in remaining
        assert "research.md" in remaining
        assert "spec.md" in remaining
        assert "spec_review.md" in remaining
        assert "review.md" not in remaining
        assert "independent_review.md" not in remaining
        assert "feedback.md" not in remaining

    def test_reimplement_resets_to_implement_setup(self, mock_issue, issue_dir):
        """Reimplement should set stage to implement.setup."""
        with _patch_reset(mock_issue, issue_dir):
            reimplement_issue(42, quiet=True)

        reloaded = Issue.from_yaml(issue_dir / "issue.yaml")
        assert reloaded.stage == "implement.setup"
        assert reloaded.branch is None
        assert reloaded.pr_number is None

    def test_reimplement_keeps_pre_implement_history(self, mock_issue, issue_dir):
        """Reimplement should keep history up to plan stages, drop implement history."""
        with _patch_reset(mock_issue, issue_dir):
            reimplement_issue(42, quiet=True)

        reloaded = Issue.from_yaml(issue_dir / "issue.yaml")
        stages = [h.stage for h in reloaded.history]
        assert "explore.define" in stages
        assert "plan.review" in stages
        assert "implement.setup" in stages  # reimplement entry
        assert "implement.code" not in stages  # dropped


class TestNudgeConfig:
    """Tests for nudge_agents config option."""

    def test_ensure_stage_agents_skips_when_nudge_disabled(self, tmp_path):
        """ensure_stage_agents should be a no-op when nudge_agents is False."""
        from agenttree.actions import ensure_stage_agents

        mock_config = MagicMock()
        mock_config.manager.nudge_agents = False

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.issues.list_issues") as mock_list:

            ensure_stage_agents(tmp_path)

        mock_list.assert_not_called()

    def test_check_stalled_agents_skips_when_nudge_disabled(self, tmp_path):
        """check_stalled_agents should be a no-op when nudge_agents is False."""
        from agenttree.actions import check_stalled_agents

        mock_config = MagicMock()
        mock_config.manager.nudge_agents = False

        with patch("agenttree.config.load_config", return_value=mock_config), \
             patch("agenttree.issues.list_issues") as mock_list:

            check_stalled_agents(tmp_path)

        mock_list.assert_not_called()

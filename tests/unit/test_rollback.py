"""Tests for rollback functionality."""

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner


@pytest.fixture
def cli_runner():
    """Create a Click test runner."""
    return CliRunner()


@pytest.fixture
def mock_config():
    """Create a mock config with stage definitions."""
    from agenttree.config import Config, StageConfig, SubstageConfig

    config = Config(
        project="testproject",
        stages={
            "backlog": StageConfig(name="backlog"),
            "explore": StageConfig(name="explore", substages={
                "define": SubstageConfig(name="define", output="problem.md"),
                "research": SubstageConfig(name="research", output="research.md"),
            }),
            "plan": StageConfig(name="plan", substages={
                "draft": SubstageConfig(name="draft", output="spec.md"),
                "assess": SubstageConfig(name="assess", output="spec_review.md"),
                "revise": SubstageConfig(name="revise", output="spec.md"),
                "review": SubstageConfig(name="review", human_review=True),
            }),
            "implement": StageConfig(name="implement", substages={
                "code": SubstageConfig(name="code"),
                "code_review": SubstageConfig(name="code_review", output="review.md"),
                "address_review": SubstageConfig(name="address_review"),
                "wrapup": SubstageConfig(name="wrapup"),
                "feedback": SubstageConfig(name="feedback", output="feedback.md"),
                "review": SubstageConfig(name="review", human_review=True),
            }),
            "accepted": StageConfig(name="accepted", is_parking_lot=True),
            "not_doing": StageConfig(name="not_doing", is_parking_lot=True, redirect_only=True),
        },
    )
    return config


@pytest.fixture
def temp_issue_dir(tmp_path):
    """Create a temporary issue directory with sample files."""
    issues_dir = tmp_path / "_agenttree" / "issues" / "042-test-issue"
    issues_dir.mkdir(parents=True)

    # Create issue.yaml
    issue_data = {
        "id": "42",
        "slug": "test-issue",
        "title": "Test Issue",
        "stage": "implement.code",
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-01T00:00:00Z",
        "history": [],
        "labels": [],
        "priority": "medium",
    }
    yaml_path = issues_dir / "issue.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(issue_data, f)

    # Create output files
    (issues_dir / "problem.md").write_text("# Problem\nTest problem")
    (issues_dir / "research.md").write_text("# Research\nTest research")
    (issues_dir / "spec.md").write_text("# Spec\nTest spec")
    (issues_dir / "spec_review.md").write_text("# Review\nTest review")
    (issues_dir / "review.md").write_text("# Code Review\nTest code review")

    return issues_dir


class TestGetOutputFilesAfterStage:
    """Tests for get_output_files_after_stage function."""

    def test_after_research_returns_plan_and_later_files(self, mock_config):
        """Given stage explore.research, should return files from plan and later stages."""
        from agenttree.issues import get_output_files_after_stage

        with patch("agenttree.config.load_config", return_value=mock_config):
            files = get_output_files_after_stage("explore.research")

        # After explore.research: plan.draft (spec.md), plan.selfcheck (spec_review.md),
        # implement.code_review (review.md), implement.feedback (feedback.md)
        assert "spec.md" in files
        assert "spec_review.md" in files
        assert "review.md" in files
        assert "feedback.md" in files
        assert "research.md" not in files
        assert "problem.md" not in files

    def test_after_plan_returns_later_files(self, mock_config):
        """Given stage plan.draft, should return files from plan.selfcheck and later."""
        from agenttree.issues import get_output_files_after_stage

        with patch("agenttree.config.load_config", return_value=mock_config):
            files = get_output_files_after_stage("plan.draft")

        assert "spec_review.md" in files
        assert "review.md" in files
        assert "feedback.md" in files
        # spec.md may or may not be included depending on flow config
        assert "research.md" not in files

    def test_after_implement_returns_empty(self, mock_config):
        """Given stage implement.review, should return empty (no files after)."""
        from agenttree.issues import get_output_files_after_stage

        with patch("agenttree.config.load_config", return_value=mock_config):
            files = get_output_files_after_stage("implement.review")

        # Only terminal stages after implement.review, none have output
        assert files == []

    def test_invalid_stage_raises_error(self, mock_config):
        """Given invalid stage name, should raise ValueError."""
        from agenttree.issues import get_output_files_after_stage

        with patch("agenttree.config.load_config", return_value=mock_config):
            with pytest.raises(ValueError, match="Unknown stage"):
                get_output_files_after_stage("nonexistent_stage")

    def test_deduplicates_files(self, mock_config):
        """Should deduplicate files that appear in multiple stages."""
        from agenttree.issues import get_output_files_after_stage

        # Multiple stages may output spec.md
        with patch("agenttree.config.load_config", return_value=mock_config):
            files = get_output_files_after_stage("explore.define")

        # Count occurrences of spec.md
        spec_count = sum(1 for f in files if f == "spec.md")
        assert spec_count == 1


class TestArchiveIssueFiles:
    """Tests for archive_issue_files function."""

    def test_moves_existing_files_to_archive(self, temp_issue_dir):
        """Should move existing files to archive directory with timestamp."""
        from agenttree.issues import archive_issue_files

        files_to_archive = ["spec.md", "spec_review.md"]

        with patch("agenttree.issues.get_issue_dir", return_value=temp_issue_dir):
            archived = archive_issue_files("42", files_to_archive)

        # Files should be moved to archive/
        archive_dir = temp_issue_dir / "archive"
        assert archive_dir.exists()

        # Original files should be gone
        assert not (temp_issue_dir / "spec.md").exists()
        assert not (temp_issue_dir / "spec_review.md").exists()

        # Archived files should exist with timestamp prefix
        archive_files = list(archive_dir.iterdir())
        assert len(archive_files) == 2
        archived_names = [f.name for f in archive_files]
        assert any("spec.md" in name for name in archived_names)
        assert any("spec_review.md" in name for name in archived_names)

        # Return value should list archived files
        assert len(archived) == 2

    def test_creates_archive_directory_if_needed(self, temp_issue_dir):
        """Should create archive directory if it doesn't exist."""
        from agenttree.issues import archive_issue_files

        with patch("agenttree.issues.get_issue_dir", return_value=temp_issue_dir):
            archive_issue_files("42", ["spec.md"])

        assert (temp_issue_dir / "archive").is_dir()

    def test_skips_nonexistent_files_silently(self, temp_issue_dir):
        """Should skip files that don't exist without error."""
        from agenttree.issues import archive_issue_files

        with patch("agenttree.issues.get_issue_dir", return_value=temp_issue_dir):
            archived = archive_issue_files("42", ["nonexistent.md", "spec.md"])

        # Only spec.md should be archived
        assert len(archived) == 1
        assert "spec.md" in archived[0]

    def test_uses_timestamp_prefix_for_collisions(self, temp_issue_dir):
        """Should use timestamp prefix to avoid name collisions."""
        from agenttree.issues import archive_issue_files

        # Create archive dir and a pre-existing archived file
        archive_dir = temp_issue_dir / "archive"
        archive_dir.mkdir()
        (archive_dir / "20260101000000-spec.md").write_text("old version")

        with patch("agenttree.issues.get_issue_dir", return_value=temp_issue_dir):
            archived = archive_issue_files("42", ["spec.md"])

        # Should create new file with different timestamp
        archive_files = list(archive_dir.iterdir())
        assert len(archive_files) == 2  # Old + new

    def test_returns_empty_list_for_no_existing_files(self, temp_issue_dir):
        """Should return empty list when no files exist to archive."""
        from agenttree.issues import archive_issue_files

        with patch("agenttree.issues.get_issue_dir", return_value=temp_issue_dir):
            archived = archive_issue_files("42", ["nonexistent1.md", "nonexistent2.md"])

        assert archived == []


class TestRollbackValidation:
    """Tests for rollback command validation."""

    def test_rejects_invalid_stage_name(self, cli_runner, mock_config, temp_issue_dir):
        """Should error for invalid stage name."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test",
            title="Test",
            stage="implement.code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["rollback", "42", "invalid_stage", "-y"])

        assert result.exit_code == 1
        assert "Invalid stage" in result.output or "Unknown stage" in result.output

    def test_rejects_terminal_stages(self, cli_runner, mock_config, temp_issue_dir):
        """Should error for terminal stages (accepted, not_doing)."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test",
            title="Test",
            stage="implement.code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["rollback", "42", "accepted", "-y"])

        assert result.exit_code == 1
        assert "terminal" in result.output.lower() or "Cannot rollback" in result.output

    def test_rejects_rollback_forward(self, cli_runner, mock_config, temp_issue_dir):
        """Should error when target stage is ahead of current stage."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test",
            title="Test",
            stage="explore.research",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["rollback", "42", "implement.code", "-y"])

        assert result.exit_code == 1
        # The message says target stage is "not before" current stage
        assert "not before" in result.output.lower() or "cannot rollback" in result.output.lower() or "backwards" in result.output.lower()

    def test_rejects_rollback_in_container(self, cli_runner, mock_config):
        """Should error when running inside a container."""
        from agenttree.cli import main

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.is_running_in_container", return_value=True):
                result = cli_runner.invoke(main, ["rollback", "42", "research", "-y"])

        assert result.exit_code == 1
        assert "container" in result.output.lower()


class TestRollbackUpdatesState:
    """Tests for rollback state updates (CLI delegates to execute_rollback)."""

    def test_updates_stage(self, cli_runner, mock_config, temp_issue_dir):
        """Should call execute_rollback with correct params."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.rollback.execute_rollback", return_value=True) as mock_rb:
                            result = cli_runner.invoke(main, ["rollback", "42", "plan.draft", "-y"])

        assert result.exit_code == 0
        mock_rb.assert_called_once_with(
            issue_id=42,
            target_stage="plan.draft",
            yes=True,
            reset_worktree=False,
            keep_changes=False,
        )

    def test_clears_pr_metadata(self, cli_runner, mock_config, temp_issue_dir):
        """Should pass correct params when rolling back from implement.review."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
            pr_number=123,
            pr_url="https://github.com/org/repo/pull/123",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.rollback.execute_rollback", return_value=True) as mock_rb:
                            result = cli_runner.invoke(main, ["rollback", "42", "implement.code", "-y"])

        assert result.exit_code == 0
        mock_rb.assert_called_once()


class TestRollbackHandlesAgent:
    """Tests for agent cleanup during rollback."""

    def test_kills_running_agent(self, cli_runner, mock_config, temp_issue_dir):
        """Should call execute_rollback (which handles agent cleanup)."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.rollback.execute_rollback", return_value=True) as mock_rb:
                            result = cli_runner.invoke(main, ["rollback", "42", "explore.research", "-y"])

        assert result.exit_code == 0
        # Agent cleanup is handled inside execute_rollback
        mock_rb.assert_called_once()


class TestRollbackWorktreeReset:
    """Tests for worktree reset during rollback."""

    def test_reset_worktree_passes_flag(self, cli_runner, mock_config, temp_issue_dir):
        """With --reset-worktree, should pass flag to execute_rollback."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.rollback.execute_rollback", return_value=True) as mock_rb:
                            result = cli_runner.invoke(
                                main, ["rollback", "42", "explore.research", "-y", "--reset-worktree"]
                            )

        assert result.exit_code == 0
        mock_rb.assert_called_once_with(
            issue_id=42,
            target_stage="explore.research",
            yes=True,
            reset_worktree=True,
            keep_changes=False,
        )

    def test_keep_changes_passes_flag(self, cli_runner, mock_config, temp_issue_dir):
        """With --keep-changes, should pass flag to execute_rollback."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.rollback.execute_rollback", return_value=True) as mock_rb:
                            result = cli_runner.invoke(main, ["rollback", "42", "plan.draft", "-y", "--keep-changes"])

        assert result.exit_code == 0
        mock_rb.assert_called_once_with(
            issue_id=42,
            target_stage="plan.draft",
            yes=True,
            reset_worktree=False,
            keep_changes=True,
        )


class TestRollbackCLIIntegration:
    """Integration tests for rollback CLI command."""

    def test_requires_confirmation_without_yes_flag(self, cli_runner, mock_config, temp_issue_dir):
        """Should require confirmation when --yes flag not provided."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            # Send 'n' to decline confirmation
                            result = cli_runner.invoke(main, ["rollback", "42", "explore.research"], input="n\n")

        # Should prompt for confirmation and abort (Cancelled or Aborted)
        assert "Cancelled" in result.output or "Aborted" in result.output or result.exit_code != 0

    def test_shows_preview_before_confirmation(self, cli_runner, mock_config, temp_issue_dir):
        """Should show what will be archived before asking for confirmation."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            result = cli_runner.invoke(main, ["rollback", "42", "explore.research"], input="n\n")

        # Should show files to archive or the target stage
        assert "spec.md" in result.output or "research" in result.output

    def test_successful_rollback_message(self, cli_runner, mock_config, temp_issue_dir):
        """Should show success message after rollback."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.workflow.load_config", return_value=mock_config):
            with patch("agenttree.cli.workflow.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.workflow.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.workflow.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.cli.workflow.delete_session"):
                            with patch("agenttree.agents_repo.sync_agents_repo"):
                                with patch("agenttree.state.get_active_agent", return_value=None):
                                    result = cli_runner.invoke(main, ["rollback", "42", "explore.research", "-y"])

        assert result.exit_code == 0
        assert "research" in result.output.lower() or "rolled back" in result.output.lower()


class TestRollbackMaxIterations:
    """Tests for max_rollbacks parameter in execute_rollback."""

    def test_rollback_succeeds_under_limit(self, mock_config, temp_issue_dir):
        """Rollback succeeds when history has fewer rollbacks to target stage than max."""
        from agenttree.rollback import execute_rollback
        from agenttree.issues import Issue

        # Create issue with 2 rollbacks to code_review in history
        yaml_path = temp_issue_dir / "issue.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        data["stage"] = "implement.address_review"
        data["history"] = [
            {"stage": "implement.code_review", "timestamp": "2026-01-01T00:00:00Z", "type": "rollback"},
            {"stage": "implement.code_review", "timestamp": "2026-01-01T01:00:00Z", "type": "rollback"},
        ]
        with open(yaml_path, "w") as f:
            yaml.dump(data, f)

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.address_review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
            history=data["history"],
        )

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", return_value=mock_issue):
                with patch("agenttree.issues.get_issue_dir", return_value=temp_issue_dir):
                    with patch("agenttree.issues.delete_session"):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            with patch("agenttree.state.unregister_agent"):
                                # max_rollbacks=5, history has 2 rollbacks - should succeed
                                result = execute_rollback(
                                    "42",
                                    "implement.code_review",
                                    yes=True,
                                    skip_sync=True,
                                    max_rollbacks=5,
                                )

        assert result is True

    def test_rollback_fails_at_limit(self, mock_config, temp_issue_dir):
        """Rollback fails when history has max rollbacks to target stage."""
        from agenttree.rollback import execute_rollback
        from agenttree.issues import Issue

        # Create issue with 5 rollbacks to code_review in history
        yaml_path = temp_issue_dir / "issue.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        data["stage"] = "implement.address_review"
        data["history"] = [
            {"stage": "implement.code_review", "timestamp": "2026-01-01T00:00:00Z", "type": "rollback"},
            {"stage": "implement.code_review", "timestamp": "2026-01-01T01:00:00Z", "type": "rollback"},
            {"stage": "implement.code_review", "timestamp": "2026-01-01T02:00:00Z", "type": "rollback"},
            {"stage": "implement.code_review", "timestamp": "2026-01-01T03:00:00Z", "type": "rollback"},
            {"stage": "implement.code_review", "timestamp": "2026-01-01T04:00:00Z", "type": "rollback"},
        ]
        with open(yaml_path, "w") as f:
            yaml.dump(data, f)

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.address_review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
            history=data["history"],
        )

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", return_value=mock_issue):
                with patch("agenttree.issues.get_issue_dir", return_value=temp_issue_dir):
                    with patch("agenttree.issues.delete_session"):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            with patch("agenttree.state.unregister_agent"):
                                # max_rollbacks=5, history has 5 rollbacks - should fail
                                result = execute_rollback(
                                    "42",
                                    "implement.code_review",
                                    yes=True,
                                    skip_sync=True,
                                    max_rollbacks=5,
                                )

        assert result is False

    def test_rollback_counts_only_matching_target_stage(self, mock_config, temp_issue_dir):
        """Rollbacks to different stages don't count toward limit."""
        from agenttree.rollback import execute_rollback
        from agenttree.issues import Issue

        # Create issue with rollbacks to different stages
        yaml_path = temp_issue_dir / "issue.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        data["stage"] = "implement.address_review"
        data["history"] = [
            {"stage": "implement.code_review", "timestamp": "2026-01-01T00:00:00Z", "type": "rollback"},
            {"stage": "explore.define", "timestamp": "2026-01-01T01:00:00Z", "type": "rollback"},
            {"stage": "plan.draft", "timestamp": "2026-01-01T02:00:00Z", "type": "rollback"},
            {"stage": "implement.code", "timestamp": "2026-01-01T03:00:00Z", "type": "rollback"},
        ]
        with open(yaml_path, "w") as f:
            yaml.dump(data, f)

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.address_review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
            history=data["history"],
        )

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", return_value=mock_issue):
                with patch("agenttree.issues.get_issue_dir", return_value=temp_issue_dir):
                    with patch("agenttree.issues.delete_session"):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            with patch("agenttree.state.unregister_agent"):
                                # max_rollbacks=2, but only 1 rollback to code_review - should succeed
                                result = execute_rollback(
                                    "42",
                                    "implement.code_review",
                                    yes=True,
                                    skip_sync=True,
                                    max_rollbacks=2,
                                )

        assert result is True

    def test_rollback_no_limit_when_max_not_specified(self, mock_config, temp_issue_dir):
        """Rollback has no limit when max_rollbacks is None."""
        from agenttree.rollback import execute_rollback
        from agenttree.issues import Issue

        # Create issue with many rollbacks to code_review
        yaml_path = temp_issue_dir / "issue.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        data["stage"] = "implement.address_review"
        data["history"] = [
            {"stage": "implement.code_review", "timestamp": f"2026-01-01T{i:02d}:00:00Z", "type": "rollback"}
            for i in range(10)
        ]
        with open(yaml_path, "w") as f:
            yaml.dump(data, f)

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement.address_review",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
            history=data["history"],
        )

        with patch("agenttree.config.load_config", return_value=mock_config):
            with patch("agenttree.issues.get_issue", return_value=mock_issue):
                with patch("agenttree.issues.get_issue_dir", return_value=temp_issue_dir):
                    with patch("agenttree.issues.delete_session"):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            with patch("agenttree.state.unregister_agent"):
                                # No max_rollbacks specified - should succeed regardless of history
                                result = execute_rollback(
                                    "42",
                                    "implement.code_review",
                                    yes=True,
                                    skip_sync=True,
                                )

        assert result is True

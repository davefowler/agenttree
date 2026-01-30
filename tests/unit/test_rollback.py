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
        stages=[
            StageConfig(name="backlog"),
            StageConfig(name="define", output="problem.md"),
            StageConfig(name="research", output="research.md"),
            StageConfig(
                name="plan",
                output="spec.md",
                substages={"draft": SubstageConfig(name="draft"), "refine": SubstageConfig(name="refine")},
            ),
            StageConfig(name="plan_assess", output="spec_review.md"),
            StageConfig(name="plan_revise", output="spec.md"),
            StageConfig(name="plan_review", human_review=True),
            StageConfig(
                name="implement",
                substages={
                    "setup": SubstageConfig(name="setup"),
                    "code": SubstageConfig(name="code"),
                    "code_review": SubstageConfig(name="code_review", output="review.md"),
                    "address_review": SubstageConfig(name="address_review"),
                    "wrapup": SubstageConfig(name="wrapup"),
                    "feedback": SubstageConfig(name="feedback", output="feedback.md"),
                },
            ),
            StageConfig(name="implementation_review", human_review=True),
            StageConfig(name="accepted", terminal=True),
            StageConfig(name="not_doing", terminal=True),
        ],
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
        "stage": "implement",
        "substage": "code",
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
        """Given stage research, should return files from plan and later stages."""
        from agenttree.issues import get_output_files_after_stage

        with patch("agenttree.config.load_config", return_value=mock_config):
            files = get_output_files_after_stage("research")

        # After research: plan (spec.md), plan_assess (spec_review.md),
        # plan_revise (spec.md), implement.code_review (review.md), implement.feedback (feedback.md)
        assert "spec.md" in files
        assert "spec_review.md" in files
        assert "review.md" in files
        assert "feedback.md" in files
        assert "research.md" not in files
        assert "problem.md" not in files

    def test_after_plan_returns_later_files(self, mock_config):
        """Given stage plan, should return files from plan_assess and later."""
        from agenttree.issues import get_output_files_after_stage

        with patch("agenttree.config.load_config", return_value=mock_config):
            files = get_output_files_after_stage("plan")

        assert "spec_review.md" in files
        assert "review.md" in files
        assert "feedback.md" in files
        # spec.md IS included because plan_revise (after plan) also outputs spec.md
        assert "spec.md" in files
        assert "research.md" not in files

    def test_after_implement_returns_empty(self, mock_config):
        """Given stage implement, should return empty (no files after implement)."""
        from agenttree.issues import get_output_files_after_stage

        with patch("agenttree.config.load_config", return_value=mock_config):
            files = get_output_files_after_stage("implement")

        # Only implementation_review and terminal stages after implement, none have output
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

        # plan and plan_revise both have spec.md as output
        with patch("agenttree.config.load_config", return_value=mock_config):
            files = get_output_files_after_stage("define")

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
            stage="implement",
            substage="code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
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
            stage="implement",
            substage="code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
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
            stage="research",
            substage=None,
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    result = cli_runner.invoke(main, ["rollback", "42", "implement", "-y"])

        assert result.exit_code == 1
        # The message says target stage is "not before" current stage
        assert "not before" in result.output.lower() or "cannot rollback" in result.output.lower() or "backwards" in result.output.lower()

    def test_rejects_rollback_in_container(self, cli_runner, mock_config):
        """Should error when running inside a container."""
        from agenttree.cli import main

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.is_running_in_container", return_value=True):
                result = cli_runner.invoke(main, ["rollback", "42", "research", "-y"])

        assert result.exit_code == 1
        assert "container" in result.output.lower()


class TestRollbackUpdatesState:
    """Tests for rollback state updates."""

    def test_updates_stage_and_substage(self, cli_runner, mock_config, temp_issue_dir):
        """Should update issue stage and substage after rollback."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement",
            substage="code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.cli.delete_session"):
                            with patch("agenttree.agents_repo.sync_agents_repo"):
                                with patch("agenttree.state.get_active_agent", return_value=None):
                                    result = cli_runner.invoke(main, ["rollback", "42", "plan", "-y"])

        assert result.exit_code == 0
        # Check the issue.yaml was updated
        yaml_path = temp_issue_dir / "issue.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["stage"] == "plan"
        assert data["substage"] == "draft"  # first substage of plan

    def test_clears_pr_metadata(self, cli_runner, mock_config, temp_issue_dir):
        """Should clear PR metadata when rolling back."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implementation_review",
            substage=None,
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
            pr_number=123,
            pr_url="https://github.com/org/repo/pull/123",
        )

        # Update the issue.yaml with PR metadata
        yaml_path = temp_issue_dir / "issue.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        data["stage"] = "implementation_review"
        data["substage"] = None
        data["pr_number"] = 123
        data["pr_url"] = "https://github.com/org/repo/pull/123"
        with open(yaml_path, "w") as f:
            yaml.dump(data, f)

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.cli.delete_session"):
                            with patch("agenttree.agents_repo.sync_agents_repo"):
                                with patch("agenttree.state.get_active_agent", return_value=None):
                                    result = cli_runner.invoke(main, ["rollback", "42", "implement", "-y"])

        assert result.exit_code == 0
        # Check the issue.yaml had PR metadata cleared
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert "pr_number" not in data
        assert "pr_url" not in data


class TestRollbackHandlesAgent:
    """Tests for agent cleanup during rollback."""

    def test_kills_running_agent(self, cli_runner, mock_config, temp_issue_dir):
        """Should unregister running agent when rolling back."""
        from agenttree.cli import main
        from agenttree.issues import Issue
        from agenttree.state import ActiveAgent

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement",
            substage="code",
            assigned_agent="1",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        mock_agent = MagicMock(spec=ActiveAgent)
        mock_agent.tmux_session = "testproject-issue-42"
        mock_agent.issue_id = "42"
        mock_agent.worktree = Path("/path/to/worktree")

        agent_unregistered = False

        def capture_unregister(issue_id):
            nonlocal agent_unregistered
            agent_unregistered = True

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.cli.delete_session"):
                            with patch("agenttree.agents_repo.sync_agents_repo"):
                                with patch("agenttree.state.get_active_agents_for_issue", return_value=[mock_agent]):
                                    with patch("agenttree.state.unregister_all_agents_for_issue", side_effect=capture_unregister):
                                        result = cli_runner.invoke(main, ["rollback", "42", "research", "-y"])

        assert result.exit_code == 0
        assert agent_unregistered is True


class TestRollbackWorktreeReset:
    """Tests for worktree reset during rollback."""

    def test_reset_worktree_runs_git_reset(self, cli_runner, mock_config, temp_issue_dir):
        """With --reset-worktree and active agent, should run git reset --hard."""
        from agenttree.cli import main
        from agenttree.issues import Issue
        from agenttree.state import ActiveAgent

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement",
            substage="code",
            worktree_dir="/path/to/worktree",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        # Mock active agent with worktree path
        mock_agent = MagicMock(spec=ActiveAgent)
        mock_agent.tmux_session = "testproject-issue-42"
        mock_agent.issue_id = "42"
        mock_agent.worktree = temp_issue_dir  # Use temp dir as worktree

        git_reset_called = False

        def mock_run(cmd, **kwargs):
            nonlocal git_reset_called
            if isinstance(cmd, list) and "git" in cmd and "reset" in cmd:
                git_reset_called = True
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.cli.delete_session"):
                            with patch("agenttree.agents_repo.sync_agents_repo"):
                                with patch("agenttree.state.get_active_agents_for_issue", return_value=[mock_agent]):
                                    with patch("agenttree.state.unregister_all_agents_for_issue"):
                                        with patch("subprocess.run", side_effect=mock_run):
                                            result = cli_runner.invoke(
                                                main, ["rollback", "42", "research", "-y", "--reset-worktree"]
                                            )

        assert result.exit_code == 0
        assert git_reset_called is True

    def test_no_reset_without_flag(self, cli_runner, mock_config, temp_issue_dir):
        """Without --reset-worktree, should not run git reset (for implement stage onwards)."""
        from agenttree.cli import main
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test-issue",
            title="Test",
            stage="implement",
            substage="code",
            worktree_dir="/path/to/worktree",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        git_reset_called = False

        def mock_run(cmd, **kwargs):
            nonlocal git_reset_called
            if isinstance(cmd, list) and "git" in cmd and "reset" in cmd:
                git_reset_called = True
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.cli.delete_session"):
                            with patch("agenttree.agents_repo.sync_agents_repo"):
                                with patch("agenttree.state.get_active_agent", return_value=None):
                                    with patch("subprocess.run", side_effect=mock_run):
                                        # Rolling back to plan (before implement) but with --keep-changes
                                        result = cli_runner.invoke(main, ["rollback", "42", "plan", "-y", "--keep-changes"])

        # With --keep-changes, git reset should not be called even for pre-implement rollback
        assert git_reset_called is False


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
            stage="implement",
            substage="code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            # Send 'n' to decline confirmation
                            result = cli_runner.invoke(main, ["rollback", "42", "research"], input="n\n")

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
            stage="implement",
            substage="code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.state.get_active_agent", return_value=None):
                            result = cli_runner.invoke(main, ["rollback", "42", "research"], input="n\n")

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
            stage="implement",
            substage="code",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        with patch("agenttree.cli.load_config", return_value=mock_config):
            with patch("agenttree.cli.get_issue_func", return_value=mock_issue):
                with patch("agenttree.cli.is_running_in_container", return_value=False):
                    with patch("agenttree.cli.get_issue_dir", return_value=temp_issue_dir):
                        with patch("agenttree.cli.delete_session"):
                            with patch("agenttree.agents_repo.sync_agents_repo"):
                                with patch("agenttree.state.get_active_agent", return_value=None):
                                    result = cli_runner.invoke(main, ["rollback", "42", "research", "-y"])

        assert result.exit_code == 0
        assert "research" in result.output.lower() or "rolled back" in result.output.lower()

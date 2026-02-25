"""Tests for CLI documentation helper functions.

This module tests the helper functions used by CLI commands, not the
Click commands themselves (which are integration-test territory).
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agenttree.cli_docs import (
    get_next_rfc_number,
    open_editor,
    get_current_task_info,
)


class TestGetNextRfcNumber:
    """Tests for get_next_rfc_number function."""

    def test_returns_1_when_no_rfcs_exist(self, tmp_path: Path) -> None:
        """Test returns 1 when rfcs directory doesn't exist."""
        agents_path = tmp_path / "agents"
        agents_path.mkdir()

        result = get_next_rfc_number(agents_path)

        assert result == 1

    def test_returns_1_when_rfcs_dir_empty(self, tmp_path: Path) -> None:
        """Test returns 1 when rfcs directory is empty."""
        agents_path = tmp_path / "agents"
        rfcs_dir = agents_path / "rfcs"
        rfcs_dir.mkdir(parents=True)

        result = get_next_rfc_number(agents_path)

        assert result == 1

    def test_finds_max_rfc_number(self, tmp_path: Path) -> None:
        """Test finds the maximum RFC number and returns next."""
        agents_path = tmp_path / "agents"
        rfcs_dir = agents_path / "rfcs"
        rfcs_dir.mkdir(parents=True)

        # Create some RFC files
        (rfcs_dir / "001-first-rfc.md").write_text("# RFC")
        (rfcs_dir / "002-second-rfc.md").write_text("# RFC")
        (rfcs_dir / "005-skipped-numbers.md").write_text("# RFC")

        result = get_next_rfc_number(agents_path)

        assert result == 6

    def test_handles_malformed_filenames(self, tmp_path: Path) -> None:
        """Test handles malformed RFC filenames gracefully."""
        agents_path = tmp_path / "agents"
        rfcs_dir = agents_path / "rfcs"
        rfcs_dir.mkdir(parents=True)

        # Create some valid and invalid filenames
        (rfcs_dir / "001-valid.md").write_text("# RFC")
        (rfcs_dir / "not-an-rfc.md").write_text("# Not RFC")
        (rfcs_dir / "abc-invalid-number.md").write_text("# Invalid")

        result = get_next_rfc_number(agents_path)

        assert result == 2  # Only counted the valid RFC-001

    def test_handles_rfc_prefix_in_filename(self, tmp_path: Path) -> None:
        """Test handles RFC prefix in filenames (like RFC001-title.md)."""
        agents_path = tmp_path / "agents"
        rfcs_dir = agents_path / "rfcs"
        rfcs_dir.mkdir(parents=True)

        # Create RFC files with RFC prefix
        (rfcs_dir / "RFC001-with-prefix.md").write_text("# RFC")
        (rfcs_dir / "RFC003-another.md").write_text("# RFC")

        result = get_next_rfc_number(agents_path)

        # Should parse RFC001 -> 1, RFC003 -> 3, return 4
        assert result == 4


class TestOpenEditor:
    """Tests for open_editor function."""

    @patch("subprocess.run")
    @patch.dict("os.environ", {"EDITOR": "vim"})
    def test_open_editor_success(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test opening editor returns True on success."""
        mock_run.return_value = Mock(returncode=0)
        test_file = tmp_path / "test.md"
        test_file.write_text("# Content")

        result = open_editor(test_file)

        assert result is True
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "vim" in call_args
        assert str(test_file) in call_args

    @patch("subprocess.run")
    @patch.dict("os.environ", {"EDITOR": "nano"})
    def test_open_editor_uses_editor_env(
        self, mock_run: Mock, tmp_path: Path
    ) -> None:
        """Test uses EDITOR environment variable."""
        mock_run.return_value = Mock(returncode=0)
        test_file = tmp_path / "test.md"
        test_file.write_text("# Content")

        open_editor(test_file)

        call_args = mock_run.call_args[0][0]
        assert "nano" in call_args

    @patch("subprocess.run")
    @patch.dict("os.environ", {}, clear=True)
    def test_open_editor_defaults_to_vim(
        self, mock_run: Mock, tmp_path: Path
    ) -> None:
        """Test defaults to vim when EDITOR not set."""
        mock_run.return_value = Mock(returncode=0)
        test_file = tmp_path / "test.md"
        test_file.write_text("# Content")

        open_editor(test_file)

        call_args = mock_run.call_args[0][0]
        assert "vim" in call_args

    @patch("subprocess.run")
    @patch.dict("os.environ", {"EDITOR": "nonexistent-editor"})
    def test_open_editor_not_found(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test returns False when editor command not found."""
        mock_run.side_effect = FileNotFoundError("Editor not found")
        test_file = tmp_path / "test.md"
        test_file.write_text("# Content")

        result = open_editor(test_file)

        assert result is False

    @patch("subprocess.run")
    @patch.dict("os.environ", {"EDITOR": "vim"})
    def test_open_editor_failure_returncode(
        self, mock_run: Mock, tmp_path: Path
    ) -> None:
        """Test returns False when editor returns non-zero exit code."""
        mock_run.return_value = Mock(returncode=1)  # Non-zero exit
        test_file = tmp_path / "test.md"
        test_file.write_text("# Content")

        result = open_editor(test_file)

        assert result is False


class TestGetCurrentTaskInfo:
    """Tests for get_current_task_info function."""

    def test_returns_empty_dict_when_no_tasks_dir(self, tmp_path: Path) -> None:
        """Test returns empty dict when tasks directory doesn't exist."""
        agents_path = tmp_path / "agents"
        agents_path.mkdir()

        result = get_current_task_info(agents_path, 1)

        assert result == {}

    def test_returns_empty_dict_when_no_task_files(self, tmp_path: Path) -> None:
        """Test returns empty dict when task directory is empty."""
        agents_path = tmp_path / "agents"
        task_dir = agents_path / "tasks" / "agent-1"
        task_dir.mkdir(parents=True)

        result = get_current_task_info(agents_path, 1)

        assert result == {}

    def test_finds_most_recent_task_file(self, tmp_path: Path) -> None:
        """Test finds the most recent task file."""
        agents_path = tmp_path / "agents"
        task_dir = agents_path / "tasks" / "agent-1"
        task_dir.mkdir(parents=True)

        # Create task files - names sorted reverse will put 002 first
        (task_dir / "001-first-task.md").write_text(
            "---\nissue_number: 1\ntask_id: task1\n---\n\n# Task"
        )
        (task_dir / "002-second-task.md").write_text(
            "---\nissue_number: 2\ntask_id: task2\n---\n\n# Task"
        )

        result = get_current_task_info(agents_path, 1)

        # Should get the most recent (002)
        assert "002-second-task.md" in result.get("task_log", "")
        assert result.get("issue_number") == 2

    def test_parses_frontmatter(self, tmp_path: Path) -> None:
        """Test parses frontmatter from task file."""
        agents_path = tmp_path / "agents"
        task_dir = agents_path / "tasks" / "agent-1"
        task_dir.mkdir(parents=True)

        (task_dir / "001-task.md").write_text(
            "---\nissue_number: 42\ntask_id: my-task\n---\n\n# Task Content"
        )

        result = get_current_task_info(agents_path, 1)

        assert result["issue_number"] == 42
        assert result["task_id"] == "my-task"

    def test_handles_invalid_frontmatter(self, tmp_path: Path) -> None:
        """Test handles task files with invalid/missing frontmatter."""
        agents_path = tmp_path / "agents"
        task_dir = agents_path / "tasks" / "agent-1"
        task_dir.mkdir(parents=True)

        # Task file with no frontmatter
        (task_dir / "001-task.md").write_text("# Just markdown, no frontmatter")

        result = get_current_task_info(agents_path, 1)

        # Should still return task_log path
        assert "task_log" in result
        assert "001-task.md" in result["task_log"]

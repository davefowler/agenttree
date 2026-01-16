"""Tests for agenttree.commands module.

Tests command execution for template variables and CLI commands.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agenttree.commands import (
    execute_command,
    execute_commands,
    get_command_output,
    get_referenced_commands,
)


class TestExecuteCommand:
    """Tests for execute_command function."""

    def test_execute_command_success(self, tmp_path: Path) -> None:
        """Should return stdout on successful command."""
        result = execute_command("echo hello", cwd=tmp_path)
        assert result == "hello"

    def test_execute_command_strips_output(self, tmp_path: Path) -> None:
        """Should strip whitespace from output."""
        result = execute_command("echo '  hello  '", cwd=tmp_path)
        assert result == "hello"

    def test_execute_command_failure_returns_empty(self, tmp_path: Path) -> None:
        """Should return empty string on command failure."""
        result = execute_command("exit 1", cwd=tmp_path)
        assert result == ""

    def test_execute_command_timeout_returns_empty(self, tmp_path: Path) -> None:
        """Should return empty string on timeout."""
        result = execute_command("sleep 10", cwd=tmp_path, timeout=1)
        assert result == ""

    def test_execute_command_in_directory(self, tmp_path: Path) -> None:
        """Should run command in specified working directory."""
        # Create a marker file
        (tmp_path / "marker.txt").write_text("test content")

        # Read it via command
        result = execute_command("cat marker.txt", cwd=tmp_path)
        assert result == "test content"

    def test_execute_command_with_pipe(self, tmp_path: Path) -> None:
        """Should handle piped commands."""
        result = execute_command("echo 'a\nb\nc' | wc -l", cwd=tmp_path)
        assert result.strip() == "3"

    def test_execute_command_nonexistent_returns_empty(self, tmp_path: Path) -> None:
        """Should return empty string for nonexistent command."""
        result = execute_command("nonexistent_command_xyz", cwd=tmp_path)
        assert result == ""


class TestExecuteCommands:
    """Tests for execute_commands function."""

    def test_execute_commands_single(self, tmp_path: Path) -> None:
        """Should execute single command in list."""
        result = execute_commands(["echo hello"], cwd=tmp_path)
        assert result == "hello"

    def test_execute_commands_multiple(self, tmp_path: Path) -> None:
        """Should join outputs with newlines."""
        result = execute_commands(["echo one", "echo two"], cwd=tmp_path)
        assert result == "one\ntwo"

    def test_execute_commands_empty_list(self, tmp_path: Path) -> None:
        """Should handle empty list."""
        result = execute_commands([], cwd=tmp_path)
        assert result == ""

    def test_execute_commands_mixed_success_failure(self, tmp_path: Path) -> None:
        """Should include empty strings for failed commands."""
        result = execute_commands(["echo one", "exit 1", "echo three"], cwd=tmp_path)
        assert result == "one\n\nthree"


class TestGetCommandOutput:
    """Tests for get_command_output function."""

    def test_get_command_output_string(self, tmp_path: Path) -> None:
        """Should execute string command."""
        commands = {"test": "echo hello"}
        result = get_command_output(commands, "test", cwd=tmp_path)
        assert result == "hello"

    def test_get_command_output_list(self, tmp_path: Path) -> None:
        """Should execute list of commands."""
        commands = {"test": ["echo one", "echo two"]}
        result = get_command_output(commands, "test", cwd=tmp_path)
        assert result == "one\ntwo"

    def test_get_command_output_not_found(self, tmp_path: Path) -> None:
        """Should return empty string for missing command."""
        commands = {"other": "echo hello"}
        result = get_command_output(commands, "missing", cwd=tmp_path)
        assert result == ""

    def test_get_command_output_from_config(self, tmp_path: Path) -> None:
        """Should retrieve and execute named command from config-like dict."""
        commands = {
            "git_branch": "git branch --show-current",
            "lint": "echo 'linting...'",
            "test": ["echo 'running tests'", "echo 'tests done'"],
        }
        result = get_command_output(commands, "lint", cwd=tmp_path)
        assert result == "linting..."

    def test_get_command_output_cwd_is_worktree(self, tmp_path: Path) -> None:
        """Should run commands in specified working directory."""
        # Create test file in tmp_path
        (tmp_path / "test.txt").write_text("worktree content")

        commands = {"read_file": "cat test.txt"}
        result = get_command_output(commands, "read_file", cwd=tmp_path)
        assert result == "worktree content"


class TestGetReferencedCommands:
    """Tests for get_referenced_commands function."""

    def test_find_single_reference(self) -> None:
        """Should find single command reference."""
        template = "Branch: {{git_branch}}"
        commands = {"git_branch": "git branch --show-current"}

        result = get_referenced_commands(template, commands)
        assert result == {"git_branch"}

    def test_find_multiple_references(self) -> None:
        """Should find multiple command references."""
        template = """
## Stats
- Branch: {{git_branch}}
- Files: {{files_changed}}
- Lines added: {{lines_added}}
"""
        commands = {
            "git_branch": "git branch",
            "files_changed": "git diff --stat",
            "lines_added": "git diff | grep +",
            "unused": "echo unused",
        }

        result = get_referenced_commands(template, commands)
        assert result == {"git_branch", "files_changed", "lines_added"}

    def test_ignore_non_commands(self) -> None:
        """Should ignore variables that aren't in commands dict."""
        template = "Issue: {{issue_id}}, Branch: {{git_branch}}"
        commands = {"git_branch": "git branch"}

        result = get_referenced_commands(template, commands)
        # issue_id is not in commands, so only git_branch
        assert result == {"git_branch"}

    def test_empty_template(self) -> None:
        """Should handle empty template."""
        commands = {"test": "echo test"}
        result = get_referenced_commands("", commands)
        assert result == set()

    def test_no_commands(self) -> None:
        """Should handle empty commands dict."""
        template = "{{some_var}}"
        result = get_referenced_commands(template, {})
        assert result == set()

    def test_whitespace_in_braces(self) -> None:
        """Should handle whitespace inside braces."""
        template = "{{ git_branch }} and {{  files_changed  }}"
        commands = {"git_branch": "git branch", "files_changed": "git diff"}

        result = get_referenced_commands(template, commands)
        assert result == {"git_branch", "files_changed"}

    def test_nested_braces_ignored(self) -> None:
        """Should handle jinja control structures gracefully."""
        template = """
{% if show_stats %}
  {{git_branch}}
{% endif %}
"""
        commands = {"git_branch": "git branch"}

        result = get_referenced_commands(template, commands)
        assert result == {"git_branch"}

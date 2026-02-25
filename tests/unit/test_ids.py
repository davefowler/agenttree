"""Tests for issue ID formatting and parsing."""

import pytest

from agenttree.ids import (
    parse_issue_id,
    format_issue_id,
    container_name,
    session_name,
    tmux_session_name,
    manager_session_name,
    serve_session_name,
    container_type_session_name,
    worktree_dir_name,
)


class TestParseIssueId:
    """Tests for parse_issue_id function."""

    def test_parse_simple_id(self) -> None:
        """Test parsing a simple numeric string."""
        assert parse_issue_id("1") == 1
        assert parse_issue_id("42") == 42
        assert parse_issue_id("999") == 999

    def test_parse_padded_id(self) -> None:
        """Test parsing IDs with leading zeros."""
        assert parse_issue_id("001") == 1
        assert parse_issue_id("042") == 42
        assert parse_issue_id("0001") == 1

    def test_parse_large_id(self) -> None:
        """Test parsing large IDs (4+ digits)."""
        assert parse_issue_id("1001") == 1001
        assert parse_issue_id("9999") == 9999
        assert parse_issue_id("12345") == 12345

    def test_parse_zero(self) -> None:
        """Test parsing zero - edge case for leading zeros."""
        assert parse_issue_id("0") == 0
        assert parse_issue_id("00") == 0
        assert parse_issue_id("000") == 0

    def test_parse_empty_string_raises(self) -> None:
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid issue ID"):
            parse_issue_id("")

    def test_parse_whitespace_only_raises(self) -> None:
        """Test that whitespace-only string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid issue ID"):
            parse_issue_id("   ")

    def test_parse_non_numeric_raises(self) -> None:
        """Test that non-numeric strings raise ValueError."""
        with pytest.raises(ValueError):
            parse_issue_id("abc")

    def test_parse_with_surrounding_whitespace(self) -> None:
        """Test parsing with leading/trailing whitespace (stripped by lstrip)."""
        # Note: parse_issue_id uses lstrip("0"), not strip()
        # Leading whitespace is handled, trailing may cause int() to fail
        assert parse_issue_id("  42") == 42


class TestFormatIssueId:
    """Tests for format_issue_id function."""

    def test_format_single_digit(self) -> None:
        """Test formatting single-digit IDs to 3 digits."""
        assert format_issue_id(1) == "001"
        assert format_issue_id(9) == "009"

    def test_format_double_digit(self) -> None:
        """Test formatting double-digit IDs."""
        assert format_issue_id(10) == "010"
        assert format_issue_id(42) == "042"
        assert format_issue_id(99) == "099"

    def test_format_triple_digit(self) -> None:
        """Test formatting triple-digit IDs."""
        assert format_issue_id(100) == "100"
        assert format_issue_id(999) == "999"

    def test_format_large_id(self) -> None:
        """Test formatting IDs with 4+ digits (no truncation)."""
        assert format_issue_id(1000) == "1000"
        assert format_issue_id(1001) == "1001"
        assert format_issue_id(9999) == "9999"
        assert format_issue_id(12345) == "12345"

    def test_format_zero(self) -> None:
        """Test formatting zero."""
        assert format_issue_id(0) == "000"


class TestContainerName:
    """Tests for container_name function."""

    def test_container_name_format(self) -> None:
        """Test correct container name format."""
        assert container_name("myproject", 1) == "agenttree-myproject-001"
        assert container_name("myproject", 42) == "agenttree-myproject-042"
        assert container_name("myproject", 999) == "agenttree-myproject-999"

    def test_container_name_large_id(self) -> None:
        """Test container name with large IDs."""
        assert container_name("myproject", 1001) == "agenttree-myproject-1001"

    def test_container_name_different_projects(self) -> None:
        """Test container names for different projects."""
        assert container_name("foo", 1) == "agenttree-foo-001"
        assert container_name("bar-baz", 1) == "agenttree-bar-baz-001"


class TestSessionName:
    """Tests for session_name function."""

    def test_session_name_default_template(self) -> None:
        """Test session name with default template."""
        result = session_name("myproject", "developer", 42)
        assert result == "myproject-developer-042"

    def test_session_name_custom_template(self) -> None:
        """Test session name with custom template."""
        result = session_name(
            "myproject",
            "developer",
            42,
            template="{session_type}@{project}:{issue_id}",
        )
        assert result == "developer@myproject:042"

    def test_session_name_placeholder_substitution(self) -> None:
        """Test all placeholders are substituted."""
        result = session_name(
            "proj",
            "dev",
            1,
            template="{project}-{session_type}-{issue_id}",
        )
        assert result == "proj-dev-001"
        assert "{" not in result  # No unsubstituted placeholders


class TestTmuxSessionName:
    """Tests for tmux_session_name function."""

    def test_tmux_session_name_default_role(self) -> None:
        """Test tmux session name with default developer role."""
        result = tmux_session_name("myproject", 42)
        assert result == "myproject-developer-042"

    def test_tmux_session_name_custom_role(self) -> None:
        """Test tmux session name with custom role."""
        result = tmux_session_name("myproject", 42, role="reviewer")
        assert result == "myproject-reviewer-042"

    def test_tmux_session_name_zero_id(self) -> None:
        """Test tmux session name with zero ID."""
        result = tmux_session_name("myproject", 0)
        assert result == "myproject-developer-000"


class TestManagerSessionName:
    """Tests for manager_session_name function."""

    def test_manager_session_name_format(self) -> None:
        """Test manager session name uses issue_id=0."""
        result = manager_session_name("myproject")
        assert result == "myproject-manager-000"

    def test_manager_session_name_different_projects(self) -> None:
        """Test manager session names for different projects."""
        assert manager_session_name("foo") == "foo-manager-000"
        assert manager_session_name("bar") == "bar-manager-000"


class TestServeSessionName:
    """Tests for serve_session_name function."""

    def test_serve_session_name_format(self) -> None:
        """Test serve session name uses 'serve' session type."""
        result = serve_session_name("myproject", 42)
        assert result == "myproject-serve-042"

    def test_serve_session_name_different_ids(self) -> None:
        """Test serve session names for different issue IDs."""
        assert serve_session_name("myproject", 1) == "myproject-serve-001"
        assert serve_session_name("myproject", 999) == "myproject-serve-999"


class TestContainerTypeSessionName:
    """Tests for container_type_session_name function."""

    def test_container_type_session_name_format(self) -> None:
        """Test container type session name format."""
        result = container_type_session_name("myproject", "sandbox", "my-sandbox")
        assert result == "myproject-sandbox-my-sandbox"

    def test_container_type_session_name_different_types(self) -> None:
        """Test different container types."""
        assert (
            container_type_session_name("proj", "reviewer", "rev1")
            == "proj-reviewer-rev1"
        )
        assert (
            container_type_session_name("proj", "worker", "w1")
            == "proj-worker-w1"
        )


class TestWorktreeDirName:
    """Tests for worktree_dir_name function."""

    def test_worktree_dir_name_format(self) -> None:
        """Test worktree directory name format."""
        assert worktree_dir_name(1) == "issue-001"
        assert worktree_dir_name(42) == "issue-042"
        assert worktree_dir_name(999) == "issue-999"

    def test_worktree_dir_name_large_id(self) -> None:
        """Test worktree directory name with large IDs."""
        assert worktree_dir_name(1001) == "issue-1001"
        assert worktree_dir_name(9999) == "issue-9999"

    def test_worktree_dir_name_zero(self) -> None:
        """Test worktree directory name for zero."""
        assert worktree_dir_name(0) == "issue-000"

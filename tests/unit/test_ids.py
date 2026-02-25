"""Tests for agenttree/ids.py."""

import pytest

from agenttree.ids import (
    slugify,
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


class TestSlugify:
    """Tests for the slugify function."""

    def test_slugify_basic(self) -> None:
        """Basic text is converted to lowercase with hyphens."""
        assert slugify("Hello World") == "hello-world"

    def test_slugify_special_chars(self) -> None:
        """Special characters are removed."""
        assert slugify("Test: 123!") == "test-123"

    def test_slugify_whitespace(self) -> None:
        """Leading and trailing whitespace is handled."""
        assert slugify("  padded  ") == "padded"

    def test_slugify_underscores(self) -> None:
        """Underscores become hyphens."""
        assert slugify("foo_bar") == "foo-bar"

    def test_slugify_max_length(self) -> None:
        """Length limit is applied."""
        result = slugify("very long title here", max_length=10)
        assert len(result) <= 10
        assert result == "very-long-"

    def test_slugify_no_length_limit(self) -> None:
        """No limit when max_length is None."""
        long_text = "a" * 100
        result = slugify(long_text)
        assert len(result) == 100

    def test_slugify_preserves_hyphens(self) -> None:
        """Existing hyphens are preserved."""
        assert slugify("pre-existing") == "pre-existing"

    def test_slugify_multiple_spaces(self) -> None:
        """Multiple spaces become single hyphen."""
        assert slugify("hello   world") == "hello-world"

    def test_slugify_mixed_underscores_spaces(self) -> None:
        """Mixed underscores and spaces become hyphens."""
        assert slugify("hello_world test") == "hello-world-test"

    def test_slugify_empty_string(self) -> None:
        """Empty string returns empty string."""
        assert slugify("") == ""

    def test_slugify_only_special_chars(self) -> None:
        """String with only special chars returns empty."""
        assert slugify("!@#$%") == ""

    def test_slugify_numbers(self) -> None:
        """Numbers are preserved."""
        assert slugify("test123") == "test123"
        assert slugify("123test") == "123test"


class TestParseIssueId:
    """Tests for parse_issue_id function."""

    def test_parse_simple(self) -> None:
        """Simple numbers are parsed."""
        assert parse_issue_id("1") == 1
        assert parse_issue_id("42") == 42

    def test_parse_with_leading_zeros(self) -> None:
        """Leading zeros are stripped."""
        assert parse_issue_id("001") == 1
        assert parse_issue_id("042") == 42

    def test_parse_zero(self) -> None:
        """Zero is parsed correctly."""
        assert parse_issue_id("0") == 0
        assert parse_issue_id("000") == 0

    def test_parse_empty_raises(self) -> None:
        """Empty string raises ValueError."""
        with pytest.raises(ValueError):
            parse_issue_id("")

    def test_parse_whitespace_raises(self) -> None:
        """Whitespace-only string raises ValueError."""
        with pytest.raises(ValueError):
            parse_issue_id("   ")


class TestFormatIssueId:
    """Tests for format_issue_id function."""

    def test_format_single_digit(self) -> None:
        """Single digit gets zero-padded."""
        assert format_issue_id(1) == "001"

    def test_format_double_digit(self) -> None:
        """Double digit gets zero-padded."""
        assert format_issue_id(42) == "042"

    def test_format_triple_digit(self) -> None:
        """Triple digit is unchanged."""
        assert format_issue_id(999) == "999"

    def test_format_four_digit(self) -> None:
        """Four digit is unchanged (no truncation)."""
        assert format_issue_id(1001) == "1001"


class TestSessionNames:
    """Tests for session name functions."""

    def test_session_name_default_template(self) -> None:
        """Default template produces expected format."""
        assert session_name("myapp", "developer", 42) == "myapp-developer-042"

    def test_tmux_session_name(self) -> None:
        """tmux_session_name uses developer role by default."""
        assert tmux_session_name("myapp", 42) == "myapp-developer-042"
        assert tmux_session_name("myapp", 42, "reviewer") == "myapp-reviewer-042"

    def test_manager_session_name(self) -> None:
        """Manager session uses issue 0."""
        assert manager_session_name("myapp") == "myapp-manager-000"

    def test_serve_session_name(self) -> None:
        """Serve session has expected format."""
        assert serve_session_name("myapp", 42) == "myapp-serve-042"


class TestContainerNames:
    """Tests for container name functions."""

    def test_container_name(self) -> None:
        """Container name has expected format."""
        assert container_name("myproject", 42) == "agenttree-myproject-042"

    def test_container_type_session_name(self) -> None:
        """Container type session name has expected format."""
        assert container_type_session_name("myapp", "sandbox", "test") == "myapp-sandbox-test"


class TestWorktreeDirName:
    """Tests for worktree_dir_name function."""

    def test_worktree_dir_name(self) -> None:
        """Worktree directory name has expected format."""
        assert worktree_dir_name(42) == "issue-042"
        assert worktree_dir_name(1) == "issue-001"

"""Tests for frontmatter utilities."""

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agenttree.frontmatter import (
    create_frontmatter,
    parse_frontmatter,
    get_git_context,
    get_commits_since,
    update_frontmatter_field,
    add_frontmatter_fields,
    utc_now,
    validate_required_fields,
)


class TestCreateFrontmatter:
    """Tests for create_frontmatter function."""

    def test_create_basic_frontmatter(self) -> None:
        """Test creating frontmatter from a simple dict."""
        data = {"title": "Test", "version": 1}
        result = create_frontmatter(data)

        assert result.startswith("---\n")
        assert result.endswith("---\n\n")
        assert "title: Test" in result
        assert "version: 1" in result

    def test_create_frontmatter_preserves_order(self) -> None:
        """Test that frontmatter preserves key order."""
        data = {"first": 1, "second": 2, "third": 3}
        result = create_frontmatter(data)

        # Keys should appear in insertion order
        first_pos = result.find("first:")
        second_pos = result.find("second:")
        third_pos = result.find("third:")

        assert first_pos < second_pos < third_pos

    def test_create_frontmatter_handles_special_characters(self) -> None:
        """Test handling of special characters in values."""
        data = {"title": "Test: With Colon", "desc": "Line with 'quotes'"}
        result = create_frontmatter(data)

        assert "---\n" in result
        assert "---\n\n" in result[-6:]

    def test_create_frontmatter_handles_lists(self) -> None:
        """Test handling of list values."""
        data = {"tags": ["tag1", "tag2", "tag3"]}
        result = create_frontmatter(data)

        assert "tags:" in result
        assert "- tag1" in result
        assert "- tag2" in result

    def test_create_frontmatter_handles_none(self) -> None:
        """Test handling of None values."""
        data = {"title": "Test", "optional_field": None}
        result = create_frontmatter(data)

        assert "optional_field: null" in result or "optional_field:" in result


class TestParseFrontmatter:
    """Tests for parse_frontmatter function."""

    def test_parse_valid_frontmatter(self) -> None:
        """Test parsing valid frontmatter."""
        content = "---\ntitle: Test\nversion: 1\n---\n\n# Content"
        frontmatter, markdown = parse_frontmatter(content)

        assert frontmatter["title"] == "Test"
        assert frontmatter["version"] == 1
        assert markdown == "# Content"

    def test_parse_no_frontmatter(self) -> None:
        """Test parsing content with no frontmatter."""
        content = "# Just markdown\n\nNo frontmatter here."
        frontmatter, markdown = parse_frontmatter(content)

        assert frontmatter == {}
        assert markdown == content

    def test_parse_invalid_yaml(self) -> None:
        """Test parsing content with invalid YAML frontmatter."""
        content = "---\ninvalid: yaml: here\n---\n\n# Content"
        frontmatter, markdown = parse_frontmatter(content)

        # Should return empty dict on invalid YAML, not crash
        assert frontmatter == {} or isinstance(frontmatter, dict)

    def test_parse_content_after_frontmatter_preserved(self) -> None:
        """Test that content after frontmatter is preserved."""
        content = "---\ntitle: Test\n---\n\n# Heading\n\nParagraph with text."
        frontmatter, markdown = parse_frontmatter(content)

        assert "# Heading" in markdown
        assert "Paragraph with text." in markdown

    def test_parse_empty_frontmatter(self) -> None:
        """Test parsing empty frontmatter block."""
        content = "---\n---\n\n# Content"
        frontmatter, markdown = parse_frontmatter(content)

        assert frontmatter == {} or frontmatter is None
        assert "# Content" in markdown

    def test_parse_incomplete_delimiters(self) -> None:
        """Test parsing with incomplete frontmatter delimiters."""
        content = "---\ntitle: Test\nNo closing delimiter"
        frontmatter, markdown = parse_frontmatter(content)

        # Should handle gracefully
        assert isinstance(frontmatter, dict)


class TestGetGitContext:
    """Tests for get_git_context function."""

    @patch("subprocess.run")
    def test_get_git_context_success(self, mock_run: Mock) -> None:
        """Test getting git context successfully."""
        # Mock the three git calls
        mock_run.side_effect = [
            Mock(stdout="abc123def456", returncode=0),  # git rev-parse HEAD
            Mock(stdout="feature-branch", returncode=0),  # git rev-parse --abbrev-ref
            Mock(stdout="https://github.com/user/repo.git", returncode=0),  # git config
        ]

        result = get_git_context(Path("/tmp/repo"))

        assert result["starting_commit"] == "abc123def456"
        assert result["starting_branch"] == "feature-branch"
        assert result["repo_url"] == "https://github.com/user/repo"

    @patch("subprocess.run")
    def test_get_git_context_ssh_url_conversion(self, mock_run: Mock) -> None:
        """Test conversion of SSH URL to HTTPS."""
        mock_run.side_effect = [
            Mock(stdout="abc123", returncode=0),
            Mock(stdout="main", returncode=0),
            Mock(stdout="git@github.com:user/repo.git", returncode=0),
        ]

        result = get_git_context(Path("/tmp/repo"))

        assert result["repo_url"] == "https://github.com/user/repo"

    @patch("subprocess.run")
    def test_get_git_context_error_handling(self, mock_run: Mock) -> None:
        """Test handling of git command failures."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        result = get_git_context(Path("/tmp/repo"))

        assert result["repo_url"] is None
        assert result["starting_commit"] is None
        assert result["starting_branch"] is None


class TestGetCommitsSince:
    """Tests for get_commits_since function."""

    @patch("subprocess.run")
    def test_get_commits_since_success(self, mock_run: Mock) -> None:
        """Test getting commits since a given commit."""
        mock_run.return_value = Mock(
            stdout="abc123|Fix bug|2026-01-01T10:00:00Z\ndef456|Add feature|2026-01-02T10:00:00Z",
            returncode=0,
        )

        result = get_commits_since(Path("/tmp/repo"), "start123")

        assert len(result) == 2
        assert result[0]["hash"] == "abc123"
        assert result[0]["message"] == "Fix bug"
        assert result[1]["hash"] == "def456"

    @patch("subprocess.run")
    def test_get_commits_since_empty_result(self, mock_run: Mock) -> None:
        """Test when there are no commits since."""
        mock_run.return_value = Mock(stdout="", returncode=0)

        result = get_commits_since(Path("/tmp/repo"), "latest")

        assert result == []

    @patch("subprocess.run")
    def test_get_commits_since_error(self, mock_run: Mock) -> None:
        """Test handling of git command failure."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git log")

        result = get_commits_since(Path("/tmp/repo"), "badcommit")

        assert result == []


class TestUpdateFrontmatterField:
    """Tests for update_frontmatter_field function."""

    def test_update_existing_field(self, tmp_path: Path) -> None:
        """Test updating an existing field."""
        file = tmp_path / "test.md"
        file.write_text("---\ntitle: Old\nversion: 1\n---\n\n# Content")

        update_frontmatter_field(file, "title", "New")

        content = file.read_text()
        frontmatter, _ = parse_frontmatter(content)
        assert frontmatter["title"] == "New"
        assert frontmatter["version"] == 1

    def test_update_creates_new_field(self, tmp_path: Path) -> None:
        """Test creating a field that doesn't exist."""
        file = tmp_path / "test.md"
        file.write_text("---\ntitle: Test\n---\n\n# Content")

        update_frontmatter_field(file, "new_field", "value")

        content = file.read_text()
        frontmatter, _ = parse_frontmatter(content)
        assert frontmatter["new_field"] == "value"

    def test_update_preserves_markdown(self, tmp_path: Path) -> None:
        """Test that markdown content is preserved after update."""
        file = tmp_path / "test.md"
        original_md = "# Heading\n\nParagraph text."
        file.write_text(f"---\ntitle: Test\n---\n\n{original_md}")

        update_frontmatter_field(file, "title", "Updated")

        content = file.read_text()
        _, markdown = parse_frontmatter(content)
        assert original_md in markdown


class TestAddFrontmatterFields:
    """Tests for add_frontmatter_fields function."""

    def test_add_multiple_fields(self, tmp_path: Path) -> None:
        """Test adding multiple fields at once."""
        file = tmp_path / "test.md"
        file.write_text("---\nexisting: value\n---\n\n# Content")

        add_frontmatter_fields(file, {"new1": "val1", "new2": "val2"})

        content = file.read_text()
        frontmatter, _ = parse_frontmatter(content)
        assert frontmatter["existing"] == "value"
        assert frontmatter["new1"] == "val1"
        assert frontmatter["new2"] == "val2"

    def test_add_fields_merges_with_existing(self, tmp_path: Path) -> None:
        """Test that new fields merge with existing ones."""
        file = tmp_path / "test.md"
        file.write_text("---\nold: value\n---\n\n# Content")

        add_frontmatter_fields(file, {"new": "added"})

        content = file.read_text()
        frontmatter, _ = parse_frontmatter(content)
        assert frontmatter["old"] == "value"
        assert frontmatter["new"] == "added"

    def test_add_fields_overwrites_existing(self, tmp_path: Path) -> None:
        """Test that existing fields are overwritten."""
        file = tmp_path / "test.md"
        file.write_text("---\nfield: old\n---\n\n# Content")

        add_frontmatter_fields(file, {"field": "new"})

        content = file.read_text()
        frontmatter, _ = parse_frontmatter(content)
        assert frontmatter["field"] == "new"


class TestUtcNow:
    """Tests for utc_now function."""

    @patch("agenttree.frontmatter.datetime")
    def test_utc_now_format(self, mock_datetime: Mock) -> None:
        """Test UTC timestamp has correct ISO 8601 format."""
        mock_now = datetime(2026, 1, 4, 10, 30, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now

        result = utc_now()

        assert result == "2026-01-04T10:30:00Z"

    @patch("agenttree.frontmatter.datetime")
    def test_utc_now_uses_utc_timezone(self, mock_datetime: Mock) -> None:
        """Test that utc_now uses UTC timezone."""
        mock_now = datetime(2026, 6, 15, 23, 59, 59, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now

        result = utc_now()

        assert result.endswith("Z")  # Z suffix indicates UTC


class TestValidateRequiredFields:
    """Tests for validate_required_fields function."""

    def test_validate_all_present(self) -> None:
        """Test when all required fields are present."""
        frontmatter = {"title": "Test", "version": 1, "author": "me"}
        required = ["title", "version"]

        missing = validate_required_fields(frontmatter, required)

        assert missing == []

    def test_validate_some_missing(self) -> None:
        """Test when some required fields are missing."""
        frontmatter = {"title": "Test"}
        required = ["title", "version", "author"]

        missing = validate_required_fields(frontmatter, required)

        assert "version" in missing
        assert "author" in missing
        assert "title" not in missing

    def test_validate_handles_none_values(self) -> None:
        """Test that None values are treated as missing."""
        frontmatter = {"title": "Test", "version": None}
        required = ["title", "version"]

        missing = validate_required_fields(frontmatter, required)

        assert "version" in missing

    def test_validate_empty_frontmatter(self) -> None:
        """Test with empty frontmatter."""
        frontmatter: dict[str, object] = {}
        required = ["title", "version"]

        missing = validate_required_fields(frontmatter, required)

        assert "title" in missing
        assert "version" in missing

    def test_validate_no_requirements(self) -> None:
        """Test with no required fields."""
        frontmatter = {"title": "Test"}
        required: list[str] = []

        missing = validate_required_fields(frontmatter, required)

        assert missing == []

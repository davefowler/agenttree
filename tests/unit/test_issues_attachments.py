"""Unit tests for attachment handling in issues.py."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from agenttree.issues import create_issue, sanitize_filename


class TestSanitizeFilename:
    """Tests for the sanitize_filename helper function."""

    def test_removes_path_traversal(self):
        """Verify ../  and absolute paths are sanitized."""
        # Path traversal should be stripped, leaving just the filename
        result1 = sanitize_filename("../../../etc/passwd")
        assert "passwd" in result1
        assert "../" not in result1
        assert "etc" not in result1  # Path components are stripped

        result2 = sanitize_filename("..\\..\\windows\\system32")
        assert "system32" in result2
        assert "..\\" not in result2

        result3 = sanitize_filename("/etc/passwd")
        assert "passwd" in result3
        assert "/" not in result3

    def test_adds_timestamp_prefix(self):
        """Verify filenames get unique timestamp prefix."""
        result = sanitize_filename("screenshot.png")
        # Should have format: {timestamp}_{original_name}
        parts = result.split("_", 1)
        assert len(parts) == 2
        assert parts[0].isdigit()
        assert parts[1] == "screenshot.png"

    def test_replaces_unsafe_chars(self):
        """Verify unsafe characters are replaced."""
        result = sanitize_filename("my file<name>:test.png")
        # Should not contain any unsafe chars
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        # Should still end with the safe version
        assert result.endswith(".png")

    def test_preserves_extension(self):
        """Verify file extension is preserved."""
        for ext in [".png", ".jpg", ".gif", ".txt", ".log"]:
            result = sanitize_filename(f"test{ext}")
            assert result.endswith(ext)


class TestCreateIssueWithAttachments:
    """Tests for create_issue with attachments parameter."""

    @pytest.fixture
    def mock_agenttree_path(self, tmp_path):
        """Mock the agenttree path to use a temp directory."""
        issues_path = tmp_path / "_agenttree" / "issues"
        issues_path.mkdir(parents=True)

        with patch("agenttree.issues.get_agenttree_path", return_value=tmp_path / "_agenttree"), \
             patch("agenttree.issues.get_issues_path", return_value=issues_path), \
             patch("agenttree.issues.sync_agents_repo"), \
             patch("agenttree.issues.get_next_issue_number", return_value=999):
            yield tmp_path

    def test_creates_attachments_dir(self, mock_agenttree_path):
        """Verify attachments directory is created when files are provided."""
        attachments = [("screenshot.png", b"fake image data")]

        issue = create_issue(
            title="Test issue with attachment",
            problem="Test problem",
            attachments=attachments,
        )

        issue_dir = mock_agenttree_path / "_agenttree" / "issues" / f"{issue.id}-test-issue-with-attachment"
        attachments_dir = issue_dir / "attachments"
        assert attachments_dir.exists()
        assert attachments_dir.is_dir()

    def test_saves_files(self, mock_agenttree_path):
        """Verify files are written to disk with correct content."""
        file_content = b"fake image data 12345"
        attachments = [("screenshot.png", file_content)]

        issue = create_issue(
            title="Test issue with file",
            problem="Test problem",
            attachments=attachments,
        )

        issue_dir = mock_agenttree_path / "_agenttree" / "issues" / f"{issue.id}-test-issue-with-file"
        attachments_dir = issue_dir / "attachments"

        # Find the saved file (has timestamp prefix)
        saved_files = list(attachments_dir.glob("*_screenshot.png"))
        assert len(saved_files) == 1
        assert saved_files[0].read_bytes() == file_content

    def test_adds_markdown_section(self, mock_agenttree_path):
        """Verify problem.md includes Attachments section."""
        attachments = [("screenshot.png", b"image data")]

        issue = create_issue(
            title="Test with attachments section",
            problem="Test problem",
            attachments=attachments,
        )

        issue_dir = mock_agenttree_path / "_agenttree" / "issues" / f"{issue.id}-test-with-attachments-section"
        problem_md = issue_dir / "problem.md"
        content = problem_md.read_text()

        assert "## Attachments" in content

    def test_image_uses_image_syntax(self, mock_agenttree_path):
        """Verify PNG/JPG files use ![name](path) syntax."""
        attachments = [("photo.jpg", b"image data")]

        issue = create_issue(
            title="Test image syntax",
            problem="Test problem",
            attachments=attachments,
        )

        issue_dir = mock_agenttree_path / "_agenttree" / "issues" / f"{issue.id}-test-image-syntax"
        problem_md = issue_dir / "problem.md"
        content = problem_md.read_text()

        # Should use image markdown syntax
        assert "![photo.jpg]" in content

    def test_text_file_uses_link_syntax(self, mock_agenttree_path):
        """Verify TXT files use [name](path) syntax (not image syntax)."""
        attachments = [("error.log", b"log content")]

        issue = create_issue(
            title="Test link syntax",
            problem="Test problem",
            attachments=attachments,
        )

        issue_dir = mock_agenttree_path / "_agenttree" / "issues" / f"{issue.id}-test-link-syntax"
        problem_md = issue_dir / "problem.md"
        content = problem_md.read_text()

        # Should use link syntax, not image syntax
        assert "[error.log]" in content
        assert "![error.log]" not in content

    def test_no_attachments_section_when_empty(self, mock_agenttree_path):
        """Verify no Attachments section when no files provided."""
        issue = create_issue(
            title="Test no attachments",
            problem="Test problem",
        )

        issue_dir = mock_agenttree_path / "_agenttree" / "issues" / f"{issue.id}-test-no-attachments"
        problem_md = issue_dir / "problem.md"
        content = problem_md.read_text()

        assert "## Attachments" not in content

    def test_multiple_attachments(self, mock_agenttree_path):
        """Verify multiple files are all saved correctly."""
        attachments = [
            ("screenshot1.png", b"image 1"),
            ("screenshot2.png", b"image 2"),
            ("log.txt", b"log content"),
        ]

        issue = create_issue(
            title="Test multiple attachments",
            problem="Test problem",
            attachments=attachments,
        )

        issue_dir = mock_agenttree_path / "_agenttree" / "issues" / f"{issue.id}-test-multiple-attachments"
        attachments_dir = issue_dir / "attachments"

        # Should have 3 files
        saved_files = list(attachments_dir.iterdir())
        assert len(saved_files) == 3

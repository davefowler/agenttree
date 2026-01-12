"""Tests for agenttree.issues module."""

import tempfile
from pathlib import Path

import pytest

from agenttree.issues import (
    Issue,
    Stage,
    Priority,
    slugify,
    create_issue,
    list_issues,
    get_issue,
    get_agenttrees_path,
)


class TestSlugify:
    """Tests for slugify function."""

    def test_basic_slugify(self):
        assert slugify("Hello World") == "hello-world"

    def test_special_characters(self):
        assert slugify("Fix login bug!") == "fix-login-bug"

    def test_multiple_spaces(self):
        assert slugify("Fix   the   bug") == "fix-the-bug"

    def test_underscores(self):
        assert slugify("fix_the_bug") == "fix-the-bug"

    def test_length_limit(self):
        long_title = "This is a very long title that should be truncated"
        assert len(slugify(long_title)) <= 50


class TestIssueModel:
    """Tests for Issue Pydantic model."""

    def test_create_issue_model(self):
        issue = Issue(
            id="001",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
        )
        assert issue.id == "001"
        assert issue.stage == Stage.BACKLOG
        assert issue.priority == Priority.MEDIUM

    def test_issue_with_all_fields(self):
        issue = Issue(
            id="001",
            slug="test",
            title="Test",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage=Stage.IMPLEMENT,
            substage="code",
            assigned_agent=3,
            branch="agenttree-3/001-test",
            labels=["bug", "critical"],
            priority=Priority.CRITICAL,
        )
        assert issue.stage == Stage.IMPLEMENT
        assert issue.substage == "code"
        assert issue.assigned_agent == 3
        assert "bug" in issue.labels


class TestIssueCRUD:
    """Tests for issue CRUD operations."""

    @pytest.fixture
    def temp_agenttrees(self, monkeypatch, tmp_path):
        """Create a temporary .agenttrees directory."""
        agenttrees_path = tmp_path / ".agenttrees"
        agenttrees_path.mkdir()
        (agenttrees_path / "issues").mkdir()
        (agenttrees_path / "templates").mkdir()

        # Create problem template
        template = agenttrees_path / "templates" / "problem.md"
        template.write_text("# Problem Statement\n\n")

        # Monkeypatch get_agenttrees_path to return our temp dir
        monkeypatch.setattr(
            "agenttree.issues.get_agenttrees_path",
            lambda: agenttrees_path
        )

        return agenttrees_path

    def test_create_issue(self, temp_agenttrees):
        issue = create_issue("Test Issue", Priority.HIGH)

        assert issue.id == "001"
        assert issue.title == "Test Issue"
        assert issue.priority == Priority.HIGH
        assert issue.stage == Stage.BACKLOG

        # Check files created
        issue_dir = temp_agenttrees / "issues" / "001-test-issue"
        assert issue_dir.exists()
        assert (issue_dir / "issue.yaml").exists()
        assert (issue_dir / "problem.md").exists()

    def test_create_multiple_issues(self, temp_agenttrees):
        issue1 = create_issue("First Issue")
        issue2 = create_issue("Second Issue")
        issue3 = create_issue("Third Issue")

        assert issue1.id == "001"
        assert issue2.id == "002"
        assert issue3.id == "003"

    def test_list_issues(self, temp_agenttrees):
        create_issue("Issue A", Priority.LOW)
        create_issue("Issue B", Priority.HIGH)
        create_issue("Issue C", Priority.MEDIUM)

        issues = list_issues()
        assert len(issues) == 3

    def test_list_issues_filter_by_priority(self, temp_agenttrees):
        create_issue("Low Priority", Priority.LOW)
        create_issue("High Priority", Priority.HIGH)

        high_issues = list_issues(priority=Priority.HIGH)
        assert len(high_issues) == 1
        assert high_issues[0].title == "High Priority"

    def test_get_issue_by_id(self, temp_agenttrees):
        create_issue("Test Issue")

        issue = get_issue("001")
        assert issue is not None
        assert issue.title == "Test Issue"

    def test_get_issue_by_id_without_leading_zeros(self, temp_agenttrees):
        create_issue("Test Issue")

        issue = get_issue("1")
        assert issue is not None
        assert issue.id == "001"

    def test_get_issue_not_found(self, temp_agenttrees):
        issue = get_issue("999")
        assert issue is None

    def test_create_issue_with_custom_stage(self, temp_agenttrees):
        """Test creating an issue with a custom starting stage."""
        issue = create_issue("Test Issue", stage=Stage.PROBLEM)

        assert issue.id == "001"
        assert issue.title == "Test Issue"
        assert issue.stage == Stage.PROBLEM

        # Check history entry
        assert len(issue.history) == 1
        assert issue.history[0].stage == "problem"

    def test_create_issue_with_research_stage(self, temp_agenttrees):
        """Test creating an issue starting at research stage."""
        issue = create_issue("Research Task", stage=Stage.RESEARCH, priority=Priority.HIGH)

        assert issue.stage == Stage.RESEARCH
        assert issue.priority == Priority.HIGH
        assert issue.history[0].stage == "research"

    def test_create_issue_with_implement_stage(self, temp_agenttrees):
        """Test creating an issue starting at implement stage."""
        issue = create_issue("Quick Fix", stage=Stage.IMPLEMENT)

        assert issue.stage == Stage.IMPLEMENT
        assert issue.history[0].stage == "implement"

    def test_create_issue_defaults_to_backlog(self, temp_agenttrees):
        """Test that not providing a stage defaults to backlog."""
        issue = create_issue("Default Stage Issue")

        assert issue.stage == Stage.BACKLOG
        assert issue.history[0].stage == "backlog"

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
    get_next_stage,
    update_issue_stage,
    load_skill,
    STAGE_ORDER,
    STAGE_SUBSTAGES,
    HUMAN_REVIEW_STAGES,
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


class TestStageTransitions:
    """Tests for stage transition functions."""

    def test_get_next_stage_from_backlog(self):
        """Backlog -> problem.draft"""
        next_stage, next_substage, is_review = get_next_stage(Stage.BACKLOG, None)
        assert next_stage == Stage.PROBLEM
        assert next_substage == "draft"
        assert is_review is False

    def test_get_next_stage_within_problem_substages(self):
        """problem.draft -> problem.refine"""
        next_stage, next_substage, is_review = get_next_stage(Stage.PROBLEM, "draft")
        assert next_stage == Stage.PROBLEM
        assert next_substage == "refine"
        assert is_review is False

    def test_get_next_stage_problem_to_review(self):
        """problem.refine -> problem_review (human review)"""
        next_stage, next_substage, is_review = get_next_stage(Stage.PROBLEM, "refine")
        assert next_stage == Stage.PROBLEM_REVIEW
        assert next_substage is None
        assert is_review is True

    def test_get_next_stage_from_problem_review(self):
        """problem_review -> research.explore"""
        next_stage, next_substage, is_review = get_next_stage(Stage.PROBLEM_REVIEW, None)
        assert next_stage == Stage.RESEARCH
        assert next_substage == "explore"
        assert is_review is False

    def test_get_next_stage_within_research_substages(self):
        """research.explore -> research.plan"""
        next_stage, next_substage, is_review = get_next_stage(Stage.RESEARCH, "explore")
        assert next_stage == Stage.RESEARCH
        assert next_substage == "plan"
        assert is_review is False

    def test_get_next_stage_research_to_plan_review(self):
        """research.spec -> plan_review (human review)"""
        next_stage, next_substage, is_review = get_next_stage(Stage.RESEARCH, "spec")
        assert next_stage == Stage.PLAN_REVIEW
        assert next_substage is None
        assert is_review is True

    def test_get_next_stage_within_implement_substages(self):
        """implement.test -> implement.code"""
        next_stage, next_substage, is_review = get_next_stage(Stage.IMPLEMENT, "test")
        assert next_stage == Stage.IMPLEMENT
        assert next_substage == "code"
        assert is_review is False

    def test_get_next_stage_implement_to_review(self):
        """implement.code_review -> implementation_review (human review)"""
        next_stage, next_substage, is_review = get_next_stage(Stage.IMPLEMENT, "code_review")
        assert next_stage == Stage.IMPLEMENTATION_REVIEW
        assert next_substage is None
        assert is_review is True

    def test_get_next_stage_to_accepted(self):
        """implementation_review -> accepted"""
        next_stage, next_substage, is_review = get_next_stage(Stage.IMPLEMENTATION_REVIEW, None)
        assert next_stage == Stage.ACCEPTED
        assert next_substage is None
        assert is_review is False

    def test_get_next_stage_at_accepted(self):
        """accepted -> stays at accepted"""
        next_stage, next_substage, is_review = get_next_stage(Stage.ACCEPTED, None)
        assert next_stage == Stage.ACCEPTED
        assert next_substage is None
        assert is_review is False

    def test_human_review_stages(self):
        """Verify HUMAN_REVIEW_STAGES contains expected stages."""
        assert Stage.PROBLEM_REVIEW in HUMAN_REVIEW_STAGES
        assert Stage.PLAN_REVIEW in HUMAN_REVIEW_STAGES
        assert Stage.IMPLEMENTATION_REVIEW in HUMAN_REVIEW_STAGES
        assert len(HUMAN_REVIEW_STAGES) == 3


class TestUpdateIssueStage:
    """Tests for update_issue_stage function."""

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

    def test_update_issue_stage(self, temp_agenttrees):
        """Update issue stage."""
        issue = create_issue("Test Issue")
        assert issue.stage == Stage.BACKLOG

        updated = update_issue_stage("001", Stage.PROBLEM, "draft")
        assert updated is not None
        assert updated.stage == Stage.PROBLEM
        assert updated.substage == "draft"

    def test_update_issue_stage_adds_history(self, temp_agenttrees):
        """Updating stage adds history entry."""
        issue = create_issue("Test Issue")
        assert len(issue.history) == 1

        updated = update_issue_stage("001", Stage.PROBLEM, "draft", agent=1)
        assert len(updated.history) == 2
        assert updated.history[-1].stage == "problem"
        assert updated.history[-1].substage == "draft"
        assert updated.history[-1].agent == 1

    def test_update_issue_stage_not_found(self, temp_agenttrees):
        """Return None for non-existent issue."""
        result = update_issue_stage("999", Stage.PROBLEM)
        assert result is None


class TestLoadSkill:
    """Tests for load_skill function."""

    @pytest.fixture
    def temp_agenttrees_with_skills(self, monkeypatch, tmp_path):
        """Create a temporary .agenttrees directory with skills."""
        agenttrees_path = tmp_path / ".agenttrees"
        agenttrees_path.mkdir()
        (agenttrees_path / "issues").mkdir()
        (agenttrees_path / "skills").mkdir()

        # Create some skill files
        (agenttrees_path / "skills" / "problem.md").write_text("# Problem Skill")
        (agenttrees_path / "skills" / "implement.md").write_text("# Implement Skill")
        (agenttrees_path / "skills" / "implement-test.md").write_text("# Test Substage Skill")

        # Monkeypatch get_agenttrees_path to return our temp dir
        monkeypatch.setattr(
            "agenttree.issues.get_agenttrees_path",
            lambda: agenttrees_path
        )

        return agenttrees_path

    def test_load_stage_skill(self, temp_agenttrees_with_skills):
        """Load skill for stage."""
        skill = load_skill(Stage.PROBLEM)
        assert skill == "# Problem Skill"

    def test_load_substage_skill(self, temp_agenttrees_with_skills):
        """Load skill for substage (falls back to stage skill)."""
        skill = load_skill(Stage.IMPLEMENT, "code")
        assert skill == "# Implement Skill"

    def test_load_specific_substage_skill(self, temp_agenttrees_with_skills):
        """Load skill for specific substage when available."""
        skill = load_skill(Stage.IMPLEMENT, "test")
        assert skill == "# Test Substage Skill"

    def test_load_skill_not_found(self, temp_agenttrees_with_skills):
        """Return None when skill not found."""
        skill = load_skill(Stage.ACCEPTED)
        assert skill is None

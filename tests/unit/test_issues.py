"""Tests for agenttree.issues module."""

import tempfile
from pathlib import Path

import pytest

from agenttree.issues import (
    Issue,
    Priority,
    slugify,
    create_issue,
    list_issues,
    get_issue,
    get_agenttree_path,
    get_next_stage,
    update_issue_stage,
    load_skill,
    STAGE_ORDER,
    STAGE_SUBSTAGES,
    HUMAN_REVIEW_STAGES,
    # Stage constants (strings, not enum)
    BACKLOG,
    DEFINE,
    PROBLEM_REVIEW,
    RESEARCH,
    PLAN,
    PLAN_ASSESS,
    PLAN_REVISE,
    PLAN_REVIEW,
    IMPLEMENT,
    IMPLEMENTATION_REVIEW,
    ACCEPTED,
    NOT_DOING,
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
        assert issue.stage == BACKLOG
        assert issue.priority == Priority.MEDIUM

    def test_issue_with_all_fields(self):
        issue = Issue(
            id="001",
            slug="test",
            title="Test",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage=IMPLEMENT,
            substage="code",
            assigned_agent=3,
            branch="agenttree-3/001-test",
            labels=["bug", "critical"],
            priority=Priority.CRITICAL,
        )
        assert issue.stage == IMPLEMENT
        assert issue.substage == "code"
        assert issue.assigned_agent == 3
        assert "bug" in issue.labels


class TestIssueCRUD:
    """Tests for issue CRUD operations."""

    @pytest.fixture
    def temp_agenttrees(self, monkeypatch, tmp_path):
        """Create a temporary _agenttree directory."""
        agenttrees_path = tmp_path / "_agenttree"
        agenttrees_path.mkdir()
        (agenttrees_path / "issues").mkdir()
        (agenttrees_path / "templates").mkdir()

        # Create problem template
        template = agenttrees_path / "templates" / "problem.md"
        template.write_text("# Problem Statement\n\n")

        # Monkeypatch get_agenttree_path to return our temp dir
        monkeypatch.setattr(
            "agenttree.issues.get_agenttree_path",
            lambda: agenttrees_path
        )

        return agenttrees_path

    def test_create_issue(self, temp_agenttrees):
        issue = create_issue("Test Issue", Priority.HIGH)

        assert issue.id == "001"
        assert issue.title == "Test Issue"
        assert issue.priority == Priority.HIGH
        assert issue.stage == BACKLOG

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
        issue = create_issue("Test Issue", stage=DEFINE)

        assert issue.id == "001"
        assert issue.title == "Test Issue"
        assert issue.stage == DEFINE

        # Check history entry
        assert len(issue.history) == 1
        assert issue.history[0].stage == "define"

    def test_create_issue_with_research_stage(self, temp_agenttrees):
        """Test creating an issue starting at research stage."""
        issue = create_issue("Research Task", stage=RESEARCH, priority=Priority.HIGH)

        assert issue.stage == RESEARCH
        assert issue.priority == Priority.HIGH
        assert issue.history[0].stage == "research"

    def test_create_issue_with_implement_stage(self, temp_agenttrees):
        """Test creating an issue starting at implement stage."""
        issue = create_issue("Quick Fix", stage=IMPLEMENT)

        assert issue.stage == IMPLEMENT
        assert issue.history[0].stage == "implement"

    def test_create_issue_defaults_to_backlog(self, temp_agenttrees):
        """Test that not providing a stage defaults to backlog."""
        issue = create_issue("Default Stage Issue")

        assert issue.stage == BACKLOG
        assert issue.history[0].stage == "backlog"


class TestStageTransitions:
    """Tests for stage transition functions.

    New stage flow:
    backlog -> define -> problem_review -> research -> plan -> plan_assess ->
    plan_revise -> plan_review -> implement -> implementation_review -> accepted
    """

    def test_get_next_stage_from_backlog(self):
        """Backlog -> define.draft"""
        next_stage, next_substage, is_review = get_next_stage(BACKLOG, None)
        assert next_stage == DEFINE
        assert next_substage == "draft"
        assert is_review is False

    def test_get_next_stage_within_define_substages(self):
        """define.draft -> define.refine"""
        next_stage, next_substage, is_review = get_next_stage(DEFINE, "draft")
        assert next_stage == DEFINE
        assert next_substage == "refine"
        assert is_review is False

    def test_get_next_stage_define_to_review(self):
        """define.refine -> problem_review (human review)"""
        next_stage, next_substage, is_review = get_next_stage(DEFINE, "refine")
        assert next_stage == PROBLEM_REVIEW
        assert next_substage is None
        assert is_review is True

    def test_get_next_stage_from_problem_review(self):
        """problem_review -> research.explore"""
        next_stage, next_substage, is_review = get_next_stage(PROBLEM_REVIEW, None)
        assert next_stage == RESEARCH
        assert next_substage == "explore"
        assert is_review is False

    def test_get_next_stage_within_research_substages(self):
        """research.explore -> research.document"""
        next_stage, next_substage, is_review = get_next_stage(RESEARCH, "explore")
        assert next_stage == RESEARCH
        assert next_substage == "document"
        assert is_review is False

    def test_get_next_stage_research_to_plan(self):
        """research.document -> plan.draft (not directly to plan_review)"""
        next_stage, next_substage, is_review = get_next_stage(RESEARCH, "document")
        assert next_stage == PLAN
        assert next_substage == "draft"
        assert is_review is False

    def test_get_next_stage_plan_to_plan_assess(self):
        """plan.refine -> plan_assess"""
        next_stage, next_substage, is_review = get_next_stage(PLAN, "refine")
        assert next_stage == PLAN_ASSESS
        assert next_substage is None
        assert is_review is False

    def test_get_next_stage_plan_assess_to_plan_revise(self):
        """plan_assess -> plan_revise"""
        next_stage, next_substage, is_review = get_next_stage(PLAN_ASSESS, None)
        assert next_stage == PLAN_REVISE
        assert next_substage is None
        assert is_review is False

    def test_get_next_stage_plan_revise_to_plan_review(self):
        """plan_revise -> plan_review (human review)"""
        next_stage, next_substage, is_review = get_next_stage(PLAN_REVISE, None)
        assert next_stage == PLAN_REVIEW
        assert next_substage is None
        assert is_review is True

    def test_get_next_stage_within_implement_substages(self):
        """implement.test -> implement.code"""
        next_stage, next_substage, is_review = get_next_stage(IMPLEMENT, "test")
        assert next_stage == IMPLEMENT
        assert next_substage == "code"
        assert is_review is False

    def test_get_next_stage_implement_code_review_to_address_review(self):
        """implement.code_review -> implement.address_review"""
        next_stage, next_substage, is_review = get_next_stage(IMPLEMENT, "code_review")
        assert next_stage == IMPLEMENT
        assert next_substage == "address_review"
        assert is_review is False

    def test_get_next_stage_implement_to_wrapup(self):
        """implement.address_review -> implement.wrapup"""
        next_stage, next_substage, is_review = get_next_stage(IMPLEMENT, "address_review")
        assert next_stage == IMPLEMENT
        assert next_substage == "wrapup"
        assert is_review is False

    def test_get_next_stage_wrapup_to_review(self):
        """implement.wrapup -> implementation_review (human review)"""
        next_stage, next_substage, is_review = get_next_stage(IMPLEMENT, "wrapup")
        assert next_stage == IMPLEMENTATION_REVIEW
        assert next_substage is None
        assert is_review is True

    def test_get_next_stage_to_accepted(self):
        """implementation_review -> accepted"""
        next_stage, next_substage, is_review = get_next_stage(IMPLEMENTATION_REVIEW, None)
        assert next_stage == ACCEPTED
        assert next_substage is None
        assert is_review is False

    def test_get_next_stage_at_accepted(self):
        """accepted -> stays at accepted"""
        next_stage, next_substage, is_review = get_next_stage(ACCEPTED, None)
        assert next_stage == ACCEPTED
        assert next_substage is None
        assert is_review is False

    def test_human_review_stages(self):
        """Verify HUMAN_REVIEW_STAGES contains expected stages."""
        assert PROBLEM_REVIEW in HUMAN_REVIEW_STAGES
        assert PLAN_REVIEW in HUMAN_REVIEW_STAGES
        assert IMPLEMENTATION_REVIEW in HUMAN_REVIEW_STAGES
        assert len(HUMAN_REVIEW_STAGES) == 3

    def test_get_next_stage_not_doing_stays_not_doing(self):
        """NOT_DOING is a terminal state - stays at NOT_DOING."""
        next_stage, next_substage, is_review = get_next_stage(NOT_DOING, None)
        assert next_stage == NOT_DOING
        assert next_substage is None
        assert is_review is False


class TestUpdateIssueStage:
    """Tests for update_issue_stage function."""

    @pytest.fixture
    def temp_agenttrees(self, monkeypatch, tmp_path):
        """Create a temporary _agenttree directory."""
        agenttrees_path = tmp_path / "_agenttree"
        agenttrees_path.mkdir()
        (agenttrees_path / "issues").mkdir()
        (agenttrees_path / "templates").mkdir()

        # Create problem template
        template = agenttrees_path / "templates" / "problem.md"
        template.write_text("# Problem Statement\n\n")

        # Monkeypatch get_agenttree_path to return our temp dir
        monkeypatch.setattr(
            "agenttree.issues.get_agenttree_path",
            lambda: agenttrees_path
        )

        return agenttrees_path

    def test_update_issue_stage(self, temp_agenttrees):
        """Update issue stage."""
        issue = create_issue("Test Issue")
        assert issue.stage == BACKLOG

        updated = update_issue_stage("001", DEFINE, "draft")
        assert updated is not None
        assert updated.stage == DEFINE
        assert updated.substage == "draft"

    def test_update_issue_stage_adds_history(self, temp_agenttrees):
        """Updating stage adds history entry."""
        issue = create_issue("Test Issue")
        assert len(issue.history) == 1

        updated = update_issue_stage("001", DEFINE, "draft", agent=1)
        assert len(updated.history) == 2
        assert updated.history[-1].stage == "define"
        assert updated.history[-1].substage == "draft"
        assert updated.history[-1].agent == 1

    def test_update_issue_stage_not_found(self, temp_agenttrees):
        """Return None for non-existent issue."""
        result = update_issue_stage("999", DEFINE)
        assert result is None


class TestLoadSkill:
    """Tests for load_skill function."""

    @pytest.fixture
    def temp_agenttrees_with_skills(self, monkeypatch, tmp_path):
        """Create a temporary _agenttree directory with skills."""
        agenttrees_path = tmp_path / "_agenttree"
        agenttrees_path.mkdir()
        (agenttrees_path / "issues").mkdir()
        (agenttrees_path / "skills").mkdir()

        # Create some skill files (using new naming convention)
        (agenttrees_path / "skills" / "define.md").write_text("# Define Skill")
        (agenttrees_path / "skills" / "implement.md").write_text("# Implement Skill")
        (agenttrees_path / "skills" / "implement-test.md").write_text("# Test Substage Skill")

        # Monkeypatch get_agenttree_path to return our temp dir
        monkeypatch.setattr(
            "agenttree.issues.get_agenttree_path",
            lambda: agenttrees_path
        )

        return agenttrees_path

    def test_load_define_stage_skill(self, temp_agenttrees_with_skills):
        """Load skill for DEFINE stage."""
        skill = load_skill(DEFINE)
        assert skill == "# Define Skill"

    def test_load_substage_skill(self, temp_agenttrees_with_skills):
        """Load skill for substage (falls back to stage skill)."""
        skill = load_skill(IMPLEMENT, "code")
        assert skill == "# Implement Skill"

    def test_load_specific_substage_skill(self, temp_agenttrees_with_skills):
        """Load skill for specific substage when available."""
        skill = load_skill(IMPLEMENT, "test")
        assert skill == "# Test Substage Skill"

    def test_load_skill_not_found(self, temp_agenttrees_with_skills):
        """Return None when skill not found."""
        skill = load_skill(ACCEPTED)
        assert skill is None


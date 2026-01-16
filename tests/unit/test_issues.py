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
        assert issue.stage == DEFINE  # New issues start at define stage
        assert issue.substage == "refine"  # Human provides draft, agent refines
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
            assigned_agent="3",
            branch="agenttree-3/001-test",
            labels=["bug", "critical"],
            priority=Priority.CRITICAL,
        )
        assert issue.stage == IMPLEMENT
        assert issue.substage == "code"
        assert issue.assigned_agent == "3"
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
        assert issue.stage == DEFINE  # New issues start at define stage
        assert issue.substage == "refine"  # Human provides draft, agent refines

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

    def test_create_issue_defaults_to_define(self, temp_agenttrees):
        """Test that not providing a stage defaults to define.refine."""
        issue = create_issue("Default Stage Issue")

        assert issue.stage == DEFINE
        assert issue.substage == "refine"
        assert issue.history[0].stage == "define"
        assert issue.history[0].substage == "refine"


class TestStageTransitions:
    """Tests for stage transition functions.

    Stage flow (no problem_review gate):
    backlog -> define -> research -> plan -> plan_assess ->
    plan_revise -> plan_review -> implement -> implementation_review -> accepted
    """

    def test_get_next_stage_from_backlog(self):
        """Backlog -> define.refine"""
        next_stage, next_substage, is_review = get_next_stage(BACKLOG, None)
        assert next_stage == DEFINE
        assert next_substage == "refine"
        assert is_review is False

    def test_get_next_stage_define_to_research(self):
        """define.refine -> research.explore (no problem_review gate)"""
        next_stage, next_substage, is_review = get_next_stage(DEFINE, "refine")
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
        """implement.setup -> implement.code"""
        next_stage, next_substage, is_review = get_next_stage(IMPLEMENT, "setup")
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

    def test_get_next_stage_wrapup_to_feedback(self):
        """implement.wrapup -> implement.feedback"""
        next_stage, next_substage, is_review = get_next_stage(IMPLEMENT, "wrapup")
        assert next_stage == IMPLEMENT
        assert next_substage == "feedback"
        assert is_review is False

    def test_get_next_stage_feedback_to_review(self):
        """implement.feedback -> implementation_review (human review)"""
        next_stage, next_substage, is_review = get_next_stage(IMPLEMENT, "feedback")
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
        assert PLAN_REVIEW in HUMAN_REVIEW_STAGES
        assert IMPLEMENTATION_REVIEW in HUMAN_REVIEW_STAGES
        assert len(HUMAN_REVIEW_STAGES) == 2

    def test_get_next_stage_not_doing_stays_not_doing(self):
        """NOT_DOING is a terminal state - stays at NOT_DOING."""
        next_stage, next_substage, is_review = get_next_stage(NOT_DOING, None)
        assert next_stage == NOT_DOING
        assert next_substage is None
        assert is_review is False


class TestDependencies:
    """Tests for dependency-related functions."""

    @pytest.fixture
    def temp_agenttrees_deps(self, monkeypatch, tmp_path):
        """Create a temporary _agenttree directory with issues."""
        agenttrees_path = tmp_path / "_agenttree"
        agenttrees_path.mkdir()
        issues_path = agenttrees_path / "issues"
        issues_path.mkdir()
        (agenttrees_path / "templates").mkdir()

        # Create problem template
        template = agenttrees_path / "templates" / "problem.md"
        template.write_text("# Problem Statement\n\n")

        # Monkeypatch get_agenttree_path to return our temp dir
        monkeypatch.setattr(
            "agenttree.issues.get_agenttree_path",
            lambda: agenttrees_path
        )

        # Disable sync to avoid git operations
        monkeypatch.setattr("agenttree.issues.sync_agents_repo", lambda *args, **kwargs: True)

        return agenttrees_path

    def test_check_dependencies_met_no_deps(self, temp_agenttrees_deps):
        """Issue with no dependencies should return all_met=True."""
        from agenttree.issues import check_dependencies_met

        issue = create_issue("No deps issue")
        all_met, unmet = check_dependencies_met(issue)

        assert all_met is True
        assert unmet == []

    def test_check_dependencies_met_with_completed_dep(self, temp_agenttrees_deps):
        """Issue with completed dependency should return all_met=True."""
        from agenttree.issues import check_dependencies_met, update_issue_stage

        # Create dependency issue and mark as accepted
        dep_issue = create_issue("Dependency Issue")
        update_issue_stage(dep_issue.id, ACCEPTED, None)

        # Create issue with dependency
        dependent_issue = create_issue("Dependent Issue", dependencies=[dep_issue.id])

        all_met, unmet = check_dependencies_met(dependent_issue)

        assert all_met is True
        assert unmet == []

    def test_check_dependencies_met_with_incomplete_dep(self, temp_agenttrees_deps):
        """Issue with incomplete dependency should return all_met=False."""
        from agenttree.issues import check_dependencies_met

        # Create dependency issue (starts at define stage)
        dep_issue = create_issue("Dependency Issue")

        # Create issue with dependency
        dependent_issue = create_issue("Dependent Issue", dependencies=[dep_issue.id])

        all_met, unmet = check_dependencies_met(dependent_issue)

        assert all_met is False
        assert dep_issue.id in unmet

    def test_check_dependencies_met_with_nonexistent_dep(self, temp_agenttrees_deps):
        """Issue with nonexistent dependency should return all_met=False."""
        from agenttree.issues import check_dependencies_met

        issue = create_issue("Test Issue", dependencies=["999"])

        all_met, unmet = check_dependencies_met(issue)

        assert all_met is False
        assert "999" in unmet

    def test_get_blocked_issues(self, temp_agenttrees_deps):
        """get_blocked_issues should return issues in backlog waiting on a dependency."""
        from agenttree.issues import get_blocked_issues

        # Create completed issue
        completed = create_issue("Completed Issue")

        # Create blocked issue in backlog with dependency
        blocked = create_issue("Blocked Issue", stage=BACKLOG, dependencies=[completed.id])

        # Get issues blocked by completed issue
        blocked_issues = get_blocked_issues(completed.id)

        assert len(blocked_issues) == 1
        assert blocked_issues[0].id == blocked.id

    def test_get_blocked_issues_empty(self, temp_agenttrees_deps):
        """get_blocked_issues should return empty list if no blocked issues."""
        from agenttree.issues import get_blocked_issues

        issue = create_issue("No dependents")
        blocked_issues = get_blocked_issues(issue.id)

        assert blocked_issues == []

    def test_get_ready_issues(self, temp_agenttrees_deps):
        """get_ready_issues should return backlog issues with all deps met."""
        from agenttree.issues import get_ready_issues, update_issue_stage

        # Create dependency and mark as accepted
        dep = create_issue("Dependency")
        update_issue_stage(dep.id, ACCEPTED, None)

        # Create blocked issue in backlog
        blocked = create_issue("Blocked Issue", stage=BACKLOG, dependencies=[dep.id])

        ready = get_ready_issues()

        assert len(ready) == 1
        assert ready[0].id == blocked.id

    def test_create_issue_with_dependencies(self, temp_agenttrees_deps):
        """create_issue should normalize and store dependencies."""
        issue = create_issue("Test Issue", dependencies=["1", "02", "003"])

        # Dependencies should be normalized to 3-digit format
        assert issue.dependencies == ["001", "002", "003"]


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
        assert issue.stage == DEFINE  # New issues start at define

        updated = update_issue_stage("001", RESEARCH, "explore")
        assert updated is not None
        assert updated.stage == RESEARCH
        assert updated.substage == "explore"

    def test_update_issue_stage_adds_history(self, temp_agenttrees):
        """Updating stage adds history entry."""
        issue = create_issue("Test Issue")
        assert len(issue.history) == 1

        updated = update_issue_stage("001", RESEARCH, "explore", agent=1)
        assert len(updated.history) == 2
        assert updated.history[-1].stage == "research"
        assert updated.history[-1].substage == "explore"
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


class TestSessionManagement:
    """Tests for session management (restart detection)."""

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
        # Also monkeypatch sync to do nothing
        monkeypatch.setattr(
            "agenttree.issues.sync_agents_repo",
            lambda *args, **kwargs: True
        )

        return agenttrees_path

    def test_create_session(self, temp_agenttrees):
        """Create a new session for an issue."""
        from agenttree.issues import create_session, get_session

        issue = create_issue("Test Issue")
        session = create_session(issue.id)

        assert session.issue_id == issue.id
        assert session.oriented is False
        assert session.session_id is not None

        # Session should be retrievable
        loaded = get_session(issue.id)
        assert loaded is not None
        assert loaded.session_id == session.session_id

    def test_is_restart_false_for_new_session(self, temp_agenttrees):
        """Fresh session (just created) is not a restart - it's oriented=False initially."""
        from agenttree.issues import create_session, is_restart

        issue = create_issue("Test Issue")
        create_session(issue.id)

        # New session with oriented=False means is_restart returns True
        # because agent hasn't been oriented yet
        assert is_restart(issue.id) is True

    def test_is_restart_false_after_orientation(self, temp_agenttrees):
        """After marking oriented, is_restart returns False."""
        from agenttree.issues import create_session, is_restart, mark_session_oriented

        issue = create_issue("Test Issue")
        create_session(issue.id)
        mark_session_oriented(issue.id)

        assert is_restart(issue.id) is False

    def test_is_restart_false_no_session(self, temp_agenttrees):
        """No session = not a restart (fresh start)."""
        from agenttree.issues import is_restart

        issue = create_issue("Test Issue")
        # Don't create session

        assert is_restart(issue.id) is False

    def test_update_session_stage(self, temp_agenttrees):
        """Updating session stage also marks it as oriented."""
        from agenttree.issues import create_session, get_session, update_session_stage

        issue = create_issue("Test Issue")
        create_session(issue.id)

        update_session_stage(issue.id, RESEARCH, "explore")

        session = get_session(issue.id)
        assert session.last_stage == RESEARCH
        assert session.last_substage == "explore"
        assert session.oriented is True

    def test_delete_session(self, temp_agenttrees):
        """Deleting session removes the file."""
        from agenttree.issues import create_session, get_session, delete_session

        issue = create_issue("Test Issue")
        create_session(issue.id)

        # Session exists
        assert get_session(issue.id) is not None

        delete_session(issue.id)

        # Session is gone
        assert get_session(issue.id) is None


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
    get_issue_context,
    get_issue_dir,
    get_agenttree_path,
    get_next_stage,
    update_issue_stage,
    update_issue_priority,
    load_skill,
    set_processing,
    resolve_conflict_markers,
    safe_yaml_load,
)


class TestResolveConflictMarkers:
    """Tests for resolve_conflict_markers function."""

    def test_no_conflict_markers(self):
        """Content without conflict markers should be unchanged."""
        content = "stage: implement\nsubstage: code\n"
        resolved, had_conflicts = resolve_conflict_markers(content)
        assert resolved == content
        assert had_conflicts is False

    def test_simple_conflict_resolution(self):
        """Should resolve conflict by keeping local (ours) content."""
        content = """id: '001'
<<<<<<< Updated upstream
stage: research
=======
stage: implement
>>>>>>> Stashed changes
substage: code
"""
        resolved, had_conflicts = resolve_conflict_markers(content)
        assert had_conflicts is True
        assert "stage: implement" in resolved
        assert "stage: research" not in resolved
        assert "<<<<<<<" not in resolved
        assert "=======" not in resolved
        assert ">>>>>>>" not in resolved

    def test_multiple_conflicts(self):
        """Should resolve multiple conflict blocks."""
        content = """id: '001'
<<<<<<< HEAD
stage: research
=======
stage: implement
>>>>>>> local
pr_number: null
<<<<<<< HEAD
substage: explore
=======
substage: code
>>>>>>> local
"""
        resolved, had_conflicts = resolve_conflict_markers(content)
        assert had_conflicts is True
        assert "stage: implement" in resolved
        assert "substage: code" in resolved
        assert "stage: research" not in resolved
        assert "substage: explore" not in resolved

    def test_conflict_with_multiline_content(self):
        """Should handle conflicts with multiple lines on each side."""
        content = """id: '001'
<<<<<<< Updated upstream
stage: research
substage: explore
pr_number: 42
=======
stage: implement
substage: code
pr_number: null
>>>>>>> Stashed changes
"""
        resolved, had_conflicts = resolve_conflict_markers(content)
        assert had_conflicts is True
        assert "stage: implement" in resolved
        assert "substage: code" in resolved
        assert "pr_number: null" in resolved
        assert "pr_number: 42" not in resolved


class TestSafeYamlLoad:
    """Tests for safe_yaml_load function."""

    def test_load_clean_yaml(self, tmp_path):
        """Should load YAML file without conflicts."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("id: '001'\nstage: implement\n")

        data = safe_yaml_load(yaml_file)
        assert data["id"] == "001"
        assert data["stage"] == "implement"

    def test_load_and_fix_conflicted_yaml(self, tmp_path):
        """Should auto-fix conflict markers and load YAML."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("""id: '001'
<<<<<<< Updated upstream
stage: research
=======
stage: implement
>>>>>>> Stashed changes
substage: code
""")

        data = safe_yaml_load(yaml_file)
        assert data["id"] == "001"
        assert data["stage"] == "implement"
        assert data["substage"] == "code"

        # File should be fixed on disk
        fixed_content = yaml_file.read_text()
        assert "<<<<<<<" not in fixed_content
        assert "stage: implement" in fixed_content

    def test_file_not_found(self, tmp_path):
        """Should raise FileNotFoundError for missing files."""
        yaml_file = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError):
            safe_yaml_load(yaml_file)


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
        assert issue.id == 1
        assert issue.stage == "explore.define"  # New issues start at explore.define
        assert issue.priority == Priority.MEDIUM

    def test_issue_with_all_fields(self):
        issue = Issue(
            id="001",
            slug="test",
            title="Test",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage="implement.code",
            branch="agenttree-3/001-test",
            labels=["bug", "critical"],
            priority=Priority.CRITICAL,
        )
        assert issue.stage == "implement.code"
        assert "bug" in issue.labels

    def test_processing_field_defaults_to_none(self):
        """Processing field should default to None."""
        issue = Issue(
            id="001",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
        )
        assert issue.processing is None

    def test_processing_field_can_be_set(self):
        """Processing field can be set to a string value."""
        issue = Issue(
            id="001",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            processing="exit",
        )
        assert issue.processing == "exit"


class TestProcessingHelpers:
    """Tests for set_processing helper function."""

    @pytest.fixture
    def temp_agenttrees_with_issue(self, monkeypatch, tmp_path):
        """Create a temporary _agenttree directory with an issue."""
        import yaml

        agenttrees_path = tmp_path / "_agenttree"
        agenttrees_path.mkdir()
        (agenttrees_path / "issues").mkdir()

        # Create an issue directory and issue.yaml
        issue_dir = agenttrees_path / "issues" / "001"
        issue_dir.mkdir()

        issue_data = {
            "id": "001",
            "slug": "test-issue",
            "title": "Test Issue",
            "created": "2026-01-11T12:00:00Z",
            "updated": "2026-01-11T12:00:00Z",
            "stage": "explore.define",
            "labels": [],
            "priority": "medium",
            "dependencies": [],
            "history": [],
        }

        with open(issue_dir / "issue.yaml", "w") as f:
            yaml.dump(issue_data, f, default_flow_style=False, sort_keys=False)

        # Monkeypatch get_agenttree_path to return our temp dir
        monkeypatch.setattr(
            "agenttree.issues.get_agenttree_path",
            lambda: agenttrees_path
        )

        return agenttrees_path

    def test_set_processing_sets_state(self, temp_agenttrees_with_issue):
        """set_processing should set the processing field in issue.yaml."""
        import yaml

        result = set_processing("001", "exit")
        assert result is True

        # Verify it was written to issue.yaml
        issue_yaml = temp_agenttrees_with_issue / "issues" / "001" / "issue.yaml"
        with open(issue_yaml) as f:
            data = yaml.safe_load(f)
        assert data["processing"] == "exit"

    def test_set_processing_returns_false_for_missing_issue(self, temp_agenttrees_with_issue):
        """set_processing should return False for nonexistent issue."""
        result = set_processing("999", "exit")
        assert result is False

    def test_set_processing_clears_state_with_none(self, temp_agenttrees_with_issue):
        """set_processing(id, None) should clear the processing state."""
        import yaml

        # First set processing
        set_processing("001", "exit")

        # Then clear it by passing None
        result = set_processing("001", None)
        assert result is True

        # Verify it was cleared in issue.yaml
        issue_yaml = temp_agenttrees_with_issue / "issues" / "001" / "issue.yaml"
        with open(issue_yaml) as f:
            data = yaml.safe_load(f)
        assert data.get("processing") is None


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

        assert issue.id == 1
        assert issue.title == "Test Issue"
        assert issue.priority == Priority.HIGH
        assert issue.stage == "explore.define"  # New issues start at explore.define

        # Check files created
        issue_dir = temp_agenttrees / "issues" / "001"
        assert issue_dir.exists()
        assert (issue_dir / "issue.yaml").exists()
        assert (issue_dir / "problem.md").exists()

    def test_create_multiple_issues(self, temp_agenttrees):
        issue1 = create_issue("First Issue")
        issue2 = create_issue("Second Issue")
        issue3 = create_issue("Third Issue")

        assert issue1.id == 1
        assert issue2.id == 2
        assert issue3.id == 3

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
        assert issue.id == 1

    def test_get_issue_not_found(self, temp_agenttrees):
        issue = get_issue("999")
        assert issue is None


    def test_create_issue_with_custom_stage(self, temp_agenttrees):
        """Test creating an issue with a custom starting stage."""
        issue = create_issue("Test Issue", stage="explore.define")

        assert issue.id == 1
        assert issue.title == "Test Issue"
        assert issue.stage == "explore.define"

        # Check history entry
        assert len(issue.history) == 1
        assert issue.history[0].stage == "explore.define"

    def test_create_issue_with_research_stage(self, temp_agenttrees):
        """Test creating an issue starting at research stage."""
        issue = create_issue("Research Task", stage="explore.research", priority=Priority.HIGH)

        assert issue.stage == "explore.research"
        assert issue.priority == Priority.HIGH
        assert issue.history[0].stage == "explore.research"

    def test_create_issue_with_implement_stage(self, temp_agenttrees):
        """Test creating an issue starting at implement stage."""
        issue = create_issue("Quick Fix", stage="implement.code")

        assert issue.stage == "implement.code"
        assert issue.history[0].stage == "implement.code"

    def test_create_issue_defaults_to_define(self, temp_agenttrees):
        """Test that not providing a stage defaults to explore.define."""
        issue = create_issue("Default Stage Issue")

        assert issue.stage == "explore.define"
        assert issue.history[0].stage == "explore.define"


class TestStageTransitions:
    """Tests for stage transition functions.

    Stage flow (dot paths):
    backlog -> explore.define -> explore.research -> plan.draft -> plan.assess ->
    plan.revise -> plan.review -> implement.code -> implement.independent_review ->
    implement.review -> knowledge_base -> accepted
    """

    def test_get_next_stage_from_backlog(self):
        """backlog -> explore.define"""
        next_stage, is_review = get_next_stage("backlog")
        assert next_stage == "explore.define"
        assert is_review is False

    def test_get_next_stage_define_to_research(self):
        """explore.define -> explore.research"""
        next_stage, is_review = get_next_stage("explore.define")
        assert next_stage == "explore.research"
        assert is_review is False

    def test_get_next_stage_research_to_plan(self):
        """explore.research -> plan.draft"""
        next_stage, is_review = get_next_stage("explore.research")
        assert next_stage == "plan.draft"
        assert is_review is False

    def test_get_next_stage_plan_draft_to_plan_assess(self):
        """plan.draft -> plan.assess"""
        next_stage, is_review = get_next_stage("plan.draft")
        assert next_stage == "plan.assess"
        assert is_review is False

    def test_get_next_stage_plan_assess_to_plan_revise(self):
        """plan.assess -> plan.revise"""
        next_stage, is_review = get_next_stage("plan.assess")
        assert next_stage == "plan.revise"
        assert is_review is False

    def test_get_next_stage_plan_revise_to_plan_review(self):
        """plan.revise -> plan.review (human review)"""
        next_stage, is_review = get_next_stage("plan.revise")
        assert next_stage == "plan.review"
        assert is_review is True

    def test_get_next_stage_plan_review_to_implement(self):
        """plan.review -> implement.setup"""
        next_stage, is_review = get_next_stage("plan.review")
        assert next_stage == "implement.setup"
        assert is_review is False

    def test_get_next_stage_implement_to_debug(self):
        """implement.code -> implement.debug"""
        next_stage, is_review = get_next_stage("implement.code")
        assert next_stage == "implement.debug"
        assert is_review is False

    def test_get_next_stage_independent_review_to_ci_wait(self):
        """implement.independent_review -> implement.ci_wait (conditional stages skipped)"""
        next_stage, is_review = get_next_stage("implement.independent_review")
        assert next_stage == "implement.ci_wait"
        assert is_review is False

    def test_get_next_stage_to_knowledge_base(self):
        """implement.review -> knowledge_base"""
        next_stage, is_review = get_next_stage("implement.review")
        assert next_stage == "knowledge_base"
        assert is_review is False

    def test_get_next_stage_at_knowledge_base(self):
        """knowledge_base -> accepted"""
        next_stage, is_review = get_next_stage("knowledge_base")
        assert next_stage == "accepted"
        assert is_review is False

    def test_get_next_stage_at_accepted(self):
        """accepted -> stays at accepted (terminal)"""
        next_stage, is_review = get_next_stage("accepted")
        assert next_stage == "accepted"
        assert is_review is False

    def test_human_review_stages(self):
        """Verify human review stages via config."""
        from agenttree.config import load_config

        config = load_config()
        human_review_stages = config.get_human_review_stages()
        assert "plan.review" in human_review_stages
        assert "implement.review" in human_review_stages

    def test_get_next_stage_not_doing_stays_not_doing(self):
        """not_doing is a terminal state - stays at not_doing."""
        next_stage, is_review = get_next_stage("not_doing")
        assert next_stage == "not_doing"
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
        update_issue_stage(dep_issue.id, "accepted")

        # Create issue with dependency
        dependent_issue = create_issue("Dependent Issue", dependencies=[dep_issue.id])

        all_met, unmet = check_dependencies_met(dependent_issue)

        assert all_met is True
        assert unmet == []

    def test_check_dependencies_met_with_incomplete_dep(self, temp_agenttrees_deps):
        """Issue with incomplete dependency should return all_met=False."""
        from agenttree.issues import check_dependencies_met

        # Create dependency issue (starts at explore.define stage)
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
        assert 999 in unmet

    def test_get_blocked_issues(self, temp_agenttrees_deps):
        """get_blocked_issues should return issues in backlog waiting on a dependency."""
        from agenttree.issues import get_blocked_issues

        # Create completed issue
        completed = create_issue("Completed Issue")

        # Create blocked issue in backlog with dependency
        blocked = create_issue("Blocked Issue", stage="backlog", dependencies=[completed.id])

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

    def test_get_dependent_issues(self, temp_agenttrees_deps):
        """get_dependent_issues should return all issues depending on a given issue."""
        from agenttree.issues import get_dependent_issues, update_issue_stage

        # Create a base issue
        base = create_issue("Base Issue")

        # Create issues that depend on it (in various stages)
        dep1 = create_issue("Dependent 1 Backlog", stage="backlog", dependencies=[base.id])
        dep2 = create_issue("Dependent 2 Define", dependencies=[base.id])  # default: explore.define
        dep3 = create_issue("Dependent 3 Implement")
        update_issue_stage(dep3.id, "implement.code")
        # Add dependency after stage change
        from agenttree.issues import get_issue_dir
        import yaml
        issue_dir = get_issue_dir(dep3.id)
        yaml_path = issue_dir / "issue.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        data["dependencies"] = [base.id]
        with open(yaml_path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

        # Get dependents - should include all stages
        dependents = get_dependent_issues(base.id)

        assert len(dependents) == 3
        dependent_ids = {d.id for d in dependents}
        assert dep1.id in dependent_ids
        assert dep2.id in dependent_ids
        assert dep3.id in dependent_ids

    def test_get_dependent_issues_empty(self, temp_agenttrees_deps):
        """get_dependent_issues should return empty list if no dependents."""
        from agenttree.issues import get_dependent_issues

        issue = create_issue("No dependents")
        dependents = get_dependent_issues(issue.id)

        assert dependents == []

    def test_get_ready_issues(self, temp_agenttrees_deps):
        """get_ready_issues should return backlog issues with all deps met."""
        from agenttree.issues import get_ready_issues, update_issue_stage

        # Create dependency and mark as accepted
        dep = create_issue("Dependency")
        update_issue_stage(dep.id, "accepted")

        # Create blocked issue in backlog
        blocked = create_issue("Blocked Issue", stage="backlog", dependencies=[dep.id])

        ready = get_ready_issues()

        assert len(ready) == 1
        assert ready[0].id == blocked.id

    def test_create_issue_with_dependencies(self, temp_agenttrees_deps):
        """create_issue should normalize and store dependencies."""
        # First create the dependency issues
        dep1 = create_issue("Dependency 1")  # 001
        dep2 = create_issue("Dependency 2")  # 002
        dep3 = create_issue("Dependency 3")  # 003

        # Now create an issue that depends on them (using various formats)
        issue = create_issue("Test Issue", dependencies=["1", "02", "003"])

        # Dependencies should be ints
        assert issue.dependencies == [1, 2, 3]

    def test_detect_circular_dependency_none(self, temp_agenttrees_deps):
        """No circular dependency when deps are valid."""
        from agenttree.issues import detect_circular_dependency

        # Create issue A
        issue_a = create_issue("Issue A")

        # Check if new issue B depending on A would be circular
        cycle = detect_circular_dependency("002", [issue_a.id])
        assert cycle is None

    def test_detect_circular_dependency_direct(self, temp_agenttrees_deps):
        """Detect direct circular dependency (A -> B -> A)."""
        from agenttree.issues import detect_circular_dependency

        # Create issue A depending on (future) issue B
        issue_a = create_issue("Issue A", dependencies=["002"])

        # Check if B depending on A would be circular
        cycle = detect_circular_dependency("002", [issue_a.id])
        assert cycle is not None
        assert 1 in cycle
        assert 2 in cycle

    def test_detect_circular_dependency_indirect(self, temp_agenttrees_deps):
        """Detect indirect circular dependency (A -> B -> C -> A)."""
        from agenttree.issues import detect_circular_dependency

        # Create A -> B -> C
        issue_a = create_issue("Issue A", dependencies=["002"])
        issue_b = create_issue("Issue B", dependencies=["003"])

        # Check if C depending on A would be circular
        cycle = detect_circular_dependency("003", [issue_a.id])
        assert cycle is not None
        # Cycle should contain all three
        assert len([c for c in cycle if c in [1, 2, 3]]) >= 2

    def test_detect_circular_dependency_self(self, temp_agenttrees_deps):
        """Detect self-dependency (A -> A)."""
        from agenttree.issues import detect_circular_dependency

        # Check if A depending on itself would be circular
        cycle = detect_circular_dependency("001", [1])
        assert cycle is not None
        assert 1 in cycle

    def test_create_issue_rejects_circular_dependency(self, temp_agenttrees_deps):
        """create_issue should raise ValueError for circular dependencies."""
        # Create A -> B
        issue_a = create_issue("Issue A", dependencies=["002"])

        # Creating B -> A should fail
        with pytest.raises(ValueError, match="Circular dependency detected"):
            create_issue("Issue B", dependencies=["001"])

    def test_create_issue_allows_valid_dependency_chain(self, temp_agenttrees_deps):
        """create_issue should allow valid (non-circular) dependency chains."""
        # Create A
        issue_a = create_issue("Issue A")

        # Create B -> A (valid)
        issue_b = create_issue("Issue B", dependencies=[issue_a.id])
        assert issue_b.dependencies == [1]

        # Create C -> B (valid)
        issue_c = create_issue("Issue C", dependencies=[issue_b.id])
        assert issue_c.dependencies == [2]


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
        assert issue.stage == "explore.define"  # New issues start at explore.define

        updated = update_issue_stage("001", "explore.research")
        assert updated is not None
        assert updated.stage == "explore.research"

    def test_update_issue_stage_adds_history(self, temp_agenttrees):
        """Updating stage adds history entry."""
        issue = create_issue("Test Issue")
        assert len(issue.history) == 1

        updated = update_issue_stage("001", "explore.research", agent=1)
        assert len(updated.history) == 2
        assert updated.history[-1].stage == "explore.research"
        assert updated.history[-1].agent == 1

    def test_update_issue_stage_not_found(self, temp_agenttrees):
        """Return None for non-existent issue."""
        result = update_issue_stage("999", "explore.define")
        assert result is None

    def test_update_issue_stage_unrecognized_stage_still_succeeds(self, temp_agenttrees):
        """Stage transition succeeds even with an unrecognized stage name (logs warning)."""
        issue = create_issue("Test Issue")
        updated = update_issue_stage("001", "nonexistent_stage")
        assert updated is not None
        assert updated.stage == "nonexistent_stage"

    def test_update_issue_stage_preserves_non_model_fields(self, temp_agenttrees):
        """Non-model fields like manager_hooks_executed must survive stage updates."""
        issue = create_issue("Test Issue")

        # Simulate what check_manager_stages does: write a non-model field to the YAML
        issue_dir = get_issue_dir("001")
        yaml_path = issue_dir / "issue.yaml"
        data = safe_yaml_load(yaml_path)
        data["manager_hooks_executed"] = "implement.review"
        import yaml
        with open(yaml_path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

        # Now update the stage (this used to clobber manager_hooks_executed)
        updated = update_issue_stage("001", "implement.review")
        assert updated is not None

        # Verify the non-model field survived
        data_after = safe_yaml_load(yaml_path)
        assert data_after.get("manager_hooks_executed") == "implement.review"


class TestLoadSkill:
    """Tests for load_skill function."""

    @pytest.fixture
    def temp_agenttrees_with_skills(self, monkeypatch, tmp_path):
        """Create a temporary _agenttree directory with skills."""
        agenttrees_path = tmp_path / "_agenttree"
        agenttrees_path.mkdir()
        (agenttrees_path / "issues").mkdir()
        (agenttrees_path / "skills").mkdir()
        (agenttrees_path / "skills" / "explore").mkdir()

        # Create skill files using convention paths
        # explore.define -> skills/explore/define.md
        (agenttrees_path / "skills" / "explore" / "define.md").write_text("# Define Skill")
        # implement.code -> falls back to skills/implement.md
        (agenttrees_path / "skills" / "implement.md").write_text("# Implement Skill")
        # implement.test -> legacy naming skills/implement-test.md
        (agenttrees_path / "skills" / "implement-test.md").write_text("# Test Substage Skill")

        # Monkeypatch get_agenttree_path to return our temp dir
        monkeypatch.setattr(
            "agenttree.issues.get_agenttree_path",
            lambda: agenttrees_path
        )

        return agenttrees_path

    def test_load_define_stage_skill(self, temp_agenttrees_with_skills):
        """Load skill for explore.define stage."""
        skill = load_skill("explore.define")
        assert skill == "# Define Skill"

    def test_load_substage_skill(self, temp_agenttrees_with_skills):
        """Load skill for implement.code (falls back to stage skill)."""
        skill = load_skill("implement.code")
        assert skill == "# Implement Skill"

    def test_load_specific_substage_skill(self, temp_agenttrees_with_skills):
        """Load skill for specific substage when available via legacy naming."""
        skill = load_skill("implement.test")
        assert skill == "# Test Substage Skill"

    def test_load_skill_not_found(self, temp_agenttrees_with_skills):
        """Return None when skill not found (convention-based)."""
        skill = load_skill("accepted")
        assert skill is None

    def test_load_skill_explicit_not_found_raises(self, temp_agenttrees_with_skills, monkeypatch):
        """Raise FileNotFoundError when explicitly configured skill doesn't exist."""
        from agenttree.config import Config, StageConfig

        # Create a config that explicitly references a non-existent skill file
        mock_config = Config(
            stages={"test_stage": StageConfig(name="test_stage", skill="nonexistent/skill.md")}
        )
        monkeypatch.setattr("agenttree.config.load_config", lambda *args, **kwargs: mock_config)

        with pytest.raises(FileNotFoundError) as exc_info:
            load_skill("test_stage")

        assert "nonexistent/skill.md" in str(exc_info.value)
        assert "does not exist" in str(exc_info.value)

    def test_load_skill_with_command_variable(self, temp_agenttrees_with_skills, monkeypatch):
        """Command outputs should be injected into templates."""
        # Create a template with a command variable (using convention path)
        skill_path = temp_agenttrees_with_skills / "skills" / "explore" / "define.md"
        skill_path.write_text("Branch: {{git_branch}}")

        # Mock the config to include a command
        from agenttree.config import Config
        mock_config = Config(commands={"git_branch": "echo 'test-branch'"})
        monkeypatch.setattr("agenttree.config.load_config", lambda *args, **kwargs: mock_config)

        # Mock is_running_in_container at environment module level (where get_code_directory calls it)
        monkeypatch.setattr("agenttree.environment.is_running_in_container", lambda: False)

        # Create a mock issue
        from agenttree.issues import Issue
        issue = Issue(
            id="001",
            slug="test",
            title="Test",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
        )

        # Create issue dir
        issue_dir = temp_agenttrees_with_skills / "issues" / "001"
        issue_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agenttree.issues.get_issue_dir",
            lambda x: issue_dir
        )

        skill = load_skill("explore.define", issue=issue)
        assert skill == "Branch: test-branch"

    def test_load_skill_builtin_vars_take_precedence(self, temp_agenttrees_with_skills, monkeypatch):
        """Built-in context variables should not be overwritten by commands."""
        # Create a template using issue_id (using convention path)
        skill_path = temp_agenttrees_with_skills / "skills" / "explore" / "define.md"
        skill_path.write_text("Issue: {{issue_id}}")

        # Mock the config with a command named issue_id (should be ignored)
        from agenttree.config import Config
        mock_config = Config(commands={"issue_id": "echo 'WRONG'"})
        monkeypatch.setattr("agenttree.config.load_config", lambda *args, **kwargs: mock_config)

        # Create a mock issue
        from agenttree.issues import Issue
        issue = Issue(
            id="042",
            slug="test",
            title="Test",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
        )

        # Create issue dir
        issue_dir = temp_agenttrees_with_skills / "issues" / "042"
        issue_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agenttree.issues.get_issue_dir",
            lambda x: issue_dir
        )

        skill = load_skill("explore.define", issue=issue)
        # Should use the built-in issue_id, not the command output
        assert skill == "Issue: 42"

    def test_load_skill_only_runs_referenced_commands(self, temp_agenttrees_with_skills, monkeypatch):
        """Only commands referenced in template should be executed."""
        # Create a template with only one command reference (using convention path)
        skill_path = temp_agenttrees_with_skills / "skills" / "explore" / "define.md"
        skill_path.write_text("Branch: {{git_branch}}")

        # Track which commands are executed
        executed_commands = []

        from agenttree.config import Config
        mock_config = Config(commands={
            "git_branch": "echo 'main'",
            "unused_cmd": "echo 'should not run'",
        })
        monkeypatch.setattr("agenttree.config.load_config", lambda *args, **kwargs: mock_config)

        # Patch get_command_output to track calls
        def tracking_get_output(commands, name, cwd=None):
            executed_commands.append(name)
            from agenttree.commands import execute_command
            cmd = commands.get(name, "")
            if isinstance(cmd, list):
                cmd = cmd[0] if cmd else ""
            return execute_command(cmd, cwd=cwd)

        monkeypatch.setattr(
            "agenttree.commands.get_command_output",
            tracking_get_output
        )

        from agenttree.issues import Issue
        issue = Issue(
            id="001",
            slug="test",
            title="Test",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
        )

        issue_dir = temp_agenttrees_with_skills / "issues" / "001"
        issue_dir.mkdir(parents=True)

        monkeypatch.setattr(
            "agenttree.issues.get_issue_dir",
            lambda x: issue_dir
        )

        load_skill("explore.define", issue=issue)

        # Only git_branch should have been executed
        assert "git_branch" in executed_commands
        assert "unused_cmd" not in executed_commands


class TestLoadSkillJinja:
    """Tests for load_skill Jinja template rendering."""

    @pytest.fixture
    def temp_agenttrees_jinja(self, monkeypatch, tmp_path):
        """Create a temporary _agenttree directory with skills and issues for Jinja tests."""
        agenttrees_path = tmp_path / "_agenttree"
        agenttrees_path.mkdir()
        (agenttrees_path / "issues").mkdir()
        (agenttrees_path / "skills").mkdir()
        (agenttrees_path / "skills" / "explore").mkdir()
        (agenttrees_path / "templates").mkdir()

        # Create problem template (needed for create_issue)
        template = agenttrees_path / "templates" / "problem.md"
        template.write_text("# Problem Statement\n\n")

        # Monkeypatch get_agenttree_path to return our temp dir
        monkeypatch.setattr(
            "agenttree.issues.get_agenttree_path",
            lambda: agenttrees_path
        )

        # Disable sync to avoid git operations
        monkeypatch.setattr(
            "agenttree.issues.sync_agents_repo",
            lambda *args, **kwargs: True
        )

        return agenttrees_path

    def test_load_skill_renders_basic_variables(self, temp_agenttrees_jinja):
        """load_skill should render basic issue variables with Jinja."""
        # Create skill file with Jinja template (convention path)
        skill_path = temp_agenttrees_jinja / "skills" / "explore" / "define.md"
        skill_path.write_text("Issue #{{issue_id}}: {{issue_title}}")

        # Create an issue
        issue = create_issue("Test Issue")

        # Load skill with issue context
        skill = load_skill("explore.define", issue=issue)

        assert skill == "Issue #1: Test Issue"

    def test_load_skill_renders_document_content(self, temp_agenttrees_jinja):
        """load_skill should render document content variables."""
        # Create skill file that references problem_md (convention path)
        skill_path = temp_agenttrees_jinja / "skills" / "explore" / "research.md"
        skill_path.write_text("## Problem\n{{problem_md}}")

        # Create an issue and update its problem.md
        issue = create_issue("Test Issue")
        issue_dir = temp_agenttrees_jinja / "issues" / issue.dir_name
        (issue_dir / "problem.md").write_text("This is the problem description.")

        # Load skill with issue context
        skill = load_skill("explore.research", issue=issue)

        assert "This is the problem description." in skill

    def test_load_skill_includes_system_prompt(self, temp_agenttrees_jinja):
        """load_skill should prepend AGENTS.md when include_system=True."""
        # Create AGENTS.md system prompt
        agents_md = temp_agenttrees_jinja / "skills" / "AGENTS.md"
        agents_md.write_text("# System Prompt\nYou are an AI agent.")

        # Create skill file (convention path)
        skill_path = temp_agenttrees_jinja / "skills" / "explore" / "define.md"
        skill_path.write_text("# Define Stage")

        # Create an issue
        issue = create_issue("Test Issue")

        # Load skill with include_system=True
        skill = load_skill("explore.define", issue=issue, include_system=True)

        assert skill.startswith("# System Prompt")
        assert "You are an AI agent." in skill
        assert "# Define Stage" in skill

    def test_load_skill_without_issue_returns_raw(self, temp_agenttrees_jinja):
        """load_skill without issue should return raw template content."""
        # Create skill file with Jinja template (convention path)
        skill_path = temp_agenttrees_jinja / "skills" / "explore" / "define.md"
        skill_path.write_text("Issue #{{issue_id}}: {{issue_title}}")

        # Load skill without issue context
        skill = load_skill("explore.define")

        # Should return raw template, not rendered
        assert skill == "Issue #{{issue_id}}: {{issue_title}}"


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

        update_session_stage(issue.id, "explore.research")

        session = get_session(issue.id)
        assert session.last_stage == "explore.research"
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


class TestLoadPersona:
    """Tests for load_persona function (shows persona on restart/takeover)."""

    @pytest.fixture
    def temp_agenttrees_with_persona(self, monkeypatch, tmp_path):
        """Create a temporary _agenttree directory with a persona file."""
        agenttrees_path = tmp_path / "_agenttree"
        agenttrees_path.mkdir()
        (agenttrees_path / "issues").mkdir()
        (agenttrees_path / "templates").mkdir()
        (agenttrees_path / "skills").mkdir()
        (agenttrees_path / "skills" / "roles").mkdir()

        # Create problem template
        template = agenttrees_path / "templates" / "problem.md"
        template.write_text("# Problem Statement\n\n")

        # Create roles/developer.md with Jinja variables
        persona = agenttrees_path / "skills" / "roles" / "developer.md"
        persona.write_text(
            "# Developer Persona\n\n"
            "Stage: {{ current_stage }}\n"
            "Is takeover: {{ is_takeover }}\n"
            "Completed stages: {{ completed_stages|join(', ') }}\n"
        )

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

    def test_load_persona_returns_content(self, temp_agenttrees_with_persona):
        """load_persona returns persona content."""
        from agenttree.issues import load_persona

        persona = load_persona()
        assert persona is not None
        assert "Developer Persona" in persona

    def test_load_persona_with_stage_context(self, temp_agenttrees_with_persona):
        """load_persona renders stage context variables."""
        from agenttree.issues import load_persona

        persona = load_persona(
            current_stage="implement.code",
            is_takeover=False,
        )
        assert persona is not None
        assert "Stage: implement.code" in persona
        assert "Is takeover: False" in persona

    def test_load_persona_calculates_completed_stages(self, temp_agenttrees_with_persona):
        """load_persona calculates completed stages before current stage."""
        from agenttree.issues import load_persona

        persona = load_persona(
            current_stage="implement.code",
            is_takeover=True,
        )
        assert persona is not None
        # Should include dot-path stages before implement.code
        assert "explore.define" in persona
        assert "explore.research" in persona
        assert "plan.draft" in persona
        assert "plan.review" in persona

    def test_load_persona_takeover_true_mid_workflow(self, temp_agenttrees_with_persona):
        """is_takeover should be True when starting mid-workflow."""
        from agenttree.issues import load_persona

        persona = load_persona(
            current_stage="implement.code",
            is_takeover=True,
        )
        assert persona is not None
        assert "Is takeover: True" in persona

    def test_load_persona_takeover_false_for_early_stages(self, temp_agenttrees_with_persona):
        """is_takeover should be False when starting from beginning stages."""
        from agenttree.issues import load_persona

        persona = load_persona(
            current_stage="explore.define",
            is_takeover=False,
        )
        assert persona is not None
        assert "Is takeover: False" in persona

    def test_load_persona_returns_none_if_missing(self, monkeypatch, tmp_path):
        """load_persona returns None if persona file doesn't exist."""
        from agenttree.issues import load_persona

        agenttrees_path = tmp_path / "_agenttree"
        agenttrees_path.mkdir()
        (agenttrees_path / "skills").mkdir()
        (agenttrees_path / "skills" / "roles").mkdir()
        # Don't create developer.md

        monkeypatch.setattr(
            "agenttree.issues.get_agenttree_path",
            lambda: agenttrees_path
        )
        monkeypatch.setattr(
            "agenttree.issues.sync_agents_repo",
            lambda *args, **kwargs: True
        )

        persona = load_persona()
        assert persona is None

    def test_load_persona_with_issue_context(self, temp_agenttrees_with_persona):
        """load_persona includes issue context when issue is provided."""
        from agenttree.issues import load_persona, create_issue

        # Update persona template to include issue vars
        persona_path = temp_agenttrees_with_persona / "skills" / "roles" / "developer.md"
        persona_path.write_text(
            "Issue: {{ issue_id }} - {{ issue_title }}\n"
            "Stage: {{ current_stage }}\n"
        )

        issue = create_issue("Test Feature")
        persona = load_persona(
            issue=issue,
            current_stage="plan.draft",
        )
        assert persona is not None
        assert str(issue.id) in persona
        assert "Test Feature" in persona

    def test_load_persona_loads_different_agent_types(self, temp_agenttrees_with_persona):
        """load_persona loads correct file based on agent_type."""
        from agenttree.issues import load_persona

        # Create a reviewer persona
        reviewer_path = temp_agenttrees_with_persona / "skills" / "roles" / "reviewer.md"
        reviewer_path.write_text("# Reviewer Persona\n\nYou are a code reviewer.\n")

        # Load developer (default)
        dev_persona = load_persona(agent_type="developer")
        assert "Developer Persona" in dev_persona

        # Load reviewer
        reviewer_persona = load_persona(agent_type="reviewer")
        assert "Reviewer Persona" in reviewer_persona


class TestGetIssueContext:
    """Tests for get_issue_context function (DRY context builder)."""

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

    def test_get_issue_context_includes_all_model_fields(self, temp_agenttrees):
        """get_issue_context should include all Issue model fields."""
        issue = create_issue("Test Issue", priority=Priority.HIGH)

        context = get_issue_context(issue)

        # Core model fields
        assert context["id"] == 1
        assert context["slug"] == "test-issue"
        assert context["title"] == "Test Issue"
        assert context["stage"] == "explore.define"
        assert context["priority"] == "high"
        assert "created" in context
        assert "updated" in context
        assert context["labels"] == []
        assert context["dependencies"] == []

    def test_get_issue_context_includes_derived_fields(self, temp_agenttrees):
        """get_issue_context should include derived fields."""
        issue = create_issue("Test Issue")

        context = get_issue_context(issue)

        # Derived fields
        assert context["issue_id"] == 1  # alias
        assert context["issue_title"] == "Test Issue"  # alias
        assert "issue_dir" in context
        assert context["issue_dir_rel"] == "_agenttree/issues/001"
        # Dot path is parsed into stage_group and substage
        assert context["stage_group"] == "explore"
        assert context["substage"] == "define"

    def test_get_issue_context_stage_without_substage(self, temp_agenttrees):
        """stage_group and substage should handle single-level stages."""
        from agenttree.issues import update_issue_stage

        issue = create_issue("Test Issue")
        update_issue_stage(issue.id, "accepted")

        # Reload issue to get updated data
        issue = get_issue(issue.id)
        context = get_issue_context(issue)

        assert context["stage"] == "accepted"
        assert context["stage_group"] == "accepted"
        assert context["substage"] == ""

    def test_get_issue_context_includes_documents(self, temp_agenttrees):
        """get_issue_context should include document contents when include_docs=True."""
        issue = create_issue("Test Issue")

        # Write some document content
        issue_dir = temp_agenttrees / "issues" / "001"
        (issue_dir / "research.md").write_text("Research findings here")

        context = get_issue_context(issue, include_docs=True)

        assert context["problem_md"] == "# Problem Statement\n\n"
        assert context["research_md"] == "Research findings here"
        assert context["spec_md"] == ""  # Missing file = empty string
        assert context["spec_review_md"] == ""
        assert context["review_md"] == ""

    def test_get_issue_context_excludes_documents(self, temp_agenttrees):
        """get_issue_context should skip documents when include_docs=False."""
        issue = create_issue("Test Issue")

        context = get_issue_context(issue, include_docs=False)

        assert "problem_md" not in context
        assert "research_md" not in context
        assert "spec_md" not in context

    def test_get_issue_context_includes_optional_fields(self, temp_agenttrees):
        """get_issue_context should include optional fields."""
        from agenttree.issues import update_issue_metadata

        issue = create_issue("Test Issue")
        update_issue_metadata(
            issue.id,
            branch="issue-001-test-issue",
            worktree_dir="/path/to/worktree",
            pr_number=42,
            pr_url="https://github.com/org/repo/pull/42",
        )

        # Reload issue
        issue = get_issue(issue.id)
        context = get_issue_context(issue)

        assert context["branch"] == "issue-001-test-issue"
        assert context["worktree_dir"] == "/path/to/worktree"
        assert context["pr_number"] == 42
        assert context["pr_url"] == "https://github.com/org/repo/pull/42"

    def test_get_issue_context_includes_history(self, temp_agenttrees):
        """get_issue_context should include history as list of dicts."""
        from agenttree.issues import update_issue_stage

        issue = create_issue("Test Issue")
        update_issue_stage(issue.id, "explore.research", agent=1)

        # Reload issue
        issue = get_issue(issue.id)
        context = get_issue_context(issue)

        assert "history" in context
        assert len(context["history"]) == 2
        assert context["history"][0]["stage"] == "explore.define"
        assert context["history"][1]["stage"] == "explore.research"
        assert context["history"][1]["agent"] == 1


class TestNeedsUIReview:
    """Tests for needs_ui_review field on Issue model."""

    def test_issue_needs_ui_review_default_false(self):
        """New issues should have needs_ui_review=False by default."""
        issue = Issue(
            id="001",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
        )
        assert issue.needs_ui_review is False

    def test_issue_needs_ui_review_can_be_set_true(self):
        """Issues should be able to have needs_ui_review=True."""
        issue = Issue(
            id="001",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            needs_ui_review=True,
        )
        assert issue.needs_ui_review is True

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

    def test_issue_needs_ui_review_in_context(self, temp_agenttrees):
        """get_issue_context should include needs_ui_review field."""
        issue = create_issue("Test Issue")

        # Default should be False
        context = get_issue_context(issue)
        assert "needs_ui_review" in context
        assert context["needs_ui_review"] is False

    def test_issue_needs_ui_review_true_in_context(self, temp_agenttrees):
        """get_issue_context should include needs_ui_review=True when set."""
        from agenttree.issues import update_issue_metadata

        issue = create_issue("Test Issue")
        update_issue_metadata(issue.id, needs_ui_review=True)

        # Reload issue
        issue = get_issue(issue.id)
        context = get_issue_context(issue)

        assert context["needs_ui_review"] is True


class TestUpdateIssuePriority:
    """Tests for update_issue_priority function."""

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

    def test_update_priority_from_medium_to_high(self, temp_agenttrees):
        """Update issue priority from medium to high."""
        issue = create_issue("Test Issue")
        assert issue.priority == Priority.MEDIUM

        updated = update_issue_priority("001", Priority.HIGH)

        assert updated is not None
        assert updated.priority == Priority.HIGH

        # Verify persisted to disk
        reloaded = get_issue("001")
        assert reloaded.priority == Priority.HIGH

    def test_update_priority_to_critical(self, temp_agenttrees):
        """Update issue priority to critical."""
        issue = create_issue("Test Issue")

        updated = update_issue_priority(issue.id, Priority.CRITICAL)

        assert updated is not None
        assert updated.priority == Priority.CRITICAL

    def test_update_priority_to_low(self, temp_agenttrees):
        """Update issue priority to low."""
        issue = create_issue("Test Issue", priority=Priority.HIGH)
        assert issue.priority == Priority.HIGH

        updated = update_issue_priority(issue.id, Priority.LOW)

        assert updated is not None
        assert updated.priority == Priority.LOW

    def test_update_priority_nonexistent_issue(self, temp_agenttrees):
        """Return None for non-existent issue."""
        result = update_issue_priority("999", Priority.HIGH)
        assert result is None

    def test_update_priority_updates_timestamp(self, temp_agenttrees):
        """Updating priority should set the updated timestamp."""
        issue = create_issue("Test Issue")

        updated = update_issue_priority(issue.id, Priority.HIGH)

        assert updated is not None
        # Verify the updated timestamp is set (not empty)
        assert updated.updated is not None
        assert len(updated.updated) > 0


class TestConfigValidation:
    """Tests that validate config references exist."""

    def test_all_explicit_skills_exist(self):
        """Every skill explicitly referenced in config should exist."""
        from agenttree.config import load_config
        from pathlib import Path

        # Skip if _agenttree doesn't exist (CI environment)
        agenttree_path = Path("_agenttree")
        if not agenttree_path.exists():
            pytest.skip("_agenttree directory not present")

        config = load_config()
        missing_skills = []

        for stage_name, stage in config.stages.items():
            # Check stage-level explicit skill
            if stage.skill:
                skill_path = agenttree_path / "skills" / stage.skill
                if not skill_path.exists():
                    missing_skills.append(f"{stage_name}: {stage.skill}")

            # Check substage-level explicit skills
            if stage.substages:
                for substage_name, substage in stage.substages.items():
                    if substage and substage.skill:
                        skill_path = agenttree_path / "skills" / substage.skill
                        if not skill_path.exists():
                            missing_skills.append(f"{stage_name}.{substage_name}: {substage.skill}")

        assert not missing_skills, f"Missing skill files: {missing_skills}"

    def test_all_templates_exist(self):
        """Every template referenced in create_file hooks should exist."""
        from agenttree.config import load_config
        from pathlib import Path

        # Skip if _agenttree doesn't exist (CI environment)
        agenttree_path = Path("_agenttree")
        if not agenttree_path.exists():
            pytest.skip("_agenttree directory not present")

        config = load_config()
        missing_templates = []

        def check_hooks(hooks: list, context: str):
            for hook in hooks:
                if isinstance(hook, dict) and "create_file" in hook:
                    template_name = hook["create_file"].get("template")
                    if template_name:
                        template_path = agenttree_path / "templates" / template_name
                        if not template_path.exists():
                            missing_templates.append(f"{context}: {template_name}")

        for stage_name, stage in config.stages.items():
            # Check stage-level hooks
            check_hooks(stage.post_start, f"{stage_name}.post_start")
            check_hooks(stage.pre_completion, f"{stage_name}.pre_completion")

            # Check substage-level hooks
            if stage.substages:
                for substage_name, substage in stage.substages.items():
                    if substage:
                        check_hooks(substage.post_start, f"{stage_name}.{substage_name}.post_start")
                        check_hooks(substage.pre_completion, f"{stage_name}.{substage_name}.pre_completion")

        assert not missing_templates, f"Missing template files: {missing_templates}"

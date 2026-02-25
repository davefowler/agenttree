"""Full workflow integration tests.

Tests the complete issue lifecycle from backlog to accepted,
verifying each stage transition works correctly.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from agenttree.ids import format_issue_id
from tests.integration.helpers import (
    create_valid_problem_md,
    create_valid_research_md,
    create_valid_spec_md,
    create_valid_spec_review_md,
    create_valid_review_md,
    make_commit,
    setup_issue_at_stage,
)


class TestStageTransitions:
    """Test individual stage transitions."""

    def test_define_to_research(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test transition from explore.define to explore.research."""
        from agenttree.issues import create_issue, get_next_stage
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    # Create issue
                    issue = create_issue(title="Test Define to Research")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    # Issue starts at explore.define
                    assert issue.stage == "explore.define"

                    # Create valid content for define stage
                    create_valid_problem_md(issue_dir)

                    # Get config for hooks
                    config = load_config()
                    stage_config, substage_config = config.resolve_stage("explore.define")

                    # Execute pre_completion hooks
                    errors = execute_hooks(
                        issue_dir=issue_dir,
                        stage="explore.define",
                        substage_config=substage_config or stage_config,
                        event="pre_completion"
                    )

                    # Should pass with valid content
                    assert errors == [], f"Hooks failed: {errors}"

                    # Get next stage
                    next_stage, is_human_review = get_next_stage("explore.define")

                    assert next_stage == "explore.research"
                    assert is_human_review is False

    def test_research_to_plan(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test transition from explore.research to plan.draft."""
        from agenttree.issues import create_issue, get_next_stage
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Research to Plan")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    # Create valid research content
                    create_valid_problem_md(issue_dir)
                    create_valid_research_md(issue_dir)

                    config = load_config()
                    stage_config, substage_config = config.resolve_stage("explore.research")

                    errors = execute_hooks(
                        issue_dir=issue_dir,
                        stage="explore.research",
                        substage_config=substage_config or stage_config,
                        event="pre_completion"
                    )

                    assert errors == [], f"Hooks failed: {errors}"

                    next_stage, _ = get_next_stage("explore.research")
                    assert next_stage == "plan.draft"

    def test_plan_to_plan_assess(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test transition from plan.draft to plan.assess."""
        from agenttree.issues import create_issue, get_next_stage
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Plan to Plan Assess")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    # Create valid content
                    create_valid_problem_md(issue_dir)
                    create_valid_research_md(issue_dir)
                    create_valid_spec_md(issue_dir)

                    config = load_config()
                    stage_config, substage_config = config.resolve_stage("plan.draft")

                    errors = execute_hooks(
                        issue_dir=issue_dir,
                        stage="plan.draft",
                        substage_config=substage_config or stage_config,
                        event="pre_completion"
                    )

                    assert errors == [], f"Hooks failed: {errors}"

                    next_stage, _ = get_next_stage("plan.draft")
                    assert next_stage == "plan.assess"

    def test_plan_revise_to_plan_review(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test transition from plan.revise to plan.review (human gate)."""
        from agenttree.issues import get_next_stage

        with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
            next_stage, is_human_review = get_next_stage("plan.revise")

            assert next_stage == "plan.review"
            assert is_human_review is True  # Human review gate!


class TestHumanReviewGates:
    """Test that human review gates block agent progression."""

    def test_agent_blocked_at_plan_review(self, workflow_repo: Path, mock_sync: MagicMock):
        """Agent should not be able to advance past plan.review."""
        from agenttree.config import load_config

        with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
            config = load_config()

            # Verify plan.review is a human review stage
            human_review_stages = config.get_human_review_stages()
            assert "plan.review" in human_review_stages

            # Verify the substage config has human_review=True
            _, substage_config = config.resolve_stage("plan.review")
            assert substage_config is not None
            assert substage_config.human_review is True

    def test_agent_blocked_at_implementation_review(self, workflow_repo: Path, mock_sync: MagicMock):
        """Agent should not be able to advance past implement.review."""
        from agenttree.config import load_config

        with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
            config = load_config()

            human_review_stages = config.get_human_review_stages()
            assert "implement.review" in human_review_stages

            _, substage_config = config.resolve_stage("implement.review")
            assert substage_config is not None
            assert substage_config.human_review is True


class TestImplementSubstages:
    """Test the implement stage substages."""

    def test_implement_code_to_code_review(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test transition from implement.code to implement.code_review."""
        from agenttree.issues import get_next_stage

        with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
            next_stage, _ = get_next_stage("implement.code")

            assert next_stage == "implement.code_review"

    def test_code_review_requires_checklist(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that code_review exit requires all checklist items checked."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config
        from tests.integration.helpers import create_failing_review_md

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Code Review Checklist")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    # Create review.md with unchecked items
                    create_failing_review_md(issue_dir, reason="unchecked")

                    config = load_config()
                    _, substage_config = config.resolve_stage("implement.code_review")

                    errors = execute_hooks(
                        issue_dir=issue_dir,
                        stage="implement.code_review",
                        substage_config=substage_config,
                        event="pre_completion"
                    )

                    # Should fail because checklist items are unchecked
                    assert len(errors) > 0
                    assert any("checklist" in e.lower() or "checked" in e.lower() for e in errors)

    def test_wrapup_requires_score_7(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that wrapup exit requires average score >= 7."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config
        from tests.integration.helpers import create_failing_review_md

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Wrapup Score")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    # Create review.md with low score
                    create_failing_review_md(issue_dir, reason="low_score")

                    config = load_config()
                    _, substage_config = config.resolve_stage("implement.wrapup")

                    errors = execute_hooks(
                        issue_dir=issue_dir,
                        stage="implement.wrapup",
                        substage_config=substage_config,
                        event="pre_completion"
                    )

                    # Should fail because score < 7
                    assert len(errors) > 0
                    assert any("7" in e or "average" in e.lower() for e in errors)

    def test_feedback_requires_commits(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that feedback exit requires unpushed commits."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    with patch("agenttree.hooks.has_commits_to_push", return_value=False):
                        issue = create_issue(title="Test Feedback Commits")
                        issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                        # Create valid review.md
                        create_valid_review_md(issue_dir)

                        config = load_config()
                        _, substage_config = config.resolve_stage("implement.feedback")

                        errors = execute_hooks(
                            issue_dir=issue_dir,
                            stage="implement.feedback",
                            substage_config=substage_config,
                            event="pre_completion"
                        )

                        # Should fail because no commits
                        assert len(errors) > 0
                        assert any("commit" in e.lower() for e in errors)

    def test_feedback_blocks_with_critical_issues(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that feedback exit blocks if Critical Issues section is not empty."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config
        from tests.integration.helpers import create_failing_review_md

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    with patch("agenttree.hooks.has_commits_to_push", return_value=True):
                        issue = create_issue(title="Test Critical Issues Block")
                        issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                        # Create review.md with critical issues
                        create_failing_review_md(issue_dir, reason="critical_issues")

                        config = load_config()
                        _, substage_config = config.resolve_stage("implement.feedback")

                        errors = execute_hooks(
                            issue_dir=issue_dir,
                            stage="implement.feedback",
                            substage_config=substage_config,
                            event="pre_completion"
                        )

                        # Should fail because critical issues exist
                        assert len(errors) > 0
                        assert any("critical" in e.lower() or "empty" in e.lower() for e in errors)


class TestTerminalStates:
    """Test terminal state behavior."""

    def test_cannot_advance_from_accepted(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that accepted is a terminal state."""
        from agenttree.config import load_config

        with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
            config = load_config()
            stage = config.get_stage("accepted")

            assert stage.is_parking_lot is True

    def test_not_doing_is_parking_lot(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that not_doing is a parking lot stage."""
        from agenttree.config import load_config

        with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
            config = load_config()
            stage = config.get_stage("not_doing")

            assert stage.is_parking_lot is True


class TestFullWorkflowHappyPath:
    """Test complete workflow from start to finish."""

    def test_full_workflow_creates_all_files(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that advancing through workflow creates expected files."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Full Workflow Test")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    config = load_config()

                    # Create all content files
                    create_valid_problem_md(issue_dir)
                    create_valid_research_md(issue_dir)
                    create_valid_spec_md(issue_dir)
                    create_valid_spec_review_md(issue_dir)
                    create_valid_review_md(issue_dir)

                    # Verify files exist
                    assert (issue_dir / "problem.md").exists()
                    assert (issue_dir / "research.md").exists()
                    assert (issue_dir / "spec.md").exists()
                    assert (issue_dir / "spec_review.md").exists()
                    assert (issue_dir / "review.md").exists()

                    # Verify all stage hooks would pass with this content

                    # Define stage (explore.define)
                    _, sub_config = config.resolve_stage("explore.define")
                    errors = execute_hooks(issue_dir, "explore.define", sub_config, "pre_completion")
                    assert errors == [], f"Define hooks failed: {errors}"

                    # Research stage (explore.research)
                    _, sub_config = config.resolve_stage("explore.research")
                    errors = execute_hooks(issue_dir, "explore.research", sub_config, "pre_completion")
                    assert errors == [], f"Research hooks failed: {errors}"

                    # Plan stage (plan.draft)
                    _, sub_config = config.resolve_stage("plan.draft")
                    errors = execute_hooks(issue_dir, "plan.draft", sub_config, "pre_completion")
                    assert errors == [], f"Plan hooks failed: {errors}"

                    # Plan assess stage (plan.assess)
                    _, sub_config = config.resolve_stage("plan.assess")
                    errors = execute_hooks(issue_dir, "plan.assess", sub_config, "pre_completion")
                    assert errors == [], f"Plan assess hooks failed: {errors}"

                    # Plan review stage (plan.review)
                    _, sub_config = config.resolve_stage("plan.review")
                    errors = execute_hooks(issue_dir, "plan.review", sub_config, "pre_completion")
                    # May have rebase-related errors in container mode, that's OK
                    non_rebase_errors = [e for e in errors if "rebase" not in e.lower()]
                    assert non_rebase_errors == [], f"Plan review hooks failed: {non_rebase_errors}"

    def test_stage_order_is_complete(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that flow stage names contain all stages."""
        from agenttree.config import load_config

        with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
            config = load_config()

            # Get all dot paths from config
            all_dot_paths = config.get_all_dot_paths()

            # Get flow stage names
            flow_stages = config.get_flow_stage_names()

            # Flow stages should cover all dot paths
            assert set(flow_stages) == set(all_dot_paths), \
                f"Flow mismatch. Missing: {set(all_dot_paths) - set(flow_stages)}, Extra: {set(flow_stages) - set(all_dot_paths)}"

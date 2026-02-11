"""End-to-end workflow integration test.

This test actually runs an issue through the complete workflow from creation
to acceptance, executing real hooks and verifying transitions work correctly.

KEY DIFFERENCE FROM test_full_workflow.py:
- test_full_workflow.py: Tests individual stage transitions and hook validation
  in isolation using execute_hooks() directly
- test_end_to_end_workflow.py (this file): Tests actual workflow progression
  using update_issue_stage() + execute_exit_hooks() + execute_enter_hooks(),
  simulating how the real system advances issues through stages

The tests here catch integration issues between stages that wouldn't be found
by testing stages in isolation.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tests.integration.helpers import (
    create_valid_problem_md,
    create_valid_research_md,
    create_valid_spec_md,
    create_valid_spec_review_md,
    create_valid_review_md,
    make_commit,
)


class TestEndToEndWorkflow:
    """Test complete workflow from issue creation to acceptance."""

    def test_full_workflow_define_to_plan_review(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test workflow from define through plan_review (first human gate).

        This tests the agent-driven portion of the workflow before human review.
        """
        from agenttree.issues import create_issue, get_issue, get_next_stage, update_issue_stage
        from agenttree.hooks import execute_exit_hooks, execute_enter_hooks, ValidationError

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                # Step 1: Create issue (starts at define.refine)
                issue = create_issue(title="E2E Test Issue")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                assert issue.stage == "define"
                assert issue.substage == "refine"

                # Track stages we've visited
                visited_stages = [(issue.stage, issue.substage)]

                # Step 2: Create valid problem.md
                create_valid_problem_md(issue_dir)

                # Step 3: Advance through stages until plan_review
                max_iterations = 20  # Safety limit
                iteration = 0

                while iteration < max_iterations:
                    iteration += 1

                    # Refresh issue
                    issue = get_issue(issue.id)
                    current_stage = issue.stage
                    current_substage = issue.substage

                    # Stop at plan_review (human gate)
                    if current_stage == "plan_review":
                        break

                    # Create content needed for current stage
                    # Always overwrite with valid content (templates may have empty sections)
                    if current_stage == "research":
                        create_valid_research_md(issue_dir)
                    elif current_stage in ["plan", "plan_revise"]:
                        create_valid_spec_md(issue_dir)
                    elif current_stage == "plan_assess":
                        create_valid_spec_review_md(issue_dir)

                    # Execute exit hooks (validates stage completion)
                    try:
                        execute_exit_hooks(issue, current_stage, current_substage)
                    except ValidationError as e:
                        pytest.fail(f"Exit hooks failed at {current_stage}.{current_substage}: {e}")

                    # Get next stage
                    next_stage, next_substage = get_next_stage(current_stage, current_substage)

                    # Update to next stage
                    update_issue_stage(issue.id, next_stage, next_substage)

                    # Execute enter hooks
                    issue = get_issue(issue.id)
                    execute_enter_hooks(issue, next_stage, next_substage)

                    visited_stages.append((next_stage, next_substage))

                # Verify we reached plan_review
                final_issue = get_issue(issue.id)
                assert final_issue.stage == "plan_review", f"Expected plan_review, got {final_issue.stage}"

                # Verify we visited expected stages
                stage_names = [s[0] for s in visited_stages]
                assert "define" in stage_names
                assert "research" in stage_names
                assert "plan" in stage_names
                assert "plan_assess" in stage_names
                assert "plan_revise" in stage_names
                assert "plan_review" in stage_names

    def test_full_workflow_implement_to_implementation_review(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test workflow from implement through implementation_review (second human gate).

        This tests the implementation portion after plan approval.
        """
        from agenttree.issues import create_issue, get_issue, get_next_stage, update_issue_stage
        from agenttree.hooks import execute_exit_hooks, execute_enter_hooks, ValidationError

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                # Create issue and advance to implement stage
                issue = create_issue(title="E2E Implement Test")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                # Create all prior content
                create_valid_problem_md(issue_dir)
                create_valid_research_md(issue_dir)
                create_valid_spec_md(issue_dir)
                create_valid_spec_review_md(issue_dir)

                # Skip directly to implement stage
                update_issue_stage(issue.id, "implement", "code")
                issue = get_issue(issue.id)

                assert issue.stage == "implement"
                assert issue.substage == "code"

                visited_substages = ["code"]
                max_iterations = 10
                iteration = 0

                while iteration < max_iterations:
                    iteration += 1

                    issue = get_issue(issue.id)
                    current_stage = issue.stage
                    current_substage = issue.substage

                    # Stop at implementation_review
                    if current_stage == "implementation_review":
                        break

                    # Create/overwrite review.md with valid content when needed
                    # (enter hooks may create template with unchecked items)
                    if current_substage in ["code_review", "address_review", "wrapup", "feedback"]:
                        create_valid_review_md(issue_dir)

                    # Mock has_commits_to_push for feedback stage
                    with patch("agenttree.hooks.has_commits_to_push", return_value=True):
                        try:
                            execute_exit_hooks(issue, current_stage, current_substage)
                        except ValidationError as e:
                            pytest.fail(f"Exit hooks failed at {current_stage}.{current_substage}: {e}")

                    next_stage, next_substage = get_next_stage(current_stage, current_substage)
                    update_issue_stage(issue.id, next_stage, next_substage)

                    issue = get_issue(issue.id)
                    execute_enter_hooks(issue, next_stage, next_substage)

                    if next_substage:
                        visited_substages.append(next_substage)

                # Verify we reached implementation_review
                final_issue = get_issue(issue.id)
                assert final_issue.stage == "implementation_review"

                # Verify we visited all implement substages
                assert "code" in visited_substages
                assert "code_review" in visited_substages
                assert "address_review" in visited_substages
                assert "wrapup" in visited_substages
                assert "feedback" in visited_substages

    def test_full_workflow_to_accepted(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test complete workflow from create to accepted.

        This is the full end-to-end test, including human review gates
        (simulated by skipping the human_review check).
        """
        from agenttree.issues import create_issue, get_issue, get_next_stage, update_issue_stage, ACCEPTED
        from agenttree.hooks import execute_exit_hooks, execute_enter_hooks, ValidationError

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                # Create issue
                issue = create_issue(title="Full E2E Test")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                all_stages_visited = []
                max_iterations = 30
                iteration = 0

                while iteration < max_iterations:
                    iteration += 1

                    issue = get_issue(issue.id)
                    current_stage = issue.stage
                    current_substage = issue.substage

                    all_stages_visited.append((current_stage, current_substage))

                    # Stop at accepted
                    if current_stage == ACCEPTED:
                        break

                    # Create/overwrite content based on stage
                    # Always overwrite because enter hooks may create templates with empty sections
                    if current_stage == "define":
                        create_valid_problem_md(issue_dir)
                    elif current_stage == "research":
                        create_valid_research_md(issue_dir)
                    elif current_stage in ["plan", "plan_assess", "plan_revise", "plan_review"]:
                        create_valid_spec_md(issue_dir)
                        create_valid_spec_review_md(issue_dir)
                    elif current_stage in ["implement", "implementation_review"]:
                        create_valid_review_md(issue_dir)

                    # Execute exit hooks with proper mocking for hooks that need external setup
                    with patch("agenttree.hooks.has_commits_to_push", return_value=True):
                        # Mock rebase hook (requires actual git remote)
                        with patch("agenttree.hooks.run_command_hook", return_value=[]):
                            # Skip PR approval check (no actual PR in tests)
                            execute_exit_hooks(issue, current_stage, current_substage, skip_pr_approval=True)

                    next_stage, next_substage = get_next_stage(current_stage, current_substage)

                    if next_stage is None:
                        pytest.fail(f"No next stage from {current_stage}.{current_substage}")

                    update_issue_stage(issue.id, next_stage, next_substage)

                    issue = get_issue(issue.id)
                    execute_enter_hooks(issue, next_stage, next_substage)

                # Verify we reached accepted
                final_issue = get_issue(issue.id)
                assert final_issue.stage == ACCEPTED, f"Expected accepted, got {final_issue.stage}"

                # Verify we touched all major stages
                stage_names = set(s[0] for s in all_stages_visited)
                expected_stages = {"define", "research", "plan", "plan_assess", "plan_revise",
                                   "plan_review", "implement", "implementation_review", "accepted"}
                missing = expected_stages - stage_names
                assert not missing, f"Missing stages: {missing}"

    def test_validation_blocks_invalid_content(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that validation actually blocks progression with invalid content."""
        from agenttree.issues import create_issue, get_issue
        from agenttree.hooks import execute_exit_hooks, ValidationError

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                issue = create_issue(title="Validation Test")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                # Create invalid problem.md (missing Context section)
                (issue_dir / "problem.md").write_text("""# Problem

Just a brief problem description without required sections.
""")

                issue = get_issue(issue.id)

                # Should fail validation
                with pytest.raises(ValidationError):
                    execute_exit_hooks(issue, issue.stage, issue.substage)

    def test_substage_progression(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that substages progress in correct order."""
        from agenttree.issues import get_next_stage
        from agenttree.config import load_config

        with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
            config = load_config()

            # Test define substages
            next_stage, next_substage = get_next_stage("define", "refine")
            assert next_stage == "research"
            assert next_substage == "explore"

            # Test research substages
            next_stage, next_substage = get_next_stage("research", "explore")
            assert next_stage == "research"
            assert next_substage == "document"

            next_stage, next_substage = get_next_stage("research", "document")
            assert next_stage == "plan"

            # Test implement substages (code → code_review → address_review → wrapup → feedback)
            next_stage, next_substage = get_next_stage("implement", "code")
            assert next_stage == "implement"
            assert next_substage == "code_review"

            next_stage, next_substage = get_next_stage("implement", "code_review")
            assert next_stage == "implement"
            assert next_substage == "address_review"

            next_stage, next_substage = get_next_stage("implement", "address_review")
            assert next_stage == "implement"
            assert next_substage == "wrapup"

            next_stage, next_substage = get_next_stage("implement", "wrapup")
            assert next_stage == "implement"
            assert next_substage == "feedback"

            next_stage, next_substage = get_next_stage("implement", "feedback")
            assert next_stage == "implementation_review"

    def test_history_tracks_transitions(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that issue history tracks all stage transitions."""
        from agenttree.issues import create_issue, get_issue, update_issue_stage

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                issue = create_issue(title="History Test")

                # Make some transitions
                update_issue_stage(issue.id, "research", "explore")
                update_issue_stage(issue.id, "research", "document")
                update_issue_stage(issue.id, "plan", "draft")

                # Check history
                issue = get_issue(issue.id)
                assert len(issue.history) >= 3

                # Verify history entries have required fields
                for entry in issue.history:
                    assert entry.stage is not None
                    assert entry.timestamp is not None


class TestWorkflowEdgeCases:
    """Test edge cases in the workflow."""

    def test_cannot_skip_stages(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that stages enforce content requirements via hooks.

        This tests that the validation hooks actually block progression when
        required content is missing or invalid.

        Note: Stage-level pre_completion hooks only run when exiting the LAST
        substage of a stage (e.g., plan.refine, not plan.draft).
        """
        from agenttree.issues import create_issue, get_issue, update_issue_stage
        from agenttree.hooks import execute_exit_hooks, execute_enter_hooks, ValidationError

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                issue = create_issue(title="Skip Test")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                # Create problem.md and skip to plan.refine (last substage of plan)
                create_valid_problem_md(issue_dir)
                update_issue_stage(issue.id, "plan", "refine")
                issue = get_issue(issue.id)

                # Execute enter hooks - this creates spec.md from template with empty sections
                execute_enter_hooks(issue, "plan", "refine")

                # Plan stage requires spec.md sections to be filled in - template has empty sections
                # Stage-level hooks run when exiting last substage (refine)
                # Validation should fail because Approach section is empty (only HTML comments)
                with pytest.raises(ValidationError):
                    execute_exit_hooks(issue, "plan", "refine")

    # Note: Tests for human_review stages and terminal stages are in test_full_workflow.py
    # (TestHumanReviewGates and TestTerminalStates classes)

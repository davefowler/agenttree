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
        """Test workflow from explore.define through plan.review (first human gate).

        This tests the agent-driven portion of the workflow before human review.
        """
        from agenttree.issues import create_issue, get_issue, get_next_stage, update_issue_stage
        from agenttree.hooks import execute_exit_hooks, execute_enter_hooks, ValidationError

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                # Step 1: Create issue (starts at explore.define)
                issue = create_issue(title="E2E Test Issue")
<<<<<<< HEAD
                issue_dir = agenttree_path / "issues" / issue.dir_name
=======
                issue_dir = agenttree_path / "issues" / f"{issue.id:03d}"
>>>>>>> origin/main

                assert issue.stage == "explore.define"

                # Track stages we've visited
                visited_stages = [issue.stage]

                # Step 2: Create valid problem.md
                create_valid_problem_md(issue_dir)

                # Step 3: Advance through stages until plan.review
                max_iterations = 20  # Safety limit
                iteration = 0

                while iteration < max_iterations:
                    iteration += 1

                    # Refresh issue
                    issue = get_issue(issue.id)
                    current_stage = issue.stage

                    # Stop at plan.review (human gate)
                    if current_stage == "plan.review":
                        break

                    # Create content needed for current stage
                    if current_stage.startswith("explore.research"):
                        create_valid_research_md(issue_dir)
                    elif current_stage == "plan.draft":
                        create_valid_spec_md(issue_dir)
                    elif current_stage == "plan.selfcheck":
                        create_valid_spec_review_md(issue_dir)

                    # Execute exit hooks (validates stage completion)
                    try:
                        execute_exit_hooks(issue, current_stage)
                    except ValidationError as e:
                        pytest.fail(f"Exit hooks failed at {current_stage}: {e}")

                    # Get next stage
                    next_stage, is_human_review = get_next_stage(current_stage)

                    # Update to next stage
                    update_issue_stage(issue.id, next_stage)

                    # Execute enter hooks
                    issue = get_issue(issue.id)
                    execute_enter_hooks(issue, next_stage)

                    visited_stages.append(next_stage)

                # Verify we reached plan.review
                final_issue = get_issue(issue.id)
                assert final_issue.stage == "plan.review", f"Expected plan.review, got {final_issue.stage}"

                # Verify we visited expected stages
                assert "explore.define" in visited_stages
                assert "explore.research" in visited_stages
                assert "plan.draft" in visited_stages
                assert "plan.selfcheck" in visited_stages
                assert "plan.review" in visited_stages

    def test_full_workflow_implement_to_implementation_review(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test workflow from implement.code through implement.review (second human gate).

        This tests the implementation portion after plan approval.
        """
        from agenttree.issues import create_issue, get_issue, get_next_stage, update_issue_stage
        from agenttree.hooks import execute_exit_hooks, execute_enter_hooks, ValidationError

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                # Create issue and advance to implement stage
                issue = create_issue(title="E2E Implement Test")
<<<<<<< HEAD
                issue_dir = agenttree_path / "issues" / issue.dir_name
=======
                issue_dir = agenttree_path / "issues" / f"{issue.id:03d}"
>>>>>>> origin/main

                # Create all prior content
                create_valid_problem_md(issue_dir)
                create_valid_research_md(issue_dir)
                create_valid_spec_md(issue_dir)
                create_valid_spec_review_md(issue_dir)

                # Skip directly to implement.code
                update_issue_stage(issue.id, "implement.code")
                issue = get_issue(issue.id)

                assert issue.stage == "implement.code"

                visited_stages = ["implement.code"]
                max_iterations = 10
                iteration = 0

                while iteration < max_iterations:
                    iteration += 1

                    issue = get_issue(issue.id)
                    current_stage = issue.stage

                    # Stop at implement.review
                    if current_stage == "implement.review":
                        break

                    # Create/overwrite review.md with valid content when needed
                    if current_stage in ["implement.code_review", "implement.address_review",
                                         "implement.wrapup", "implement.feedback"]:
                        create_valid_review_md(issue_dir)

                    # Mock has_commits_to_push for feedback stage
                    with patch("agenttree.hooks.has_commits_to_push", return_value=True):
                        try:
                            execute_exit_hooks(issue, current_stage)
                        except ValidationError as e:
                            pytest.fail(f"Exit hooks failed at {current_stage}: {e}")

                    next_stage, _ = get_next_stage(current_stage)
                    update_issue_stage(issue.id, next_stage)

                    issue = get_issue(issue.id)
                    execute_enter_hooks(issue, next_stage)

                    visited_stages.append(next_stage)

                # Verify we reached implement.review
                final_issue = get_issue(issue.id)
                assert final_issue.stage == "implement.review"

                # Verify we visited all implement substages
                assert "implement.code" in visited_stages
                assert "implement.code_review" in visited_stages
                assert "implement.address_review" in visited_stages
                assert "implement.wrapup" in visited_stages
                assert "implement.feedback" in visited_stages

    def test_full_workflow_to_accepted(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test complete workflow from create to accepted.

        This is the full end-to-end test, including human review gates
        (simulated by skipping the human_review check).
        """
        from agenttree.issues import create_issue, get_issue, get_next_stage, update_issue_stage
        from agenttree.hooks import execute_exit_hooks, execute_enter_hooks, ValidationError

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                # Create issue
                issue = create_issue(title="Full E2E Test")
<<<<<<< HEAD
                issue_dir = agenttree_path / "issues" / issue.dir_name
=======
                issue_dir = agenttree_path / "issues" / f"{issue.id:03d}"
>>>>>>> origin/main

                all_stages_visited = []
                max_iterations = 30
                iteration = 0

                while iteration < max_iterations:
                    iteration += 1

                    issue = get_issue(issue.id)
                    current_stage = issue.stage

                    all_stages_visited.append(current_stage)

                    # Stop at accepted
                    if current_stage == "accepted":
                        break

                    # Create/overwrite content based on stage
                    if current_stage.startswith("explore.define"):
                        create_valid_problem_md(issue_dir)
                    elif current_stage.startswith("explore.research"):
                        create_valid_research_md(issue_dir)
                    elif current_stage.startswith("plan."):
                        create_valid_spec_md(issue_dir)
                        create_valid_spec_review_md(issue_dir)
                    elif current_stage.startswith("implement."):
                        create_valid_review_md(issue_dir)

                    # Execute exit hooks with proper mocking for hooks that need external setup
                    with patch("agenttree.hooks.has_commits_to_push", return_value=True):
                        # Mock rebase hook (requires actual git remote)
                        with patch("agenttree.hooks.run_command_hook", return_value=[]):
                            # Skip PR approval check (no actual PR in tests)
                            execute_exit_hooks(issue, current_stage, skip_pr_approval=True)

                    next_stage, _ = get_next_stage(current_stage)

                    if next_stage is None:
                        pytest.fail(f"No next stage from {current_stage}")

                    update_issue_stage(issue.id, next_stage)

                    issue = get_issue(issue.id)
                    execute_enter_hooks(issue, next_stage)

                # Verify we reached accepted
                final_issue = get_issue(issue.id)
                assert final_issue.stage == "accepted", f"Expected accepted, got {final_issue.stage}"

                # Verify we touched all major stages
                stage_prefixes = set()
                for s in all_stages_visited:
                    stage_prefixes.add(s.split(".")[0] if "." in s else s)
                expected_prefixes = {"explore", "plan", "implement", "accepted"}
                missing = expected_prefixes - stage_prefixes
                assert not missing, f"Missing stage groups: {missing}"

    def test_validation_blocks_invalid_content(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that validation actually blocks progression with invalid content."""
        from agenttree.issues import create_issue, get_issue
        from agenttree.hooks import execute_exit_hooks, ValidationError

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                issue = create_issue(title="Validation Test")
<<<<<<< HEAD
                issue_dir = agenttree_path / "issues" / issue.dir_name
=======
                issue_dir = agenttree_path / "issues" / f"{issue.id:03d}"
>>>>>>> origin/main

                # Create invalid problem.md (missing Context section)
                (issue_dir / "problem.md").write_text("""# Problem

Just a brief problem description without required sections.
""")

                issue = get_issue(issue.id)

                # Should fail validation
                with pytest.raises(ValidationError):
                    execute_exit_hooks(issue, issue.stage)

    def test_substage_progression(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that substages progress in correct order."""
        from agenttree.issues import get_next_stage
        from agenttree.config import load_config

        with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
            config = load_config()

            # Test explore substages
            next_stage, _ = get_next_stage("explore.define")
            assert next_stage == "explore.research"

            # Test explore -> plan transition
            next_stage, _ = get_next_stage("explore.research")
            assert next_stage == "plan.draft"

            # Test plan substages
            next_stage, _ = get_next_stage("plan.draft")
            assert next_stage == "plan.selfcheck"

            # Test implement substages (code -> code_review -> address_review -> wrapup -> feedback)
            next_stage, _ = get_next_stage("implement.code")
            assert next_stage == "implement.code_review"

            next_stage, _ = get_next_stage("implement.code_review")
            assert next_stage == "implement.address_review"

            next_stage, _ = get_next_stage("implement.address_review")
            assert next_stage == "implement.wrapup"

            next_stage, _ = get_next_stage("implement.wrapup")
            assert next_stage == "implement.feedback"

            next_stage, _ = get_next_stage("implement.feedback")
            assert next_stage == "implement.review"

    def test_history_tracks_transitions(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that issue history tracks all stage transitions."""
        from agenttree.issues import create_issue, get_issue, update_issue_stage

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                issue = create_issue(title="History Test")

                # Make some transitions
                update_issue_stage(issue.id, "explore.research")
                update_issue_stage(issue.id, "plan.draft")
                update_issue_stage(issue.id, "plan.selfcheck")

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
        substage of a stage (e.g., plan.draft has its own hooks).
        """
        from agenttree.issues import create_issue, get_issue, update_issue_stage
        from agenttree.hooks import execute_exit_hooks, execute_enter_hooks, ValidationError

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                issue = create_issue(title="Skip Test")
<<<<<<< HEAD
                issue_dir = agenttree_path / "issues" / issue.dir_name
=======
                issue_dir = agenttree_path / "issues" / f"{issue.id:03d}"
>>>>>>> origin/main

                # Create problem.md and skip to plan.draft (has pre_completion hooks)
                create_valid_problem_md(issue_dir)
                update_issue_stage(issue.id, "plan.draft")
                issue = get_issue(issue.id)

                # Execute enter hooks - this creates spec.md from template with empty sections
                execute_enter_hooks(issue, "plan.draft")

                # Plan.draft stage requires spec.md sections to be filled in -
                # template has empty sections
                # Validation should fail because Approach section is empty (only HTML comments)
                with pytest.raises(ValidationError):
                    execute_exit_hooks(issue, "plan.draft")

    # Note: Tests for human_review stages and terminal stages are in test_full_workflow.py
    # (TestHumanReviewGates and TestTerminalStates classes)

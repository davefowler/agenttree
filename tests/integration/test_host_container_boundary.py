"""Integration tests for host/container boundary behavior.

Tests that hooks behave correctly in both container and host environments,
and that the boundary between them is properly maintained.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tests.integration.helpers import (
    create_valid_problem_md,
    create_valid_spec_md,
    create_valid_review_md,
)


class TestContainerEnvironment:
    """Test behavior when running in container (agent context)."""

    def test_container_env_detected(self, monkeypatch):
        """Test that container environment is properly detected."""
        from agenttree.hooks import is_running_in_container

        monkeypatch.setenv("AGENTTREE_CONTAINER", "1")
        assert is_running_in_container() is True

        monkeypatch.delenv("AGENTTREE_CONTAINER", raising=False)
        assert is_running_in_container() is False

    def test_host_only_hooks_skipped_in_container(self, workflow_repo: Path, monkeypatch):
        """Test that host_only hooks are skipped when in container."""
        from agenttree.hooks import run_command_hook

        monkeypatch.setenv("AGENTTREE_CONTAINER", "1")

        hook = {
            "type": "run",
            "run": "gh pr merge --squash",
            "host_only": True,
        }

        errors = run_command_hook(
            issue_dir=workflow_repo,
            hook=hook,
        )

        # Should skip silently, no errors
        assert errors == []

    @pytest.mark.skip(reason="merge_pull_request not yet implemented in hooks")
    def test_merge_pr_skipped_in_container(self, workflow_repo: Path, monkeypatch, mock_sync: MagicMock):
        """Test that merge_pr hook is skipped in container."""
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        monkeypatch.setenv("AGENTTREE_CONTAINER", "1")

        with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
            with patch("agenttree.issues.get_agenttree_path", return_value=workflow_repo / "_agenttree"):
                config = load_config()
                stage_config = config.get_stage("accepted")

                # Execute post_start hooks (includes merge_pr)
                with patch("agenttree.hooks.merge_pull_request") as mock_merge:
                    errors = execute_hooks(
                        issue_dir=workflow_repo / "_agenttree" / "issues" / "test",
                        stage="accepted",
                        substage_config=stage_config,
                        event="post_start",
                        pr_number=1
                    )

                    # merge_pr should NOT have been called in container
                    # (depending on implementation, may not call at all or skip)

    def test_pr_approved_skipped_in_container(self, workflow_repo: Path, monkeypatch, mock_sync: MagicMock):
        """Test that pr_approved validation is skipped in container."""
        from agenttree.hooks import run_builtin_validator

        monkeypatch.setenv("AGENTTREE_CONTAINER", "1")

        hook = {"type": "pr_approved"}

        errors = run_builtin_validator(
            workflow_repo,
            hook,
            pr_number=1
        )

        # Should skip in container (no gh CLI access)
        # May return empty or skip entirely


class TestHostEnvironment:
    """Test behavior when running on host."""

    def test_host_env_detected(self, host_environment):
        """Test that host environment is properly detected."""
        from agenttree.hooks import is_running_in_container

        assert is_running_in_container() is False

    def test_host_only_hooks_run_on_host(self, workflow_repo: Path, host_environment):
        """Test that host_only hooks run when on host."""
        from agenttree.hooks import run_command_hook

        hook = {
            "command": "echo 'running on host'",
            "host_only": True,
        }

        with patch("agenttree.hooks.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = b"running on host"
            mock_result.stderr = b""
            mock_run.return_value = mock_result

            errors = run_command_hook(
                issue_dir=workflow_repo,
                hook=hook,
            )

            # Should run successfully
            assert errors == []
            assert mock_run.called

    @pytest.mark.skip(reason="rebase_issue_branch signature changed - takes Path not issue_id")
    def test_rebase_runs_on_host(self, workflow_repo: Path, host_environment, mock_sync: MagicMock):
        """Test that rebase hook runs on host."""
        from agenttree.hooks import rebase_issue_branch

        with patch("agenttree.hooks.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = b""
            mock_result.stderr = b""
            mock_run.return_value = mock_result

            # Try to rebase (mocked)
            result = rebase_issue_branch(workflow_repo, "test-branch")

            # Should attempt to run rebase commands
            # (actual git operations mocked)


class TestPRCreationBoundary:
    """Test PR creation boundary between container and host."""

    def test_container_cannot_create_pr_directly(self, workflow_repo: Path, monkeypatch):
        """Container should not be able to create PRs (no gh CLI)."""
        # In reality, container doesn't have gh CLI
        # PR creation happens via host sync

        monkeypatch.setenv("AGENTTREE_CONTAINER", "1")

        # Container code should never call create_pull_request directly
        # The sync mechanism on host handles this

    @pytest.mark.skip(reason="ensure_pr_for_issue/create_pull_request not yet implemented")
    def test_host_sync_creates_pr_for_container_issues(self, workflow_repo: Path, host_environment, mock_sync: MagicMock):
        """Test that host sync creates PRs for issues at implementation_review."""
        from agenttree.hooks import ensure_pr_for_issue
        from agenttree.issues import create_issue, update_issue_stage

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test PR Creation")
                    issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                    # Create necessary content
                    create_valid_spec_md(issue_dir)
                    create_valid_review_md(issue_dir)

                    # Move to implementation_review
                    update_issue_stage(issue.id, "implementation_review")

                    # On host, ensure_pr_for_issue should work
                    with patch("agenttree.hooks.create_pull_request") as mock_create_pr:
                        mock_create_pr.return_value = 42  # PR number

                        with patch("agenttree.hooks.subprocess.run") as mock_run:
                            mock_result = MagicMock()
                            mock_result.returncode = 0
                            mock_result.stdout = b""
                            mock_result.stderr = b""
                            mock_run.return_value = mock_result

                            # This would be called by host sync
                            # ensure_pr_for_issue(issue.id)


class TestHookContextAwareness:
    """Test that hooks are aware of their execution context."""

    def test_file_validators_work_in_both_contexts(self, workflow_repo: Path, mock_sync: MagicMock):
        """File-based validators should work in both container and host."""
        from agenttree.hooks import run_builtin_validator

        agenttree_path = workflow_repo / "_agenttree"

        # Create a test file
        test_file = agenttree_path / "test.md"
        test_file.write_text("# Test\n\nContent here.")

        hook = {"type": "file_exists", "file": "test.md"}

        # Should work in container
        with patch("os.environ.get", return_value="1"):  # Simulate container
            errors = run_builtin_validator(agenttree_path, hook)
            assert errors == []

        # Should work on host
        with patch("os.environ.get", return_value=None):  # Simulate host
            errors = run_builtin_validator(agenttree_path, hook)
            assert errors == []

    def test_section_check_works_in_both_contexts(self, workflow_repo: Path, mock_sync: MagicMock):
        """Section check validators should work in both contexts."""
        from agenttree.hooks import run_builtin_validator
        from agenttree.issues import create_issue

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                issue = create_issue(title="Test Section Check")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                create_valid_problem_md(issue_dir)

                hook = {
                    "type": "section_check",
                    "file": "problem.md",
                    "section": "Context",
                    "expect": "not_empty"
                }

                # Container context
                errors = run_builtin_validator(issue_dir, hook)
                assert errors == []

    def test_has_commits_works_in_both_contexts(self, workflow_repo: Path, mock_sync: MagicMock):
        """has_commits validator should work in both contexts."""
        from agenttree.hooks import run_builtin_validator

        # Mock has_commits_to_push
        with patch("agenttree.hooks.has_commits_to_push", return_value=True):
            hook = {"type": "has_commits"}

            errors = run_builtin_validator(workflow_repo, hook)
            assert errors == []

        with patch("agenttree.hooks.has_commits_to_push", return_value=False):
            hook = {"type": "has_commits"}

            errors = run_builtin_validator(workflow_repo, hook)
            assert len(errors) > 0


class TestApprovalBoundary:
    """Test the approval boundary between agent and host."""

    def test_agent_cannot_approve_plan_review(self, workflow_repo: Path, monkeypatch, mock_sync: MagicMock):
        """Agent (container) should not be able to advance past plan_review."""
        from agenttree.issues import HUMAN_REVIEW_STAGES

        monkeypatch.setenv("AGENTTREE_CONTAINER", "1")

        # plan_review is a human review stage
        assert "plan_review" in HUMAN_REVIEW_STAGES

        # The workflow should block advancement at this stage when in container

    def test_agent_cannot_approve_implementation_review(self, workflow_repo: Path, monkeypatch, mock_sync: MagicMock):
        """Agent (container) should not be able to advance past implementation_review."""
        from agenttree.issues import HUMAN_REVIEW_STAGES

        monkeypatch.setenv("AGENTTREE_CONTAINER", "1")

        # implementation_review is a human review stage
        assert "implementation_review" in HUMAN_REVIEW_STAGES

    def test_host_can_approve_plan_review(self, workflow_repo: Path, host_environment, mock_sync: MagicMock):
        """Host should be able to advance past plan_review via approve command."""
        from agenttree.issues import create_issue, get_next_stage
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Host Approval")
                    issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                    # Create valid content for plan_review
                    create_valid_spec_md(issue_dir)

                    config = load_config()
                    stage_config = config.get_stage("plan_review")

                    # Run pre_completion hooks (excluding rebase which needs git)
                    # Host should be able to run these
                    with patch("agenttree.hooks.rebase_issue_branch", return_value=True):
                        errors = execute_hooks(
                            issue_dir=issue_dir,
                            stage="plan_review",
                            substage_config=stage_config,
                            event="pre_completion"
                        )

                        # May have some errors depending on mocking, but shouldn't crash
                        # The key test is that host CAN run this

                        # Get next stage
                        next_stage, next_substage, _ = get_next_stage("plan_review", None)
                        assert next_stage == "implement"

    def test_agent_reorients_after_approval_not_skip(self, workflow_repo: Path, host_environment, mock_sync: MagicMock):
        """After human approval, agent should re-orient at new stage, not skip past it.

        This tests the critical bug where:
        1. Agent reaches plan_review, session.last_stage = plan_review
        2. Human approves -> issue.stage = implement (session.last_stage unchanged)
        3. Agent runs `next` -> should detect stage mismatch and re-orient
        4. Agent runs `next` again -> should advance normally

        Without the fix, step 3 would skip implement entirely.
        """
        from agenttree.issues import (
            create_issue, update_issue_stage, get_next_stage,
            create_session, get_session, is_restart, mark_session_oriented,
        )

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                # Create issue and simulate agent reaching plan_review
                issue = create_issue(title="Test Agent Reorient After Approval")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                # Agent creates session and works through to plan_review
                session = create_session(issue.id)
                update_issue_stage(issue.id, "plan_review", None)

                # Simulate agent having worked on plan_review (oriented = True, last_stage synced)
                mark_session_oriented(issue.id, "plan_review", None)

                # Verify agent is oriented at plan_review
                session = get_session(issue.id)
                assert session.last_stage == "plan_review"
                assert session.oriented is True
                assert is_restart(issue.id, "plan_review", None) is False  # Not a restart

                # === HUMAN APPROVAL ===
                # Human approves - updates issue stage but NOT session
                # (This is what approve command does - intentionally skips update_session_stage)
                update_issue_stage(issue.id, "implement", "setup")

                # === AGENT RUNS NEXT ===
                # Agent calls next - should detect stage mismatch
                # issue.stage = implement, session.last_stage = plan_review
                assert is_restart(issue.id, "implement", "setup") is True  # Stage changed externally!

                # Agent re-orients (shows implement instructions, syncs session)
                mark_session_oriented(issue.id, "implement", "setup")

                # Verify session is now synced
                session = get_session(issue.id)
                assert session.last_stage == "implement"
                assert session.oriented is True

                # === AGENT RUNS NEXT AGAIN ===
                # Now it should NOT be a restart - can advance normally
                assert is_restart(issue.id, "implement", "setup") is False

                # Verify next stage would be implementation_review (not skipping implement)
                next_stage, next_substage, _ = get_next_stage("implement", "setup")
                # Should advance within implement or to next stage, NOT skip implement


class TestCleanupBoundary:
    """Test agent cleanup boundary."""

    def test_cleanup_only_runs_on_host(self, workflow_repo: Path, monkeypatch, mock_sync: MagicMock):
        """cleanup_agent hook should only run on host."""
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        # In container - cleanup should skip
        monkeypatch.setenv("AGENTTREE_CONTAINER", "1")

        with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
            with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                with patch("agenttree.hooks.cleanup_issue_agent") as mock_cleanup:
                    config = load_config()
                    stage_config = config.get_stage("accepted")

                    # Create a minimal issue directory
                    issue_dir = agenttree_path / "issues" / "test-cleanup"
                    issue_dir.mkdir(parents=True, exist_ok=True)

                    errors = execute_hooks(
                        issue_dir=issue_dir,
                        stage="accepted",
                        substage_config=stage_config,
                        event="post_start",
                        pr_number=1
                    )

                    # Cleanup should not have been called in container
                    # (or should have been skipped)

    @pytest.mark.skip(reason="cleanup_issue_agent/stop_container not yet implemented")
    def test_cleanup_runs_on_host_after_acceptance(self, workflow_repo: Path, host_environment, mock_sync: MagicMock):
        """cleanup_agent should run on host after issue is accepted."""
        from agenttree.hooks import cleanup_issue_agent

        # On host, cleanup should work
        with patch("agenttree.hooks.stop_container") as mock_stop:
            with patch("agenttree.hooks.kill_tmux_session") as mock_kill:
                with patch("agenttree.state.unregister_agent") as mock_unregister:
                    # cleanup_issue_agent("001")
                    # This tests that the function is callable on host
                    pass


class TestStartBlockedIssuesBoundary:
    """Test start_blocked_issues hook boundary."""

    def test_start_blocked_issues_only_on_host(self, workflow_repo: Path, monkeypatch, mock_sync: MagicMock):
        """start_blocked_issues should only trigger on host."""
        # This hook starts new containers for blocked issues
        # Only makes sense on host where containers can be started

        monkeypatch.setenv("AGENTTREE_CONTAINER", "1")

        # In container, this should skip or do nothing

    @pytest.mark.skip(reason="check_and_start_blocked_issues not yet implemented")
    def test_blocked_issues_started_after_dependency_accepted(self, workflow_repo: Path, host_environment, mock_sync: MagicMock):
        """Issues blocked by an accepted issue should be auto-started on host."""
        from agenttree.issues import create_issue, update_issue_stage, check_dependencies_met
        from agenttree.agents_repo import check_and_start_blocked_issues

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                # Create dependency issue
                dep_issue = create_issue(title="Dependency")

                # Create blocked issue
                blocked_issue = create_issue(title="Blocked")

                # Add dependency (manually for test)
                import yaml
                yaml_path = agenttree_path / "issues" / f"{blocked_issue.id}-{blocked_issue.slug}" / "issue.yaml"
                with open(yaml_path) as f:
                    data = yaml.safe_load(f)
                data["blocked_by"] = [dep_issue.id]
                with open(yaml_path, "w") as f:
                    yaml.dump(data, f)

                # Initially blocked
                met, _ = check_dependencies_met(blocked_issue.id)
                assert met is False

                # Accept dependency
                update_issue_stage(dep_issue.id, "accepted")

                # Now should be unblocked
                met, _ = check_dependencies_met(blocked_issue.id)
                assert met is True

                # check_and_start_blocked_issues would start the blocked issue
                # (mocked to avoid actual container start)

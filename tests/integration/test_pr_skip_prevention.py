"""Integration tests for PR/manager hook skip prevention paths."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestTransitionRollbackOnEnterHookFailure:
    """Ensure stage transitions don't stick when enter hooks fail."""

    def test_transition_rolls_back_when_enter_hook_errors(
        self,
        workflow_repo: Path,
        mock_sync: MagicMock,
    ) -> None:
        """Failed enter hooks should rollback to the previous stage."""
        from agenttree.api import transition_issue
        from agenttree.issues import create_issue, get_issue, update_issue_stage

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                issue = create_issue(title="Rollback when accepted enter hook fails")
                updated = update_issue_stage(issue.id, "knowledge_base")
                assert updated is not None
                assert updated.stage == "knowledge_base"

                with patch("agenttree.hooks.execute_enter_hooks", side_effect=RuntimeError("merge failed")), \
                     patch("agenttree.api._ensure_stage_agent"):
                    with pytest.raises(RuntimeError, match="Enter hooks failed"):
                        transition_issue(issue.id, "accepted")

                current = get_issue(issue.id)
                assert current is not None
                assert current.stage == "knowledge_base"


class TestManagerHookRetryBehavior:
    """Ensure manager stage hooks don't get permanently skipped on failures."""

    def test_failed_manager_hooks_clear_running_flag_for_retry(
        self,
        workflow_repo: Path,
        host_environment,
        mock_sync: MagicMock,
    ) -> None:
        """If manager hooks fail once, heartbeat should retry next cycle."""
        from agenttree.agents_repo import check_manager_stages
        from agenttree.issues import Issue, create_issue, update_issue_stage

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                issue = create_issue(title="Retry manager hooks after transient failure")
                update_issue_stage(issue.id, "accepted")
                issue_yaml = agenttree_path / "issues" / f"{issue.id:03d}" / "issue.yaml"

                with patch("agenttree.hooks.execute_enter_hooks", side_effect=RuntimeError("transient failure")):
                    processed = check_manager_stages(agenttree_path)
                    assert processed == 0

                first = Issue.from_yaml(issue_yaml)
                assert first.manager_hooks_executed is None

                with patch("agenttree.hooks.execute_enter_hooks", return_value=None):
                    processed = check_manager_stages(agenttree_path)
                    assert processed == 1

                second = Issue.from_yaml(issue_yaml)
                assert second.manager_hooks_executed == "accepted"

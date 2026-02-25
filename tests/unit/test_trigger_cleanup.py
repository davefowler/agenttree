"""Tests for trigger_cleanup action."""

from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest
import yaml


class TestTriggerCleanup:
    """Tests for trigger_cleanup heartbeat action."""

    def _make_issue(self, issue_id: int, stage: str = "accepted") -> MagicMock:
        """Create a mock issue."""
        issue = MagicMock()
        issue.id = issue_id
        issue.stage = stage
        issue.title = f"Test Issue {issue_id}"
        return issue

    @patch("agenttree.events.save_event_state")
    @patch("agenttree.events.load_event_state")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.issues.create_issue")
    def test_trigger_cleanup_below_threshold(
        self,
        mock_create: MagicMock,
        mock_list: MagicMock,
        mock_load_state: MagicMock,
        mock_save_state: MagicMock,
        tmp_path: Path,
    ) -> None:
        """No issue created when accepted count is below threshold."""
        from agenttree.actions import trigger_cleanup

        # 5 accepted issues, threshold 10 - should not trigger
        mock_list.return_value = [
            self._make_issue(i, "accepted") for i in range(1, 6)
        ]
        mock_load_state.return_value = {"cleanup_trigger": {"last_batch_end": 0}}

        trigger_cleanup(tmp_path, threshold=10)

        mock_create.assert_not_called()

    @patch("agenttree.events.save_event_state")
    @patch("agenttree.events.load_event_state")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.issues.create_issue")
    def test_trigger_cleanup_at_threshold(
        self,
        mock_create: MagicMock,
        mock_list: MagicMock,
        mock_load_state: MagicMock,
        mock_save_state: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Issue created with correct flow when threshold reached."""
        from agenttree.actions import trigger_cleanup

        # 10 accepted issues, threshold 10 - should trigger
        mock_list.return_value = [
            self._make_issue(i, "accepted") for i in range(1, 11)
        ]
        mock_load_state.return_value = {"cleanup_trigger": {"last_batch_end": 0}}
        mock_create.return_value = self._make_issue(11)

        trigger_cleanup(tmp_path, threshold=10)

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["flow"] == "cleanup"
        assert "Cleanup batch" in call_kwargs["title"]

    @patch("agenttree.events.save_event_state")
    @patch("agenttree.events.load_event_state")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.issues.create_issue")
    def test_trigger_cleanup_state_tracking(
        self,
        mock_create: MagicMock,
        mock_list: MagicMock,
        mock_load_state: MagicMock,
        mock_save_state: MagicMock,
        tmp_path: Path,
    ) -> None:
        """After trigger, state tracks last_batch_end ID."""
        from agenttree.actions import trigger_cleanup

        mock_list.return_value = [
            self._make_issue(i, "accepted") for i in range(1, 11)
        ]
        mock_load_state.return_value = {"cleanup_trigger": {"last_batch_end": 0}}
        mock_create.return_value = self._make_issue(11)

        trigger_cleanup(tmp_path, threshold=10)

        # Check that save_event_state was called with updated last_batch_end
        mock_save_state.assert_called_once()
        saved_state = mock_save_state.call_args[0][1]
        assert saved_state["cleanup_trigger"]["last_batch_end"] == 10

    @patch("agenttree.events.save_event_state")
    @patch("agenttree.events.load_event_state")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.issues.create_issue")
    def test_trigger_cleanup_no_duplicate(
        self,
        mock_create: MagicMock,
        mock_list: MagicMock,
        mock_load_state: MagicMock,
        mock_save_state: MagicMock,
        tmp_path: Path,
    ) -> None:
        """No issue created when cleanup issue already exists (not accepted)."""
        from agenttree.actions import trigger_cleanup

        # 10 accepted issues + 1 cleanup in progress
        issues = [self._make_issue(i, "accepted") for i in range(1, 11)]
        cleanup_issue = self._make_issue(11, "implement.code")
        cleanup_issue.flow = "cleanup"
        issues.append(cleanup_issue)
        mock_list.return_value = issues
        mock_load_state.return_value = {"cleanup_trigger": {"last_batch_end": 0}}

        trigger_cleanup(tmp_path, threshold=10)

        mock_create.assert_not_called()

    @patch("agenttree.events.save_event_state")
    @patch("agenttree.events.load_event_state")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.issues.create_issue")
    def test_trigger_cleanup_increments_batch(
        self,
        mock_create: MagicMock,
        mock_list: MagicMock,
        mock_load_state: MagicMock,
        mock_save_state: MagicMock,
        tmp_path: Path,
    ) -> None:
        """After cleanup is accepted, next batch starts counting from there."""
        from agenttree.actions import trigger_cleanup

        # Previous batch ended at 10, now we have issues 11-20 accepted
        mock_list.return_value = [
            self._make_issue(i, "accepted") for i in range(1, 21)
        ]
        mock_load_state.return_value = {"cleanup_trigger": {"last_batch_end": 10}}
        mock_create.return_value = self._make_issue(21)

        trigger_cleanup(tmp_path, threshold=10)

        # Should create issue since we have 10 new accepted issues (11-20)
        mock_create.assert_called_once()

        # last_batch_end should update to 20
        saved_state = mock_save_state.call_args[0][1]
        assert saved_state["cleanup_trigger"]["last_batch_end"] == 20

    @patch("agenttree.events.save_event_state")
    @patch("agenttree.events.load_event_state")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.issues.create_issue")
    def test_trigger_cleanup_problem_content(
        self,
        mock_create: MagicMock,
        mock_list: MagicMock,
        mock_load_state: MagicMock,
        mock_save_state: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Created issue's problem references correct issue range."""
        from agenttree.actions import trigger_cleanup

        mock_list.return_value = [
            self._make_issue(i, "accepted") for i in range(1, 11)
        ]
        mock_load_state.return_value = {"cleanup_trigger": {"last_batch_end": 0}}
        mock_create.return_value = self._make_issue(11)

        trigger_cleanup(tmp_path, threshold=10)

        call_kwargs = mock_create.call_args[1]
        problem = call_kwargs["problem"]
        # Should reference issues 1-10
        assert "#1" in problem or "1" in problem
        assert "#10" in problem or "10" in problem
        # Should mention reviewing review.md files
        assert "review.md" in problem.lower() or "review" in problem.lower()

    @patch("agenttree.events.save_event_state")
    @patch("agenttree.events.load_event_state")
    @patch("agenttree.issues.list_issues")
    @patch("agenttree.issues.create_issue")
    def test_trigger_cleanup_first_run_no_state(
        self,
        mock_create: MagicMock,
        mock_list: MagicMock,
        mock_load_state: MagicMock,
        mock_save_state: MagicMock,
        tmp_path: Path,
    ) -> None:
        """First run with no existing state works correctly."""
        from agenttree.actions import trigger_cleanup

        mock_list.return_value = [
            self._make_issue(i, "accepted") for i in range(1, 11)
        ]
        # No existing cleanup_trigger state
        mock_load_state.return_value = {}
        mock_create.return_value = self._make_issue(11)

        trigger_cleanup(tmp_path, threshold=10)

        mock_create.assert_called_once()
        saved_state = mock_save_state.call_args[0][1]
        assert saved_state["cleanup_trigger"]["last_batch_end"] == 10

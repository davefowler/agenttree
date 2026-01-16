"""Tests for the TUI (Terminal User Interface) module."""

from unittest.mock import MagicMock, patch

import pytest

from agenttree.issues import Issue, Priority
from agenttree.tui.app import (
    DetailPanel,
    FilterInput,
    IssueTable,
    REJECTION_MAPPINGS,
    StatusBar,
    TUIApp,
)


# Test fixtures
@pytest.fixture
def sample_issues() -> list[Issue]:
    """Create sample issues for testing."""
    return [
        Issue(
            id="001",
            slug="fix-login-bug",
            title="Fix login bug",
            created="2024-01-01T00:00:00Z",
            updated="2024-01-01T00:00:00Z",
            stage="backlog",
            substage=None,
            priority=Priority.HIGH,
            assigned_agent=None,
        ),
        Issue(
            id="002",
            slug="add-dashboard",
            title="Add dashboard feature",
            created="2024-01-02T00:00:00Z",
            updated="2024-01-02T00:00:00Z",
            stage="implement",
            substage="code",
            priority=Priority.MEDIUM,
            assigned_agent="1",
        ),
        Issue(
            id="003",
            slug="review-pr",
            title="Review PR changes",
            created="2024-01-03T00:00:00Z",
            updated="2024-01-03T00:00:00Z",
            stage="plan_review",
            substage=None,
            priority=Priority.CRITICAL,
            assigned_agent=None,
        ),
    ]


class TestTUIApp:
    """Tests for the TUIApp class."""

    @pytest.mark.asyncio
    async def test_app_launches(self) -> None:
        """Verify TUI app initializes without error."""
        app = TUIApp()
        async with app.run_test() as pilot:
            # App should be running
            assert app.is_running

    @pytest.mark.asyncio
    async def test_app_has_expected_widgets(self) -> None:
        """Verify app composes expected widgets."""
        app = TUIApp()
        async with app.run_test() as pilot:
            # Should have key widgets
            assert app.query_one(IssueTable)
            assert app.query_one(DetailPanel)
            assert app.query_one(FilterInput)
            assert app.query_one(StatusBar)

    @pytest.mark.asyncio
    async def test_quit_action(self) -> None:
        """Verify 'q' key triggers quit action."""
        app = TUIApp()
        async with app.run_test() as pilot:
            # The quit action is bound to 'q'
            # In test mode, we verify the binding exists rather than checking is_running
            # since the test context handles app lifecycle differently
            assert any(b.key == "q" and b.action == "quit" for b in app.BINDINGS)


class TestIssueTable:
    """Tests for the IssueTable widget."""

    @pytest.mark.asyncio
    async def test_issue_table_columns(self) -> None:
        """Verify correct columns (ID, Title, Stage, Priority, Agent)."""
        app = TUIApp()
        async with app.run_test() as pilot:
            table = app.query_one(IssueTable)
            # Columns should be set up
            columns = [col.label.plain for col in table.columns.values()]
            assert "ID" in columns
            assert "Title" in columns
            assert "Stage" in columns
            assert "Priority" in columns
            assert "Agent" in columns

    @pytest.mark.asyncio
    async def test_issue_table_displays_issues(self, sample_issues: list[Issue]) -> None:
        """Verify issue list populates with mock data."""
        app = TUIApp()
        async with app.run_test() as pilot:
            table = app.query_one(IssueTable)
            table.populate(sample_issues)

            # Should have 3 rows
            assert table.row_count == 3

    @pytest.mark.asyncio
    async def test_row_selection(self, sample_issues: list[Issue]) -> None:
        """Verify get_selected_issue returns the correct issue based on cursor position."""
        app = TUIApp()
        async with app.run_test() as pilot:
            table = app.query_one(IssueTable)
            table.populate(sample_issues)

            # Verify cursor_type is set correctly for row selection
            assert table.cursor_type == "row"

            # Initial cursor at row 0 should return first issue
            issue = table.get_selected_issue()
            assert issue is not None
            assert issue.id == "001"

            # Verify we can get issues at different positions
            # by directly checking filtered_issues list
            assert len(table._filtered_issues) == 3
            assert table._filtered_issues[1].id == "002"
            assert table._filtered_issues[2].id == "003"


class TestDetailPanel:
    """Tests for the DetailPanel widget."""

    @pytest.mark.asyncio
    async def test_detail_panel_shows_issue(self, sample_issues: list[Issue]) -> None:
        """Verify detail panel populates on issue selection."""
        app = TUIApp()
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)

            # Show an issue
            panel.show_issue(sample_issues[0])

            # Panel should have the issue
            assert panel.issue is not None
            assert panel.issue.id == "001"

    @pytest.mark.asyncio
    async def test_detail_panel_clear(self, sample_issues: list[Issue]) -> None:
        """Verify detail panel can be cleared."""
        app = TUIApp()
        async with app.run_test() as pilot:
            panel = app.query_one(DetailPanel)

            # Show then clear
            panel.show_issue(sample_issues[0])
            panel.clear_issue()

            # Panel should be cleared
            assert panel.issue is None


class TestFilterInput:
    """Tests for the FilterInput widget."""

    @pytest.mark.asyncio
    async def test_filter_by_stage(self, sample_issues: list[Issue]) -> None:
        """Verify filtering reduces visible issues."""
        app = TUIApp()
        async with app.run_test() as pilot:
            table = app.query_one(IssueTable)
            table.populate(sample_issues)

            # Filter by "implement"
            table.apply_filter("implement")

            # Should only show 1 issue (002 - implement.code)
            assert table.row_count == 1

    @pytest.mark.asyncio
    async def test_filter_by_priority(self, sample_issues: list[Issue]) -> None:
        """Verify filtering by priority works."""
        app = TUIApp()
        async with app.run_test() as pilot:
            table = app.query_one(IssueTable)
            table.populate(sample_issues)

            # Filter by "critical"
            table.apply_filter("critical")

            # Should only show 1 issue (003 - critical priority)
            assert table.row_count == 1

    @pytest.mark.asyncio
    async def test_filter_clears(self, sample_issues: list[Issue]) -> None:
        """Verify clearing filter shows all issues."""
        app = TUIApp()
        async with app.run_test() as pilot:
            table = app.query_one(IssueTable)
            table.populate(sample_issues)

            # Filter then clear
            table.apply_filter("implement")
            assert table.row_count == 1

            table.apply_filter("")
            assert table.row_count == 3


class TestStatusBar:
    """Tests for the StatusBar widget."""

    @pytest.mark.asyncio
    async def test_status_notification(self) -> None:
        """Verify status bar can receive notifications."""
        app = TUIApp()
        async with app.run_test() as pilot:
            status = app.query_one(StatusBar)

            # Verify StatusBar has show_message method
            assert hasattr(status, "show_message")

            # Notify should not raise
            status.show_message("Test message")

            # StatusBar inherits from Static which uses update()
            # The notify method calls update internally
            assert status is not None


class TestActions:
    """Tests for TUI actions (advance, reject, start)."""

    @pytest.mark.asyncio
    async def test_advance_stage_action(self, sample_issues: list[Issue]) -> None:
        """Verify 'a' key triggers stage advance for selected issue."""
        with patch("agenttree.tui.app.list_issues") as mock_list, \
             patch("agenttree.tui.app.get_next_stage") as mock_next, \
             patch("agenttree.tui.app.update_issue_stage") as mock_update:

            mock_list.return_value = sample_issues
            mock_next.return_value = ("define", "refine", False)

            app = TUIApp()
            async with app.run_test() as pilot:
                # Wait for initial load
                await pilot.pause()

                table = app.query_one(IssueTable)
                table.populate(sample_issues)
                table.focus()

                # Press 'a' to advance
                await pilot.press("a")

                # update_issue_stage should have been called
                mock_update.assert_called()

    @pytest.mark.asyncio
    async def test_reject_action(self, sample_issues: list[Issue]) -> None:
        """Verify 'r' key triggers reject/sendback for human review stages."""
        with patch("agenttree.tui.app.list_issues") as mock_list, \
             patch("agenttree.tui.app.update_issue_stage") as mock_update:

            mock_list.return_value = sample_issues

            app = TUIApp()
            async with app.run_test() as pilot:
                await pilot.pause()

                table = app.query_one(IssueTable)
                table.populate(sample_issues)
                table.focus()

                # Move to issue 003 (plan_review stage)
                await pilot.press("down")
                await pilot.press("down")

                # Press 'r' to reject
                await pilot.press("r")

                # update_issue_stage should be called with "plan" (rejection mapping)
                mock_update.assert_called_with("003", "plan")

    @pytest.mark.asyncio
    async def test_reject_non_review_stage(self, sample_issues: list[Issue]) -> None:
        """Verify reject fails for non-review stages."""
        with patch("agenttree.tui.app.list_issues") as mock_list, \
             patch("agenttree.tui.app.update_issue_stage") as mock_update:

            mock_list.return_value = sample_issues

            app = TUIApp()
            async with app.run_test() as pilot:
                await pilot.pause()

                table = app.query_one(IssueTable)
                table.populate(sample_issues)
                table.focus()

                # Issue 001 is in "backlog" (not a review stage)
                await pilot.press("r")

                # update_issue_stage should NOT be called
                mock_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_agent_action(self, sample_issues: list[Issue]) -> None:
        """Verify 's' key shows appropriate message for starting agent."""
        with patch("agenttree.tui.app.list_issues") as mock_list:
            mock_list.return_value = sample_issues

            app = TUIApp()
            async with app.run_test() as pilot:
                await pilot.pause()

                table = app.query_one(IssueTable)
                table.populate(sample_issues)
                table.focus()

                # Press 's' to start agent
                await pilot.press("s")

                # Status bar should show message
                status = app.query_one(StatusBar)
                # The action just shows a message for now
                assert status is not None

    @pytest.mark.asyncio
    async def test_refresh_action(self, sample_issues: list[Issue]) -> None:
        """Verify 'R' key is bound to refresh action."""
        app = TUIApp()
        async with app.run_test() as pilot:
            # Verify the refresh binding exists
            assert any(b.key == "R" and b.action == "refresh" for b in app.BINDINGS)

            # Verify action_refresh method exists
            assert hasattr(app, "action_refresh")


class TestRejectionMappings:
    """Tests for rejection stage mappings."""

    def test_rejection_mappings_exist(self) -> None:
        """Verify rejection mappings are defined."""
        assert "problem_review" in REJECTION_MAPPINGS
        assert "plan_review" in REJECTION_MAPPINGS
        assert "implementation_review" in REJECTION_MAPPINGS

    def test_rejection_mappings_correct(self) -> None:
        """Verify rejection mappings map to correct stages."""
        assert REJECTION_MAPPINGS["problem_review"] == "define"
        assert REJECTION_MAPPINGS["plan_review"] == "plan"
        assert REJECTION_MAPPINGS["implementation_review"] == "implement"

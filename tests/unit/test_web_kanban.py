"""Tests for flow-based kanban board functionality."""

import pytest
from unittest.mock import Mock, patch, MagicMock

# Skip all tests if web dependencies aren't installed
pytest.importorskip("fastapi")

from agenttree.web.app import get_kanban_board
from agenttree.web.models import KanbanBoard, FlowKanbanRow
from agenttree.issues import Priority


@pytest.fixture
def mock_issue_default_flow():
    """Create a mock issue in the default flow."""
    mock = Mock()
    mock.id = 1
    mock.title = "Default Flow Issue"
    mock.stage = "explore.define"
    mock.labels = []
    mock.assigned_agent = None
    mock.pr_url = None
    mock.pr_number = None
    mock.worktree_dir = None
    mock.created = "2024-01-01T00:00:00Z"
    mock.updated = "2024-01-01T00:00:00Z"
    mock.dependencies = []
    mock.priority = Priority.MEDIUM
    mock.processing = None
    mock.ci_escalated = False
    mock.flow = "default"
    mock.history = [Mock(timestamp="2024-01-01T00:00:00Z")]
    return mock


@pytest.fixture
def mock_issue_quick_flow():
    """Create a mock issue in the quick flow."""
    mock = Mock()
    mock.id = 2
    mock.title = "Quick Flow Issue"
    mock.stage = "implement.code"
    mock.labels = []
    mock.assigned_agent = None
    mock.pr_url = None
    mock.pr_number = None
    mock.worktree_dir = None
    mock.created = "2024-01-02T00:00:00Z"
    mock.updated = "2024-01-02T00:00:00Z"
    mock.dependencies = []
    mock.priority = Priority.HIGH
    mock.processing = None
    mock.ci_escalated = False
    mock.flow = "quick"
    mock.history = [Mock(timestamp="2024-01-02T00:00:00Z")]
    return mock


@pytest.fixture
def mock_issue_backlog():
    """Create a mock issue in the backlog (parking lot)."""
    mock = Mock()
    mock.id = 3
    mock.title = "Backlog Issue"
    mock.stage = "backlog"
    mock.labels = []
    mock.assigned_agent = None
    mock.pr_url = None
    mock.pr_number = None
    mock.worktree_dir = None
    mock.created = "2024-01-03T00:00:00Z"
    mock.updated = "2024-01-03T00:00:00Z"
    mock.dependencies = []
    mock.priority = Priority.LOW
    mock.processing = None
    mock.ci_escalated = False
    mock.flow = "default"
    mock.history = [Mock(timestamp="2024-01-03T00:00:00Z")]
    return mock


class TestKanbanBoard:
    """Tests for flow-based kanban board structure."""

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app._config")
    def test_get_kanban_board_returns_flow_organized_structure(
        self, mock_config_global, mock_crud
    ):
        """Test that get_kanban_board returns a flow-organized KanbanBoard."""
        # Set up config mock
        mock_config_global.get_parking_lot_stages.return_value = {"backlog", "accepted", "not_doing"}
        mock_config_global.get_all_dot_paths.return_value = [
            "backlog", "explore.define", "implement.code", "accepted", "not_doing"
        ]
        mock_config_global.flows = {
            "default": MagicMock(),
            "quick": MagicMock(),
        }
        mock_config_global.get_flow_stage_names.side_effect = lambda f: {
            "default": ["backlog", "explore.define", "implement.code", "accepted"],
            "quick": ["backlog", "implement.code", "accepted"],
        }[f]

        mock_crud.list_issues.return_value = []

        board = get_kanban_board()

        # Verify structure
        assert isinstance(board, KanbanBoard)
        assert hasattr(board, "parking_lot_stages")
        assert hasattr(board, "parking_lot_issues")
        assert hasattr(board, "flow_rows")
        assert isinstance(board.flow_rows, list)

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app._config")
    def test_parking_lot_stages_are_separated(
        self, mock_config_global, mock_crud, mock_issue_backlog
    ):
        """Test that parking lot stages are in their own section."""
        mock_config_global.get_parking_lot_stages.return_value = {"backlog", "accepted", "not_doing"}
        mock_config_global.get_all_dot_paths.return_value = [
            "backlog", "explore.define", "accepted", "not_doing"
        ]
        mock_config_global.flows = {"default": MagicMock()}
        mock_config_global.get_flow_stage_names.return_value = [
            "backlog", "explore.define", "accepted"
        ]

        mock_crud.list_issues.return_value = [mock_issue_backlog]

        board = get_kanban_board()

        # Check parking lot contains backlog, accepted, not_doing
        assert "backlog" in board.parking_lot_stages
        assert "accepted" in board.parking_lot_stages
        assert "not_doing" in board.parking_lot_stages

        # Verify backlog issue is in parking lot issues
        assert len(board.parking_lot_issues.get("backlog", [])) == 1

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app._config")
    def test_issues_grouped_by_flow(
        self, mock_config_global, mock_crud,
        mock_issue_default_flow, mock_issue_quick_flow
    ):
        """Test that issues are grouped into correct flow rows."""
        mock_config_global.get_parking_lot_stages.return_value = {"backlog", "accepted"}
        mock_config_global.get_all_dot_paths.return_value = [
            "backlog", "explore.define", "implement.code", "accepted"
        ]
        mock_config_global.flows = {
            "default": MagicMock(),
            "quick": MagicMock(),
        }
        mock_config_global.get_flow_stage_names.side_effect = lambda f: {
            "default": ["backlog", "explore.define", "implement.code", "accepted"],
            "quick": ["backlog", "implement.code", "accepted"],
        }[f]

        mock_crud.list_issues.return_value = [mock_issue_default_flow, mock_issue_quick_flow]

        board = get_kanban_board()

        # Should have 2 flow rows (default and quick)
        assert len(board.flow_rows) == 2

        # Find the default flow row
        default_row = next((r for r in board.flow_rows if r.flow_name == "default"), None)
        assert default_row is not None
        assert len(default_row.issues_by_stage.get("explore.define", [])) == 1

        # Find the quick flow row
        quick_row = next((r for r in board.flow_rows if r.flow_name == "quick"), None)
        assert quick_row is not None
        assert len(quick_row.issues_by_stage.get("implement.code", [])) == 1

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app._config")
    def test_flow_rows_only_include_non_parking_stages(
        self, mock_config_global, mock_crud
    ):
        """Test that flow rows exclude parking lot stages."""
        mock_config_global.get_parking_lot_stages.return_value = {"backlog", "accepted"}
        mock_config_global.get_all_dot_paths.return_value = [
            "backlog", "explore.define", "accepted"
        ]
        mock_config_global.flows = {"default": MagicMock()}
        mock_config_global.get_flow_stage_names.return_value = [
            "backlog", "explore.define", "accepted"
        ]

        mock_crud.list_issues.return_value = []

        board = get_kanban_board()

        # Flow rows should not contain backlog or accepted
        for row in board.flow_rows:
            assert "backlog" not in row.stages
            assert "accepted" not in row.stages

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app._config")
    def test_search_filtering_works_across_flows(
        self, mock_config_global, mock_crud,
        mock_issue_default_flow, mock_issue_quick_flow
    ):
        """Test that search filtering works across all flows."""
        mock_config_global.get_parking_lot_stages.return_value = {"backlog", "accepted"}
        mock_config_global.get_all_dot_paths.return_value = [
            "backlog", "explore.define", "implement.code", "accepted"
        ]
        mock_config_global.flows = {
            "default": MagicMock(),
            "quick": MagicMock(),
        }
        mock_config_global.get_flow_stage_names.side_effect = lambda f: {
            "default": ["backlog", "explore.define", "implement.code", "accepted"],
            "quick": ["backlog", "implement.code", "accepted"],
        }[f]

        mock_crud.list_issues.return_value = [mock_issue_default_flow, mock_issue_quick_flow]

        # Search for "Quick" should only return the quick flow issue
        board = get_kanban_board(search="Quick")

        # Total should be 1
        assert board.total_issues == 1

    @patch("agenttree.web.app.issue_crud")
    @patch("agenttree.web.app._config")
    def test_empty_flows_excluded(
        self, mock_config_global, mock_crud
    ):
        """Test that flows with only parking lot stages are excluded."""
        mock_config_global.get_parking_lot_stages.return_value = {"backlog", "accepted", "not_doing"}
        mock_config_global.get_all_dot_paths.return_value = [
            "backlog", "explore.define", "accepted", "not_doing"
        ]
        mock_config_global.flows = {
            "default": MagicMock(),
            "not_doing": MagicMock(),  # Only has not_doing stage
        }
        mock_config_global.get_flow_stage_names.side_effect = lambda f: {
            "default": ["backlog", "explore.define", "accepted"],
            "not_doing": ["not_doing"],
        }[f]

        mock_crud.list_issues.return_value = []

        board = get_kanban_board()

        # not_doing flow should be excluded since it only has parking lot stage
        flow_names = [r.flow_name for r in board.flow_rows]
        assert "not_doing" not in flow_names
        assert "default" in flow_names

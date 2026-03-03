"""Tests for time-in-stage display feature in web UI."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

pytest.importorskip("fastapi")

from agenttree.web.utils import format_duration
from agenttree.web.models import Issue as WebIssue


class TestFormatDuration:
    """Tests for the format_duration() helper function."""

    def test_zero_minutes(self) -> None:
        """Test format_duration returns '0m' for 0 minutes."""
        assert format_duration(0) == "0m"

    def test_minutes_under_hour(self) -> None:
        """Test format_duration returns 'Xm' for minutes under 60."""
        assert format_duration(1) == "1m"
        assert format_duration(45) == "45m"
        assert format_duration(59) == "59m"

    def test_one_hour(self) -> None:
        """Test format_duration returns '1h' for 60-119 minutes."""
        assert format_duration(60) == "1h"
        assert format_duration(90) == "1h"
        assert format_duration(119) == "1h"

    def test_multiple_hours(self) -> None:
        """Test format_duration returns 'Xh' for 2+ hours under a day."""
        assert format_duration(120) == "2h"
        assert format_duration(180) == "3h"
        assert format_duration(720) == "12h"
        assert format_duration(1439) == "23h"

    def test_one_day(self) -> None:
        """Test format_duration returns '1d' for 24 hours (1440 minutes)."""
        assert format_duration(1440) == "1d"
        assert format_duration(2000) == "1d"
        assert format_duration(2879) == "1d"

    def test_multiple_days(self) -> None:
        """Test format_duration returns 'Xd' for multiple days."""
        assert format_duration(2880) == "2d"
        assert format_duration(4320) == "3d"
        assert format_duration(10080) == "7d"


class TestWebIssueModel:
    """Tests for the WebIssue model with time_in_stage field."""

    def test_time_in_stage_default(self) -> None:
        """Test WebIssue model has time_in_stage field with default."""
        issue = WebIssue(
            number=1,
            title="Test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert issue.time_in_stage == "0m"

    def test_time_in_stage_custom_value(self) -> None:
        """Test WebIssue model accepts custom time_in_stage value."""
        issue = WebIssue(
            number=1,
            title="Test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            time_in_stage="2h",
        )
        assert issue.time_in_stage == "2h"


class TestConvertIssueToWeb:
    """Tests for convert_issue_to_web() time_in_stage calculation."""

    @patch("agenttree.web.utils.agent_manager")
    def test_populates_time_in_stage(self, mock_agent_manager: MagicMock) -> None:
        """Test convert_issue_to_web() populates time_in_stage from history."""
        from agenttree.web.utils import convert_issue_to_web
        from agenttree.issues import Issue, HistoryEntry

        # Mock agent_manager to avoid tmux checks
        mock_agent_manager._check_issue_tmux_session.return_value = False

        # Create a mock issue with history
        now = datetime.now(timezone.utc)
        stage_entered = now - timedelta(minutes=45)

        issue = Issue(
            id=1,
            title="Test Issue",
            created=now.isoformat(),
            updated=now.isoformat(),
            stage="implement.code",
            history=[
                HistoryEntry(
                    stage="implement.code",
                    timestamp=stage_entered.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            ],
        )

        web_issue = convert_issue_to_web(issue)

        # Should be approximately 45 minutes
        assert web_issue.time_in_stage == "45m"

    @patch("agenttree.web.utils.agent_manager")
    def test_empty_history_defaults_to_zero(self, mock_agent_manager: MagicMock) -> None:
        """Test convert_issue_to_web() defaults to '0m' for empty history."""
        from agenttree.web.utils import convert_issue_to_web
        from agenttree.issues import Issue

        # Mock agent_manager
        mock_agent_manager._check_issue_tmux_session.return_value = False

        now = datetime.now(timezone.utc)
        issue = Issue(
            id=1,
            title="Test Issue",
            created=now.isoformat(),
            updated=now.isoformat(),
            stage="backlog",
            history=[],  # Empty history
        )

        web_issue = convert_issue_to_web(issue)
        assert web_issue.time_in_stage == "0m"

    @patch("agenttree.web.utils.agent_manager")
    def test_hours_formatting(self, mock_agent_manager: MagicMock) -> None:
        """Test convert_issue_to_web() formats hours correctly."""
        from agenttree.web.utils import convert_issue_to_web
        from agenttree.issues import Issue, HistoryEntry

        mock_agent_manager._check_issue_tmux_session.return_value = False

        now = datetime.now(timezone.utc)
        stage_entered = now - timedelta(hours=3)

        issue = Issue(
            id=1,
            title="Test Issue",
            created=now.isoformat(),
            updated=now.isoformat(),
            stage="implement.code",
            history=[
                HistoryEntry(
                    stage="implement.code",
                    timestamp=stage_entered.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            ],
        )

        web_issue = convert_issue_to_web(issue)
        assert web_issue.time_in_stage == "3h"

    @patch("agenttree.web.utils.agent_manager")
    def test_days_formatting(self, mock_agent_manager: MagicMock) -> None:
        """Test convert_issue_to_web() formats days correctly."""
        from agenttree.web.utils import convert_issue_to_web
        from agenttree.issues import Issue, HistoryEntry

        mock_agent_manager._check_issue_tmux_session.return_value = False

        now = datetime.now(timezone.utc)
        stage_entered = now - timedelta(days=2)

        issue = Issue(
            id=1,
            title="Test Issue",
            created=now.isoformat(),
            updated=now.isoformat(),
            stage="implement.code",
            history=[
                HistoryEntry(
                    stage="implement.code",
                    timestamp=stage_entered.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            ],
        )

        web_issue = convert_issue_to_web(issue)
        assert web_issue.time_in_stage == "2d"

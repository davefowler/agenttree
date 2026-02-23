"""Tests for stage constants module."""

import pytest

from agenttree.stages import Stage, TerminalStage


class TestTerminalStage:
    """Tests for TerminalStage enum."""

    def test_backlog_equals_string(self) -> None:
        """TerminalStage.BACKLOG should equal the string 'backlog'."""
        assert TerminalStage.BACKLOG == "backlog"

    def test_accepted_equals_string(self) -> None:
        """TerminalStage.ACCEPTED should equal the string 'accepted'."""
        assert TerminalStage.ACCEPTED == "accepted"

    def test_not_doing_equals_string(self) -> None:
        """TerminalStage.NOT_DOING should equal the string 'not_doing'."""
        assert TerminalStage.NOT_DOING == "not_doing"

    def test_string_comparison_both_directions(self) -> None:
        """Enum values should work with string comparison in both directions."""
        assert "backlog" == TerminalStage.BACKLOG
        assert TerminalStage.BACKLOG == "backlog"

    def test_unique_values(self) -> None:
        """All TerminalStage values should be unique."""
        values = [member.value for member in TerminalStage]
        assert len(values) == len(set(values))

    def test_in_tuple(self) -> None:
        """Enum values should work in tuple membership tests."""
        terminal_stages = (TerminalStage.BACKLOG, TerminalStage.ACCEPTED, TerminalStage.NOT_DOING)
        assert "backlog" in terminal_stages
        assert "accepted" in terminal_stages
        assert "not_doing" in terminal_stages


class TestStage:
    """Tests for Stage enum with dot-path stages."""

    def test_explore_define_equals_string(self) -> None:
        """Stage.EXPLORE_DEFINE should equal 'explore.define'."""
        assert Stage.EXPLORE_DEFINE == "explore.define"

    def test_implement_review_equals_string(self) -> None:
        """Stage.IMPLEMENT_REVIEW should equal 'implement.review'."""
        assert Stage.IMPLEMENT_REVIEW == "implement.review"

    def test_implement_ci_wait_equals_string(self) -> None:
        """Stage.IMPLEMENT_CI_WAIT should equal 'implement.ci_wait'."""
        assert Stage.IMPLEMENT_CI_WAIT == "implement.ci_wait"

    def test_implement_code_equals_string(self) -> None:
        """Stage.IMPLEMENT_CODE should equal 'implement.code'."""
        assert Stage.IMPLEMENT_CODE == "implement.code"

    def test_plan_review_equals_string(self) -> None:
        """Stage.PLAN_REVIEW should equal 'plan.review'."""
        assert Stage.PLAN_REVIEW == "plan.review"

    def test_unique_values(self) -> None:
        """All Stage values should be unique."""
        values = [member.value for member in Stage]
        assert len(values) == len(set(values))

    def test_f_string_usage(self) -> None:
        """Enum values can be formatted using .value in f-strings."""
        stage = Stage.EXPLORE_DEFINE
        # Direct f-string uses enum name, use .value for the string
        message = f"Current stage: {stage.value}"
        assert message == "Current stage: explore.define"
        # Or convert to str() explicitly
        message2 = f"Current stage: {str(stage)}"
        assert "explore.define" in message2 or "EXPLORE_DEFINE" in message2

    def test_concatenation(self) -> None:
        """Enum values should work with string concatenation."""
        prefix = "stage-"
        result = prefix + Stage.BACKLOG if hasattr(Stage, "BACKLOG") else prefix + TerminalStage.BACKLOG
        assert result == "stage-backlog"


class TestEnumInteroperability:
    """Tests for using enums as drop-in replacements for strings."""

    def test_dictionary_key(self) -> None:
        """Enum values should work as dictionary keys."""
        stages_dict = {
            TerminalStage.BACKLOG: "pending",
            TerminalStage.ACCEPTED: "done",
        }
        assert stages_dict["backlog"] == "pending"
        assert stages_dict[TerminalStage.BACKLOG] == "pending"

    def test_in_list(self) -> None:
        """Enum values should work in list membership."""
        stages = [TerminalStage.BACKLOG, Stage.EXPLORE_DEFINE]
        assert "backlog" in stages
        assert "explore.define" in stages

    def test_startswith(self) -> None:
        """Enum values should support string methods like startswith."""
        assert Stage.IMPLEMENT_REVIEW.startswith("implement.")
        assert Stage.EXPLORE_DEFINE.startswith("explore.")

    def test_split(self) -> None:
        """Enum values should support string split."""
        parts = Stage.IMPLEMENT_CODE.split(".")
        assert parts == ["implement", "code"]

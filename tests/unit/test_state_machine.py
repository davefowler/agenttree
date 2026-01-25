"""Tests for agenttree.state_machine module."""

import pytest

from agenttree.state_machine import (
    IssueStateMachine,
    InvalidTransitionError,
    validate_state_transition,
    get_all_states,
    get_all_transitions,
    generate_diagram,
)


class TestIssueStateMachine:
    """Tests for the IssueStateMachine class."""

    def test_initial_state_default(self) -> None:
        """Default initial state is backlog."""
        sm = IssueStateMachine()
        assert sm.current_state == "backlog"

    def test_initial_state_custom(self) -> None:
        """Can set custom initial state."""
        sm = IssueStateMachine(initial_state="define.refine")
        assert sm.current_state == "define.refine"

    def test_set_state(self) -> None:
        """Can set state directly."""
        sm = IssueStateMachine()
        sm.set_state("implement.code")
        assert sm.current_state == "implement.code"

    def test_set_invalid_state_raises(self) -> None:
        """Setting invalid state raises ValueError."""
        sm = IssueStateMachine()
        with pytest.raises(ValueError, match="Invalid state"):
            sm.set_state("invalid_state")

    def test_can_transition_to_valid(self) -> None:
        """can_transition_to returns True for valid transitions."""
        sm = IssueStateMachine(initial_state="backlog")
        assert sm.can_transition_to("define.refine") is True

    def test_can_transition_to_invalid(self) -> None:
        """can_transition_to returns False for invalid transitions."""
        sm = IssueStateMachine(initial_state="backlog")
        # Can't skip from backlog to implement
        assert sm.can_transition_to("implement.code") is False

    def test_can_transition_to_nonexistent_state(self) -> None:
        """can_transition_to returns False for nonexistent states."""
        sm = IssueStateMachine()
        assert sm.can_transition_to("nonexistent") is False

    def test_validate_transition_valid(self) -> None:
        """validate_transition doesn't raise for valid transitions."""
        sm = IssueStateMachine(initial_state="define.refine")
        # Should not raise
        sm.validate_transition("research.explore")

    def test_validate_transition_invalid_raises(self) -> None:
        """validate_transition raises for invalid transitions."""
        sm = IssueStateMachine(initial_state="define.refine")
        with pytest.raises(InvalidTransitionError) as exc_info:
            sm.validate_transition("accepted")
        assert exc_info.value.source == "define.refine"
        assert exc_info.value.dest == "accepted"

    def test_validate_transition_invalid_state_raises(self) -> None:
        """validate_transition raises for invalid target state."""
        sm = IssueStateMachine()
        with pytest.raises(InvalidTransitionError, match="Invalid target state"):
            sm.validate_transition("nonexistent_state")

    def test_get_next_state_from_backlog(self) -> None:
        """Next state from backlog is define.refine."""
        sm = IssueStateMachine(initial_state="backlog")
        assert sm.get_next_state() == "define.refine"

    def test_get_next_state_terminal(self) -> None:
        """Terminal states return None for next state."""
        sm = IssueStateMachine(initial_state="accepted")
        assert sm.get_next_state() is None

        sm.set_state("not_doing")
        assert sm.get_next_state() is None

    def test_is_human_review_required(self) -> None:
        """Human review states are identified correctly."""
        sm = IssueStateMachine()

        # Non-review states
        sm.set_state("define.refine")
        assert sm.is_human_review_required() is False

        sm.set_state("implement.code")
        assert sm.is_human_review_required() is False

        # Review states
        sm.set_state("plan_review")
        assert sm.is_human_review_required() is True

        sm.set_state("implementation_review.ci_wait")
        assert sm.is_human_review_required() is True

        sm.set_state("implementation_review.review")
        assert sm.is_human_review_required() is True

    def test_is_terminal(self) -> None:
        """Terminal states are identified correctly."""
        sm = IssueStateMachine()

        # Non-terminal states
        sm.set_state("define.refine")
        assert sm.is_terminal() is False

        sm.set_state("plan_review")
        assert sm.is_terminal() is False

        # Terminal states
        sm.set_state("accepted")
        assert sm.is_terminal() is True

        sm.set_state("not_doing")
        assert sm.is_terminal() is True

    def test_get_valid_transitions_from_backlog(self) -> None:
        """Valid transitions from backlog include define.refine and not_doing."""
        sm = IssueStateMachine(initial_state="backlog")
        valid = sm.get_valid_transitions()
        assert "define.refine" in valid
        assert "not_doing" in valid

    def test_get_valid_transitions_terminal(self) -> None:
        """Terminal states can only transition to themselves."""
        sm = IssueStateMachine(initial_state="accepted")
        valid = sm.get_valid_transitions()
        assert valid == ["accepted"]

    def test_format_state_with_substage(self) -> None:
        """format_state combines stage and substage."""
        assert IssueStateMachine.format_state("implement", "code") == "implement.code"

    def test_format_state_without_substage(self) -> None:
        """format_state returns just stage when no substage."""
        assert IssueStateMachine.format_state("backlog", None) == "backlog"
        assert IssueStateMachine.format_state("plan_review") == "plan_review"

    def test_parse_state_with_substage(self) -> None:
        """parse_state extracts stage and substage."""
        stage, substage = IssueStateMachine.parse_state("implement.code")
        assert stage == "implement"
        assert substage == "code"

    def test_parse_state_without_substage(self) -> None:
        """parse_state returns None for substage when not present."""
        stage, substage = IssueStateMachine.parse_state("backlog")
        assert stage == "backlog"
        assert substage is None


class TestStateTransitionWorkflow:
    """Tests for the complete workflow state transitions."""

    def test_full_workflow_happy_path(self) -> None:
        """Test transitioning through the entire workflow."""
        sm = IssueStateMachine(initial_state="backlog")

        # The complete happy path workflow
        workflow = [
            "define.refine",
            "research.explore",
            "research.document",
            "plan.draft",
            "plan.refine",
            "plan_assess",
            "plan_revise",
            "plan_review",
            "implement.setup",
            "implement.code",
            "implement.code_review",
            "implement.address_review",
            "implement.wrapup",
            "implement.feedback",
            "independent_code_review",
            "implementation_review.ci_wait",
            "implementation_review.review",
            "accepted",
        ]

        for expected_next in workflow:
            next_state = sm.get_next_state()
            assert next_state == expected_next, f"Expected {expected_next}, got {next_state}"
            # Validate and transition
            sm.validate_transition(next_state)
            sm.set_state(next_state)

        # Now at accepted, should stay there
        assert sm.is_terminal() is True
        assert sm.get_next_state() is None

    def test_reject_from_early_stages(self) -> None:
        """Can reject (move to not_doing) from early stages."""
        sm = IssueStateMachine(initial_state="define.refine")
        assert sm.can_transition_to("not_doing") is True
        sm.validate_transition("not_doing")

    def test_cannot_skip_stages(self) -> None:
        """Cannot skip stages in the workflow."""
        sm = IssueStateMachine(initial_state="backlog")

        # Cannot skip directly to research
        assert sm.can_transition_to("research.explore") is False

        # Cannot skip directly to implement
        assert sm.can_transition_to("implement.code") is False

        # Cannot skip directly to accepted
        assert sm.can_transition_to("accepted") is False

    def test_cannot_go_backwards(self) -> None:
        """Cannot transition backwards in the workflow."""
        sm = IssueStateMachine(initial_state="implement.code")

        # Cannot go back to plan
        assert sm.can_transition_to("plan.draft") is False
        assert sm.can_transition_to("define.refine") is False

        # Cannot go back to backlog
        assert sm.can_transition_to("backlog") is False


class TestValidateStateTransition:
    """Tests for the validate_state_transition convenience function."""

    def test_valid_transition(self) -> None:
        """Valid transitions don't raise."""
        # Should not raise
        validate_state_transition("backlog", None, "define", "refine")
        validate_state_transition("define", "refine", "research", "explore")
        validate_state_transition("plan", "refine", "plan_assess", None)

    def test_invalid_transition_raises(self) -> None:
        """Invalid transitions raise InvalidTransitionError."""
        with pytest.raises(InvalidTransitionError):
            validate_state_transition("backlog", None, "accepted", None)

        with pytest.raises(InvalidTransitionError):
            validate_state_transition("define", "refine", "implement", "code")


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_all_states(self) -> None:
        """get_all_states returns all defined states."""
        states = get_all_states()
        assert "backlog" in states
        assert "define.refine" in states
        assert "accepted" in states
        assert "not_doing" in states
        assert len(states) == len(IssueStateMachine.STATES)

    def test_get_all_transitions(self) -> None:
        """get_all_transitions returns all defined transitions."""
        transitions = get_all_transitions()
        assert len(transitions) == len(IssueStateMachine.TRANSITIONS)

        # Check known transitions exist
        assert {"trigger": "advance", "source": "backlog", "dest": "define.refine"} in transitions
        assert {"trigger": "reject", "source": "backlog", "dest": "not_doing"} in transitions


class TestGenerateDiagram:
    """Tests for the diagram generation function."""

    def test_generate_diagram_returns_dot_source(self) -> None:
        """generate_diagram returns valid DOT source."""
        dot = generate_diagram()
        assert "digraph" in dot
        assert "backlog" in dot
        assert "accepted" in dot

    def test_generate_diagram_includes_title(self) -> None:
        """generate_diagram includes the title."""
        dot = generate_diagram(title="My Custom Title")
        assert "My Custom Title" in dot

    def test_generate_diagram_includes_transitions(self) -> None:
        """generate_diagram includes transition arrows."""
        dot = generate_diagram()
        # Check for at least one transition
        assert "->" in dot

    def test_generate_diagram_saves_to_file(self, tmp_path) -> None:
        """generate_diagram can save to a file."""
        output_file = tmp_path / "workflow.dot"
        dot = generate_diagram(output_path=str(output_file))

        assert output_file.exists()
        content = output_file.read_text()
        assert content == dot

    def test_generate_diagram_marks_terminal_states(self) -> None:
        """generate_diagram marks terminal states differently."""
        dot = generate_diagram()
        # Terminal states should have doublecircle shape
        assert 'doublecircle' in dot

    def test_generate_diagram_marks_review_states(self) -> None:
        """generate_diagram marks human review states."""
        dot = generate_diagram()
        # Review states should be highlighted
        assert 'lightyellow' in dot


class TestInvalidTransitionError:
    """Tests for the InvalidTransitionError exception."""

    def test_error_message_default(self) -> None:
        """Default error message includes source and dest."""
        err = InvalidTransitionError("source", "dest")
        assert "source" in str(err)
        assert "dest" in str(err)

    def test_error_message_custom(self) -> None:
        """Custom error message is used when provided."""
        err = InvalidTransitionError("source", "dest", "Custom message")
        assert str(err) == "Custom message"

    def test_error_has_attributes(self) -> None:
        """Error has source and dest attributes."""
        err = InvalidTransitionError("source", "dest")
        assert err.source == "source"
        assert err.dest == "dest"

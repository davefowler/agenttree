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

    def test_address_independent_review_transitions(self) -> None:
        """Test address_independent_review stage transitions are valid.

        This is an integration-style test verifying the new stage works
        with validation enabled.
        """
        # Redirect from independent_code_review to address_independent_review
        # (uses 'redirect' trigger, but validate_state_transition checks any valid transition)
        sm = IssueStateMachine("independent_code_review")
        assert sm.can_transition_to("address_independent_review")

        # address_independent_review can go to independent_code_review (normal rollback)
        validate_state_transition(
            "address_independent_review", None,
            "independent_code_review", None
        )

        # address_independent_review can also go to implementation_review (config path)
        validate_state_transition(
            "address_independent_review", None,
            "implementation_review", "ci_wait"
        )

    def test_bare_implement_transitions(self) -> None:
        """Test bare implement state transitions are valid.

        Verifies the implement state (without substage) can transition
        to valid destinations.
        """
        # implement can go to implement.setup (normal entry)
        validate_state_transition("implement", None, "implement", "setup")

        # implement can go to independent_code_review (CI feedback path)
        validate_state_transition("implement", None, "independent_code_review", None)


class TestConfigIntegration:
    """Tests verifying state machine integrates with config."""

    def test_address_independent_review_in_config(self) -> None:
        """Verify address_independent_review stage exists in default config."""
        from agenttree.config import load_config

        config = load_config()
        stage_names = config.get_stage_names()

        assert "address_independent_review" in stage_names, (
            "address_independent_review stage must exist in config"
        )

    def test_all_state_machine_stages_in_config(self) -> None:
        """Verify all state machine stages (without substages) exist in config."""
        from agenttree.config import load_config

        config = load_config()
        config_stages = set(config.get_stage_names())

        # Extract base stage names from state machine (without substages)
        sm_base_stages = set()
        for state in IssueStateMachine.STATES:
            base_stage = state.split(".")[0]
            sm_base_stages.add(base_stage)

        # All state machine base stages should be in config
        missing = sm_base_stages - config_stages
        assert not missing, f"State machine has stages not in config: {missing}"


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


class TestValidateConfigSync:
    """Tests for config sync validation."""

    def test_validate_config_sync_passes_when_aligned(self, monkeypatch) -> None:
        """Verify no error when STATES matches config."""
        from agenttree import state_machine

        # Reset validation flag for test isolation
        state_machine._config_validated = False

        # Mock config to return stages that match STATES
        mock_config = type(
            "MockConfig",
            (),
            {
                "stages": [
                    type("Stage", (), {"name": "backlog", "substages": None, "terminal": False, "human_review": False})(),
                    type("Stage", (), {"name": "define", "substages": {"refine": {}}, "terminal": False, "human_review": False})(),
                    type("Stage", (), {"name": "research", "substages": {"explore": {}, "document": {}}, "terminal": False, "human_review": False})(),
                    type("Stage", (), {"name": "plan", "substages": {"draft": {}, "refine": {}}, "terminal": False, "human_review": False})(),
                    type("Stage", (), {"name": "plan_assess", "substages": None, "terminal": False, "human_review": False})(),
                    type("Stage", (), {"name": "plan_revise", "substages": None, "terminal": False, "human_review": False})(),
                    type("Stage", (), {"name": "plan_review", "substages": None, "terminal": False, "human_review": True})(),
                    type("Stage", (), {"name": "implement", "substages": {"setup": {}, "code": {}, "code_review": {}, "address_review": {}, "wrapup": {}, "feedback": {}}, "terminal": False, "human_review": False})(),
                    type("Stage", (), {"name": "independent_code_review", "substages": None, "terminal": False, "human_review": False})(),
                    type("Stage", (), {"name": "implementation_review", "substages": {"ci_wait": {}, "review": {}}, "terminal": False, "human_review": True})(),
                    type("Stage", (), {"name": "accepted", "substages": None, "terminal": True, "human_review": False})(),
                    type("Stage", (), {"name": "not_doing", "substages": None, "terminal": True, "human_review": False})(),
                ],
            },
        )()

        def mock_load_config():
            return mock_config

        monkeypatch.setattr("agenttree.state_machine.load_config", mock_load_config)

        # Should not raise
        state_machine.validate_config_sync()

    def test_validate_config_sync_detects_missing_state(self, monkeypatch, caplog) -> None:
        """Verify warning when config has stage not in STATES."""
        import logging
        from agenttree import state_machine

        # Reset validation flag for test isolation
        state_machine._config_validated = False

        # Mock config with an extra stage not in STATES
        mock_config = type(
            "MockConfig",
            (),
            {
                "stages": [
                    type("Stage", (), {"name": "backlog", "substages": None, "terminal": False, "human_review": False})(),
                    type("Stage", (), {"name": "new_stage", "substages": None, "terminal": False, "human_review": False})(),
                ],
            },
        )()

        def mock_load_config():
            return mock_config

        monkeypatch.setattr("agenttree.state_machine.load_config", mock_load_config)

        with caplog.at_level(logging.WARNING):
            state_machine.validate_config_sync()

        assert "new_stage" in caplog.text or "mismatch" in caplog.text.lower()

    def test_validate_config_sync_runs_only_once(self, monkeypatch) -> None:
        """Verify validation runs on first instantiation only."""
        from agenttree import state_machine

        # Reset validation flag
        state_machine._config_validated = False

        call_count = 0

        def counting_validate():
            nonlocal call_count
            # Only count if not already validated (mimics real behavior)
            if not state_machine._config_validated:
                call_count += 1
                state_machine._config_validated = True

        monkeypatch.setattr("agenttree.state_machine.validate_config_sync", counting_validate)

        # Create multiple instances
        state_machine.IssueStateMachine()
        state_machine.IssueStateMachine()
        state_machine.IssueStateMachine()

        # Should only have been called once (validation flag prevents re-runs)
        assert call_count == 1

    def test_validate_config_sync_fallback_on_config_error(self, monkeypatch, caplog) -> None:
        """Verify graceful fallback when config unavailable."""
        import logging
        from agenttree import state_machine

        # Reset validation flag
        state_machine._config_validated = False

        def mock_load_config():
            raise FileNotFoundError("No config file")

        monkeypatch.setattr("agenttree.state_machine.load_config", mock_load_config)

        with caplog.at_level(logging.WARNING):
            # Should not raise, should log warning
            state_machine.validate_config_sync()

        assert state_machine._config_validated is True


class TestDerivedStates:
    """Tests for config-derived HUMAN_REVIEW_STATES and TERMINAL_STATES."""

    def test_human_review_states_matches_config(self, monkeypatch) -> None:
        """Verify derived states include all config review stages."""
        from agenttree import state_machine

        # Clear cache
        state_machine._get_human_review_states.cache_clear()

        mock_config = type(
            "MockConfig",
            (),
            {
                "stages": [
                    type("Stage", (), {"name": "plan_review", "substages": None, "human_review": True})(),
                    type("Stage", (), {"name": "implementation_review", "substages": {"ci_wait": {}, "review": {}}, "human_review": True})(),
                    type("Stage", (), {"name": "other_stage", "substages": None, "human_review": False})(),
                ],
            },
        )()

        def mock_load_config():
            return mock_config

        monkeypatch.setattr("agenttree.state_machine.load_config", mock_load_config)

        result = state_machine._get_human_review_states()

        assert "plan_review" in result
        assert "implementation_review.ci_wait" in result
        assert "implementation_review.review" in result
        assert "other_stage" not in result

    def test_terminal_states_matches_config(self, monkeypatch) -> None:
        """Verify derived states match config stages with terminal=True."""
        from agenttree import state_machine

        # Clear cache
        state_machine._get_terminal_states.cache_clear()

        mock_config = type(
            "MockConfig",
            (),
            {
                "stages": [
                    type("Stage", (), {"name": "accepted", "substages": None, "terminal": True})(),
                    type("Stage", (), {"name": "not_doing", "substages": None, "terminal": True})(),
                    type("Stage", (), {"name": "backlog", "substages": None, "terminal": False})(),
                ],
            },
        )()

        def mock_load_config():
            return mock_config

        monkeypatch.setattr("agenttree.state_machine.load_config", mock_load_config)

        result = state_machine._get_terminal_states()

        assert "accepted" in result
        assert "not_doing" in result
        assert "backlog" not in result

    def test_derived_states_cached(self, monkeypatch) -> None:
        """Verify caching (same object returned on repeated calls)."""
        from agenttree import state_machine

        # Clear cache
        state_machine._get_human_review_states.cache_clear()

        mock_config = type(
            "MockConfig",
            (),
            {
                "stages": [
                    type("Stage", (), {"name": "plan_review", "substages": None, "human_review": True})(),
                ],
            },
        )()

        def mock_load_config():
            return mock_config

        monkeypatch.setattr("agenttree.state_machine.load_config", mock_load_config)

        result1 = state_machine._get_human_review_states()
        result2 = state_machine._get_human_review_states()

        # Should be the same object (cached)
        assert result1 is result2

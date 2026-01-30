"""State machine for AgentTree issue workflow.

This module provides a formal state machine implementation using the transitions library
to validate and manage issue stage transitions. It centralizes state logic, prevents
invalid transitions, and can generate state machine diagrams for documentation.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from agenttree.config import Config

from transitions import Machine

logger = logging.getLogger(__name__)

# Module-level flag to ensure config validation runs only once
_config_validated: bool = False

# Fallback values for when config loading fails
_FALLBACK_HUMAN_REVIEW_STATES = frozenset({
    "plan_review",
    "implementation_review.ci_wait",
    "implementation_review.review",
})

_FALLBACK_TERMINAL_STATES = frozenset({"accepted", "not_doing"})


def load_config() -> Config:
    """Lazy import of load_config to avoid circular imports."""
    from agenttree.config import load_config as _load_config
    return _load_config()


@lru_cache(maxsize=1)
def _get_human_review_states() -> frozenset[str]:
    """Get human review states from config, with fallback.

    Returns a frozenset of all states that require human review.
    For stages with substages, includes all substages (e.g., "implementation_review.ci_wait").
    """
    try:
        config = load_config()
        result: set[str] = set()

        for stage in config.stages:
            if stage.human_review:
                if stage.substages:
                    # Add all substages
                    for substage_name in stage.substages.keys():
                        result.add(f"{stage.name}.{substage_name}")
                else:
                    result.add(stage.name)

        return frozenset(result)
    except Exception as e:
        logger.warning(f"Could not load config for human review states, using fallback: {e}")
        return _FALLBACK_HUMAN_REVIEW_STATES


@lru_cache(maxsize=1)
def _get_terminal_states() -> frozenset[str]:
    """Get terminal states from config, with fallback.

    Returns a frozenset of all terminal states (states that cannot advance further).
    """
    try:
        config = load_config()
        result: set[str] = set()

        for stage in config.stages:
            if stage.terminal:
                result.add(stage.name)

        return frozenset(result)
    except Exception as e:
        logger.warning(f"Could not load config for terminal states, using fallback: {e}")
        return _FALLBACK_TERMINAL_STATES


def validate_config_sync() -> None:
    """Validate that state machine STATES matches config.

    This function runs once on first IssueStateMachine instantiation.
    It compares the hardcoded STATES list with config-derived states
    and logs a warning if there's a mismatch.
    """
    global _config_validated

    if _config_validated:
        return

    _config_validated = True

    try:
        config = load_config()

        # Build set of states from config
        config_states: set[str] = set()
        for stage in config.stages:
            if stage.substages:
                for substage_name in stage.substages.keys():
                    config_states.add(f"{stage.name}.{substage_name}")
            else:
                config_states.add(stage.name)

        # Compare with hardcoded STATES
        machine_states = set(IssueStateMachine.STATES)

        missing_from_machine = config_states - machine_states
        extra_in_machine = machine_states - config_states

        if missing_from_machine:
            logger.warning(
                f"Config has states not in state machine STATES: {sorted(missing_from_machine)}. "
                "Update agenttree/state_machine.py to add these states."
            )

        if extra_in_machine:
            logger.debug(
                f"State machine has states not in config: {sorted(extra_in_machine)}. "
                "These may be transitional states or the config was simplified."
            )

    except Exception as e:
        logger.warning(f"Could not validate config sync: {e}")


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, source: str, dest: str, message: Optional[str] = None) -> None:
        self.source = source
        self.dest = dest
        if message:
            super().__init__(message)
        else:
            super().__init__(f"Invalid transition from '{source}' to '{dest}'")


class IssueStateMachine:
    """State machine for managing issue stage transitions.

    This class provides formal validation of state transitions in the AgentTree workflow.
    It uses the transitions library to define valid states and transitions, preventing
    invalid state changes.

    The state machine uses a combined state format:
    - For stages without substages: just the stage name (e.g., "backlog", "plan_review")
    - For stages with substages: "stage.substage" format (e.g., "define.refine", "implement.code")

    Example usage:
        >>> sm = IssueStateMachine()
        >>> sm.set_state("define.refine")
        >>> sm.can_transition_to("research.explore")
        True
        >>> sm.validate_transition("research.explore")  # Raises if invalid
        >>> sm.advance()  # Moves to next state
    """

    # All valid states in the workflow
    # Format: stage.substage for stages with substages, just stage for others
    STATES = [
        # Backlog - no substages
        "backlog",
        # Define stage
        "define.refine",
        # Research stage
        "research.explore",
        "research.document",
        # Plan stage
        "plan.draft",
        "plan.refine",
        # Plan assessment and revision
        "plan_assess",
        "plan_revise",
        # Plan review (human review gate)
        "plan_review",
        # Implement stage with substages
        "implement.setup",
        "implement.code",
        "implement.code_review",
        "implement.address_review",
        "implement.wrapup",
        "implement.feedback",
        # Independent code review (custom agent stage)
        "independent_code_review",
        # Address independent review feedback (redirect_only stage)
        "address_independent_review",
        # Implementation review (human review gate)
        "implementation_review.ci_wait",
        "implementation_review.review",
        # Terminal states
        "accepted",
        "not_doing",
    ]

    # All valid transitions in the workflow
    # Each dict has trigger, source, and dest keys
    TRANSITIONS = [
        # Backlog to define
        {"trigger": "advance", "source": "backlog", "dest": "define.refine"},
        # Define to research
        {"trigger": "advance", "source": "define.refine", "dest": "research.explore"},
        # Research substages and to plan
        {"trigger": "advance", "source": "research.explore", "dest": "research.document"},
        {"trigger": "advance", "source": "research.document", "dest": "plan.draft"},
        # Plan substages and to plan_assess
        {"trigger": "advance", "source": "plan.draft", "dest": "plan.refine"},
        {"trigger": "advance", "source": "plan.refine", "dest": "plan_assess"},
        # Plan assessment flow
        {"trigger": "advance", "source": "plan_assess", "dest": "plan_revise"},
        {"trigger": "advance", "source": "plan_revise", "dest": "plan_review"},
        # Plan review to implement (human approval required)
        {"trigger": "advance", "source": "plan_review", "dest": "implement.setup"},
        # Implement substages
        {"trigger": "advance", "source": "implement.setup", "dest": "implement.code"},
        {"trigger": "advance", "source": "implement.code", "dest": "implement.code_review"},
        {"trigger": "advance", "source": "implement.code_review", "dest": "implement.address_review"},
        {"trigger": "advance", "source": "implement.address_review", "dest": "implement.wrapup"},
        {"trigger": "advance", "source": "implement.wrapup", "dest": "implement.feedback"},
        # Implement feedback to independent code review
        {"trigger": "advance", "source": "implement.feedback", "dest": "independent_code_review"},
        # Independent code review to implementation review (normal flow)
        {"trigger": "advance", "source": "independent_code_review", "dest": "implementation_review.ci_wait"},
        # Independent code review redirect to address feedback (when reviewer requests changes)
        {"trigger": "redirect", "source": "independent_code_review", "dest": "address_independent_review"},
        # Address independent review rolls back to independent_code_review for re-review
        {"trigger": "advance", "source": "address_independent_review", "dest": "independent_code_review"},
        # Also allow advance to implementation_review (config calculates this as next, hook redirects)
        {"trigger": "advance", "source": "address_independent_review", "dest": "implementation_review.ci_wait"},
        # Implementation review substages and to accepted
        {"trigger": "advance", "source": "implementation_review.ci_wait", "dest": "implementation_review.review"},
        {"trigger": "advance", "source": "implementation_review.review", "dest": "accepted"},
        # Terminal states stay at themselves
        {"trigger": "advance", "source": "accepted", "dest": "accepted"},
        {"trigger": "advance", "source": "not_doing", "dest": "not_doing"},
        # Reject transitions - can move to not_doing from most stages
        {"trigger": "reject", "source": "backlog", "dest": "not_doing"},
        {"trigger": "reject", "source": "define.refine", "dest": "not_doing"},
        {"trigger": "reject", "source": "research.explore", "dest": "not_doing"},
        {"trigger": "reject", "source": "research.document", "dest": "not_doing"},
        {"trigger": "reject", "source": "plan.draft", "dest": "not_doing"},
        {"trigger": "reject", "source": "plan.refine", "dest": "not_doing"},
        {"trigger": "reject", "source": "plan_assess", "dest": "not_doing"},
        {"trigger": "reject", "source": "plan_revise", "dest": "not_doing"},
        {"trigger": "reject", "source": "plan_review", "dest": "not_doing"},
    ]

    def __init__(self, initial_state: str = "backlog") -> None:
        """Initialize the state machine.

        Args:
            initial_state: Initial state for the machine (default: "backlog")
        """
        # Validate config sync on first instantiation
        validate_config_sync()

        self._state = initial_state

        # Create the machine
        self.machine = Machine(
            model=self,
            states=self.STATES,
            transitions=self.TRANSITIONS,
            initial=initial_state,
            auto_transitions=False,  # Only allow explicitly defined transitions
            send_event=False,
        )

    @property
    def current_state(self) -> str:
        """Get the current state."""
        return str(getattr(self, "state", self._state))

    def set_state(self, state: str) -> None:
        """Set the current state directly.

        This is used to initialize the state machine to match an existing issue's state.

        Args:
            state: The state to set (in "stage.substage" or "stage" format)

        Raises:
            ValueError: If the state is not valid
        """
        if state not in self.STATES:
            raise ValueError(f"Invalid state: '{state}'. Valid states: {self.STATES}")
        self.machine.set_state(state)

    def can_transition_to(self, target_state: str) -> bool:
        """Check if a transition to the target state is valid.

        Args:
            target_state: The state to transition to

        Returns:
            True if the transition is valid, False otherwise
        """
        if target_state not in self.STATES:
            return False

        # Check if any transition exists from current state to target
        for t in self.TRANSITIONS:
            if t["source"] == self.current_state and t["dest"] == target_state:
                return True

        return False

    def validate_transition(self, target_state: str) -> None:
        """Validate that a transition to the target state is allowed.

        Args:
            target_state: The state to transition to

        Raises:
            InvalidTransitionError: If the transition is not valid
        """
        if target_state not in self.STATES:
            raise InvalidTransitionError(
                self.current_state,
                target_state,
                f"Invalid target state: '{target_state}'. Valid states: {self.STATES}",
            )

        if not self.can_transition_to(target_state):
            raise InvalidTransitionError(self.current_state, target_state)

    def get_next_state(self) -> Optional[str]:
        """Get the next state in the workflow (via 'advance' trigger).

        Returns:
            The next state, or None if at a terminal state
        """
        if self.current_state in _get_terminal_states():
            return None

        for t in self.TRANSITIONS:
            if t["trigger"] == "advance" and t["source"] == self.current_state:
                return t["dest"]

        return None

    def is_human_review_required(self) -> bool:
        """Check if the current state requires human review.

        Returns:
            True if human review is required before advancing
        """
        return self.current_state in _get_human_review_states()

    def is_terminal(self) -> bool:
        """Check if the current state is terminal.

        Returns:
            True if this is a terminal state (accepted or not_doing)
        """
        return self.current_state in _get_terminal_states()

    def get_valid_transitions(self) -> list[str]:
        """Get all valid target states from the current state.

        Returns:
            List of valid target state names
        """
        valid = []
        for t in self.TRANSITIONS:
            if t["source"] == self.current_state and t["dest"] not in valid:
                valid.append(t["dest"])
        return valid

    @staticmethod
    def format_state(stage: str, substage: Optional[str] = None) -> str:
        """Format stage and substage into a state string.

        Args:
            stage: The stage name
            substage: Optional substage name

        Returns:
            Formatted state string (e.g., "implement.code" or "backlog")
        """
        if substage:
            return f"{stage}.{substage}"
        return stage

    @staticmethod
    def parse_state(state: str) -> tuple[str, Optional[str]]:
        """Parse a state string into stage and substage.

        Args:
            state: State string (e.g., "implement.code" or "backlog")

        Returns:
            Tuple of (stage, substage) where substage may be None
        """
        if "." in state:
            parts = state.split(".", 1)
            return parts[0], parts[1]
        return state, None


def validate_state_transition(
    current_stage: str,
    current_substage: Optional[str],
    target_stage: str,
    target_substage: Optional[str],
) -> None:
    """Validate a state transition between issue stages.

    This is a convenience function for validating transitions without
    creating a full state machine instance.

    Args:
        current_stage: Current stage name
        current_substage: Current substage (may be None)
        target_stage: Target stage name
        target_substage: Target substage (may be None)

    Raises:
        InvalidTransitionError: If the transition is not valid
    """
    current_state = IssueStateMachine.format_state(current_stage, current_substage)
    target_state = IssueStateMachine.format_state(target_stage, target_substage)

    sm = IssueStateMachine()
    sm.set_state(current_state)
    sm.validate_transition(target_state)


def get_all_states() -> list[str]:
    """Get all valid states in the workflow.

    Returns:
        List of all state names
    """
    return list(IssueStateMachine.STATES)


def get_all_transitions() -> list[dict[str, str]]:
    """Get all valid transitions in the workflow.

    Returns:
        List of dicts with keys 'trigger', 'source', 'dest'
    """
    return list(IssueStateMachine.TRANSITIONS)


def generate_diagram(
    output_path: Optional[str] = None,
    title: str = "AgentTree Issue Workflow",
) -> str:
    """Generate a Graphviz diagram of the state machine.

    Args:
        output_path: Optional path to save the diagram (as .dot file)
        title: Title for the diagram

    Returns:
        The Graphviz DOT source as a string
    """
    # Build DOT source manually for full control
    lines = [
        "digraph {",
        f'    label="{title}";',
        "    labelloc=t;",
        "    rankdir=TB;",
        "    node [shape=box, style=rounded];",
        "",
        "    // States",
    ]

    # Add state nodes with styling
    terminal_states = _get_terminal_states()
    human_review_states = _get_human_review_states()

    for state in IssueStateMachine.STATES:
        if state in terminal_states:
            # Terminal states are double-bordered
            lines.append(f'    "{state}" [shape=doublecircle];')
        elif state in human_review_states:
            # Human review states are highlighted
            lines.append(f'    "{state}" [style="rounded,filled", fillcolor=lightyellow];')
        else:
            lines.append(f'    "{state}";')

    lines.append("")
    lines.append("    // Transitions")

    # Add transitions
    for t in IssueStateMachine.TRANSITIONS:
        if t["trigger"] == "reject":
            # Reject transitions are dashed
            lines.append(f'    "{t["source"]}" -> "{t["dest"]}" [style=dashed, label="reject"];')
        else:
            lines.append(f'    "{t["source"]}" -> "{t["dest"]}";')

    lines.append("}")

    dot_source = "\n".join(lines)

    if output_path:
        with open(output_path, "w") as f:
            f.write(dot_source)

    return dot_source

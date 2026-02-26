"""Stage constants for AgentTree workflow.

This module provides string enum constants for commonly-used stage names,
preventing typos and enabling IDE autocomplete. Uses the (str, Enum) pattern
for Python 3.10+ compatibility.
"""

from enum import Enum


class TerminalStage(str, Enum):
    """Terminal/parking-lot stages that exist in all workflow configurations."""

    BACKLOG = "backlog"
    ACCEPTED = "accepted"
    NOT_DOING = "not_doing"


class Stage(str, Enum):
    """Commonly-used stage dot-paths.

    These are full dot-paths for stages frequently referenced in code.
    Dynamic stage composition (f"{stage}.{substage}") should continue
    using string parts, not enum values.
    """

    # Explore stages
    EXPLORE_DEFINE = "explore.define"
    EXPLORE_RESEARCH = "explore.research"

    # Plan stages
    PLAN_DRAFT = "plan.draft"
    PLAN_ASSESS = "plan.assess"
    PLAN_REVISE = "plan.revise"
    PLAN_REVIEW = "plan.review"

    # Implement stages
    IMPLEMENT_CODE = "implement.code"
    IMPLEMENT_CODE_REVIEW = "implement.code_review"
    IMPLEMENT_INDEPENDENT_REVIEW = "implement.independent_review"
    IMPLEMENT_CI_WAIT = "implement.ci_wait"
    IMPLEMENT_REVIEW = "implement.review"
    IMPLEMENT_DEBUG = "implement.debug"
    IMPLEMENT_FEEDBACK = "implement.feedback"

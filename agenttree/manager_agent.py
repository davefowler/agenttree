"""Manager agent stall detection and monitoring.

This module provides helper functions for the manager agent to detect
stalled agents and log interventions.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import yaml


class StalledAgent(TypedDict):
    """Type definition for stalled agent info."""

    issue_id: str
    stage: str
    minutes_stalled: int
    title: str



# Human review stages that should be excluded from stall detection
HUMAN_REVIEW_STAGES = {"plan_review", "implementation_review"}


def get_stalled_agents(
    agents_dir: Path,
    threshold_min: int = 20,
) -> list[StalledAgent]:
    """Return list of stalled agents with their details.

    An agent is considered stalled if:
    - It has an assigned_agent (agent is running)
    - It's not in a human_review or parking_lot stage
    - It hasn't advanced stages for threshold_min minutes

    Note: This does not verify tmux session existence. The CLI caller
    should verify session status if needed.

    Args:
        agents_dir: Path to _agenttree directory
        threshold_min: Minutes without advancement before considered stalled

    Returns:
        List of StalledAgent dicts with:
        - issue_id: Issue ID
        - stage: Current stage (with substage if any)
        - minutes_stalled: How many minutes since last advancement
        - title: Issue title
    """
    from agenttree.config import load_config

    issues_dir = agents_dir / "issues"
    if not issues_dir.exists():
        return []

    config = load_config()
    stalled: list[StalledAgent] = []
    now = datetime.now(timezone.utc)

    for issue_dir in issues_dir.iterdir():
        if not issue_dir.is_dir():
            continue

        issue_yaml = issue_dir / "issue.yaml"
        if not issue_yaml.exists():
            continue

        try:
            with open(issue_yaml) as f:
                issue_data = yaml.safe_load(f)

            # Skip if no active agent running for this issue
            from agenttree.state import get_active_agent
            issue_id = issue_data.get("id", "")
            if not issue_id:
                continue
            active_agent = get_active_agent(issue_id)
            if not active_agent:
                continue

            # Get stage info
            stage = issue_data.get("stage", "")
            substage = issue_data.get("substage")

            # Skip human review stages
            if stage in HUMAN_REVIEW_STAGES:
                continue

            # Skip parking lot stages (no active agent expected)
            if config.is_parking_lot(stage):
                continue

            # Read session file for last_advanced_at
            session_file = issue_dir / ".agent_session.yaml"
            if not session_file.exists():
                continue

            with open(session_file) as f:
                session_data = yaml.safe_load(f)

            last_advanced_at = session_data.get("last_advanced_at")
            if not last_advanced_at:
                continue

            # Parse timestamp and check if stalled
            try:
                last_time = datetime.fromisoformat(last_advanced_at.replace("Z", "+00:00"))
                minutes_since = (now - last_time).total_seconds() / 60

                if minutes_since < threshold_min:
                    continue  # Not stalled yet
            except (ValueError, TypeError):
                continue

            # Build stage string
            stage_str = f"{stage}.{substage}" if substage else stage

            stalled.append({
                "issue_id": issue_id,
                "stage": stage_str,
                "minutes_stalled": int(minutes_since),
                "title": issue_data.get("title", ""),
            })

        except (OSError, yaml.YAMLError, KeyError, TypeError):
            # Skip issues with invalid or malformed data
            continue

    return stalled

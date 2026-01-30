"""Controller agent stall detection and monitoring.

This module provides helper functions for the controller agent to detect
stalled agents and log interventions.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TypedDict

import yaml


class StalledAgent(TypedDict):
    """Type definition for stalled agent info."""

    issue_id: str
    stage: str
    minutes_stalled: int
    title: str



# Human review stages that should be excluded from stall detection
HUMAN_REVIEW_STAGES = {"plan_review", "implementation_review"}

# Terminal stages that should be excluded (no active agent)
TERMINAL_STAGES = {"accepted", "not_doing", "closed"}


def get_stalled_agents(
    agents_dir: Path,
    threshold_min: int = 20,
) -> list[StalledAgent]:
    """Return list of stalled agents with their details.

    An agent is considered stalled if:
    - It has an assigned_agent (agent is running)
    - It's not in a human_review or terminal stage
    - It hasn't advanced stages for threshold_min minutes
    - Its tmux session is still active

    Args:
        agents_dir: Path to _agenttree directory
        threshold_min: Minutes without advancement before considered stalled

    Returns:
        List of dicts with stalled agent info:
        - issue_id: Issue ID
        - stage: Current stage (with substage if any)
        - minutes_stalled: How many minutes since last advancement
        - session_name: Tmux session name
    """
    issues_dir = agents_dir / "issues"
    if not issues_dir.exists():
        return []

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

            # Skip if no agent assigned
            if not issue_data.get("assigned_agent"):
                continue

            # Get stage info
            stage = issue_data.get("stage", "")
            substage = issue_data.get("substage")

            # Skip human review stages
            if stage in HUMAN_REVIEW_STAGES:
                continue

            # Skip terminal stages
            if stage in TERMINAL_STAGES:
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

            # Check if tmux session is still alive
            issue_id = issue_data.get("id", "")
            # Build session name - format is {project}-issue-{id}
            # We need to check if session exists, but we don't have project name here
            # For now, just assume it exists if we got this far
            # The CLI command will verify session existence

            # Build stage string
            stage_str = f"{stage}.{substage}" if substage else stage

            stalled.append({
                "issue_id": issue_id,
                "stage": stage_str,
                "minutes_stalled": int(minutes_since),
                "title": issue_data.get("title", ""),
            })

        except Exception:
            # Skip issues with invalid data
            continue

    return stalled


def log_stall(
    agents_dir: Path,
    issue_id: str,
    stage: str,
    nudge_message: str,
    escalated: bool = False,
) -> None:
    """Log a stall intervention to stalls.yaml.

    Args:
        agents_dir: Path to _agenttree directory
        issue_id: Issue ID
        stage: Current stage (with substage if any)
        nudge_message: The nudge message that was sent
        escalated: Whether this triggered escalation
    """
    logs_dir = agents_dir / "controller_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / "stalls.yaml"

    # Load existing data or start fresh
    if log_file.exists():
        with open(log_file) as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    if "stalls" not in data:
        data["stalls"] = []

    # Add new stall entry
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "issue_id": issue_id,
        "stage": stage,
        "detected_at": now,
        "nudge_sent": nudge_message,
        "escalation_needed": escalated,
    }
    data["stalls"].append(entry)

    # Write back
    with open(log_file, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def get_nudge_count(agents_dir: Path, issue_id: str) -> int:
    """Get the number of nudges sent to an issue without stage advancement.

    Args:
        agents_dir: Path to _agenttree directory
        issue_id: Issue ID

    Returns:
        Number of nudges sent since last stage advancement
    """
    log_file = agents_dir / "controller_logs" / "stalls.yaml"
    if not log_file.exists():
        return 0

    try:
        with open(log_file) as f:
            data = yaml.safe_load(f) or {}

        stalls = data.get("stalls", [])
        count = 0
        for stall in reversed(stalls):  # Most recent first
            if stall.get("issue_id") == issue_id:
                count += 1
            else:
                # Once we see a different issue, stop counting
                break
        return count
    except Exception:
        return 0

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
        - stage: Current stage dot path (e.g., "explore.define")
        - minutes_stalled: How many minutes since last advancement
        - title: Issue title
    """
    from agenttree.config import load_config

    issues_dir = agents_dir / "issues"
    if not issues_dir.exists():
        return []

    config = load_config()
    human_review_stages = set(config.get_human_review_stages())
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

            # Get stage (dot path when substage present: implement.code)
            stage = issue_data.get("stage", "")
            substage = issue_data.get("substage") or ""
            if substage:
                stage = f"{stage}.{substage}"

            # Skip human review stages
            if stage in human_review_stages:
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

            stalled.append({
                "issue_id": issue_id,
                "stage": stage,
                "minutes_stalled": int(minutes_since),
                "title": issue_data.get("title", ""),
            })

        except (OSError, yaml.YAMLError, KeyError, TypeError):
            # Skip issues with invalid or malformed data
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
    logs_dir = agents_dir / "manager_logs"
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
    log_file = agents_dir / "manager_logs" / "stalls.yaml"
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
    except (OSError, yaml.YAMLError, KeyError, TypeError):
        return 0


def should_notify_stall(agents_dir: Path, issue_id: str, stage: str, cooldown_min: int = 10) -> bool:
    """Check if we should notify about this stall (avoid duplicate notifications).

    Args:
        agents_dir: Path to _agenttree directory
        issue_id: Issue ID
        stage: Current stage string
        cooldown_min: Minutes to wait before re-notifying about same stall

    Returns:
        True if we should notify, False if recently notified
    """
    state_file = agents_dir / "controller_logs" / "stall_notifications.yaml"

    now = datetime.now(timezone.utc)

    if state_file.exists():
        try:
            with open(state_file) as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            data = {}
    else:
        data = {}

    key = f"{issue_id}:{stage}"
    last_notified = data.get(key)

    if last_notified:
        try:
            last_time = datetime.fromisoformat(last_notified.replace("Z", "+00:00"))
            minutes_since = (now - last_time).total_seconds() / 60
            if minutes_since < cooldown_min:
                return False  # Recently notified, skip
        except (ValueError, TypeError):
            pass

    return True


def mark_stall_notified(agents_dir: Path, issue_id: str, stage: str) -> None:
    """Mark that we notified about this stall.

    Args:
        agents_dir: Path to _agenttree directory
        issue_id: Issue ID
        stage: Current stage string
    """
    logs_dir = agents_dir / "controller_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    state_file = logs_dir / "stall_notifications.yaml"

    if state_file.exists():
        try:
            with open(state_file) as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            data = {}
    else:
        data = {}

    key = f"{issue_id}:{stage}"
    data[key] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(state_file, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

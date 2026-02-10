"""Action registry for AgentTree event system.

This module provides a registry mapping action names to functions.
Actions are executed by the event dispatcher when events fire.

Built-in Actions:
    - start_manager: Start the manager agent
    - auto_start_agents: Start agents for issues not in parking lot
    - stop_all_agents: Stop all running agents
    - sync: Git pull/push _agenttree
    - check_stalled_agents: Nudge stalled agents
    - check_ci_status: Check GitHub CI status
    - check_merged_prs: Detect and handle merged PRs
    - push_pending_branches: Push branches with unpushed commits
    - check_manager_stages: Process issues in manager stages
    - check_custom_agent_stages: Spawn custom agents

Naming convention: Action names match function names exactly.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()

# Type alias for action functions
ActionFn = Callable[..., None]

# Action registry: maps action names to functions
ACTION_REGISTRY: dict[str, ActionFn] = {}


def register_action(name: str) -> Callable[[ActionFn], ActionFn]:
    """Decorator to register an action function.
    
    Args:
        name: Action name (should match function name by convention)
        
    Returns:
        Decorator function
    """
    def decorator(fn: ActionFn) -> ActionFn:
        ACTION_REGISTRY[name] = fn
        return fn
    return decorator


def get_action(name: str) -> ActionFn | None:
    """Get an action function by name.
    
    Args:
        name: Action name
        
    Returns:
        Action function or None if not found
    """
    return ACTION_REGISTRY.get(name)


def list_actions() -> list[str]:
    """List all registered action names.
    
    Returns:
        List of action names
    """
    return sorted(ACTION_REGISTRY.keys())


# =============================================================================
# Built-in Actions
# =============================================================================


@register_action("start_manager")
def start_manager(agents_dir: Path, **kwargs: Any) -> None:
    """Start the manager agent (agent 0).
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    import subprocess
    from agenttree.config import load_config
    from agenttree.tmux import session_exists
    
    config = load_config()
    manager_session = config.get_manager_tmux_session()
    
    if session_exists(manager_session):
        console.print("[dim]Manager already running[/dim]")
        return
    
    console.print("[cyan]Starting manager agent...[/cyan]")
    subprocess.Popen(
        ["uv", "run", "agenttree", "start", "0", "--skip-preflight"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=agents_dir.parent,  # Project root
        start_new_session=True,
    )
    console.print("[green]✓ Started manager agent[/green]")


@register_action("auto_start_agents")
def auto_start_agents(agents_dir: Path, **kwargs: Any) -> None:
    """Start agents for all issues not in parking lot stages.
    
    Uses fast session_exists checks instead of slow get_active_agent.
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    import subprocess
    from agenttree.config import load_config
    from agenttree.issues import list_issues, BACKLOG, ACCEPTED, NOT_DOING
    from agenttree.tmux import session_exists
    
    config = load_config()
    
    # Get active issues (not parking lot stages)
    issues = [
        i for i in list_issues(sync=False)
        if i.stage not in (BACKLOG, ACCEPTED, NOT_DOING)
    ]
    
    started = 0
    
    for issue in issues:
        # Fast check using session_exists instead of slow get_active_agent
        session_name = config.get_issue_tmux_session(issue.id, "developer")
        if session_exists(session_name):
            console.print(f"[dim]Issue #{issue.id} already has an agent[/dim]")
            continue
        
        console.print(f"[cyan]Starting agent for issue #{issue.id} ({issue.stage})...[/cyan]")
        result = subprocess.run(
            ["agenttree", "start", issue.id, "--skip-preflight"],
            capture_output=True,
            text=True,
            timeout=120,  # Container startup can be slow
        )
        if result.returncode == 0:
            started += 1
    
    console.print(f"[green]✓ Started {started} agent(s)[/green]")


@register_action("stop_all_agents")
def stop_all_agents(agents_dir: Path, **kwargs: Any) -> None:
    """Stop all running agents including orphaned sessions and containers.
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    import subprocess
    import re
    import time
    from agenttree.config import load_config
    from agenttree.tmux import kill_session
    
    config = load_config()
    prefix = f"{config.project}-"
    
    # Get all tmux sessions
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    if result.returncode != 0:
        console.print("[dim]No tmux sessions running[/dim]")
        # Still clean up containers in case there are orphans
        from agenttree.api import cleanup_all_with_retry
        cleanup_all_with_retry(quiet=True)
        console.print(f"[green]✓ Stopped 0 agent(s)[/green]")
        return
    
    sessions = result.stdout.strip().split("\n")
    stopped = 0
    
    # Step 1: Kill all tmux sessions first (fast)
    for session in sessions:
        if session.startswith(prefix) and not session.endswith("-manager-000"):
            kill_session(session)
            stopped += 1
            console.print(f"[dim]Stopped {session}[/dim]")
    
    # Step 2: Wait for containers to begin stopping
    if stopped > 0:
        time.sleep(2.0)
    
    # Step 3: Clean up all agenttree containers with multiple passes
    # Apple Container deletion can take a long time - retry until all are gone
    from agenttree.api import cleanup_all_with_retry
    cleanup_all_with_retry(max_passes=5, delay_s=2.0, quiet=True)
    
    console.print(f"[green]✓ Stopped {stopped} agent(s)[/green]")


@register_action("sync")
def sync(agents_dir: Path, pull_only: bool = True, **kwargs: Any) -> None:
    """Sync _agenttree repo with remote (pull and optionally push).
    
    Note: This is a lightweight sync that doesn't run post-sync hooks.
    Use this action within heartbeat to avoid recursive hook calls.
    
    Args:
        agents_dir: Path to _agenttree directory
        pull_only: If True, only pull changes (default)
    """
    from agenttree.hooks import is_running_in_container
    import subprocess
    
    if is_running_in_container():
        return
    
    if not agents_dir.exists() or not (agents_dir / ".git").exists():
        return
    
    # Commit any local changes first
    status_result = subprocess.run(
        ["git", "-C", str(agents_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    if status_result.stdout.strip():
        subprocess.run(
            ["git", "-C", str(agents_dir), "add", "-A"],
            capture_output=True,
            timeout=10,
        )
        subprocess.run(
            ["git", "-C", str(agents_dir), "commit", "-m", "Auto-sync: update issue data"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    
    # Pull
    subprocess.run(
        ["git", "-C", str(agents_dir), "pull", "--no-rebase"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    
    # Push if not pull_only
    if not pull_only:
        subprocess.run(
            ["git", "-C", str(agents_dir), "push"],
            capture_output=True,
            text=True,
            timeout=30,
        )


@register_action("check_stalled_agents")
def check_stalled_agents(
    agents_dir: Path,
    threshold_min: int = 15,
    **kwargs: Any
) -> None:
    """Check for stalled agents and write to stalled.yaml, then notify manager.
    
    Writes stall data to _agenttree/stalled.yaml so manager can read it anytime,
    then sends a brief notification to the manager.
    
    Uses fast session_exists() checks instead of slow get_active_agent().
    
    Args:
        agents_dir: Path to _agenttree directory
        threshold_min: Minutes before considering agent stalled
    """
    import yaml
    from datetime import datetime, timezone
    from agenttree.config import load_config
    from agenttree.issues import list_issues, BACKLOG, ACCEPTED, NOT_DOING
    from agenttree.tmux import session_exists, send_message, is_claude_running
    
    config = load_config()
    manager_session = config.get_manager_tmux_session()
    
    # Get active issues (not backlog/accepted/not_doing)
    issues = [
        i for i in list_issues(sync=False)
        if i.stage not in (BACKLOG, ACCEPTED, NOT_DOING)
    ]
    
    stalled: list[dict[str, Any]] = []
    dead: list[dict[str, Any]] = []
    
    for issue in issues:
        # Build session name directly (fast) instead of get_active_agent (slow)
        session_name = config.get_issue_tmux_session(issue.id, "developer")
        
        # Check if session exists
        if not session_exists(session_name):
            # No session = dead agent (if not in a human review stage)
            stage_config = config.get_stage(issue.stage)
            if stage_config and stage_config.role == "manager":
                continue  # Waiting on human, not dead
            dead.append({
                "id": issue.id,
                "title": issue.title[:60],
                "stage": issue.stage,
                "reason": "no_session",
            })
            continue
        
        # Session exists - check if Claude is running
        claude_running = is_claude_running(session_name)
        
        # Check last activity
        try:
            last_updated = datetime.fromisoformat(issue.updated.replace("Z", "+00:00"))
            elapsed_min = int((datetime.now(timezone.utc) - last_updated).total_seconds() / 60)
            
            if not claude_running:
                dead.append({
                    "id": issue.id,
                    "title": issue.title[:60],
                    "stage": issue.stage,
                    "reason": "claude_exited",
                })
            elif elapsed_min > threshold_min:
                stalled.append({
                    "id": issue.id,
                    "title": issue.title[:60],
                    "stage": issue.stage,
                    "stalled_minutes": elapsed_min,
                })
        except (ValueError, TypeError):
            continue
    
    # Read previous stall data to detect changes
    stall_file = agents_dir / "stalled.yaml"
    prev_dead_ids: set[str] = set()
    prev_stalled_ids: set[str] = set()
    
    if stall_file.exists():
        try:
            prev_data = yaml.safe_load(stall_file.read_text())
            prev_dead_ids = {a["id"] for a in prev_data.get("dead_agents", [])}
            prev_stalled_ids = {a["id"] for a in prev_data.get("stalled_agents", [])}
        except Exception:
            pass
    
    # Write to stalled.yaml (always, even if empty - so manager knows state is fresh)
    stall_data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "threshold_min": threshold_min,
        "dead_agents": dead,
        "stalled_agents": stalled,
    }
    stall_file.write_text(yaml.dump(stall_data, default_flow_style=False))
    
    # If nothing to report, we're done
    if not stalled and not dead:
        return
    
    # Only notify manager if there are NEW dead/stalled agents (not already alerted)
    current_dead_ids = {a["id"] for a in dead}
    current_stalled_ids = {a["id"] for a in stalled}
    new_dead = current_dead_ids - prev_dead_ids
    new_stalled = current_stalled_ids - prev_stalled_ids
    
    if not new_dead and not new_stalled:
        console.print(f"[dim]Stall state unchanged ({len(dead)} dead, {len(stalled)} stalled) - not re-alerting manager[/dim]")
        return
    
    # Ensure manager is running before sending notification
    if not session_exists(manager_session):
        console.print("[yellow]Manager not running, restarting...[/yellow]")
        start_manager(agents_dir)
        # Give it a moment to spin up - notification will reach it on next cycle
        return
    
    # Send brief notification pointing to file
    lines = ["STALL REPORT - Check _agenttree/stalled.yaml for details:"]
    
    if dead:
        lines.append(f"  {len(dead)} dead agent(s) need restart")
        for agent in dead[:3]:  # Show first 3
            lines.append(f"    #{agent['id']}: {agent['title'][:30]}")
        if len(dead) > 3:
            lines.append(f"    ... and {len(dead) - 3} more")
    
    if stalled:
        lines.append(f"  {len(stalled)} stalled agent(s)")
        for agent in stalled[:3]:  # Show first 3
            lines.append(f"    #{agent['id']}: {agent['title'][:30]} ({agent['stalled_minutes']}min)")
        if len(stalled) > 3:
            lines.append(f"    ... and {len(stalled) - 3} more")
    
    lines.append("\nUse: agenttree start <id> --force --skip-preflight (restart) or agenttree output <id> (diagnose)")
    
    message = "\n".join(lines)
    result = send_message(manager_session, message)
    
    if result == "sent":
        console.print(f"[dim]Wrote stalled.yaml, notified manager ({len(new_dead)} new dead, {len(new_stalled)} new stalled)[/dim]")


@register_action("check_ci_status")
def check_ci_status(agents_dir: Path, **kwargs: Any) -> None:
    """Check CI status for PRs and notify agents on failure.
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    from agenttree.agents_repo import check_ci_status as do_check_ci
    
    count = do_check_ci(agents_dir)
    if count > 0:
        console.print(f"[dim]Processed {count} CI failure(s)[/dim]")


@register_action("check_merged_prs")
def check_merged_prs(agents_dir: Path, **kwargs: Any) -> None:
    """Detect and handle externally merged PRs.
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    from agenttree.agents_repo import check_merged_prs as do_check_merged
    
    count = do_check_merged(agents_dir)
    if count > 0:
        console.print(f"[dim]Processed {count} merged PR(s)[/dim]")


@register_action("push_pending_branches")
def push_pending_branches(agents_dir: Path, **kwargs: Any) -> None:
    """Push branches that have unpushed commits.
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    from agenttree.agents_repo import push_pending_branches as do_push
    
    count = do_push(agents_dir)
    if count > 0:
        console.print(f"[dim]Pushed {count} branch(es)[/dim]")


@register_action("ensure_review_branches")
def ensure_review_branches(agents_dir: Path, **kwargs: Any) -> None:
    """Ensure PRs exist and branches stay rebased for issues in implementation_review.

    Creates missing PRs, updates stale branches, and redirects conflicting
    issues back to the developer for rebase.

    Args:
        agents_dir: Path to _agenttree directory
    """
    from agenttree.agents_repo import ensure_review_branches as do_ensure

    count = do_ensure(agents_dir)
    if count > 0:
        console.print(f"[dim]Processed {count} review branch(es)[/dim]")


@register_action("check_manager_stages")
def check_manager_stages(agents_dir: Path, **kwargs: Any) -> None:
    """Process issues in manager-owned stages.
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    from agenttree.agents_repo import check_manager_stages as do_check
    
    count = do_check(agents_dir)
    if count > 0:
        console.print(f"[dim]Processed {count} manager stage issue(s)[/dim]")


@register_action("check_custom_agent_stages")
def check_custom_agent_stages(agents_dir: Path, **kwargs: Any) -> None:
    """Spawn custom agents for issues in custom agent stages.
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    from agenttree.agents_repo import check_custom_agent_stages as do_check
    
    count = do_check(agents_dir)
    if count > 0:
        console.print(f"[dim]Spawned {count} custom agent(s)[/dim]")


@register_action("cleanup_resources")
def cleanup_resources(
    agents_dir: Path,
    log_file: str | None = None,
    **kwargs: Any
) -> None:
    """Clean up stale resources (worktrees, branches, sessions).
    
    Args:
        agents_dir: Path to _agenttree directory
        log_file: Optional path to log cleanup activity
    """
    # Placeholder - cleanup is complex and might warrant its own implementation
    # For now, just log that cleanup would run
    if log_file:
        log_path = agents_dir / log_file.lstrip("/")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        with open(log_path, "a") as f:
            f.write(f"{datetime.now().isoformat()}: cleanup_resources executed\n")


# =============================================================================
# Rate Limit Fallback
# =============================================================================

import re
from datetime import datetime, timezone, timedelta

# Pattern to detect rate limit message in tmux output
RATE_LIMIT_PATTERN = re.compile(
    r"You've hit your limit · resets (\d{1,2})(am|pm) \(UTC\)"
)


def detect_rate_limit(tmux_output: str) -> datetime | None:
    """Check if output contains rate limit message, return reset time if found.
    
    Args:
        tmux_output: Captured tmux pane content
        
    Returns:
        Reset time as datetime (UTC) if rate limited, None otherwise
    """
    match = RATE_LIMIT_PATTERN.search(tmux_output)
    if not match:
        return None
    
    hour = int(match.group(1))
    ampm = match.group(2)
    
    # Convert to 24-hour format
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    
    # Calculate next reset time
    now = datetime.now(timezone.utc)
    reset_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    
    # If reset time has passed today, it's tomorrow
    if reset_time <= now:
        reset_time = reset_time + timedelta(days=1)
    
    return reset_time


def check_agent_rate_limited(session_name: str) -> datetime | None:
    """Check if an agent is rate limited, return reset time if so.
    
    Args:
        session_name: Tmux session name
        
    Returns:
        Reset time if rate limited, None otherwise
    """
    from agenttree.tmux import capture_pane, session_exists
    
    if not session_exists(session_name):
        return None
    
    output = capture_pane(session_name, lines=50)
    if not output:
        return None
    
    return detect_rate_limit(output)


def load_rate_limit_state(agents_dir: Path) -> dict[str, Any] | None:
    """Load rate limit state from file.
    
    Args:
        agents_dir: Path to _agenttree directory
        
    Returns:
        State dict or None if no state file
    """
    import yaml
    
    state_file = agents_dir / "rate_limit_state.yaml"
    if not state_file.exists():
        return None
    
    try:
        data = yaml.safe_load(state_file.read_text())
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        return None


def save_rate_limit_state(agents_dir: Path, state: dict[str, Any]) -> None:
    """Save rate limit state to file.
    
    Args:
        agents_dir: Path to _agenttree directory
        state: State dict to save
    """
    import yaml
    
    state_file = agents_dir / "rate_limit_state.yaml"
    state_file.write_text(yaml.dump(state, default_flow_style=False))


def clear_rate_limit_state(agents_dir: Path) -> None:
    """Clear rate limit state file.
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    state_file = agents_dir / "rate_limit_state.yaml"
    if state_file.exists():
        state_file.unlink()


def switch_agent_to_api_key(
    session_name: str,
    model: str,
) -> bool:
    """Switch an agent from oauth to API key mode.
    
    Kills the tmux session and restarts with API key auth.
    The container keeps running - we just restart the tmux session.
    
    Args:
        session_name: Tmux session name
        model: Model to use in API key mode
        
    Returns:
        True if switched successfully
    """
    from agenttree.tmux import kill_session, create_session, wait_for_prompt, send_keys, session_exists
    from agenttree.config import load_config
    
    config = load_config()
    
    # Extract issue_id from session name (e.g., "agenttree-developer-128" -> "128")
    parts = session_name.split("-")
    if len(parts) < 3:
        return False
    issue_id = parts[-1]
    
    # Get worktree path from issue
    from agenttree.issues import get_issue
    issue = get_issue(issue_id)
    if not issue or not issue.worktree_dir:
        return False
    
    worktree_path = Path(issue.worktree_dir)
    if not worktree_path.exists():
        return False
    
    # Kill the tmux session (container keeps running)
    kill_session(session_name)
    
    # Build new claude command with API key
    # We use tmux to run the command in the existing container
    # Since ANTHROPIC_API_KEY is already in the container env, just start claude
    claude_cmd = f"claude --model {model} --dangerously-skip-permissions"
    
    # For containerized agents, we need to exec into the container
    container_name = config.get_issue_container_name(issue_id)
    
    # Create new tmux session that execs into the container
    exec_cmd = f"docker exec -it {container_name} {claude_cmd} 2>/dev/null || container exec -it {container_name} {claude_cmd}"
    
    create_session(session_name, worktree_path, exec_cmd)
    
    # Wait for prompt and send restart message
    if wait_for_prompt(session_name, prompt_char="❯", timeout=60.0):
        send_keys(
            session_name,
            f"RATE LIMIT FALLBACK - Switched to API key mode ({model}). "
            f"Run 'agenttree next' to see your current stage and resume work."
        )
        return True
    
    return session_exists(session_name)


def switch_agent_to_oauth(
    session_name: str,
    model: str,
) -> bool:
    """Switch an agent from API key back to oauth mode.
    
    Uses --resume to try to continue the API key session (tested to work).
    
    Args:
        session_name: Tmux session name  
        model: Model to use in oauth mode
        
    Returns:
        True if switched successfully
    """
    from agenttree.tmux import kill_session, create_session, wait_for_prompt, send_keys, session_exists
    from agenttree.config import load_config
    
    config = load_config()
    
    # Extract issue_id from session name
    parts = session_name.split("-")
    if len(parts) < 3:
        return False
    issue_id = parts[-1]
    
    # Get worktree path from issue
    from agenttree.issues import get_issue
    issue = get_issue(issue_id)
    if not issue or not issue.worktree_dir:
        return False
    
    worktree_path = Path(issue.worktree_dir)
    if not worktree_path.exists():
        return False
    
    # Kill the tmux session
    kill_session(session_name)
    
    # Build new claude command with -r to resume API key session (tested to work!)
    claude_cmd = f"claude -r --model {model} --dangerously-skip-permissions"

    container_name = config.get_issue_container_name(issue_id)
    
    # Note: We unset ANTHROPIC_API_KEY to force oauth mode
    exec_cmd = f"docker exec -it {container_name} sh -c 'unset ANTHROPIC_API_KEY && {claude_cmd}' 2>/dev/null || container exec -it {container_name} sh -c 'unset ANTHROPIC_API_KEY && {claude_cmd}'"
    
    create_session(session_name, worktree_path, exec_cmd)
    
    # Wait for prompt - might take longer due to -r session picker
    if wait_for_prompt(session_name, prompt_char="❯", timeout=90.0):
        send_keys(
            session_name,
            f"RATE LIMIT RESET - Switched back to subscription ({model}). "
            f"Your previous session context was preserved. Continue working."
        )
        return True
    
    return session_exists(session_name)


@register_action("check_rate_limits")
def check_rate_limits(agents_dir: Path, **kwargs: Any) -> None:
    """Check for rate-limited agents and handle recovery.
    
    This action:
    1. Detects rate limits and saves state (but does NOT auto-switch to API key)
    2. After reset time passes, restarts agents in subscription mode
    
    Manual switch to API key mode is triggered via the web UI.
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    import os
    import subprocess
    from agenttree.config import load_config
    from agenttree.tmux import session_exists, list_sessions
    
    config = load_config()
    
    # First, check for recovery (reset time has passed)
    state = load_rate_limit_state(agents_dir)
    if state:
        stored_reset_time_str = state.get("reset_time")
        if stored_reset_time_str:
            stored_reset_time = datetime.fromisoformat(stored_reset_time_str.replace("Z", "+00:00"))
            buffer = timedelta(minutes=config.rate_limit_fallback.switch_back_buffer_min)
            
            if datetime.now(timezone.utc) >= stored_reset_time + buffer:
                # Time to restart agents in subscription mode!
                stored_agents = state.get("affected_agents", [])
                mode = state.get("mode", "subscription")  # "subscription" or "api_key"
                restarted = 0
                
                for agent_info in stored_agents:
                    issue_id = agent_info.get("issue_id")
                    if not issue_id:
                        continue
                    
                    # Restart agent in subscription mode (without --api-key flag)
                    result = subprocess.run(
                        ["agenttree", "start", str(issue_id), "--skip-preflight", "--force"],
                        capture_output=True,
                        text=True,
                        timeout=120,  # Container startup can be slow
                    )
                    if result.returncode == 0:
                        restarted += 1
                        console.print(f"[green]✓ Restarted agent #{issue_id} in subscription mode[/green]")
                    else:
                        console.print(f"[yellow]Failed to restart agent #{issue_id}: {result.stderr[:100]}[/yellow]")
                
                # Clear state
                clear_rate_limit_state(agents_dir)
                
                if restarted > 0:
                    action = "switched back" if mode == "api_key" else "woken up"
                    console.print(f"[green]Rate limit reset - {action} {restarted} agent(s) to subscription mode[/green]")
                return  # Don't check for new limits right after recovery
    
    # Get all active sessions for this project
    all_sessions = list_sessions()
    project_sessions = [
        s.name for s in all_sessions 
        if s.name.startswith(f"{config.project}-developer-")
    ]
    
    if not project_sessions:
        return
    
    # Check each session for rate limit
    reset_time: datetime | None = None
    rate_limited_sessions: list[str] = []
    
    for session_name in project_sessions:
        detected_reset = check_agent_rate_limited(session_name)
        if detected_reset:
            rate_limited_sessions.append(session_name)
            # Use the latest reset time found
            if reset_time is None or detected_reset > reset_time:
                reset_time = detected_reset
    
    if not rate_limited_sessions:
        return
    
    # Rate limit detected! Save state but DON'T auto-switch (user can manually switch via UI)
    # Only update state if not already tracking this rate limit
    existing_state = load_rate_limit_state(agents_dir)
    if existing_state:
        return  # Already tracking, don't overwrite
    
    # Build list of affected agents
    affected_agents: list[dict[str, str]] = []
    for session_name in project_sessions:
        parts = session_name.split("-")
        if len(parts) >= 3:
            issue_id = parts[-1]
            affected_agents.append({
                "issue_id": issue_id,
                "session_name": session_name,
            })
    
    # Save state for UI warning and auto-recovery
    if affected_agents and reset_time:
        save_rate_limit_state(agents_dir, {
            "rate_limited": True,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "reset_time": reset_time.isoformat(),
            "mode": "subscription",  # Not switched yet, still in subscription (but blocked)
            "affected_agents": affected_agents,
        })
        console.print(f"[yellow]⚠ Rate limit detected! {len(affected_agents)} agent(s) blocked until {reset_time.strftime('%I%p UTC')}[/yellow]")
        console.print(f"[yellow]Use web UI to switch to API key mode, or wait for auto-restart after reset.[/yellow]")


# =============================================================================
# Default Event Configurations
# =============================================================================

DEFAULT_EVENT_CONFIGS: dict[str, list[str] | dict[str, Any]] = {
    "startup": [
        "start_manager",
        "auto_start_agents",
    ],
    "shutdown": [
        "sync",
        "stop_all_agents",
    ],
    "heartbeat": {
        "interval_s": 10,
        "actions": [
            "sync",
            {"start_manager": {"min_interval_s": 30}},  # Ensure manager stays alive
            {"push_pending_branches": {}},
            {"check_manager_stages": {}},
            {"ensure_review_branches": {"min_interval_s": 60}},
            {"check_custom_agent_stages": {}},
            {"check_rate_limits": {"min_interval_s": 30}},  # Check for rate limits
            {"check_stalled_agents": {"min_interval_s": 180}},
            {"check_ci_status": {"min_interval_s": 60}},
            {"check_merged_prs": {"min_interval_s": 30}},
        ],
    },
}


def get_default_event_config(event: str) -> list[str] | dict[str, Any] | None:
    """Get default configuration for an event.
    
    Args:
        event: Event name
        
    Returns:
        Default config or None if no default exists
    """
    return DEFAULT_EVENT_CONFIGS.get(event)

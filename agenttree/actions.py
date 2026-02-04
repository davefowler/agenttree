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
    manager_session = f"{config.project}-manager-000"
    
    if session_exists(manager_session):
        console.print("[dim]Manager already running[/dim]")
        return
    
    console.print("[cyan]Starting manager agent...[/cyan]")
    subprocess.Popen(
        ["uv", "run", "agenttree", "start", "0"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=agents_dir.parent,  # Project root
        start_new_session=True,
    )
    console.print("[green]✓ Started manager agent[/green]")


@register_action("auto_start_agents")
def auto_start_agents(agents_dir: Path, **kwargs: Any) -> None:
    """Start agents for all issues not in parking lot stages.
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    import subprocess
    from agenttree.config import load_config
    from agenttree.issues import list_issues
    from agenttree.state import get_active_agent
    
    config = load_config()
    parking_lot_stages = config.get_parking_lot_stages()
    
    issues = list_issues(sync=False)
    started = 0
    
    for issue in issues:
        if issue.stage in parking_lot_stages:
            continue
        
        if get_active_agent(issue.id):
            console.print(f"[dim]Issue #{issue.id} already has an agent[/dim]")
            continue
        
        console.print(f"[cyan]Starting agent for issue #{issue.id} ({issue.stage})...[/cyan]")
        result = subprocess.run(
            ["agenttree", "start", issue.id, "--skip-preflight"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            started += 1
    
    console.print(f"[green]✓ Started {started} agent(s)[/green]")


@register_action("stop_all_agents")
def stop_all_agents(agents_dir: Path, **kwargs: Any) -> None:
    """Stop all running agents.
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    from agenttree.issues import list_issues
    from agenttree.state import stop_all_agents_for_issue, get_active_agent
    
    issues = list_issues(sync=False)
    stopped = 0
    
    for issue in issues:
        if get_active_agent(issue.id):
            count = stop_all_agents_for_issue(issue.id, quiet=True)
            if count > 0:
                stopped += count
                console.print(f"[dim]Stopped agent(s) for issue #{issue.id}[/dim]")
    
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
    """Check for stalled agents and notify the manager.
    
    Instead of nudging agents directly, this builds a report of stalled agents
    and sends it to the manager so it can decide how to handle them
    (restart, nudge, or investigate).
    
    Args:
        agents_dir: Path to _agenttree directory
        threshold_min: Minutes before considering agent stalled
    """
    from datetime import datetime, timezone
    from agenttree.config import load_config
    from agenttree.issues import list_issues
    from agenttree.state import get_active_agent
    from agenttree.tmux import session_exists, send_message, is_claude_running
    
    config = load_config()
    parking_lot_stages = config.get_parking_lot_stages()
    manager_session = f"{config.project}-manager-000"
    
    # Check if manager is running
    if not session_exists(manager_session):
        console.print("[dim]Manager not running, skipping stall check[/dim]")
        return
    
    issues = list_issues(sync=False)
    stalled: list[tuple[str, str, int]] = []  # (id, title, minutes)
    dead: list[tuple[str, str]] = []  # (id, title) - session exists but claude exited
    
    for issue in issues:
        if issue.stage in parking_lot_stages:
            continue
        
        agent = get_active_agent(issue.id)
        if not agent or not agent.tmux_session:
            continue
        
        if not session_exists(agent.tmux_session):
            continue
        
        # Check if Claude is actually running
        claude_running = is_claude_running(agent.tmux_session)
        
        # Check last activity
        try:
            last_updated = datetime.fromisoformat(issue.updated.replace("Z", "+00:00"))
            elapsed_min = int((datetime.now(timezone.utc) - last_updated).total_seconds() / 60)
            
            if not claude_running:
                # Claude exited - agent is dead
                dead.append((issue.id, issue.title[:40]))
            elif elapsed_min > threshold_min:
                # Claude running but stalled
                stalled.append((issue.id, issue.title[:40], elapsed_min))
        except (ValueError, TypeError):
            continue
    
    # Build message for controller
    if not stalled and not dead:
        return
    
    lines = ["STALL REPORT - Please investigate and take action:"]
    
    if dead:
        lines.append(f"\nDEAD AGENTS ({len(dead)}) - Claude exited, need restart:")
        for issue_id, title in dead:
            lines.append(f"  #{issue_id}: {title}")
        lines.append("  → Use 'agenttree start <id> --force' to restart")
    
    if stalled:
        lines.append(f"\nSTALLED AGENTS ({len(stalled)}) - No progress:")
        for issue_id, title, mins in stalled:
            lines.append(f"  #{issue_id}: {title} ({mins}min)")
        lines.append("  → Use 'agenttree output <id>' to diagnose")
        lines.append("  → Use 'agenttree send <id> \"message\" --interrupt' to nudge")
    
    message = "\n".join(lines)
    result = send_message(manager_session, message)
    
    if result == "sent":
        console.print(f"[dim]Sent stall report to manager ({len(dead)} dead, {len(stalled)} stalled)[/dim]")


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


@register_action("check_manager_stages")
def check_manager_stages(agents_dir: Path, **kwargs: Any) -> None:
    """Process issues in controller-owned stages.
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    from agenttree.agents_repo import check_manager_stages as do_check
    
    count = do_check(agents_dir)
    if count > 0:
        console.print(f"[dim]Processed {count} controller stage issue(s)[/dim]")


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
            {"push_pending_branches": {}},
            {"check_manager_stages": {}},
            {"check_custom_agent_stages": {}},
            {"check_stalled_agents": {"min_interval_s": 60}},
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

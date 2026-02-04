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
    """Stop all running agents including orphaned sessions.
    
    Args:
        agents_dir: Path to _agenttree directory
    """
    import subprocess
    from agenttree.config import load_config
    from agenttree.tmux import kill_session
    
    config = load_config()
    prefix = f"{config.project}-"
    
    # Get all tmux sessions
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        console.print("[dim]No tmux sessions running[/dim]")
        return
    
    sessions = result.stdout.strip().split("\n")
    stopped = 0
    
    for session in sessions:
        # Kill all sessions with our project prefix (except manager, handled separately)
        if session.startswith(prefix) and not session.endswith("-manager-000"):
            kill_session(session)
            stopped += 1
            console.print(f"[dim]Stopped {session}[/dim]")
    
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
    
    Args:
        agents_dir: Path to _agenttree directory
        threshold_min: Minutes before considering agent stalled
    """
    import yaml
    from datetime import datetime, timezone
    from agenttree.config import load_config
    from agenttree.issues import list_issues
    from agenttree.state import get_active_agent
    from agenttree.tmux import session_exists, send_message, is_claude_running
    
    config = load_config()
    parking_lot_stages = config.get_parking_lot_stages()
    manager_session = f"{config.project}-manager-000"
    
    issues = list_issues(sync=False)
    stalled: list[dict[str, Any]] = []
    dead: list[dict[str, Any]] = []
    
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
    
    # Write to stalled.yaml (always, even if empty - so manager knows state is fresh)
    stall_file = agents_dir / "stalled.yaml"
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
    
    # Check if manager is running before sending notification
    if not session_exists(manager_session):
        console.print("[dim]Manager not running, wrote stalled.yaml only[/dim]")
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
    
    lines.append("\nUse: agenttree start <id> --force (restart) or agenttree output <id> (diagnose)")
    
    message = "\n".join(lines)
    result = send_message(manager_session, message)
    
    if result == "sent":
        console.print(f"[dim]Wrote stalled.yaml, notified manager ({len(dead)} dead, {len(stalled)} stalled)[/dim]")


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

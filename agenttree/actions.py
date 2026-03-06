"""Action registry for AgentTree event system.

This module provides a registry mapping action names to functions.
Actions are executed by the event dispatcher when events fire.

Built-in Actions:
    - start_manager: Start the manager agent
    - ensure_stage_agents: Ensure agents running for active issues (safety net)
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

import re
from collections.abc import Callable
from pathlib import Path
import shlex
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
    from agenttree.api import start_controller, AgentAlreadyRunningError

    try:
        start_controller(quiet=True)
        console.print("[green]✓ Started manager agent[/green]")
    except AgentAlreadyRunningError:
        console.print("[dim]Manager already running[/dim]")


@register_action("ensure_stage_agents")
def ensure_stage_agents(agents_dir: Path, max_stage_age_min: int = 10, **kwargs: Any) -> None:
    """Ensure agents are running for issues that need them (heartbeat safety net).

    The primary mechanism is transition_issue() which starts agents inline.
    This heartbeat action catches anything that slipped through — e.g., server
    restart, crashed agent, or edge cases where the transition didn't start one.

    Sends a message (which auto-starts the agent if not running) for issues
    where the last stage transition was within max_stage_age_min minutes.

    Skips parking lots, human review stages, and manager stages.

    Args:
        agents_dir: Path to _agenttree directory
        max_stage_age_min: Only ensure if stage was entered within this many minutes
    """
    from datetime import datetime, timezone
    from agenttree.api import send_message
    from agenttree.config import load_config
    from agenttree.issues import list_issues
    from agenttree.tmux import session_exists

    config = load_config()

    if not config.manager.nudge_agents:
        return

    issues = list_issues(sync=False)
    ensured = 0
    now = datetime.now(timezone.utc)

    for issue in issues:
        if config.is_parking_lot(issue.stage):
            continue
        if config.is_human_review(issue.stage):
            continue

        role = config.role_for(issue.stage)
        if role == "manager":
            continue

        # Only ensure if the issue recently entered its current stage.
        # Old issues without agents are handled by the stall detector.
        if issue.history:
            last_entry = issue.history[-1]
            try:
                stage_start = datetime.fromisoformat(
                    last_entry.timestamp.replace("Z", "+00:00")
                )
                age_min = (now - stage_start).total_seconds() / 60
                if age_min > max_stage_age_min:
                    continue
            except (ValueError, TypeError):
                continue
        else:
            try:
                created = datetime.fromisoformat(
                    issue.created.replace("Z", "+00:00")
                )
                age_min = (now - created).total_seconds() / 60
                if age_min > max_stage_age_min:
                    continue
            except (ValueError, TypeError):
                continue

        session_name = config.get_issue_tmux_session(issue.id, role)
        if session_exists(session_name):
            continue

        console.print(f"[cyan]Ensuring agent for issue #{issue.id} ({issue.stage})...[/cyan]")
        try:
            result = send_message(
                issue.id,
                f"Stage is {issue.stage}. Run `agenttree next` for your instructions.",
                host=role,
                quiet=True,
            )
            if result in ("sent", "restarted"):
                console.print(f"[green]✓ Agent running for issue #{issue.id}[/green]")
                ensured += 1
            else:
                console.print(f"[yellow]Could not ensure agent for issue #{issue.id}: {result}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Failed to ensure agent for issue #{issue.id}: {e}[/yellow]")

    if ensured:
        console.print(f"[green]Ensured {ensured} agent(s)[/green]")


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
    from agenttree.environment import is_running_in_container
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
    threshold_min: int = 10,
    max_notifications: int = 3,
    **kwargs: Any
) -> None:
    """Check for issues where agents should be working but aren't progressing.

    Role-aware: uses config.role_for(stage) instead of hardcoding "developer".
    Skips parking lots, human review stages, and manager stages.
    Notifies manager up to max_notifications times per issue+stage, then stops.
    Tracks notification state in .heartbeat_state.yaml (stall_notifications key).

    Args:
        agents_dir: Path to _agenttree directory
        threshold_min: Minutes in same stage before first notification
        max_notifications: Max notifications per issue+stage (default 3)
    """
    from datetime import datetime, timezone
    from agenttree.config import load_config
    from agenttree.events import load_event_state, save_event_state
    from agenttree.issues import list_issues
    from agenttree.tmux import session_exists, send_message

    config = load_config()

    if not config.manager.nudge_agents:
        return

    manager_session = config.get_manager_tmux_session()

    issues = list_issues(sync=False)
    needs_attention: list[str] = []

    # Use dispatcher's state if available to avoid write-after-write race;
    # the dispatcher loads state, calls us, then saves — if we load/save
    # independently, the dispatcher's final save overwrites our changes.
    shared_state: dict[str, Any] | None = kwargs.get("_event_state")
    state: dict[str, Any] = shared_state if shared_state is not None else load_event_state(agents_dir)
    stall_state: dict[int | str, Any] = state.get("stall_notifications", {})
    now = datetime.now(timezone.utc)

    for issue in issues:
        # Skip parking lots (backlog, accepted, not_doing)
        if config.is_parking_lot(issue.stage):
            continue

        # Skip human review and manager stages
        role = config.role_for(issue.stage)
        if role == "manager":
            continue
        if config.is_human_review(issue.stage):
            continue

        # Compute time-in-stage from history
        if not issue.history:
            continue
        last_entry = issue.history[-1]
        try:
            stage_start = datetime.fromisoformat(
                last_entry.timestamp.replace("Z", "+00:00")
            )
            elapsed_min = int((now - stage_start).total_seconds() / 60)
        except (ValueError, TypeError):
            continue

        if elapsed_min < threshold_min:
            continue

        # Check if the correct role's agent is running
        session_name = config.get_issue_tmux_session(issue.id, role)
        agent_running = session_exists(session_name)

        if agent_running and elapsed_min < threshold_min * 2:
            # Agent is running, not stalled long enough for extra concern
            continue

        # Check notification state for this issue+stage
        issue_stall = stall_state.get(issue.id, {})
        prev_stage = issue_stall.get("stage")
        prev_count = issue_stall.get("count", 0)

        # Reset if stage changed
        if prev_stage != issue.stage:
            prev_count = 0

        # For running agents crossing threshold*2 for the first time,
        # treat as if one notification already sent so the next fires at 3x
        if agent_running and prev_count == 0:
            prev_count = 1

        if prev_count >= max_notifications:
            continue  # Already notified max times for this stage

        # Determine notification interval: notify at threshold_min, 2x, 3x
        next_notify_at = threshold_min * (prev_count + 1)
        if elapsed_min < next_notify_at:
            continue

        # Record this notification
        stall_state[issue.id] = {
            "stage": issue.stage,
            "count": prev_count + 1,
            "last_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        status = "dead" if not agent_running else "stalled"
        needs_attention.append(
            f"  #{issue.id}: {issue.title[:40]} — {status} at {issue.stage} ({elapsed_min}min)"
        )

    state["stall_notifications"] = stall_state
    if shared_state is None:
        save_event_state(agents_dir, state)

    if not needs_attention:
        return

    # Send a single informational message to manager
    if not session_exists(manager_session):
        console.print("[yellow]Manager not running, restarting...[/yellow]")
        start_manager(agents_dir)
        return

    lines = [
        "Issues may need attention. Run `agenttree status --active-only` to review.",
        "",
    ] + needs_attention

    result = send_message(manager_session, "\n".join(lines))
    if result == "sent":
        console.print(f"[dim]Notified manager about {len(needs_attention)} issue(s) needing attention[/dim]")


@register_action("ping_architect")
def ping_architect(agents_dir: Path, **kwargs: Any) -> None:
    """Send a periodic status reminder to the architect agent.

    Sends the current time and a checklist of things to check.
    Only sends if the architect tmux session is running.

    Args:
        agents_dir: Path to _agenttree directory
    """
    from datetime import datetime, timezone
    from agenttree.config import load_config
    from agenttree.tmux import session_exists, send_message

    config = load_config()
    session_name = config.get_role_tmux_session("architect")

    if not session_exists(session_name):
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = (
        f"[ARCHITECT HEARTBEAT — {now}]\n"
        f"Time to check on progress:\n"
        f"1. What stage is the current issue at? → agenttree status\n"
        f"2. Is the agent making progress? → agenttree output <id>\n"
        f"3. Is the manager running and healthy? → agenttree output 0\n"
        f"4. Any issues stuck or erroring?\n"
        f"5. If stuck, has the manager noticed? Give it a few minutes before intervening.\n"
        f"6. Log anything wrong to your architect log."
    )

    result = send_message(session_name, message)
    if result == "sent":
        console.print(f"[dim]Pinged architect[/dim]")


# =============================================================================
# Permission Prompt Detection
# =============================================================================

# Patterns that indicate Claude is waiting for permission approval.
# Claude Code shows tool name + command + "Allow" prompt when permissions needed.
PERMISSION_PROMPT_PATTERNS = [
    re.compile(r"Allow\s+(tool|this)\s+(call|action)", re.IGNORECASE),
    re.compile(r"\bAllow\?\s*\(?\s*[yYnNaA]", re.IGNORECASE),
    re.compile(r"Do you want to (allow|run|execute)", re.IGNORECASE),
    re.compile(r"Yes\s*/\s*No\s*/\s*Always", re.IGNORECASE),
    re.compile(r"\[y/n(/a)?\]", re.IGNORECASE),
    re.compile(r"\(y\s*=\s*yes", re.IGNORECASE),
]

# Commands that are safe to auto-approve (read-only or agenttree management).
# Each pattern is matched against the full command string.
SAFE_COMMAND_PATTERNS = [
    # Read-only git commands
    re.compile(r"^git\s+(status|log|diff|branch|show|rev-parse|ls-files|ls-tree|shortlog|describe|remote\s+-v)\b"),
    # Read-only file inspection
    re.compile(r"^(ls|cat|head|tail|find|grep|rg|wc|file|stat|du|tree)\b"),
    # Agenttree CLI (read-only commands)
    re.compile(r"^agenttree\s+(status|output|next|list|show)\b"),
    # Python/uv test and lint (safe, sandboxed)
    re.compile(r"^(uv\s+run\s+(pytest|mypy|ruff|pylint|flake8))\b"),
    # Read tool
    re.compile(r"^Read\b", re.IGNORECASE),
    # Glob/Grep tools
    re.compile(r"^(Glob|Grep)\b", re.IGNORECASE),
]

# Commands that are never safe to auto-approve.
UNSAFE_COMMAND_PATTERNS = [
    re.compile(r"\brm\s+-rf?\b"),
    re.compile(r"^git\s+(push\s+--force|reset\s+--hard|clean\s+-f)"),
    re.compile(r"^git\s+push\b.*--force"),
    re.compile(r"\b(curl|wget)\b.*\b(POST|PUT|DELETE|PATCH)\b", re.IGNORECASE),
]


def detect_permission_prompt(tmux_output: str) -> str | None:
    """Check if tmux output shows a permission prompt.

    Scans the last 20 lines for permission-related patterns.

    Args:
        tmux_output: Captured tmux pane content

    Returns:
        The matched line if a permission prompt is detected, None otherwise
    """
    lines = tmux_output.strip().split("\n")
    # Only check the last 20 lines (permission prompts appear at the bottom)
    recent_lines = lines[-20:]

    for line in reversed(recent_lines):
        stripped = line.strip()
        if not stripped:
            continue
        for pattern in PERMISSION_PROMPT_PATTERNS:
            if pattern.search(stripped):
                return stripped

    return None


def extract_command_from_output(tmux_output: str) -> str | None:
    """Extract the command/tool being requested from tmux output near a permission prompt.

    Looks for tool names and commands in the lines preceding the permission prompt.

    Args:
        tmux_output: Captured tmux pane content

    Returns:
        The extracted command string, or None if not found
    """
    lines = tmux_output.strip().split("\n")
    recent_lines = lines[-30:]

    # Look for common Claude Code patterns showing the tool/command
    tool_pattern = re.compile(r"(?:Bash|Command|Tool)[\s:]+(.+)", re.IGNORECASE)
    # Also match lines that look like shell commands (indented or after a box border)
    cmd_pattern = re.compile(r"^\s*[│|]\s*(.+?)\s*[│|]?\s*$")

    for line in reversed(recent_lines):
        stripped = line.strip()
        if not stripped:
            continue

        # Skip the permission prompt line itself
        is_prompt = False
        for pattern in PERMISSION_PROMPT_PATTERNS:
            if pattern.search(stripped):
                is_prompt = True
                break
        if is_prompt:
            continue

        # Try tool/command pattern
        match = tool_pattern.search(stripped)
        if match:
            return match.group(1).strip()

        # Try box-style command display
        match = cmd_pattern.match(stripped)
        if match:
            cmd = match.group(1).strip()
            # Verify it looks like an actual command (not decoration)
            if cmd and not all(c in "─═╭╮╰╯┌┐└┘" for c in cmd):
                return cmd

    return None


def is_safe_command(command: str) -> bool:
    """Determine if a command is safe to auto-approve.

    Checks against allowlist of safe (read-only) commands and blocklist
    of dangerous commands.

    Args:
        command: The command string to evaluate

    Returns:
        True if the command matches a safe pattern and no unsafe pattern
    """
    # Check unsafe patterns first — these always block
    for pattern in UNSAFE_COMMAND_PATTERNS:
        if pattern.search(command):
            return False

    # Check safe patterns
    for pattern in SAFE_COMMAND_PATTERNS:
        if pattern.search(command):
            return True

    return False


@register_action("check_permission_prompts")
def check_permission_prompts(agents_dir: Path, **kwargs: Any) -> None:
    """Check if manager or architect is stuck at a permission prompt.

    Deterministic heartbeat action that:
    1. Captures manager's tmux output
    2. Detects permission prompt patterns
    3. Extracts the requested command
    4. If safe: auto-approves by sending 'y' to the session
    5. If unsafe/unknown: pings architect to review and approve

    Args:
        agents_dir: Path to _agenttree directory
    """
    from agenttree.config import load_config
    from agenttree.tmux import session_exists, capture_pane, send_keys, send_message

    config = load_config()
    manager_session = config.get_role_tmux_session("manager")
    architect_session = config.get_role_tmux_session("architect")

    if not session_exists(manager_session):
        return

    # Capture manager's recent output
    output = capture_pane(manager_session, lines=40)
    if not output:
        return

    # Check for permission prompt
    prompt_line = detect_permission_prompt(output)
    if not prompt_line:
        return

    # Extract what command is being requested
    command = extract_command_from_output(output)
    command_desc = command or "unknown command"

    if command and is_safe_command(command):
        # Safe command — auto-approve by sending 'y'
        send_keys(manager_session, "y", submit=True, interrupt=False)
        console.print(f"[green]Auto-approved safe command for manager: {command_desc}[/green]")
    else:
        # Unsafe or unknown — ping architect to review
        if not session_exists(architect_session):
            console.print(f"[yellow]Manager stuck at permission prompt ({command_desc}) but architect not running[/yellow]")
            return

        message = (
            f"[PERMISSION CHECK] Manager is stuck at a permission prompt.\n"
            f"Command: {command_desc}\n"
            f"This command was NOT auto-approved (not in safe allowlist).\n"
            f"Please review: attach to manager with `agenttree attach manager` "
            f"and approve or deny the action."
        )
        result = send_message(architect_session, message)
        if result == "sent":
            console.print(f"[dim]Notified architect about manager permission prompt: {command_desc}[/dim]")


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


@register_action("trigger_cleanup")
def trigger_cleanup(
    agents_dir: Path,
    threshold: int = 10,
    **kwargs: Any
) -> None:
    """Create a cleanup issue when N issues have been accepted since last cleanup.

    Tracks accepted issue count in state file. When count reaches threshold,
    creates a cleanup issue with flow="cleanup" to review recent code reviews
    for deferred items and consolidation opportunities.

    Args:
        agents_dir: Path to _agenttree directory
        threshold: Number of accepted issues before triggering cleanup (default: 10)
    """
    from agenttree.events import load_event_state, save_event_state
    from agenttree.issues import list_issues, create_issue, Priority

    # Load state
    state = load_event_state(agents_dir)
    cleanup_state = state.get("cleanup_trigger", {})
    last_batch_end = cleanup_state.get("last_batch_end", 0)

    # Get all issues
    all_issues = list_issues(sync=False)

    # Check if there's already a cleanup issue in progress (not accepted)
    for issue in all_issues:
        if issue.flow == "cleanup" and issue.stage != "accepted":
            # Cleanup in progress, skip
            return

    # Count accepted issues with id > last_batch_end
    accepted_issues = [
        i for i in all_issues
        if i.stage == "accepted" and i.id > last_batch_end
    ]

    if len(accepted_issues) < threshold:
        # Not enough accepted issues yet
        return

    # Find the highest accepted issue ID in this batch
    new_batch_end = max(i.id for i in accepted_issues)

    # Build the issue range for the problem statement
    issue_ids = sorted(i.id for i in accepted_issues)
    first_id = min(issue_ids)

    # Create problem statement
    problem = f"""# Cleanup Batch: Issues #{first_id} - #{new_batch_end}

This is an automated cleanup issue created after {len(issue_ids)} issues were accepted.

## Your Task

1. **Research Phase**: Read the `review.md` and `independent_review.md` files for issues #{first_id} through #{new_batch_end}
2. **Look for**:
   - "Should Fix" items that were deferred
   - "Proposed Next Steps > Code Improvements" suggestions
   - Patterns indicating consolidation/DRY opportunities
3. **Plan and Implement**: Address the most impactful items found

## Issues to Review

"""
    for issue_id in issue_ids:
        problem += f"- Issue #{issue_id}\n"

    problem += """
## Notes

- If no actionable items are found, document this in your research and skip to accepted
- Focus on high-impact improvements over minor cleanups
- Group related changes together for cleaner PRs
"""

    # Create the cleanup issue
    create_issue(
        title=f"Cleanup batch #{first_id}-#{new_batch_end}",
        flow="cleanup",
        priority=Priority.LOW,
        problem=problem,
        stage="explore.research",
    )

    console.print(f"[green]Created cleanup issue for batch #{first_id}-#{new_batch_end}[/green]")

    # Update state
    cleanup_state["last_batch_end"] = new_batch_end
    state["cleanup_trigger"] = cleanup_state
    save_event_state(agents_dir, state)


# =============================================================================
# Rate Limit Fallback
# =============================================================================

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
    
    # Extract issue_id from session name (e.g., "agenttree-developer-128" -> 128)
    parts = session_name.split("-")
    if len(parts) < 3:
        return False
    try:
        issue_id = int(parts[-1])
    except ValueError:
        return False

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
    
    # Get API key via the canonical container_env method
    tool_config = config.get_tool_config(config.default_tool)
    api_key = tool_config.container_env(force_api_key=True).get("ANTHROPIC_API_KEY", "")
    
    claude_cmd = f"claude --model {model} --dangerously-skip-permissions"
    container_name = config.get_issue_container_name(issue_id)
    
    # Inject API key and unset OAuth token so Claude Code uses the API key
    shell_cmd = (
        f"export ANTHROPIC_API_KEY={shlex.quote(api_key)} "
        f"&& unset CLAUDE_CODE_OAUTH_TOKEN && {claude_cmd}"
    )
    exec_cmd = f"docker exec -it {container_name} sh -c '{shell_cmd}' 2>/dev/null || container exec -it {container_name} sh -c '{shell_cmd}'"
    
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
    try:
        issue_id = int(parts[-1])
    except ValueError:
        return False

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
                
                from agenttree.api import start_issue

                for agent_info in stored_agents:
                    issue_id = agent_info.get("issue_id")
                    if not issue_id:
                        continue

                    # Restart agent in subscription mode (without force_api_key)
                    try:
                        start_issue(issue_id, force=True, skip_preflight=True, quiet=True)
                        restarted += 1
                        console.print(f"[green]✓ Restarted agent #{issue_id} in subscription mode[/green]")
                    except Exception as e:
                        console.print(f"[yellow]Failed to restart agent #{issue_id}: {e}[/yellow]")
                
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

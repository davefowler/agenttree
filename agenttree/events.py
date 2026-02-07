"""Event-driven hook system for AgentTree.

This module provides an event dispatcher that fires events and executes
configured actions. Events are configured in .agenttree.yaml under the `on:` key.

Events:
    - startup: Fires once when `agenttree run` starts
    - shutdown: Fires when `agenttree shutdown` is called
    - heartbeat: Fires periodically (configurable interval)
    - stage_enter/stage_exit: Stage-specific, configured per-stage (unchanged)

Example config:
    on:
      startup:
        - start_controller
        - auto_start_agents
      
      heartbeat:
        interval_s: 10
        actions:
          - sync
          - check_stalled_agents: { min_interval_s: 60 }
          - check_ci_status: { min_interval_s: 120 }
          - check_merged_prs: { min_interval_s: 30 }
      
      shutdown:
        - sync
        - stop_all_agents

State is persisted in _agenttree/.hook_state.yaml for rate limiting across restarts.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

console = Console()

# Event types
STARTUP = "startup"
SHUTDOWN = "shutdown"
HEARTBEAT = "heartbeat"


def load_event_state(agents_dir: Path) -> dict[str, Any]:
    """Load event/hook state from _agenttree/.hook_state.yaml.
    
    Args:
        agents_dir: Path to _agenttree directory
        
    Returns:
        State dict, empty if file doesn't exist
    """
    state_file = agents_dir / ".hook_state.yaml"
    if state_file.exists():
        try:
            with open(state_file) as f:
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_event_state(agents_dir: Path, state: dict[str, Any]) -> None:
    """Save event/hook state to _agenttree/.hook_state.yaml.
    
    Args:
        agents_dir: Path to _agenttree directory
        state: State dict to save
    """
    state_file = agents_dir / ".hook_state.yaml"
    try:
        with open(state_file, "w") as f:
            yaml.dump(state, f, default_flow_style=False, sort_keys=False)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not save event state: {e}[/yellow]")


def check_action_rate_limit(
    action_name: str,
    action_config: dict[str, Any],
    state: dict[str, Any],
    heartbeat_count: int | None = None,
) -> tuple[bool, str]:
    """Check if a rate-limited action should run.
    
    Supports two rate limiting modes:
    - min_interval_s: Minimum seconds between runs
    - every_n: Only run every Nth heartbeat (count-based)
    
    Args:
        action_name: Identifier for this action
        action_config: Action configuration with optional rate limit settings
        state: State dict with last_run_at timestamps
        heartbeat_count: Current heartbeat count (for every_n)
        
    Returns:
        Tuple of (should_run, reason)
    """
    action_state = state.get(action_name, {})
    
    # Check time-based rate limit
    min_interval = action_config.get("min_interval_s")
    if min_interval:
        last_run = action_state.get("last_run_at")
        if last_run:
            try:
                last_run_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                elapsed = (datetime.now(timezone.utc) - last_run_dt).total_seconds()
                if elapsed < min_interval:
                    return False, f"Rate limited: {elapsed:.0f}s < {min_interval}s"
            except (ValueError, TypeError):
                pass  # Invalid timestamp, allow run
    
    # Check count-based rate limit (every_n)
    every_n = action_config.get("every_n")
    if every_n and heartbeat_count is not None:
        if heartbeat_count % every_n != 0:
            return False, f"Skipped: heartbeat #{heartbeat_count} (runs every {every_n})"
    
    # Legacy: run_every_n_syncs (backwards compatibility)
    run_every_n = action_config.get("run_every_n_syncs")
    if run_every_n and heartbeat_count is not None:
        if heartbeat_count % run_every_n != 0:
            return False, f"Skipped: sync #{heartbeat_count} (runs every {run_every_n})"
    
    return True, "Running"


def update_action_state(
    action_name: str,
    state: dict[str, Any],
    success: bool = True,
    error: str | None = None,
) -> None:
    """Update action state after running.
    
    Args:
        action_name: Identifier for this action
        state: State dict to update in place
        success: Whether the action succeeded
        error: Error message if failed
    """
    if action_name not in state:
        state[action_name] = {}
    
    action_state = state[action_name]
    action_state["last_run_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action_state["run_count"] = action_state.get("run_count", 0) + 1
    action_state["last_success"] = success
    
    if error:
        action_state["last_error"] = error
    elif "last_error" in action_state:
        del action_state["last_error"]


def parse_action_entry(
    entry: str | dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Parse an action entry from config into (name, config).
    
    Supports formats:
    - "action_name" -> ("action_name", {})
    - {"action_name": {}} -> ("action_name", {})
    - {"action_name": {"min_interval_s": 60}} -> ("action_name", {"min_interval_s": 60})
    
    Args:
        entry: Action entry from config
        
    Returns:
        Tuple of (action_name, config_dict)
    """
    if isinstance(entry, str):
        return entry, {}
    
    if isinstance(entry, dict):
        # The action name is the key
        for key, value in entry.items():
            if value is None:
                return key, {}
            if isinstance(value, dict):
                return key, value
            # Value might be a simple type - wrap it
            return key, {"value": value}
    
    return str(entry), {}


def fire_event(
    event: str,
    agents_dir: Path,
    verbose: bool = False,
    heartbeat_count: int | None = None,
) -> dict[str, Any]:
    """Fire an event and execute its configured actions.
    
    Reads the event configuration from .agenttree.yaml `on:` section
    and executes each action, respecting rate limits.
    
    Args:
        event: Event name (startup, shutdown, heartbeat)
        agents_dir: Path to _agenttree directory
        verbose: If True, print detailed output
        heartbeat_count: Current heartbeat iteration (for heartbeat events)
        
    Returns:
        Dict with results: {"success": bool, "actions_run": int, "errors": list}
    """
    from agenttree.actions import get_action, get_default_event_config
    from agenttree.config import load_config
    
    results: dict[str, Any] = {
        "success": True,
        "actions_run": 0,
        "actions_skipped": 0,
        "errors": [],
    }
    
    # Load config
    try:
        config = load_config()
        raw_config = config.model_dump() if hasattr(config, "model_dump") else {}
        # Note: .get("on", {}) returns None if key exists with None value
        on_config = raw_config.get("on") or {}
    except Exception as e:
        results["errors"].append(f"Failed to load config: {e}")
        results["success"] = False
        return results
    
    # Get event config (use defaults if not specified)
    event_config = on_config.get(event)
    if event_config is None:
        # Use default config for this event
        event_config = get_default_event_config(event)
    
    if event_config is None:
        # No config for this event, nothing to do
        if verbose:
            console.print(f"[dim]No config for event '{event}'[/dim]")
        return results
    
    # Parse event config - can be a list or a dict with 'actions' key
    actions: list[str | dict[str, Any]] = []
    
    if isinstance(event_config, list):
        # Simple list of actions
        actions = event_config
    elif isinstance(event_config, dict):
        # Dict with optional 'actions' key
        actions = event_config.get("actions", [])
        # If no 'actions' key, the dict itself might be actions
        if not actions:
            # Check if it looks like action entries
            for key in event_config:
                if key not in ("interval_s", "actions"):
                    # Treat as single action config
                    actions = [event_config]
                    break
    
    # Load state for rate limiting
    state = load_event_state(agents_dir)
    
    # Increment heartbeat count in state
    if event == HEARTBEAT:
        if heartbeat_count is None:
            heartbeat_count = state.get("_heartbeat_count", 0) + 1
        state["_heartbeat_count"] = heartbeat_count
    
    # Execute each action
    for entry in actions:
        action_name, action_config = parse_action_entry(entry)
        
        # Check rate limit
        should_run, reason = check_action_rate_limit(
            action_name, action_config, state, heartbeat_count
        )
        
        if not should_run:
            if verbose:
                console.print(f"[dim]{action_name}: {reason}[/dim]")
            results["actions_skipped"] += 1
            continue
        
        # Get the action function
        action_fn = get_action(action_name)
        if action_fn is None:
            error = f"Unknown action: {action_name}"
            results["errors"].append(error)
            if verbose:
                console.print(f"[yellow]Warning: {error}[/yellow]")
            continue
        
        # Execute the action
        try:
            if verbose:
                console.print(f"[dim]Running {action_name}...[/dim]")
            
            action_fn(agents_dir, **action_config)
            update_action_state(action_name, state, success=True)
            results["actions_run"] += 1
            
        except Exception as e:
            error = f"{action_name} failed: {e}"
            results["errors"].append(error)
            update_action_state(action_name, state, success=False, error=str(e))
            
            # Check if action is optional
            if action_config.get("optional", False):
                if verbose:
                    console.print(f"[yellow]Warning: {error} (optional)[/yellow]")
            else:
                results["success"] = False
                console.print(f"[red]Error: {error}[/red]")
    
    # Save updated state
    save_event_state(agents_dir, state)
    
    return results


def get_heartbeat_interval(agents_dir: Path | None = None) -> int:
    """Get the heartbeat interval from config.
    
    Args:
        agents_dir: Optional path to agents directory (unused, for API consistency)
        
    Returns:
        Heartbeat interval in seconds (default: 10)
    """
    from agenttree.config import load_config
    
    try:
        config = load_config()
        raw_config = config.model_dump() if hasattr(config, "model_dump") else {}
        on_config = raw_config.get("on", {})
        heartbeat_config = on_config.get("heartbeat", {})
        
        if isinstance(heartbeat_config, dict):
            return int(heartbeat_config.get("interval_s", 10))
        
        # Fall back to refresh_interval for backwards compatibility
        return getattr(config, "refresh_interval", 10)
        
    except Exception:
        return 10

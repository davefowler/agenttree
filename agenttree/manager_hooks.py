"""Manager hooks - configurable post-sync hooks for the agenttree manager.

DEPRECATION NOTICE:
    This module is deprecated in favor of the event-driven architecture.
    Configure hooks in .agenttree.yaml under `on:` instead of `manager_hooks:`.
    
    New config format:
        on:
          heartbeat:
            interval_s: 10
            actions:
              - sync
              - check_stalled_agents: { min_interval_s: 60 }
              - check_ci_status: { min_interval_s: 120 }
    
    Old config format (deprecated, still works):
        manager_hooks:
          post_sync:
            - push_pending_branches: {}
            - check_ci_status: { min_interval_s: 60 }

This module now delegates to the event system for backwards compatibility.
"""

import warnings
from pathlib import Path
from typing import Any

from rich.console import Console

# Import shared hook infrastructure (still needed for backwards compat)
from agenttree.hooks import (
    run_hook,
    load_hook_state,
    save_hook_state,
)

console = Console()

# Default hooks if not configured in .agenttree.yaml
# These are now also the default heartbeat actions in agenttree/actions.py
DEFAULT_POST_SYNC_HOOKS: list[dict[str, Any]] = [
    {"push_pending_branches": {}},
    {"check_manager_stages": {}},
    {"check_custom_agent_stages": {}},
    {"check_ci_status": {}},
    {"check_merged_prs": {}},
    {"check_stalled_agents": {"threshold_min": 15}},  # Nudge agents stalled >15 min
]


def run_post_manager_hooks(agents_dir: Path, verbose: bool = False) -> None:
    """Run all configured post-sync hooks.

    DEPRECATED: This function is deprecated. Use the event system instead:
    
        from agenttree.events import fire_event, HEARTBEAT
        fire_event(HEARTBEAT, agents_dir)
    
    This function now checks if the new `on:` config is present. If so,
    it skips running hooks (the event system will handle them).
    If only old `controller_hooks:` config is present, it runs the legacy hooks
    with a deprecation warning.

    Args:
        agents_dir: Path to _agenttree directory
        verbose: If True, print detailed output
    """
    from agenttree.config import load_config

    # Load hook configuration
    try:
        config = load_config()
        raw_config = config.model_dump() if hasattr(config, "model_dump") else {}
        
        # Check if new event config exists
        on_config = raw_config.get("on", {})
        if on_config and on_config.get("heartbeat"):
            # New config exists - don't run legacy hooks (event system handles it)
            if verbose:
                console.print("[dim]Using event system for heartbeat actions[/dim]")
            return
        
        # Check for legacy manager_hooks config
        hooks = raw_config.get("manager_hooks", {}).get("post_sync", None)
        
        if hooks is not None:
            # Emit deprecation warning for old config
            warnings.warn(
                "manager_hooks.post_sync is deprecated. "
                "Use on.heartbeat.actions instead. "
                "See docs for migration guide.",
                DeprecationWarning,
                stacklevel=2,
            )
            console.print(
                "[yellow]Warning: manager_hooks.post_sync is deprecated. "
                "Migrate to on.heartbeat.actions for better control.[/yellow]"
            )
    except Exception:
        hooks = None

    if hooks is None:
        hooks = DEFAULT_POST_SYNC_HOOKS

    # Load hook state (for rate limiting)
    state = load_hook_state(agents_dir)

    # Increment sync count (used by run_every_n_syncs rate limiting)
    sync_count = state.get("_sync_count", 0) + 1
    state["_sync_count"] = sync_count

    # Run each configured hook
    for hook_entry in hooks:
        # Normalize hook entry to dict format
        hook: dict[str, Any]
        if isinstance(hook_entry, str):
            hook = {hook_entry: {}}
        else:
            hook = hook_entry

        # Use unified run_hook with rate limiting
        errors, was_skipped = run_hook(
            hook=hook,
            context_dir=agents_dir,
            hook_state=state,
            sync_count=sync_count,
            verbose=verbose,
            # Pass agents_dir for manager hooks that need it
            agents_dir=agents_dir,
        )

        # Log errors (but don't raise - manager hooks shouldn't crash sync)
        if errors:
            for error in errors:
                console.print(f"[yellow]Warning: {error}[/yellow]")

    # Save updated state
    save_hook_state(agents_dir, state)


# Re-export for backwards compatibility and testing
# (these now come from hooks.py)
from agenttree.hooks import (
    check_rate_limit,
    update_hook_state,
)

# Legacy function aliases
load_sync_hook_state = load_hook_state
save_sync_hook_state = save_hook_state

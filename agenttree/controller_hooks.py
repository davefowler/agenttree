"""Controller hooks - configurable post-sync hooks for the agenttree controller.

This module provides the entry point for running controller hooks after sync.
It uses the unified hook system from agenttree.hooks.

Controller hooks are configured in .agenttree.yaml under `controller_hooks.post_sync`.
See agenttree/hooks.py for full documentation on hook configuration, base options,
and available hook types.

Quick example:
    controller_hooks:
      post_sync:
        - push_pending_branches: {}
        - check_controller_stages: {}
        - check_merged_prs: {}
        - check_ci_status:
            min_interval_s: 60
            run_every_n_syncs: 5
        - notify_slack:
            command: "curl -X POST $SLACK_WEBHOOK"
            min_interval_s: 300
            optional: true
"""

from pathlib import Path
from typing import Any

from rich.console import Console

# Import shared hook infrastructure
from agenttree.hooks import (
    run_hook,
    load_hook_state,
    save_hook_state,
)

console = Console()

# Default hooks if not configured in .agenttree.yaml
DEFAULT_POST_SYNC_HOOKS: list[dict[str, Any]] = [
    {"push_pending_branches": {}},
    {"check_controller_stages": {}},
    {"check_merged_prs": {}},
]


def run_post_controller_hooks(agents_dir: Path, verbose: bool = False) -> None:
    """Run all configured post-sync hooks.

    Reads hook config from .agenttree.yaml and executes each hook using
    the unified hook system. Supports all base hook options including
    rate limiting.

    Args:
        agents_dir: Path to _agenttree directory
        verbose: If True, print detailed output
    """
    from agenttree.config import load_config

    # Load hook configuration
    try:
        config = load_config()
        raw_config = config.model_dump() if hasattr(config, "model_dump") else {}
        hooks = raw_config.get("controller_hooks", {}).get("post_sync", None)
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
            # Pass agents_dir for controller hooks that need it
            agents_dir=agents_dir,
        )

        # Log errors (but don't raise - controller hooks shouldn't crash sync)
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

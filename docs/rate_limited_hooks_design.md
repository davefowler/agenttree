# Rate-Limited Hooks Design

## Problem

1. Some hooks (like CI status polling) shouldn't run on every sync - need rate limiting
2. Sync currently hardcodes which hooks to call - should be configurable in `.agenttree.yaml`

## Design Goals

- **Fully configurable** - All sync hooks defined in `.agenttree.yaml`, not hardcoded
- **Rate limiting options** - Time-based and/or count-based throttling
- **Extensible** - Easy to add custom hooks (shell commands, webhooks, etc.)
- **State management** - Track when hooks last ran for rate limiting

## Config Schema

```yaml
# .agenttree.yaml

controller_hooks:
  post_sync:
    # Built-in hooks (no command needed)
    - push_pending_branches:    # Always run (default)
    - check_controller_stages:  # Always run (default)
    - check_merged_prs:         # Always run (default)

    # Rate-limited hook
    - check_ci_status:
        min_interval_s: 60       # At least 60s between runs
        run_every_n_syncs: 5     # AND only every 5th sync

    # Custom shell command
    - notify_slack:
        command: "curl -X POST https://hooks.slack.com/... -d 'Sync complete'"
        min_interval_s: 300      # At most once per 5 minutes

    # Custom webhook
    - metrics_update:
        webhook: "https://my-server/api/sync-hook"
        min_interval_s: 60
```

## Rate Limiting Options

### `min_interval_s` (Time-based)

Hook won't run if last run was less than N seconds ago.

```yaml
- check_ci_status:
    min_interval_s: 60  # At most once per minute
```

### `run_every_n_syncs` (Count-based)

Hook only runs on every Nth sync.

```yaml
- check_ci_status:
    run_every_n_syncs: 10  # Only every 10th sync
```

### Combined (Both must pass)

```yaml
- check_ci_status:
    min_interval_s: 60      # At least 60s since last run
    run_every_n_syncs: 5    # AND only every 5th sync
```

Both conditions must pass for hook to run.

## Where to Store State

### Per-Issue State (for issue-specific hooks)

Store in `issue.yaml`:

```yaml
id: "088"
stage: pr_ready
# ... other fields ...

hook_state:
  check_ci_status:
    last_run_at: "2026-01-16T12:00:00Z"
    run_count: 15
    last_result: "pending"  # Optional: cache result
```

### Global State (for repo-wide hooks)

Store in `_agenttree/state.yaml`:

```yaml
agents: [...]
port_pool: {...}

hook_state:
  some_global_hook:
    last_run_at: "2026-01-16T12:00:00Z"
```

## Implementation

### 1. Sync Hook Runner

The sync function should read hooks from config and run them:

```python
# agenttree/controller_hooks.py

from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional
import subprocess
import yaml

from agenttree.config import load_config

# Registry of built-in hooks
BUILTIN_HOOKS = {
    "push_pending_branches": "agenttree.agents_repo:push_pending_branches",
    "check_controller_stages": "agenttree.agents_repo:check_controller_stages",
    "check_merged_prs": "agenttree.agents_repo:check_merged_prs",
    "check_ci_status": "agenttree.agents_repo:check_ci_status",
}

# Default hooks if not configured
DEFAULT_POST_SYNC_HOOKS = [
    {"push_pending_branches": {}},
    {"check_controller_stages": {}},
    {"check_merged_prs": {}},
]


def run_post_controller_hooks(agents_dir: Path) -> None:
    """Run all configured post-sync hooks.

    Reads hook config from .agenttree.yaml and executes each hook,
    respecting rate limits.
    """
    config = load_config()
    hooks = config.get("controller_hooks", {}).get("post_sync", DEFAULT_POST_SYNC_HOOKS)

    # Load global hook state
    state = load_sync_hook_state(agents_dir)

    for hook_entry in hooks:
        # Parse hook entry (can be string or dict)
        if isinstance(hook_entry, str):
            hook_name = hook_entry
            hook_config = {}
        else:
            # Dict with single key
            hook_name = list(hook_entry.keys())[0]
            hook_config = hook_entry[hook_name] or {}

        # Check rate limits
        should_run, reason = check_rate_limit(hook_name, hook_config, state)
        if not should_run:
            continue

        # Execute hook
        try:
            execute_hook(hook_name, hook_config, agents_dir)
            update_hook_state(hook_name, state, success=True)
        except Exception as e:
            print(f"Warning: Hook {hook_name} failed: {e}")
            update_hook_state(hook_name, state, success=False, error=str(e))

    # Save updated state
    save_sync_hook_state(agents_dir, state)


def check_rate_limit(
    hook_name: str,
    hook_config: dict,
    state: dict,
) -> tuple[bool, str]:
    """Check if a rate-limited hook should run.

    Returns:
        (should_run, reason)
    """
    hook_state = state.get(hook_name, {})

    # Check time-based rate limit
    min_interval = hook_config.get("min_interval_s")
    if min_interval:
        last_run = hook_state.get("last_run_at")
        if last_run:
            last_run_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - last_run_dt).total_seconds()
            if elapsed < min_interval:
                return False, f"Rate limited: {elapsed:.0f}s < {min_interval}s"

    # Check count-based rate limit
    run_every_n = hook_config.get("run_every_n_syncs")
    if run_every_n:
        # Use global sync count, not per-hook
        sync_count = state.get("_sync_count", 0)
        if sync_count % run_every_n != 0:
            return False, f"Skipped: sync #{sync_count} (runs every {run_every_n})"

    return True, "Running"


def execute_hook(hook_name: str, hook_config: dict, agents_dir: Path) -> None:
    """Execute a single hook."""
    # Custom command
    if "command" in hook_config:
        subprocess.run(
            hook_config["command"],
            shell=True,
            cwd=str(agents_dir.parent),  # Run from project root
            timeout=hook_config.get("timeout_s", 60),
        )
        return

    # Custom webhook
    if "webhook" in hook_config:
        import requests
        requests.post(
            hook_config["webhook"],
            json={"event": "post_sync", "hook": hook_name},
            timeout=hook_config.get("timeout_s", 30),
        )
        return

    # Built-in hook
    if hook_name in BUILTIN_HOOKS:
        module_path, func_name = BUILTIN_HOOKS[hook_name].rsplit(":", 1)
        import importlib
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        func(agents_dir)
        return

    raise ValueError(f"Unknown hook: {hook_name}")


def update_hook_state(
    hook_name: str,
    state: dict,
    success: bool = True,
    error: Optional[str] = None,
) -> None:
    """Update hook state after running."""
    if hook_name not in state:
        state[hook_name] = {}

    hook_state = state[hook_name]
    hook_state["last_run_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hook_state["run_count"] = hook_state.get("run_count", 0) + 1
    hook_state["last_success"] = success

    if error:
        hook_state["last_error"] = error


def load_sync_hook_state(agents_dir: Path) -> dict:
    """Load global sync hook state from _agenttree/.sync_hook_state.yaml"""
    state_file = agents_dir / ".sync_hook_state.yaml"
    if state_file.exists():
        with open(state_file) as f:
            return yaml.safe_load(f) or {}
    return {}


def save_sync_hook_state(agents_dir: Path, state: dict) -> None:
    """Save global sync hook state."""
    # Increment global sync count
    state["_sync_count"] = state.get("_sync_count", 0) + 1

    state_file = agents_dir / ".sync_hook_state.yaml"
    with open(state_file, "w") as f:
        yaml.dump(state, f, default_flow_style=False, sort_keys=False)
```

### 2. Update sync_agents_repo

Replace hardcoded calls with configurable hook runner:

```python
# agenttree/agents_repo.py

def sync_agents_repo(agents_dir: Path, pull_only: bool = False, ...) -> bool:
    # ... existing git sync logic ...

    # After successful sync, run configurable post-sync hooks
    from agenttree.controller_hooks import run_post_controller_hooks
    run_post_controller_hooks(agents_dir)

    return True
```

### 3. Per-Issue Hook State (for issue-specific hooks like CI polling)

For hooks that need per-issue state (like `check_ci_status`), store state in `issue.yaml`:

```yaml
# _agenttree/issues/088-ci-failure/issue.yaml

id: "088"
stage: pr_ready
pr_number: 456

hook_state:
  check_ci_status:
    last_run_at: "2026-01-16T12:00:00Z"
    run_count: 15
    last_result: "pending"
```

## Default Configuration

If no `controller_hooks` section in config, use sensible defaults:

```yaml
# Default behavior (equivalent to current hardcoded sync)
controller_hooks:
  post_sync:
    - push_pending_branches:
    - check_controller_stages:
    - check_merged_prs:
```

Users can add rate-limited or custom hooks:

```yaml
# User-customized
controller_hooks:
  post_sync:
    - push_pending_branches:
    - check_controller_stages:
    - check_merged_prs:
    - check_ci_status:
        min_interval_s: 60
        run_every_n_syncs: 5
    - notify_slack:
        command: "curl -X POST $SLACK_WEBHOOK"
        min_interval_s: 600
```

## Summary

**Recommended approach:**
1. All sync hooks configurable in `.agenttree.yaml` under `controller_hooks.post_sync`
2. Built-in hooks (`push_pending_branches`, `check_controller_stages`, etc.) available by name
3. Custom hooks via `command` (shell) or `webhook` (HTTP POST)
4. Rate limiting via `min_interval_s` and/or `run_every_n_syncs`
5. Global hook state in `_agenttree/.sync_hook_state.yaml`
6. Per-issue state in `issue.yaml` for issue-specific hooks

**Files to create/modify:**
- `agenttree/controller_hooks.py` - New module for hook execution
- `agenttree/agents_repo.py` - Replace hardcoded calls with `run_post_controller_hooks()`
- `agenttree/agents_repo.py` - Add `check_ci_status()` as a built-in hook
- `agenttree/github.py` - Add `get_pr_ci_status()`
- `.agenttree.yaml` - Document `controller_hooks` config section

## Related Issues

- **Issue #088**: CI failure feedback loop
- **Issue #089**: Hook performance & async execution (TODO: file)

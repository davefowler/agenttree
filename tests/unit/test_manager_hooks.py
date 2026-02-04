"""Unit tests for manager_hooks module.

Tests the configurable post-sync hook system including:
- Rate limiting (time-based and count-based)
- Hook state management
- Built-in and custom command hooks
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


class TestCheckRateLimit:
    """Test rate limiting logic."""

    def test_no_rate_limit_allows_run(self):
        """Hook without rate limit should always run."""
        from agenttree.manager_hooks import check_rate_limit

        should_run, reason = check_rate_limit("test_hook", {}, {})
        assert should_run is True
        assert reason == "Running"

    def test_time_based_rate_limit_blocks(self):
        """Hook should be blocked if min_interval_s hasn't passed."""
        from agenttree.manager_hooks import check_rate_limit

        # Last run was 30 seconds ago, but we want 60 seconds between runs
        now = datetime.now(timezone.utc)
        last_run = (now - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

        hook_config = {"min_interval_s": 60}
        state = {"test_hook": {"last_run_at": last_run}}

        should_run, reason = check_rate_limit("test_hook", hook_config, state)
        assert should_run is False
        assert "Rate limited" in reason

    def test_time_based_rate_limit_allows_after_interval(self):
        """Hook should run if min_interval_s has passed."""
        from agenttree.manager_hooks import check_rate_limit

        # Last run was 120 seconds ago, we want 60 seconds between runs
        now = datetime.now(timezone.utc)
        last_run = (now - timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%SZ")

        hook_config = {"min_interval_s": 60}
        state = {"test_hook": {"last_run_at": last_run}}

        should_run, reason = check_rate_limit("test_hook", hook_config, state)
        assert should_run is True

    def test_count_based_rate_limit_blocks(self):
        """Hook should be blocked if not on Nth sync."""
        from agenttree.manager_hooks import check_rate_limit

        hook_config = {"run_every_n_syncs": 5}
        state = {}
        sync_count = 3  # Not a multiple of 5

        should_run, reason = check_rate_limit("test_hook", hook_config, state, sync_count)
        assert should_run is False
        assert "runs every 5" in reason

    def test_count_based_rate_limit_allows_on_nth_sync(self):
        """Hook should run on every Nth sync."""
        from agenttree.manager_hooks import check_rate_limit

        hook_config = {"run_every_n_syncs": 5}
        state = {}
        sync_count = 10  # Multiple of 5

        should_run, reason = check_rate_limit("test_hook", hook_config, state, sync_count)
        assert should_run is True

    def test_combined_rate_limits_both_must_pass(self):
        """Both time and count rate limits must pass."""
        from agenttree.manager_hooks import check_rate_limit

        now = datetime.now(timezone.utc)
        last_run = (now - timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%SZ")

        hook_config = {"min_interval_s": 60, "run_every_n_syncs": 5}

        # Time passes but count fails
        state = {"test_hook": {"last_run_at": last_run}}
        should_run, _ = check_rate_limit("test_hook", hook_config, state, sync_count=3)
        assert should_run is False

        # Both pass
        state = {"test_hook": {"last_run_at": last_run}}
        should_run, _ = check_rate_limit("test_hook", hook_config, state, sync_count=10)
        assert should_run is True


class TestUpdateHookState:
    """Test hook state management."""

    def test_creates_hook_state_on_first_run(self):
        """State should be created for new hooks."""
        from agenttree.manager_hooks import update_hook_state

        state = {}
        update_hook_state("new_hook", state, success=True)

        assert "new_hook" in state
        assert state["new_hook"]["run_count"] == 1
        assert state["new_hook"]["last_success"] is True
        assert "last_run_at" in state["new_hook"]

    def test_increments_run_count(self):
        """Run count should increment on each run."""
        from agenttree.manager_hooks import update_hook_state

        state = {"existing_hook": {"run_count": 5}}
        update_hook_state("existing_hook", state, success=True)

        assert state["existing_hook"]["run_count"] == 6

    def test_records_error_on_failure(self):
        """Error should be recorded on failed runs."""
        from agenttree.manager_hooks import update_hook_state

        state = {}
        update_hook_state("failed_hook", state, success=False, error="Connection failed")

        assert state["failed_hook"]["last_success"] is False
        assert state["failed_hook"]["last_error"] == "Connection failed"

    def test_clears_error_on_success(self):
        """Error should be cleared on successful run."""
        from agenttree.manager_hooks import update_hook_state

        state = {"hook": {"last_error": "Previous error"}}
        update_hook_state("hook", state, success=True)

        assert "last_error" not in state["hook"]


class TestRunHook:
    """Test unified hook execution via run_hook."""

    def test_executes_custom_command(self, tmp_path):
        """Should execute shell commands via run hook."""
        from agenttree.hooks import run_hook

        # Create a test file to verify command ran
        test_file = tmp_path / "output.txt"
        hook = {"run": {"command": f"echo 'hello' > {test_file}"}}

        errors, was_skipped = run_hook(hook, tmp_path)

        assert test_file.exists()
        assert "hello" in test_file.read_text()
        assert errors == []
        assert was_skipped is False

    def test_returns_errors_on_command_failure(self, tmp_path):
        """Should return errors on failed commands."""
        from agenttree.hooks import run_hook

        hook = {"run": {"command": "exit 1"}}

        errors, was_skipped = run_hook(hook, tmp_path)

        assert len(errors) > 0
        assert was_skipped is False

    def test_executes_builtin_hook(self, tmp_path):
        """Should execute built-in hooks by importing and calling function."""
        from agenttree.hooks import run_hook

        with patch("agenttree.agents_repo.push_pending_branches") as mock_func:
            hook = {"push_pending_branches": {}}
            errors, was_skipped = run_hook(hook, tmp_path, agents_dir=tmp_path)
            mock_func.assert_called_once_with(tmp_path)
            assert errors == []

    def test_unknown_hook_is_silently_ignored(self, tmp_path):
        """Unknown hooks are silently ignored for forward compatibility."""
        from agenttree.hooks import run_hook

        hook = {"nonexistent_hook": {}}
        errors, was_skipped = run_hook(hook, tmp_path)

        # Unknown hooks don't cause errors (allows future extensions)
        assert errors == []
        assert was_skipped is False


class TestLoadSaveHookState:
    """Test state persistence."""

    def test_load_returns_empty_for_missing_file(self, tmp_path):
        """Should return empty dict if state file doesn't exist."""
        from agenttree.hooks import load_hook_state

        state = load_hook_state(tmp_path)
        assert state == {}

    def test_save_creates_state_file(self, tmp_path):
        """Should create state file with YAML content."""
        from agenttree.hooks import save_hook_state, load_hook_state

        state = {"test_hook": {"run_count": 3}, "_sync_count": 10}
        save_hook_state(tmp_path, state)

        state_file = tmp_path / ".hook_state.yaml"
        assert state_file.exists()

        loaded = load_hook_state(tmp_path)
        assert loaded["test_hook"]["run_count"] == 3
        assert loaded["_sync_count"] == 10


class TestRunPostControllerHooks:
    """Test the main hook runner."""

    def test_runs_default_hooks_when_not_configured(self, tmp_path):
        """Should run default hooks if manager_hooks not in config."""
        from agenttree.manager_hooks import run_post_manager_hooks

        # Create minimal agenttree structure
        (tmp_path / "issues").mkdir()

        with patch("agenttree.config.load_config") as mock_config:
            # Config without manager_hooks
            mock_cfg = MagicMock()
            mock_cfg.model_dump.return_value = {}
            mock_config.return_value = mock_cfg

            with patch("agenttree.agents_repo.push_pending_branches") as mock_push:
                with patch("agenttree.agents_repo.check_manager_stages") as mock_stages:
                    with patch("agenttree.agents_repo.check_merged_prs") as mock_prs:
                        run_post_manager_hooks(tmp_path)

                        mock_push.assert_called_once()
                        mock_stages.assert_called_once()
                        mock_prs.assert_called_once()

    def test_skips_rate_limited_hooks(self, tmp_path):
        """Should skip hooks that don't pass rate limits."""
        from agenttree.manager_hooks import run_post_manager_hooks, save_sync_hook_state

        (tmp_path / "issues").mkdir()

        # Pre-seed state with recent run
        now = datetime.now(timezone.utc)
        recent_run = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        save_sync_hook_state(tmp_path, {
            "rate_limited_hook": {"last_run_at": recent_run},
            "_sync_count": 0
        })

        with patch("agenttree.config.load_config") as mock_config:
            mock_cfg = MagicMock()
            mock_cfg.model_dump.return_value = {
                "manager_hooks": {
                    "post_sync": [
                        {"rate_limited_hook": {"min_interval_s": 300, "command": "echo 'should not run'"}}
                    ]
                }
            }
            mock_config.return_value = mock_cfg

            with patch("subprocess.run") as mock_run:
                run_post_manager_hooks(tmp_path, verbose=True)
                # Command should NOT have been called due to rate limit
                mock_run.assert_not_called()

    def test_increments_sync_count(self, tmp_path):
        """Should increment sync count on each run."""
        from agenttree.manager_hooks import run_post_manager_hooks, load_sync_hook_state

        (tmp_path / "issues").mkdir()

        with patch("agenttree.config.load_config") as mock_config:
            mock_cfg = MagicMock()
            mock_cfg.model_dump.return_value = {"manager_hooks": {"post_sync": []}}
            mock_config.return_value = mock_cfg

            # Run twice
            run_post_manager_hooks(tmp_path)
            run_post_manager_hooks(tmp_path)

            state = load_sync_hook_state(tmp_path)
            assert state["_sync_count"] == 2

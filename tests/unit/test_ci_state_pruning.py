"""Tests for CI state pruning functionality."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agenttree.events import prune_stale_ci_state, load_event_state, save_event_state


class TestPruneStaleState:
    """Tests for prune_stale_ci_state function."""

    def test_prune_removes_non_ci_stage_issues(self, tmp_path: Path) -> None:
        """Entries removed for issues at backlog/accepted stages."""
        agents_dir = tmp_path / "_agenttree"
        agents_dir.mkdir()

        # Create issue directories with stages
        issues_dir = agents_dir / "issues"

        # Issue 1: at backlog (should be pruned)
        (issues_dir / "001").mkdir(parents=True)
        (issues_dir / "001" / "issue.yaml").write_text(
            "id: 1\nstage: backlog\n"
        )

        # Issue 2: at accepted (should be pruned)
        (issues_dir / "002").mkdir(parents=True)
        (issues_dir / "002" / "issue.yaml").write_text(
            "id: 2\nstage: accepted\n"
        )

        # Issue 3: at ci_wait (should be kept)
        (issues_dir / "003").mkdir(parents=True)
        (issues_dir / "003" / "issue.yaml").write_text(
            "id: 3\nstage: implement.ci_wait\npr_number: 123\n"
        )

        # Create state with entries for all issues
        state = {
            "ci_checks": {
                1: {"fingerprint": "abc", "last_status": "success"},
                2: {"fingerprint": "def", "last_status": "success"},
                3: {"fingerprint": "ghi", "last_status": "pending"},
            }
        }
        (agents_dir / ".heartbeat_state.yaml").write_text(yaml.dump(state))

        # Prune
        prune_stale_ci_state(agents_dir)

        # Verify
        new_state = load_event_state(agents_dir)
        assert 1 not in new_state.get("ci_checks", {})
        assert 2 not in new_state.get("ci_checks", {})
        assert 3 in new_state.get("ci_checks", {})

    def test_prune_keeps_ci_stage_issues(self, tmp_path: Path) -> None:
        """Entries kept for issues at ci_wait/review stages."""
        agents_dir = tmp_path / "_agenttree"
        agents_dir.mkdir()

        issues_dir = agents_dir / "issues"

        # Issue at ci_wait
        (issues_dir / "001").mkdir(parents=True)
        (issues_dir / "001" / "issue.yaml").write_text(
            "id: 1\nstage: implement.ci_wait\npr_number: 123\n"
        )

        # Issue at review
        (issues_dir / "002").mkdir(parents=True)
        (issues_dir / "002" / "issue.yaml").write_text(
            "id: 2\nstage: implement.review\npr_number: 456\n"
        )

        state = {
            "ci_checks": {
                1: {"fingerprint": "abc", "last_status": "pending"},
                2: {"fingerprint": "def", "last_status": "failure"},
            }
        }
        (agents_dir / ".heartbeat_state.yaml").write_text(yaml.dump(state))

        prune_stale_ci_state(agents_dir)

        new_state = load_event_state(agents_dir)
        assert 1 in new_state.get("ci_checks", {})
        assert 2 in new_state.get("ci_checks", {})

    def test_prune_handles_missing_issues(self, tmp_path: Path) -> None:
        """Pruning gracefully handles deleted issues."""
        agents_dir = tmp_path / "_agenttree"
        agents_dir.mkdir()

        issues_dir = agents_dir / "issues"
        issues_dir.mkdir()

        # State references issue that doesn't exist
        state = {
            "ci_checks": {
                999: {"fingerprint": "orphan", "last_status": "success"},
            }
        }
        (agents_dir / ".heartbeat_state.yaml").write_text(yaml.dump(state))

        # Should not raise
        prune_stale_ci_state(agents_dir)

        # Orphaned entry should be removed
        new_state = load_event_state(agents_dir)
        assert 999 not in new_state.get("ci_checks", {})

    def test_prune_handles_empty_state(self, tmp_path: Path) -> None:
        """Pruning handles empty or missing state file."""
        agents_dir = tmp_path / "_agenttree"
        agents_dir.mkdir()

        (agents_dir / "issues").mkdir()

        # No state file
        prune_stale_ci_state(agents_dir)  # Should not raise

        # Empty state file
        (agents_dir / ".heartbeat_state.yaml").write_text("")
        prune_stale_ci_state(agents_dir)  # Should not raise

    def test_stall_notifications_also_pruned(self, tmp_path: Path) -> None:
        """Existing stall_notifications also pruned for terminal issues."""
        agents_dir = tmp_path / "_agenttree"
        agents_dir.mkdir()

        issues_dir = agents_dir / "issues"

        # Issue 1: at accepted (terminal)
        (issues_dir / "001").mkdir(parents=True)
        (issues_dir / "001" / "issue.yaml").write_text(
            "id: 1\nstage: accepted\n"
        )

        # Issue 2: at implement.code (active)
        (issues_dir / "002").mkdir(parents=True)
        (issues_dir / "002" / "issue.yaml").write_text(
            "id: 2\nstage: implement.code\n"
        )

        state = {
            "ci_checks": {
                1: {"fingerprint": "abc", "last_status": "success"},
            },
            "stall_notifications": {
                1: {"stage": "accepted", "count": 3},
                2: {"stage": "implement.code", "count": 1},
            }
        }
        (agents_dir / ".heartbeat_state.yaml").write_text(yaml.dump(state))

        prune_stale_ci_state(agents_dir)

        new_state = load_event_state(agents_dir)
        # ci_checks for terminal issue should be pruned
        assert 1 not in new_state.get("ci_checks", {})
        # stall_notifications for terminal issue should also be pruned
        assert 1 not in new_state.get("stall_notifications", {})
        # Active issue should be kept
        assert 2 in new_state.get("stall_notifications", {})

    def test_prune_preserves_other_state(self, tmp_path: Path) -> None:
        """Pruning preserves other heartbeat state fields."""
        agents_dir = tmp_path / "_agenttree"
        agents_dir.mkdir()
        (agents_dir / "issues").mkdir()

        state = {
            "ci_checks": {},
            "_heartbeat_count": 100,
            "_sync_count": 50,
            "check_ci_status": {
                "last_run_at": "2026-03-07T12:00:00Z",
                "run_count": 10,
            },
        }
        (agents_dir / ".heartbeat_state.yaml").write_text(yaml.dump(state))

        prune_stale_ci_state(agents_dir)

        new_state = load_event_state(agents_dir)
        assert new_state.get("_heartbeat_count") == 100
        assert new_state.get("_sync_count") == 50
        assert "check_ci_status" in new_state


class TestNoDuplicateNotifications:
    """Tests verifying no duplicate notifications across restarts."""

    def test_fingerprint_persistence_prevents_duplicates(self, tmp_path: Path) -> None:
        """Fingerprint persistence prevents duplicate notifications."""
        agents_dir = tmp_path / "_agenttree"
        agents_dir.mkdir()

        # Simulate: fingerprint saved after first notification
        fingerprint = "abc123"
        state = {
            "ci_checks": {
                1: {
                    "fingerprint": fingerprint,
                    "last_status": "failure",
                    "last_alert_at": "2026-03-07T12:00:00Z",
                }
            }
        }
        save_event_state(agents_dir, state)

        # Simulate restart: load state
        loaded_state = load_event_state(agents_dir)

        # Fingerprint should be preserved
        assert loaded_state["ci_checks"][1]["fingerprint"] == fingerprint

        # If we compute same fingerprint, no notification needed
        # (the check_ci_status function would compare and skip)

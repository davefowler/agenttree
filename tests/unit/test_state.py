"""Tests for agenttree.state module with file locking."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from agenttree.state import (
    load_state,
    save_state,
    get_port_for_issue,
    register_agent,
    unregister_agent,
    ActiveAgent,
)


class TestDeterministicPorts:
    """Tests for deterministic port allocation from issue ID."""

    def test_get_port_for_issue_basic(self):
        """Port should be base + issue_id % 1000."""
        assert get_port_for_issue("001", base_port=9000) == 9001
        assert get_port_for_issue("023", base_port=9000) == 9023
        assert get_port_for_issue("100", base_port=9000) == 9100
        assert get_port_for_issue("999", base_port=9000) == 9999

    def test_get_port_for_issue_modulo_wrapping(self):
        """Issues over 1000 should wrap around."""
        # Issue 1001 should get same port as issue 1
        assert get_port_for_issue("1001", base_port=9000) == 9001
        assert get_port_for_issue("1023", base_port=9000) == 9023
        assert get_port_for_issue("2045", base_port=9000) == 9045

    def test_get_port_for_issue_custom_base(self):
        """Should work with different base ports."""
        assert get_port_for_issue("023", base_port=3000) == 3023
        assert get_port_for_issue("023", base_port=8000) == 8023
        assert get_port_for_issue("023", base_port=10000) == 10023

    def test_get_port_for_issue_string_parsing(self):
        """Should handle both padded and unpadded issue IDs."""
        # Leading zeros shouldn't matter
        assert get_port_for_issue("023", base_port=9000) == 9023
        assert get_port_for_issue("23", base_port=9000) == 9023

    def test_port_determinism(self):
        """Same issue ID should always return same port."""
        for _ in range(100):
            assert get_port_for_issue("042", base_port=9000) == 9042


class TestStateLocking:
    """Tests for state file locking to prevent race conditions."""

    def test_concurrent_register_unregister_agents(self, tmp_path, monkeypatch):
        """Concurrent agent registration and unregistration should not corrupt state."""
        state_file = tmp_path / "_agenttree" / "state.yaml"
        monkeypatch.setattr("agenttree.state.get_state_path", lambda: state_file)

        lock_file = tmp_path / "_agenttree" / "state.yaml.lock"
        if hasattr(__import__("agenttree.state", fromlist=["get_state_lock_path"]), "get_state_lock_path"):
            monkeypatch.setattr("agenttree.state.get_state_lock_path", lambda: lock_file)

        errors = []

        def register_and_unregister(issue_id: str):
            try:
                # Use deterministic port from issue ID
                port = get_port_for_issue(issue_id, base_port=9000)
                agent = ActiveAgent(
                    issue_id=issue_id,
                    host="agent",
                    container=f"container-{issue_id}",
                    worktree=Path(f"/tmp/worktree-{issue_id}"),
                    branch=f"branch-{issue_id}",
                    port=port,
                    tmux_session=f"session-{issue_id}",
                    started="2024-01-01T00:00:00Z",
                )
                register_agent(agent)
                time.sleep(0.01)  # Small delay to increase race window
                unregister_agent(issue_id, "agent")
            except Exception as e:
                errors.append(f"{issue_id}: {str(e)}")

        # Run operations concurrently
        num_agents = 5
        with ThreadPoolExecutor(max_workers=num_agents) as executor:
            futures = [executor.submit(register_and_unregister, f"{i:03d}") for i in range(1, num_agents + 1)]
            for future in as_completed(futures):
                future.result()

        assert len(errors) == 0, f"Errors occurred: {errors}"

        # Verify state is clean (all agents unregistered)
        state = load_state()
        assert state.get("active_agents", {}) == {}, f"Expected no active agents, got {state.get('active_agents')}"

    def test_save_state_creates_parent_directory(self, tmp_path, monkeypatch):
        """save_state should create parent directories if they don't exist."""
        state_file = tmp_path / "nested" / "dir" / "state.yaml"
        monkeypatch.setattr("agenttree.state.get_state_path", lambda: state_file)

        lock_file = tmp_path / "nested" / "dir" / "state.yaml.lock"
        if hasattr(__import__("agenttree.state", fromlist=["get_state_lock_path"]), "get_state_lock_path"):
            monkeypatch.setattr("agenttree.state.get_state_lock_path", lambda: lock_file)

        test_state = {"active_agents": {}}
        save_state(test_state)

        assert state_file.exists()
        loaded = load_state()
        assert loaded == test_state

    def test_load_state_returns_default_when_file_missing(self, tmp_path, monkeypatch):
        """load_state should return default state when file doesn't exist."""
        state_file = tmp_path / "_agenttree" / "state.yaml"
        monkeypatch.setattr("agenttree.state.get_state_path", lambda: state_file)

        state = load_state()

        assert "active_agents" in state
        assert state["active_agents"] == {}


class TestStateLockPath:
    """Tests for lock file path function."""

    def test_get_state_lock_path_exists(self):
        """get_state_lock_path function should exist after implementation."""
        try:
            from agenttree.state import get_state_lock_path
            lock_path = get_state_lock_path()
            assert lock_path.name == "state.yaml.lock"
        except ImportError:
            pytest.skip("get_state_lock_path not yet implemented")

    def test_lock_path_is_sibling_of_state_path(self):
        """Lock file should be in same directory as state file."""
        try:
            from agenttree.state import get_state_lock_path, get_state_path
            lock_path = get_state_lock_path()
            state_path = get_state_path()
            assert lock_path.parent == state_path.parent
        except ImportError:
            pytest.skip("get_state_lock_path not yet implemented")

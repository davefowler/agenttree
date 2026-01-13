"""Tests for agenttree.state module with file locking."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from agenttree.state import (
    load_state,
    save_state,
    allocate_port,
    free_port,
    register_agent,
    unregister_agent,
    ActiveAgent,
)


class TestStateLocking:
    """Tests for state file locking to prevent race conditions."""

    def test_concurrent_port_allocation_returns_unique_ports(self, tmp_path, monkeypatch):
        """Multiple threads allocating ports simultaneously should get unique ports.

        This is the core race condition test. Without locking, concurrent allocations
        could return the same port number.
        """
        # Setup: use temp directory for state file
        state_file = tmp_path / ".agenttree" / "state.yaml"
        monkeypatch.setattr("agenttree.state.get_state_path", lambda: state_file)

        # Also patch the lock path to use temp directory
        lock_file = tmp_path / ".agenttree" / "state.yaml.lock"
        if hasattr(__import__("agenttree.state", fromlist=["get_state_lock_path"]), "get_state_lock_path"):
            monkeypatch.setattr("agenttree.state.get_state_lock_path", lambda: lock_file)

        num_threads = 10
        allocated_ports = []
        errors = []

        def allocate_and_record():
            try:
                port = allocate_port(base_port=3000)
                allocated_ports.append(port)
            except Exception as e:
                errors.append(str(e))

        # Run allocations concurrently
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(allocate_and_record) for _ in range(num_threads)]
            for future in as_completed(futures):
                future.result()  # Raise any exceptions

        # Verify: all ports should be unique
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(allocated_ports) == num_threads, f"Expected {num_threads} ports, got {len(allocated_ports)}"
        assert len(set(allocated_ports)) == num_threads, f"Duplicate ports found: {allocated_ports}"

        # Verify ports are sequential starting from 3001
        expected_ports = set(range(3001, 3001 + num_threads))
        assert set(allocated_ports) == expected_ports, f"Expected {expected_ports}, got {set(allocated_ports)}"

    def test_concurrent_register_unregister_agents(self, tmp_path, monkeypatch):
        """Concurrent agent registration and unregistration should not corrupt state."""
        state_file = tmp_path / ".agenttree" / "state.yaml"
        monkeypatch.setattr("agenttree.state.get_state_path", lambda: state_file)

        lock_file = tmp_path / ".agenttree" / "state.yaml.lock"
        if hasattr(__import__("agenttree.state", fromlist=["get_state_lock_path"]), "get_state_lock_path"):
            monkeypatch.setattr("agenttree.state.get_state_lock_path", lambda: lock_file)

        errors = []

        def register_and_unregister(issue_id: str):
            try:
                agent = ActiveAgent(
                    issue_id=issue_id,
                    container=f"container-{issue_id}",
                    worktree=Path(f"/tmp/worktree-{issue_id}"),
                    branch=f"branch-{issue_id}",
                    port=3000 + int(issue_id),
                    tmux_session=f"session-{issue_id}",
                    started="2024-01-01T00:00:00Z",
                )
                register_agent(agent)
                time.sleep(0.01)  # Small delay to increase race window
                unregister_agent(issue_id)
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

        test_state = {"active_agents": {}, "port_pool": {"base": 3000, "allocated": []}}
        save_state(test_state)

        assert state_file.exists()
        loaded = load_state()
        assert loaded == test_state

    def test_load_state_returns_default_when_file_missing(self, tmp_path, monkeypatch):
        """load_state should return default state when file doesn't exist."""
        state_file = tmp_path / ".agenttree" / "state.yaml"
        monkeypatch.setattr("agenttree.state.get_state_path", lambda: state_file)

        state = load_state()

        assert "active_agents" in state
        assert "port_pool" in state
        assert state["active_agents"] == {}

    def test_allocate_port_starts_from_base_plus_one(self, tmp_path, monkeypatch):
        """allocate_port should return base_port + 1 for first allocation."""
        state_file = tmp_path / ".agenttree" / "state.yaml"
        monkeypatch.setattr("agenttree.state.get_state_path", lambda: state_file)

        lock_file = tmp_path / ".agenttree" / "state.yaml.lock"
        if hasattr(__import__("agenttree.state", fromlist=["get_state_lock_path"]), "get_state_lock_path"):
            monkeypatch.setattr("agenttree.state.get_state_lock_path", lambda: lock_file)

        port = allocate_port(base_port=5000)
        assert port == 5001

    def test_free_port_removes_from_allocated(self, tmp_path, monkeypatch):
        """free_port should remove port from allocated list."""
        state_file = tmp_path / ".agenttree" / "state.yaml"
        monkeypatch.setattr("agenttree.state.get_state_path", lambda: state_file)

        lock_file = tmp_path / ".agenttree" / "state.yaml.lock"
        if hasattr(__import__("agenttree.state", fromlist=["get_state_lock_path"]), "get_state_lock_path"):
            monkeypatch.setattr("agenttree.state.get_state_lock_path", lambda: lock_file)

        # Allocate then free
        port = allocate_port(base_port=3000)
        assert port == 3001

        free_port(port)

        # Next allocation should reuse the freed port
        next_port = allocate_port(base_port=3000)
        assert next_port == 3001


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

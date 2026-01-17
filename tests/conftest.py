"""Pytest configuration and fixtures for agenttree tests.

Sets AGENTTREE_CONTAINER=1 by default so tests simulate running inside a container.
This prevents tests from attempting remote git operations, PR creation, etc.
"""

import os
import pytest


@pytest.fixture(autouse=True)
def simulate_container_environment(monkeypatch):
    """Set container environment for all tests by default.

    This ensures consistent behavior - tests won't try to push to remote,
    create PRs, or do other host-only operations.
    """
    monkeypatch.setenv("AGENTTREE_CONTAINER", "1")


@pytest.fixture
def host_environment(monkeypatch):
    """Fixture to simulate running on host (not in container).

    Use this fixture for tests that specifically need to test host behavior:

        def test_pr_creation(host_environment):
            # This test will run as if on host
            ...

    Note: This also patches is_running_in_container() because the test runner
    itself may be in a container (e.g., cloud agent environment with /.dockerenv).
    """
    monkeypatch.delenv("AGENTTREE_CONTAINER", raising=False)
    # Patch is_running_in_container to return False since the test environment
    # itself may be a container (/.dockerenv exists)
    monkeypatch.setattr("agenttree.hooks.is_running_in_container", lambda: False)

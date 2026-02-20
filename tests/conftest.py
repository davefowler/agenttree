"""Pytest configuration and fixtures for agenttree tests.

Sets AGENTTREE_CONTAINER=1 by default so tests simulate running inside a container.
This prevents tests from attempting remote git operations, PR creation, etc.
"""

import os
import pytest
from click.testing import CliRunner


@pytest.fixture(autouse=True)
def simulate_container_environment(monkeypatch):
    """Set container environment for all tests by default.

    This ensures consistent behavior - tests won't try to push to remote,
    create PRs, or do other host-only operations.
    """
    monkeypatch.setenv("AGENTTREE_CONTAINER", "1")


@pytest.fixture(autouse=True)
def _clear_module_caches():
    """Clear module-level caches between tests to prevent cross-test pollution."""
    from agenttree.issues import invalidate_issues_cache
    invalidate_issues_cache()
    yield
    invalidate_issues_cache()


@pytest.fixture
def host_environment(monkeypatch):
    """Fixture to simulate running on host (not in container).

    Use this fixture for tests that specifically need to test host behavior:

        def test_pr_creation(host_environment):
            # This test will run as if on host
            ...

    This fixture both removes the env var AND patches is_running_in_container
    to return False. The patch is needed because tests may run in actual Docker
    containers (like CI or cursor's cloud agent) where /.dockerenv exists.
    """
    monkeypatch.delenv("AGENTTREE_CONTAINER", raising=False)
    # Also patch the function directly for environments where /.dockerenv exists
    monkeypatch.setattr("agenttree.hooks.is_running_in_container", lambda: False)


@pytest.fixture
def cli_runner():
    """Create a Click test runner."""
    return CliRunner()

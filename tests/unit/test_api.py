"""Tests for agenttree.api module.

The API module centralizes high-level operations like stop_agent,
cleanup_containers, etc. that coordinate between tmux/container/config.
"""

import json
import subprocess
from unittest.mock import patch, MagicMock, call

import pytest

from agenttree.api import (
    stop_agent,
    stop_all_agents_for_issue,
    cleanup_orphaned_containers,
    cleanup_all_agenttree_containers,
    cleanup_all_with_retry,
)


class TestStopAgent:
    """Tests for stop_agent function."""

    def test_stop_agent_kills_tmux_and_container(self):
        """stop_agent should kill tmux session and stop/delete container using config names."""
        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.get_issue_tmux_session.return_value = "myproject-developer-042"
        mock_config.get_issue_container_name.return_value = "agenttree-myproject-042"

        mock_runtime = MagicMock()
        mock_runtime.runtime = "container"
        mock_runtime.stop.return_value = True
        mock_runtime.delete.return_value = True

        with patch("agenttree.api.load_config", return_value=mock_config), \
             patch("agenttree.api.session_exists", return_value=True), \
             patch("agenttree.api.kill_session") as mock_kill, \
             patch("agenttree.api.get_container_runtime", return_value=mock_runtime):

            result = stop_agent("042", "developer", quiet=True)

        assert result is True
        # Verify tmux session was killed using config method
        mock_config.get_issue_tmux_session.assert_called_with("042", "developer")
        mock_kill.assert_any_call("myproject-developer-042")

        # Verify container was stopped/deleted using config method
        mock_config.get_issue_container_name.assert_called_with("042")
        mock_runtime.stop.assert_called_with("agenttree-myproject-042")
        mock_runtime.delete.assert_called_with("agenttree-myproject-042")

    def test_stop_agent_handles_no_session(self):
        """stop_agent should gracefully handle when tmux session doesn't exist."""
        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.get_issue_tmux_session.return_value = "myproject-developer-042"
        mock_config.get_issue_container_name.return_value = "agenttree-myproject-042"

        mock_runtime = MagicMock()
        mock_runtime.runtime = "container"
        mock_runtime.stop.return_value = True
        mock_runtime.delete.return_value = True

        with patch("agenttree.api.load_config", return_value=mock_config), \
             patch("agenttree.api.session_exists", return_value=False), \
             patch("agenttree.api.kill_session") as mock_kill, \
             patch("agenttree.api.get_container_runtime", return_value=mock_runtime):

            result = stop_agent("042", "developer", quiet=True)

        # Should still attempt container cleanup
        assert result is True
        # Should not attempt to kill session
        mock_kill.assert_not_called()
        # Should still stop/delete container
        mock_runtime.stop.assert_called_with("agenttree-myproject-042")
        mock_runtime.delete.assert_called_with("agenttree-myproject-042")

    def test_stop_agent_handles_no_container(self):
        """stop_agent should gracefully handle when container doesn't exist."""
        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.get_issue_tmux_session.return_value = "myproject-developer-042"
        mock_config.get_issue_container_name.return_value = "agenttree-myproject-042"

        mock_runtime = MagicMock()
        mock_runtime.runtime = None  # No container runtime

        with patch("agenttree.api.load_config", return_value=mock_config), \
             patch("agenttree.api.session_exists", return_value=True), \
             patch("agenttree.api.kill_session") as mock_kill, \
             patch("agenttree.api.get_container_runtime", return_value=mock_runtime):

            result = stop_agent("042", "developer", quiet=True)

        assert result is True  # Still returns True because tmux was stopped
        # Should kill tmux session
        mock_kill.assert_called_with("myproject-developer-042")
        # Should not attempt container operations
        mock_runtime.stop.assert_not_called()
        mock_runtime.delete.assert_not_called()


class TestStopAllAgentsForIssue:
    """Tests for stop_all_agents_for_issue function."""

    def test_stop_all_agents_for_issue(self):
        """stop_all_agents_for_issue should find all role sessions and stop each."""
        mock_agents = [
            MagicMock(issue_id="042", role="developer"),
            MagicMock(issue_id="042", role="reviewer"),
        ]

        with patch("agenttree.state.get_active_agents_for_issue", return_value=mock_agents), \
             patch("agenttree.api.stop_agent", return_value=True) as mock_stop:

            result = stop_all_agents_for_issue("042", quiet=True)

        assert result == 2
        mock_stop.assert_has_calls([
            call("042", "developer", True),
            call("042", "reviewer", True),
        ])


class TestCleanupOrphanedContainers:
    """Tests for cleanup_orphaned_containers function."""

    def test_cleanup_orphaned_containers(self):
        """cleanup_orphaned_containers should stop containers without tmux sessions using runtime abstraction."""
        mock_config = MagicMock()
        mock_config.project = "myproject"
        mock_config.get_issue_tmux_session.side_effect = lambda issue_id, role: f"myproject-{role}-{issue_id}"

        mock_containers = [
            {"name": "agenttree-myproject-042", "id": "container1"},
            {"name": "agenttree-myproject-043", "id": "container2"},
            {"name": "other-container", "id": "container3"},  # Should be ignored
        ]

        mock_runtime = MagicMock()
        mock_runtime.runtime = "container"
        mock_runtime.list_all.return_value = mock_containers

        def session_exists_side_effect(session_name):
            # Only issue 043 has an active tmux session
            return session_name == "myproject-developer-043"

        with patch("agenttree.api.load_config", return_value=mock_config), \
             patch("agenttree.api.get_container_runtime", return_value=mock_runtime), \
             patch("agenttree.api.session_exists", side_effect=session_exists_side_effect):

            result = cleanup_orphaned_containers(quiet=True)

        assert result == 1  # Only container 042 should be cleaned up
        # Should stop and delete only the orphaned container (using container ID)
        mock_runtime.stop.assert_called_once_with("container1")
        mock_runtime.delete.assert_called_once_with("container1")

    def test_cleanup_orphaned_skips_active(self):
        """cleanup_orphaned_containers should NOT clean up containers with active tmux sessions."""
        mock_config = MagicMock()
        mock_config.project = "myproject"

        mock_containers = [
            {"name": "agenttree-myproject-042", "id": "container1"},
        ]

        mock_runtime = MagicMock()
        mock_runtime.runtime = "container"
        mock_runtime.list_all.return_value = mock_containers

        with patch("agenttree.api.load_config", return_value=mock_config), \
             patch("agenttree.api.get_container_runtime", return_value=mock_runtime), \
             patch("agenttree.api.session_exists", return_value=True):  # Session exists

            result = cleanup_orphaned_containers(quiet=True)

        assert result == 0  # No containers cleaned up
        mock_runtime.stop.assert_not_called()
        mock_runtime.delete.assert_not_called()


class TestCleanupAllContainers:
    """Tests for cleanup_all_agenttree_containers function."""

    def test_cleanup_all_containers(self):
        """cleanup_all_agenttree_containers should remove all agenttree containers regardless of session state."""
        mock_config = MagicMock()
        mock_config.project = "myproject"

        mock_containers = [
            {"name": "agenttree-myproject-042", "image": ""},
            {"name": "agenttree-other-043", "image": ""},
            {"name": "other-container", "image": "agenttree:latest"},  # Match by image
            {"name": "unrelated", "image": "nginx"},  # Should be ignored
        ]

        mock_runtime = MagicMock()
        mock_runtime.runtime = "container"
        mock_runtime.list_all.return_value = mock_containers
        mock_runtime.stop.return_value = True
        mock_runtime.delete.return_value = True

        with patch("agenttree.api.load_config", return_value=mock_config), \
             patch("agenttree.api.get_container_runtime", return_value=mock_runtime):

            result = cleanup_all_agenttree_containers(quiet=True)

        assert result == 3  # Three agenttree containers
        # Should stop and delete all matching containers
        expected_calls = [
            call("agenttree-myproject-042"),
            call("agenttree-other-043"),
            call("other-container"),
        ]
        mock_runtime.stop.assert_has_calls(expected_calls, any_order=True)
        mock_runtime.delete.assert_has_calls(expected_calls, any_order=True)


class TestCleanupAllWithRetry:
    """Tests for cleanup_all_with_retry function."""

    def test_cleanup_all_with_retry(self):
        """cleanup_all_with_retry should perform multiple passes with configurable delay."""
        with patch("agenttree.api.cleanup_all_agenttree_containers", return_value=2) as mock_cleanup, \
             patch("time.sleep") as mock_sleep:

            cleanup_all_with_retry(max_passes=3, delay_s=1.0, quiet=True)

        # Should call cleanup 3 times
        assert mock_cleanup.call_count == 3
        # Should sleep between passes (2 sleeps for 3 passes)
        mock_sleep.assert_has_calls([call(1.0), call(1.0)])

    def test_cleanup_all_with_retry_single_pass(self):
        """cleanup_all_with_retry should work with single pass (no sleep)."""
        with patch("agenttree.api.cleanup_all_agenttree_containers", return_value=1) as mock_cleanup, \
             patch("time.sleep") as mock_sleep:

            cleanup_all_with_retry(max_passes=1, delay_s=2.0, quiet=True)

        mock_cleanup.assert_called_once()
        mock_sleep.assert_not_called()  # No sleep for single pass


class TestContainerNamingConsistency:
    """Tests to verify API uses consistent container naming from config."""

    def test_container_naming_consistency(self):
        """stop_agent should use same container name as config.get_issue_container_name()."""
        mock_config = MagicMock()
        mock_config.project = "testproject"
        mock_config.get_issue_tmux_session.return_value = "testproject-developer-123"
        mock_config.get_issue_container_name.return_value = "agenttree-testproject-123"

        mock_runtime = MagicMock()
        mock_runtime.runtime = "container"
        mock_runtime.stop.return_value = True
        mock_runtime.delete.return_value = True

        with patch("agenttree.api.load_config", return_value=mock_config), \
             patch("agenttree.api.session_exists", return_value=False), \
             patch("agenttree.api.kill_session"), \
             patch("agenttree.api.get_container_runtime", return_value=mock_runtime):

            stop_agent("123", "developer", quiet=True)

        # Verify both config methods were called with same issue_id
        mock_config.get_issue_container_name.assert_called_with("123")
        # Verify container operations used the config-derived name
        expected_name = "agenttree-testproject-123"
        mock_runtime.stop.assert_called_with(expected_name)
        mock_runtime.delete.assert_called_with(expected_name)

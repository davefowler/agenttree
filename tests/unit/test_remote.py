"""Tests for remote agent execution utilities.

This module only tests detection logic, following the testing-scope.md
philosophy of excluding integration-test territory (actual SSH/Tailscale calls).
"""

import subprocess
from unittest.mock import Mock, patch

import pytest

from agenttree.remote import (
    is_tailscale_available,
    get_tailscale_hosts,
    RemoteHost,
)


class TestIsTailscaleAvailable:
    """Tests for is_tailscale_available function."""

    @patch("shutil.which")
    def test_tailscale_available(self, mock_which: Mock) -> None:
        """Test returns True when tailscale binary is found."""
        mock_which.return_value = "/usr/bin/tailscale"

        result = is_tailscale_available()

        assert result is True
        mock_which.assert_called_once_with("tailscale")

    @patch("shutil.which")
    def test_tailscale_not_available(self, mock_which: Mock) -> None:
        """Test returns False when tailscale binary is not found."""
        mock_which.return_value = None

        result = is_tailscale_available()

        assert result is False


class TestGetTailscaleHosts:
    """Tests for get_tailscale_hosts function."""

    @patch("agenttree.remote.is_tailscale_available")
    def test_get_hosts_when_tailscale_unavailable(
        self, mock_available: Mock
    ) -> None:
        """Test returns empty list when tailscale is not available."""
        mock_available.return_value = False

        result = get_tailscale_hosts()

        assert result == []

    @patch("agenttree.remote.subprocess.run")
    @patch("agenttree.remote.is_tailscale_available")
    def test_get_hosts_parses_json(
        self, mock_available: Mock, mock_run: Mock
    ) -> None:
        """Test parsing of tailscale status JSON output."""
        mock_available.return_value = True
        mock_run.return_value = Mock(
            stdout="""{
                "Peer": {
                    "abc123": {"Online": true, "HostName": "host1"},
                    "def456": {"Online": true, "HostName": "host2"},
                    "ghi789": {"Online": false, "HostName": "offline-host"}
                }
            }""",
            returncode=0,
        )

        result = get_tailscale_hosts()

        assert "host1" in result
        assert "host2" in result
        assert "offline-host" not in result  # Offline hosts filtered out

    @patch("agenttree.remote.subprocess.run")
    @patch("agenttree.remote.is_tailscale_available")
    def test_get_hosts_error_handling(
        self, mock_available: Mock, mock_run: Mock
    ) -> None:
        """Test returns empty list on subprocess error."""
        mock_available.return_value = True
        mock_run.side_effect = subprocess.CalledProcessError(1, "tailscale")

        result = get_tailscale_hosts()

        assert result == []

    @patch("agenttree.remote.subprocess.run")
    @patch("agenttree.remote.is_tailscale_available")
    def test_get_hosts_invalid_json(
        self, mock_available: Mock, mock_run: Mock
    ) -> None:
        """Test returns empty list on invalid JSON."""
        mock_available.return_value = True
        mock_run.return_value = Mock(
            stdout="not valid json",
            returncode=0,
        )

        result = get_tailscale_hosts()

        assert result == []


class TestRemoteHost:
    """Tests for RemoteHost dataclass."""

    def test_remote_host_creation(self) -> None:
        """Test creating a RemoteHost instance."""
        host = RemoteHost(
            name="my-server",
            host="192.168.1.100",
            user="admin",
        )

        assert host.name == "my-server"
        assert host.host == "192.168.1.100"
        assert host.user == "admin"
        assert host.ssh_key is None
        assert host.is_tailscale is False

    def test_remote_host_with_all_fields(self) -> None:
        """Test RemoteHost with all optional fields."""
        host = RemoteHost(
            name="tailscale-server",
            host="my-machine",
            user="user",
            ssh_key="/path/to/key",
            is_tailscale=True,
        )

        assert host.ssh_key == "/path/to/key"
        assert host.is_tailscale is True

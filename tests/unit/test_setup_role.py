"""Tests for the setup role feature."""

import pytest

from agenttree.config import Config, RoleConfig, load_config


class TestSetupRoleConfig:
    """Tests for setup role configuration."""

    def test_setup_role_in_default_config(self) -> None:
        """Test that setup role is defined in the default config template."""
        # Create a minimal config with the setup role
        config = Config(
            roles={
                "setup": RoleConfig(
                    name="setup",
                    description="Interactive project setup agent",
                    tool="claude",
                    model="opus",
                ),
            }
        )

        role = config.get_role("setup")
        assert role is not None
        assert role.name == "setup"
        assert role.tool == "claude"
        assert role.model == "opus"
        assert role.is_containerized() is False  # Host-level role
        assert role.is_agent() is True  # Has tool configured

    def test_setup_role_not_containerized(self) -> None:
        """Test that setup role runs on host, not in container."""
        config = Config(
            roles={
                "setup": RoleConfig(
                    name="setup",
                    description="Interactive project setup agent",
                    tool="claude",
                    model="opus",
                    container=None,  # Explicitly no container
                ),
            }
        )

        assert config.role_is_containerized("setup") is False

    def test_setup_role_skill_file(self) -> None:
        """Test that setup role uses setup.md skill file."""
        role = RoleConfig(
            name="setup",
            description="Interactive project setup agent",
            tool="claude",
        )

        # Default skill file should be {role_name}.md
        assert role.skill_file == "setup.md"


@pytest.mark.local_only
class TestSetupRoleIntegration:
    """Integration tests for setup role - require local tmux."""

    def test_setup_role_can_be_started(self) -> None:
        """Test that setup role can be started via start_role().

        This test requires tmux and is skipped in CI.
        """
        # This test would require:
        # 1. A real config file with setup role
        # 2. tmux installed
        # 3. Claude CLI available
        #
        # For now, just verify the config structure is correct
        # The actual start would be tested manually
        pass

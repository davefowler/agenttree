"""Tests for custom agent hosts feature."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from agenttree.config import (
    HostConfig,
    ContainerConfig,
    Config,
    StageConfig,
    load_config,
)
from agenttree.hooks import (
    get_current_agent_host,
    can_agent_operate_in_stage,
    is_running_in_container,
)


class TestHostConfig:
    """Tests for HostConfig dataclass."""

    def test_host_config_with_container(self):
        """Test HostConfig with container settings."""
        config = HostConfig(
            name="review",
            description="Code reviewer",
            container=ContainerConfig(
                enabled=True,
                image="custom-image:latest"
            ),
            tool="codex",
            model="gpt-5.2",
            skill="agents/review.md"
        )
        assert config.name == "review"
        assert config.is_containerized() is True
        assert config.is_agent() is True
        assert config.container.image == "custom-image:latest"

    def test_host_config_without_container(self):
        """Test HostConfig without container (like controller)."""
        config = HostConfig(
            name="controller",
            description="Human-driven controller",
            container=None
        )
        assert config.name == "controller"
        assert config.is_containerized() is False
        assert config.is_agent() is False

    def test_host_config_disabled_container(self):
        """Test HostConfig with disabled container."""
        config = HostConfig(
            name="local-agent",
            container=ContainerConfig(enabled=False)
        )
        assert config.is_containerized() is False


class TestConfigWithHosts:
    """Tests for Config with hosts section."""

    def test_get_all_hosts_includes_defaults(self):
        """Test that get_all_hosts includes built-in controller and agent."""
        config = Config()
        all_hosts = config.get_all_hosts()

        # Should have at least controller and agent
        assert "controller" in all_hosts
        assert "agent" in all_hosts

        # Controller should not be containerized
        assert all_hosts["controller"].is_containerized() is False

        # Agent should be containerized
        assert all_hosts["agent"].is_containerized() is True

    def test_get_all_hosts_with_custom_hosts(self):
        """Test that custom hosts are merged with defaults."""
        config = Config(
            hosts={
                "review": HostConfig(
                    name="review",
                    container=ContainerConfig(enabled=True),
                    tool="codex",
                    model="gpt-5.2"
                )
            }
        )
        all_hosts = config.get_all_hosts()

        # Should have defaults plus custom
        assert "controller" in all_hosts
        assert "agent" in all_hosts
        assert "review" in all_hosts

    def test_get_host_returns_builtin(self):
        """Test get_host returns built-in hosts."""
        config = Config()

        controller = config.get_host("controller")
        assert controller is not None
        assert controller.name == "controller"

        agent = config.get_host("agent")
        assert agent is not None
        assert agent.name == "agent"

    def test_host_is_containerized(self):
        """Test host_is_containerized method."""
        config = Config(
            hosts={
                "review": HostConfig(
                    name="review",
                    container=ContainerConfig(enabled=True)
                )
            }
        )

        assert config.host_is_containerized("controller") is False
        assert config.host_is_containerized("agent") is True
        assert config.host_is_containerized("review") is True


class TestConfigWithCustomHosts:
    """Tests for Config with custom hosts section."""

    def test_config_with_hosts(self):
        """Test Config creation with custom hosts."""
        config = Config(
            hosts={
                "review": HostConfig(
                    name="review",
                    container=ContainerConfig(enabled=True),
                    tool="codex",
                    model="gpt-5.2",
                    skill="agents/review.md"
                ),
                "security": HostConfig(
                    name="security",
                    container=ContainerConfig(enabled=True),
                    tool="claude",
                    model="opus",
                    skill="agents/security.md"
                )
            }
        )
        assert len(config.hosts) == 2
        assert "review" in config.hosts
        assert "security" in config.hosts

    def test_get_agent_host(self):
        """Test get_agent_host method."""
        config = Config(
            hosts={
                "review": HostConfig(
                    name="review",
                    container=ContainerConfig(enabled=True),
                    tool="codex",
                    model="gpt-5.2",
                    skill="agents/review.md"
                )
            }
        )
        agent = config.get_agent_host("review")
        assert agent is not None
        assert agent.name == "review"
        assert agent.tool == "codex"

        # Non-existent agent
        assert config.get_agent_host("nonexistent") is None

    def test_is_custom_agent_host(self):
        """Test is_custom_agent_host method."""
        config = Config(
            hosts={
                "review": HostConfig(
                    name="review",
                    container=ContainerConfig(enabled=True),
                    tool="codex",
                    model="gpt-5.2",
                    skill="agents/review.md"
                )
            }
        )
        assert config.is_custom_agent_host("review") is True
        assert config.is_custom_agent_host("security") is False
        assert config.is_custom_agent_host("agent") is False
        assert config.is_custom_agent_host("controller") is False

    def test_get_custom_agent_stages(self):
        """Test get_custom_agent_stages method."""
        config = Config(
            hosts={
                "review": HostConfig(
                    name="review",
                    container=ContainerConfig(enabled=True),
                    tool="codex",
                    model="gpt-5.2",
                    skill="agents/review.md"
                )
            },
            stages=[
                StageConfig(name="implement", host="agent"),
                StageConfig(name="independent_code_review", host="review"),
                StageConfig(name="implementation_review", host="controller"),
                StageConfig(name="accepted", host="controller"),
            ]
        )
        custom_stages = config.get_custom_agent_stages()
        assert "independent_code_review" in custom_stages
        assert "implement" not in custom_stages
        assert "implementation_review" not in custom_stages

    def test_get_non_agent_stages(self):
        """Test get_non_agent_stages method."""
        config = Config(
            hosts={
                "review": HostConfig(
                    name="review",
                    container=ContainerConfig(enabled=True),
                    tool="codex",
                    model="gpt-5.2",
                    skill="agents/review.md"
                )
            },
            stages=[
                StageConfig(name="implement", host="agent"),
                StageConfig(name="independent_code_review", host="review"),
                StageConfig(name="implementation_review", host="controller"),
            ]
        )
        non_agent = config.get_non_agent_stages()
        assert "independent_code_review" in non_agent
        assert "implementation_review" in non_agent
        assert "implement" not in non_agent


class TestLoadConfigWithHosts:
    """Tests for loading config with hosts section from YAML."""

    def test_load_config_with_hosts_yaml(self, tmp_path):
        """Test loading config with hosts from YAML file."""
        config_content = """
hosts:
  review:
    container: true
    tool: codex
    model: gpt-5.2
    skill: agents/review.md
    description: Code reviewer
  security:
    container: true
    tool: claude
    model: opus
    skill: agents/security.md

stages:
  - name: implement
    host: agent
  - name: independent_code_review
    host: review
  - name: implementation_review
    host: controller
"""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text(config_content)

        with patch("agenttree.config.find_config_file", return_value=config_file):
            config = load_config()

        assert len(config.hosts) == 2
        assert "review" in config.hosts
        assert config.hosts["review"].name == "review"
        assert config.hosts["review"].tool == "codex"
        assert config.hosts["review"].model == "gpt-5.2"


class TestGetCurrentAgentHost:
    """Tests for get_current_agent_host function."""

    def test_explicit_agent_host_env(self):
        """Test with explicit AGENTTREE_AGENT_HOST env var."""
        with patch.dict(os.environ, {"AGENTTREE_AGENT_HOST": "review"}):
            assert get_current_agent_host() == "review"

    def test_default_in_container(self):
        """Test default is 'agent' when in container."""
        with patch.dict(os.environ, {"AGENTTREE_CONTAINER": "1"}, clear=True):
            # Clear AGENTTREE_AGENT_HOST to test default
            os.environ.pop("AGENTTREE_AGENT_HOST", None)
            assert get_current_agent_host() == "agent"

    def test_default_on_host(self):
        """Test default is 'controller' when not in container."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear container and agent host vars
            os.environ.pop("AGENTTREE_CONTAINER", None)
            os.environ.pop("AGENTTREE_AGENT_HOST", None)
            # Also mock the container detection files
            with patch("os.path.exists", return_value=False):
                assert get_current_agent_host() == "controller"


class TestCanAgentOperateInStage:
    """Tests for can_agent_operate_in_stage function."""

    def test_controller_can_operate_anywhere(self):
        """Controller (human) can operate in any stage."""
        with patch("agenttree.hooks.get_current_agent_host", return_value="controller"):
            assert can_agent_operate_in_stage("agent") is True
            assert can_agent_operate_in_stage("controller") is True
            assert can_agent_operate_in_stage("review") is True

    def test_agent_can_only_operate_in_agent_stages(self):
        """Default agent can only operate in host='agent' stages."""
        with patch("agenttree.hooks.get_current_agent_host", return_value="agent"):
            assert can_agent_operate_in_stage("agent") is True
            assert can_agent_operate_in_stage("controller") is False
            assert can_agent_operate_in_stage("review") is False

    def test_custom_agent_can_only_operate_in_own_stages(self):
        """Custom agents can only operate in their own host stages."""
        with patch("agenttree.hooks.get_current_agent_host", return_value="review"):
            assert can_agent_operate_in_stage("review") is True
            assert can_agent_operate_in_stage("agent") is False
            assert can_agent_operate_in_stage("controller") is False


class TestCheckCustomAgentStages:
    """Tests for check_custom_agent_stages function."""

    def test_skips_when_in_container(self, tmp_path):
        """Test that check_custom_agent_stages does nothing in container."""
        from agenttree.agents_repo import check_custom_agent_stages

        # is_running_in_container is imported from hooks inside the function
        with patch("agenttree.hooks.is_running_in_container", return_value=True):
            result = check_custom_agent_stages(tmp_path)
            assert result == 0

    def test_skips_when_no_custom_agent_stages(self, tmp_path):
        """Test that check_custom_agent_stages returns 0 when no custom stages."""
        from agenttree.agents_repo import check_custom_agent_stages

        issues_dir = tmp_path / "issues"
        issues_dir.mkdir()

        mock_config = MagicMock()
        mock_config.get_custom_agent_stages.return_value = []

        with patch("agenttree.hooks.is_running_in_container", return_value=False):
            with patch("agenttree.config.load_config", return_value=mock_config):
                result = check_custom_agent_stages(tmp_path)
                assert result == 0

    def test_skips_already_spawned_agents(self, tmp_path):
        """Test that issues with custom_agent_spawned set are skipped."""
        from agenttree.agents_repo import check_custom_agent_stages

        issues_dir = tmp_path / "issues"
        issues_dir.mkdir()
        issue_dir = issues_dir / "001-test"
        issue_dir.mkdir()

        # Create issue.yaml with custom_agent_spawned already set
        issue_data = {
            "id": "1",
            "slug": "test",
            "title": "Test Issue",
            "created": "2024-01-01",
            "updated": "2024-01-01",
            "stage": "independent_code_review",
            "custom_agent_spawned": "independent_code_review"  # Already spawned
        }
        (issue_dir / "issue.yaml").write_text(yaml.safe_dump(issue_data))

        mock_config = MagicMock()
        mock_config.get_custom_agent_stages.return_value = ["independent_code_review"]

        with patch("agenttree.hooks.is_running_in_container", return_value=False):
            with patch("agenttree.config.load_config", return_value=mock_config):
                result = check_custom_agent_stages(tmp_path)
                # Should skip since already spawned
                assert result == 0


class TestContainerAgentHost:
    """Tests for container runtime setting AGENTTREE_AGENT_HOST."""

    def test_build_run_command_includes_agent_host(self):
        """Test that build_run_command includes AGENTTREE_AGENT_HOST env var."""
        from agenttree.container import ContainerRuntime

        runtime = ContainerRuntime()
        # Skip if no runtime available
        if not runtime.is_available():
            pytest.skip("No container runtime available")

        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            # Create minimal git structure
            (worktree / ".git").write_text("gitdir: /some/path")

            cmd = runtime.build_run_command(
                worktree_path=worktree,
                ai_tool="claude",
                agent_host="review"
            )

            # Check that AGENTTREE_AGENT_HOST is set
            assert "-e" in cmd
            host_index = None
            for i, arg in enumerate(cmd):
                if arg == "-e" and i + 1 < len(cmd):
                    if cmd[i + 1].startswith("AGENTTREE_AGENT_HOST="):
                        host_index = i + 1
                        break

            assert host_index is not None, "AGENTTREE_AGENT_HOST not found in command"
            assert cmd[host_index] == "AGENTTREE_AGENT_HOST=review"

    def test_build_run_command_default_agent_host(self):
        """Test that default agent_host is 'agent'."""
        from agenttree.container import ContainerRuntime

        runtime = ContainerRuntime()
        if not runtime.is_available():
            pytest.skip("No container runtime available")

        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            (worktree / ".git").write_text("gitdir: /some/path")

            cmd = runtime.build_run_command(
                worktree_path=worktree,
                ai_tool="claude"
                # agent_host defaults to "agent"
            )

            # Check default value
            for i, arg in enumerate(cmd):
                if arg == "-e" and i + 1 < len(cmd):
                    if cmd[i + 1].startswith("AGENTTREE_AGENT_HOST="):
                        assert cmd[i + 1] == "AGENTTREE_AGENT_HOST=agent"
                        return

            pytest.fail("AGENTTREE_AGENT_HOST not found in command")

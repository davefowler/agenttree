"""Tests for custom agent hosts feature."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from agenttree.config import (
    RoleConfig,
    ContainerConfig,
    Config,
    StageConfig,
    load_config,
)
from agenttree.hooks import (
    get_current_role,
    can_agent_operate_in_stage,
    is_running_in_container,
)


class TestRoleConfig:
    """Tests for RoleConfig dataclass."""

    def test_role_config_with_container(self):
        """Test RoleConfig with container settings."""
        config = RoleConfig(
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

    def test_role_config_without_container(self):
        """Test RoleConfig without container (like manager)."""
        config = RoleConfig(
            name="manager",
            description="Human-driven manager",
            container=None
        )
        assert config.name == "manager"
        assert config.is_containerized() is False
        assert config.is_agent() is False

    def test_role_config_disabled_container(self):
        """Test RoleConfig with disabled container."""
        config = RoleConfig(
            name="local-agent",
            container=ContainerConfig(enabled=False)
        )
        assert config.is_containerized() is False


class TestConfigWithRoles:
    """Tests for Config with roles section."""

    def test_get_all_roles_includes_defaults(self):
        """Test that get_all_roles includes built-in manager and developer."""
        config = Config()
        all_roles = config.get_all_roles()

        # Should have at least manager and developer
        assert "manager" in all_roles
        assert "developer" in all_roles

        # Manager should not be containerized
        assert all_roles["manager"].is_containerized() is False

        # Developer should be containerized
        assert all_roles["developer"].is_containerized() is True

    def test_get_all_roles_with_custom(self):
        """Test that custom roles are merged with defaults."""
        config = Config(
            roles={
                "review": RoleConfig(
                    name="review",
                    container=ContainerConfig(enabled=True),
                    tool="codex",
                    model="gpt-5.2"
                )
            }
        )
        all_roles = config.get_all_roles()

        # Should have defaults plus custom
        assert "manager" in all_roles
        assert "developer" in all_roles
        assert "review" in all_roles

    def test_get_role_returns_builtin(self):
        """Test get_role returns built-in roles."""
        config = Config()

        mgr = config.get_role("manager")
        assert mgr is not None
        assert mgr.name == "manager"

        agent = config.get_role("developer")
        assert agent is not None
        assert agent.name == "developer"

    def test_role_is_containerized(self):
        """Test role_is_containerized method."""
        config = Config(
            roles={
                "review": RoleConfig(
                    name="review",
                    container=ContainerConfig(enabled=True)
                )
            }
        )

        assert config.role_is_containerized("manager") is False
        assert config.role_is_containerized("agent") is True
        assert config.role_is_containerized("review") is True


class TestConfigWithCustomRoles:
    """Tests for Config with custom roles section."""

    def test_config_with_custom_roles(self):
        """Test Config creation with custom roles."""
        config = Config(
            roles={
                "review": RoleConfig(
                    name="review",
                    container=ContainerConfig(enabled=True),
                    tool="codex",
                    model="gpt-5.2",
                    skill="agents/review.md"
                ),
                "security": RoleConfig(
                    name="security",
                    container=ContainerConfig(enabled=True),
                    tool="claude",
                    model="opus",
                    skill="agents/security.md"
                )
            }
        )
        assert len(config.roles) == 2
        assert "review" in config.roles
        assert "security" in config.roles

    def test_get_role(self):
        """Test get_role method."""
        config = Config(
            roles={
                "review": RoleConfig(
                    name="review",
                    container=ContainerConfig(enabled=True),
                    tool="codex",
                    model="gpt-5.2",
                    skill="agents/review.md"
                )
            }
        )
        agent = config.get_role("review")
        assert agent is not None
        assert agent.name == "review"
        assert agent.tool == "codex"

        # Non-existent agent
        assert config.get_role("nonexistent") is None

    def test_is_custom_role(self):
        """Test is_custom_role method."""
        config = Config(
            roles={
                "review": RoleConfig(
                    name="review",
                    container=ContainerConfig(enabled=True),
                    tool="codex",
                    model="gpt-5.2",
                    skill="agents/review.md"
                )
            }
        )
        assert config.is_custom_role("review") is True
        assert config.is_custom_role("security") is False
        assert config.is_custom_role("agent") is False
        assert config.is_custom_role("manager") is False

    def test_get_custom_role_stages(self):
        """Test get_custom_role_stages method."""
        config = Config(
            roles={
                "review": RoleConfig(
                    name="review",
                    container=ContainerConfig(enabled=True),
                    tool="codex",
                    model="gpt-5.2",
                    skill="agents/review.md"
                )
            },
            stages={
                "implement.code": StageConfig(name="implement.code", role="developer"),
                "implement.independent_review": StageConfig(name="implement.independent_review", role="review"),
                "implement.review": StageConfig(name="implement.review", role="manager"),
                "accepted": StageConfig(name="accepted", role="manager"),
            }
        )
        custom_stages = config.get_custom_role_stages()
        assert "implement.independent_review" in custom_stages
        assert "implement.code" not in custom_stages
        assert "implement.review" not in custom_stages

    def test_get_non_developer_stages(self):
        """Test get_non_developer_stages method."""
        config = Config(
            roles={
                "review": RoleConfig(
                    name="review",
                    container=ContainerConfig(enabled=True),
                    tool="codex",
                    model="gpt-5.2",
                    skill="agents/review.md"
                )
            },
            stages={
                "implement.code": StageConfig(name="implement.code", role="developer"),
                "implement.independent_review": StageConfig(name="implement.independent_review", role="review"),
                "implement.review": StageConfig(name="implement.review", role="manager"),
            }
        )
        non_agent = config.get_non_developer_stages()
        assert "implement.independent_review" in non_agent
        assert "implement.review" in non_agent
        assert "implement.code" not in non_agent


class TestLoadConfigWithRoles:
    """Tests for loading config with roles section from YAML."""

    def test_load_config_with_roles_yaml(self, tmp_path):
        """Test loading config with roles from YAML file."""
        config_content = """
roles:
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
    role: developer
  - name: independent_code_review
    role: review
  - name: implementation_review
    role: manager
"""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text(config_content)

        with patch("agenttree.config.find_config_file", return_value=config_file):
            config = load_config()

        assert len(config.roles) == 2
        assert "review" in config.roles
        assert config.roles["review"].name == "review"
        assert config.roles["review"].tool == "codex"
        assert config.roles["review"].model == "gpt-5.2"


class TestGetCurrentAgentHost:
    """Tests for get_current_role function."""

    def test_explicit_role_env(self):
        """Test with explicit AGENTTREE_ROLE env var."""
        with patch.dict(os.environ, {"AGENTTREE_ROLE": "review"}):
            assert get_current_role() == "review"

    def test_default_in_container(self):
        """Test default is 'agent' when in container."""
        with patch.dict(os.environ, {"AGENTTREE_CONTAINER": "1"}, clear=True):
            # Clear AGENTTREE_ROLE to test default
            os.environ.pop("AGENTTREE_ROLE", None)
            assert get_current_role() == "developer"

    def test_default_on_host(self):
        """Test default is 'manager' when not in container."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear container and agent role vars
            os.environ.pop("AGENTTREE_CONTAINER", None)
            os.environ.pop("AGENTTREE_ROLE", None)
            # Also mock the container detection files
            with patch("os.path.exists", return_value=False):
                assert get_current_role() == "manager"


class TestCanAgentOperateInStage:
    """Tests for can_agent_operate_in_stage function."""

    def test_manager_can_operate_anywhere(self):
        """Manager (human) can operate in any stage."""
        with patch("agenttree.hooks.get_current_role", return_value="manager"):
            assert can_agent_operate_in_stage("agent") is True
            assert can_agent_operate_in_stage("manager") is True
            assert can_agent_operate_in_stage("review") is True

    def test_agent_can_only_operate_in_agent_stages(self):
        """Default agent can only operate in role='developer' stages."""
        with patch("agenttree.hooks.get_current_role", return_value="agent"):
            assert can_agent_operate_in_stage("agent") is True
            assert can_agent_operate_in_stage("manager") is False
            assert can_agent_operate_in_stage("review") is False

    def test_custom_agent_can_only_operate_in_own_stages(self):
        """Custom agents can only operate in their own role stages."""
        with patch("agenttree.hooks.get_current_role", return_value="review"):
            assert can_agent_operate_in_stage("review") is True
            assert can_agent_operate_in_stage("agent") is False
            assert can_agent_operate_in_stage("manager") is False


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
        mock_config.get_custom_role_stages.return_value = []

        with patch("agenttree.hooks.is_running_in_container", return_value=False):
            with patch("agenttree.config.load_config", return_value=mock_config):
                result = check_custom_agent_stages(tmp_path)
                assert result == 0

    def test_skips_already_running_agents(self, tmp_path):
        """Test that issues with running custom agent sessions are skipped."""
        from agenttree.agents_repo import check_custom_agent_stages

        issues_dir = tmp_path / "issues"
        issues_dir.mkdir()
        issue_dir = issues_dir / "001-test"
        issue_dir.mkdir()

        # Create issue.yaml at a custom agent stage
        issue_data = {
            "id": "1",
            "slug": "test",
            "title": "Test Issue",
            "created": "2024-01-01",
            "updated": "2024-01-01",
            "stage": "implement.independent_review",
        }
        (issue_dir / "issue.yaml").write_text(yaml.safe_dump(issue_data))

        mock_config = MagicMock()
        mock_config.project = "testproj"
        mock_config.get_custom_role_stages.return_value = ["implement.independent_review"]
        mock_config.role_for.return_value = "review"
        mock_agent_config = MagicMock()
        mock_config.get_custom_role.return_value = mock_agent_config

        with patch("agenttree.hooks.is_running_in_container", return_value=False):
            with patch("agenttree.config.load_config", return_value=mock_config):
                with patch("agenttree.tmux.session_exists", return_value=True):
                    with patch("agenttree.tmux.is_claude_running", return_value=True):
                        with patch("agenttree.tmux.send_message", return_value="sent"):
                            result = check_custom_agent_stages(tmp_path)
                            assert result == 0

    def test_spawns_agent_for_substage_dot_path(self, tmp_path):
        """Test that dot paths like implement.independent_review resolve correctly."""
        from agenttree.agents_repo import check_custom_agent_stages

        issues_dir = tmp_path / "issues"
        issues_dir.mkdir()
        issue_dir = issues_dir / "170-test"
        issue_dir.mkdir()

        issue_data = {
            "id": "170",
            "slug": "test",
            "title": "Test Issue",
            "created": "2024-01-01",
            "updated": "2024-01-01",
            "stage": "implement.independent_review",
        }
        (issue_dir / "issue.yaml").write_text(yaml.safe_dump(issue_data))

        mock_config = MagicMock()
        mock_config.project = "testproj"
        mock_config.get_custom_role_stages.return_value = ["implement.independent_review"]
        mock_config.role_for.return_value = "review"
        mock_agent_config = MagicMock()
        mock_config.get_custom_role.return_value = mock_agent_config

        with patch("agenttree.hooks.is_running_in_container", return_value=False):
            with patch("agenttree.config.load_config", return_value=mock_config):
                with patch("agenttree.tmux.session_exists", return_value=False):
                    with patch("agenttree.container.is_container_running", return_value=False):
                        with patch("agenttree.api.start_agent") as mock_start:
                            result = check_custom_agent_stages(tmp_path)
                            assert result == 1
                            mock_start.assert_called_once_with(
                                170, host="review", skip_preflight=True, quiet=True, force=False
                            )


class TestContainerAgentHost:
    """Tests for container runtime setting AGENTTREE_ROLE."""

    def test_build_run_command_includes_role(self):
        """Test that build_run_command includes AGENTTREE_ROLE env var."""
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
                role="review"
            )

            # Check that AGENTTREE_ROLE is set
            assert "-e" in cmd
            host_index = None
            for i, arg in enumerate(cmd):
                if arg == "-e" and i + 1 < len(cmd):
                    if cmd[i + 1].startswith("AGENTTREE_ROLE="):
                        host_index = i + 1
                        break

            assert host_index is not None, "AGENTTREE_ROLE not found in command"
            assert cmd[host_index] == "AGENTTREE_ROLE=review"

    def test_build_run_command_default_role(self):
        """Test that default role is 'developer'."""
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
                # role defaults to "developer"
            )

            # Check default value
            for i, arg in enumerate(cmd):
                if arg == "-e" and i + 1 < len(cmd):
                    if cmd[i + 1].startswith("AGENTTREE_ROLE="):
                        assert cmd[i + 1] == "AGENTTREE_ROLE=developer"
                        return

            pytest.fail("AGENTTREE_ROLE not found in command")

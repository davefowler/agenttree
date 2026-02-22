"""Tests for serve architecture configuration.

Tests for:
- ContainerTypeConfig model
- resolve_container_type (extends resolution, mount accumulation, env merge)
- render_template (Jinja template rendering)
- ToolConfig container methods
- build_container_command
- Session naming
- Dev server URLs
"""

from pathlib import Path

import pytest

from agenttree.config import (
    Config,
    ContainerTypeConfig,
    resolve_container_type,
    render_template,
)


class TestContainerTypeConfig:
    """Tests for ContainerTypeConfig model."""

    def test_container_type_config_defaults(self) -> None:
        """Test ContainerTypeConfig default values.

        Image and allow_dangerous default to None for proper inheritance.
        resolve_container_type applies actual defaults after resolution.
        """
        config = ContainerTypeConfig()
        assert config.extends is None
        assert config.image is None  # None allows inheritance
        assert config.mounts == []
        assert config.env == {}
        assert config.allow_dangerous is None  # None allows inheritance

    def test_container_type_config_with_values(self) -> None:
        """Test ContainerTypeConfig with explicit values."""
        config = ContainerTypeConfig(
            extends="_base",
            image="custom-image:latest",
            mounts=["~/.ssh:/home/agent/.ssh:ro"],
            env={"NODE_ENV": "development"},
            allow_dangerous=False,
        )
        assert config.extends == "_base"
        assert config.image == "custom-image:latest"
        assert config.mounts == ["~/.ssh:/home/agent/.ssh:ro"]
        assert config.env == {"NODE_ENV": "development"}
        assert config.allow_dangerous is False


class TestResolveContainerType:
    """Tests for resolve_container_type function."""

    def test_resolve_simple_type(self) -> None:
        """Test resolving a container type with no extends."""
        containers = {
            "sandbox": ContainerTypeConfig(
                image="sandbox:latest",
            )
        }
        resolved = resolve_container_type("sandbox", containers)
        assert resolved.image == "sandbox:latest"
        assert resolved.extends is None  # Resolved config has no extends

    def test_resolve_single_extends(self) -> None:
        """Test resolving with single inheritance."""
        containers = {
            "_base": ContainerTypeConfig(
                image="base:latest",
            ),
            "issue": ContainerTypeConfig(
                extends="_base",
            ),
        }
        resolved = resolve_container_type("issue", containers)
        assert resolved.image == "base:latest"  # Inherited from _base

    def test_resolve_mount_accumulation(self) -> None:
        """Test that mounts accumulate through extends chain."""
        containers = {
            "_base": ContainerTypeConfig(
                mounts=["~/.ssh:/home/agent/.ssh:ro"],
            ),
            "_with_git": ContainerTypeConfig(
                extends="_base",
                mounts=["~/.gitconfig:/home/agent/.gitconfig:ro"],
            ),
            "sandbox": ContainerTypeConfig(
                extends="_with_git",
                mounts=["~/datasets:/workspace/data:ro"],
            ),
        }
        resolved = resolve_container_type("sandbox", containers)
        # Mounts accumulate from all ancestors
        assert resolved.mounts == [
            "~/.ssh:/home/agent/.ssh:ro",
            "~/.gitconfig:/home/agent/.gitconfig:ro",
            "~/datasets:/workspace/data:ro",
        ]

    def test_resolve_env_merge(self) -> None:
        """Test that env vars merge with child overriding parent."""
        containers = {
            "_base": ContainerTypeConfig(
                env={"NODE_ENV": "development", "DEBUG": "true"},
            ),
            "production": ContainerTypeConfig(
                extends="_base",
                env={"NODE_ENV": "production", "LOG_LEVEL": "warn"},
            ),
        }
        resolved = resolve_container_type("production", containers)
        # Child NODE_ENV overrides parent, DEBUG is kept, LOG_LEVEL is added
        assert resolved.env == {
            "NODE_ENV": "production",
            "DEBUG": "true",
            "LOG_LEVEL": "warn",
        }

    def test_resolve_allow_dangerous_inheritance(self) -> None:
        """Test that allow_dangerous=False propagates."""
        containers = {
            "_secure": ContainerTypeConfig(
                allow_dangerous=False,
            ),
            "locked": ContainerTypeConfig(
                extends="_secure",
            ),
        }
        resolved = resolve_container_type("locked", containers)
        assert resolved.allow_dangerous is False

    def test_resolve_multi_level_inheritance(self) -> None:
        """Test three-level inheritance chain."""
        containers = {
            "_base": ContainerTypeConfig(
                image="base:latest",
                mounts=["~/.ssh:/home/agent/.ssh:ro"],
                env={"A": "1"},
            ),
            "_with_git": ContainerTypeConfig(
                extends="_base",
                mounts=["~/.gitconfig:/home/agent/.gitconfig:ro"],
                env={"B": "2"},
            ),
            "data_science": ContainerTypeConfig(
                extends="_with_git",
                mounts=["~/data:/workspace/data:ro"],
                env={"C": "3"},
            ),
        }
        resolved = resolve_container_type("data_science", containers)
        assert resolved.image == "base:latest"
        assert resolved.mounts == [
            "~/.ssh:/home/agent/.ssh:ro",
            "~/.gitconfig:/home/agent/.gitconfig:ro",
            "~/data:/workspace/data:ro",
        ]
        assert resolved.env == {"A": "1", "B": "2", "C": "3"}

    def test_resolve_unknown_type_raises(self) -> None:
        """Test that resolving unknown type raises ValueError."""
        containers: dict[str, ContainerTypeConfig] = {}
        with pytest.raises(ValueError, match="Unknown container type: unknown"):
            resolve_container_type("unknown", containers)

    def test_resolve_unknown_extends_raises(self) -> None:
        """Test that unknown extends target raises ValueError."""
        containers = {
            "sandbox": ContainerTypeConfig(extends="_nonexistent"),
        }
        with pytest.raises(ValueError, match="Unknown container type in extends chain"):
            resolve_container_type("sandbox", containers)

    def test_resolve_circular_extends_raises(self) -> None:
        """Test that circular extends raises ValueError."""
        containers = {
            "a": ContainerTypeConfig(extends="b"),
            "b": ContainerTypeConfig(extends="a"),
        }
        with pytest.raises(ValueError, match="Circular extends detected"):
            resolve_container_type("a", containers)


class TestRenderTemplate:
    """Tests for render_template function."""

    def test_render_simple_variable(self) -> None:
        """Test rendering simple variable substitution."""
        result = render_template("port {{ port }}", {"port": 9042})
        assert result == "port 9042"

    def test_render_arithmetic(self) -> None:
        """Test rendering with arithmetic expressions."""
        result = render_template("{{ port + 100 }}", {"port": 9042})
        assert result == "9142"

    def test_render_multiple_variables(self) -> None:
        """Test rendering with multiple variables."""
        result = render_template(
            "{{ project }}-{{ role }}-{{ issue_id }}",
            {"project": "myapp", "role": "developer", "issue_id": "042"},
        )
        assert result == "myapp-developer-042"

    def test_render_complex_expression(self) -> None:
        """Test rendering with complex Jinja expression."""
        result = render_template(
            "{% if debug %}--debug{% endif %} --port {{ port }}",
            {"debug": True, "port": 8080},
        )
        assert result == "--debug --port 8080"

    def test_render_no_template_markers(self) -> None:
        """Test rendering string with no template markers."""
        result = render_template("npm run dev", {})
        assert result == "npm run dev"


class TestConfigWithContainerField:
    """Tests for Config with containers field."""

    def test_config_has_containers_field(self) -> None:
        """Test that Config has containers field."""
        config = Config()
        assert config.containers == {}

    def test_config_with_containers(self) -> None:
        """Test Config with containers configured."""
        config = Config(
            containers={
                "_base": ContainerTypeConfig(
                    image="agenttree-agent:latest",
                ),
                "issue": ContainerTypeConfig(
                    extends="_base",
                ),
            }
        )
        assert "_base" in config.containers
        assert "issue" in config.containers
        assert config.containers["issue"].extends == "_base"


class TestToolConfigContainerMethods:
    """Tests for ToolConfig container-related methods."""

    def test_container_entry_command_basic(self) -> None:
        """Test basic entry command generation."""
        from agenttree.config import ToolConfig

        tool = ToolConfig(command="claude")
        cmd = tool.container_entry_command()
        assert cmd == ["claude", "--dangerously-skip-permissions"]

    def test_container_entry_command_with_model(self) -> None:
        """Test entry command with model specified."""
        from agenttree.config import ToolConfig

        tool = ToolConfig(command="claude")
        cmd = tool.container_entry_command(model="opus")
        assert "--model" in cmd
        assert "opus" in cmd

    def test_container_entry_command_with_continue_session(self) -> None:
        """Test entry command with session continuation."""
        from agenttree.config import ToolConfig

        tool = ToolConfig(command="claude")
        cmd = tool.container_entry_command(continue_session=True)
        assert "-c" in cmd

    def test_container_entry_command_not_dangerous(self) -> None:
        """Test entry command without dangerous mode."""
        from agenttree.config import ToolConfig

        tool = ToolConfig(command="claude")
        cmd = tool.container_entry_command(dangerous=False)
        assert "--dangerously-skip-permissions" not in cmd

    def test_container_env_returns_dict(self) -> None:
        """Test container_env returns a dict."""
        from agenttree.config import ToolConfig

        tool = ToolConfig(command="claude")
        env = tool.container_env()
        assert isinstance(env, dict)

    def test_container_env_passes_oauth_token(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        """Test that CLAUDE_CODE_OAUTH_TOKEN is passed when set."""
        from agenttree.config import ToolConfig

        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test-token")
        # Clear API key to isolate test
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        tool = ToolConfig(command="claude")
        env = tool.container_env()

        assert "CLAUDE_CODE_OAUTH_TOKEN" in env
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-test-token"

    def test_container_env_passes_api_key(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        """Test that ANTHROPIC_API_KEY is passed when set."""
        from agenttree.config import ToolConfig

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-test-key")
        # Clear OAuth token to isolate test
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

        tool = ToolConfig(command="claude")
        env = tool.container_env()

        assert "ANTHROPIC_API_KEY" in env
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-api03-test-key"

    def test_container_env_passes_both_credentials(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        """Test that both credentials are passed when both are set."""
        from agenttree.config import ToolConfig

        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test-token")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-test-key")

        tool = ToolConfig(command="claude")
        env = tool.container_env()

        # Both should be present for flexible mode switching
        assert "CLAUDE_CODE_OAUTH_TOKEN" in env
        assert "ANTHROPIC_API_KEY" in env
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-test-token"
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-api03-test-key"

    def test_container_env_force_api_key_skips_oauth(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        """Test that force_api_key=True skips OAuth token."""
        from agenttree.config import ToolConfig

        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test-token")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-test-key")

        tool = ToolConfig(command="claude")
        env = tool.container_env(force_api_key=True)

        # OAuth token should be skipped
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
        # API key should still be present
        assert "ANTHROPIC_API_KEY" in env
        assert env["ANTHROPIC_API_KEY"] == "sk-ant-api03-test-key"

    def test_container_env_empty_when_no_credentials(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        """Test that empty dict is returned when no credentials are set."""
        from agenttree.config import ToolConfig

        # Clear both credential env vars
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        tool = ToolConfig(command="claude")
        env = tool.container_env()

        # Neither credential should be in the result
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
        assert "ANTHROPIC_API_KEY" not in env

    def test_container_mounts_returns_list(self, tmp_path: Path) -> None:
        """Test container_mounts returns a list of tuples."""
        from agenttree.config import ToolConfig

        tool = ToolConfig(command="claude")
        mounts = tool.container_mounts(tmp_path, "developer", tmp_path)
        assert isinstance(mounts, list)
        # Should have at least the sessions dir mount
        assert len(mounts) >= 1
        # Each mount should be a tuple
        for mount in mounts:
            assert isinstance(mount, tuple)
            assert len(mount) == 3


class TestSessionNaming:
    """Tests for session naming functions in ids.py."""

    def test_session_name_basic(self) -> None:
        """Test basic session name generation."""
        from agenttree.ids import session_name

        result = session_name("myapp", "developer", 42)
        assert result == "myapp-developer-042"

    def test_session_name_with_padding(self) -> None:
        """Test session name pads issue IDs to 3 digits."""
        from agenttree.ids import session_name

        assert session_name("app", "dev", 1) == "app-dev-001"
        assert session_name("app", "dev", 99) == "app-dev-099"
        assert session_name("app", "dev", 100) == "app-dev-100"
        assert session_name("app", "dev", 1001) == "app-dev-1001"

    def test_session_name_custom_template(self) -> None:
        """Test session name with custom template."""
        from agenttree.ids import session_name

        result = session_name(
            "myapp", "serve", 42,
            template="{project}_{session_name}_{issue_id}"
        )
        assert result == "myapp_serve_042"

    def test_tmux_session_name_delegates(self) -> None:
        """Test tmux_session_name is a wrapper."""
        from agenttree.ids import tmux_session_name, session_name

        assert tmux_session_name("app", 42, "dev") == session_name("app", "dev", 42)

    def test_manager_session_name(self) -> None:
        """Test manager session name generation."""
        from agenttree.ids import manager_session_name

        assert manager_session_name("myapp") == "myapp-manager-000"

    def test_serve_session_name(self) -> None:
        """Test serve session name generation."""
        from agenttree.ids import serve_session_name

        assert serve_session_name("myapp", 42) == "myapp-serve-042"

    def test_container_type_session_name(self) -> None:
        """Test container type session name generation."""
        from agenttree.ids import container_type_session_name

        assert container_type_session_name("myapp", "sandbox", "my-sandbox") == "myapp-sandbox-my-sandbox"
        assert container_type_session_name("proj", "data-science", "analysis") == "proj-data-science-analysis"


class TestBuildContainerCommand:
    """Tests for build_container_command function."""

    def test_build_container_command_basic(self, tmp_path: Path) -> None:
        """Test basic container command building."""
        from agenttree.config import ToolConfig, ContainerTypeConfig
        from agenttree.container import build_container_command

        tool = ToolConfig(command="claude")
        container_type = ContainerTypeConfig(image="test-image:latest")

        cmd = build_container_command(
            runtime="docker",
            worktree_path=tmp_path,
            container_type=container_type,
            container_name="test-container",
            tool_config=tool,
            role="developer",
        )

        assert "docker" in cmd
        assert "run" in cmd
        assert "-it" in cmd
        assert "--name" in cmd
        assert "test-container" in cmd
        assert "test-image:latest" in cmd
        assert "claude" in cmd

    def test_build_container_command_includes_system_env(self, tmp_path: Path) -> None:
        """Test that system env vars are included."""
        from agenttree.config import ToolConfig, ContainerTypeConfig
        from agenttree.container import build_container_command

        tool = ToolConfig(command="claude")
        container_type = ContainerTypeConfig(
            image="agenttree-agent:latest",
            allow_dangerous=True,
        )

        cmd = build_container_command(
            runtime="docker",
            worktree_path=tmp_path,
            container_type=container_type,
            container_name="test",
            tool_config=tool,
            role="developer",
            issue_id=42,
        )

        cmd_str = " ".join(cmd)
        assert "AGENTTREE_CONTAINER=1" in cmd_str
        assert "AGENTTREE_ROLE=developer" in cmd_str
        assert "AGENTTREE_ISSUE_ID=42" in cmd_str

    def test_build_container_command_port_forwarding(self, tmp_path: Path) -> None:
        """Test that ports are forwarded correctly."""
        from agenttree.config import ToolConfig, ContainerTypeConfig
        from agenttree.container import build_container_command

        tool = ToolConfig(command="claude")
        container_type = ContainerTypeConfig(
            image="agenttree-agent:latest",
            allow_dangerous=True,
        )

        cmd = build_container_command(
            runtime="docker",
            worktree_path=tmp_path,
            container_type=container_type,
            container_name="test",
            tool_config=tool,
            role="developer",
            ports=[9042, 9142],
        )

        cmd_str = " ".join(cmd)
        assert "-p 9042:9042" in cmd_str
        assert "-p 9142:9142" in cmd_str

    def test_build_container_command_user_mounts(self, tmp_path: Path) -> None:
        """Test that user mounts from config are included."""
        from agenttree.config import ToolConfig, ContainerTypeConfig
        from agenttree.container import build_container_command

        tool = ToolConfig(command="claude")
        container_type = ContainerTypeConfig(
            image="agenttree-agent:latest",
            mounts=["/host/path:/container/path:ro"],
            allow_dangerous=True,
        )

        cmd = build_container_command(
            runtime="docker",
            worktree_path=tmp_path,
            container_type=container_type,
            container_name="test",
            tool_config=tool,
            role="developer",
        )

        cmd_str = " ".join(cmd)
        assert "/host/path:/container/path:ro" in cmd_str

    def test_build_container_command_user_env(self, tmp_path: Path) -> None:
        """Test that user env vars from config are included."""
        from agenttree.config import ToolConfig, ContainerTypeConfig
        from agenttree.container import build_container_command

        tool = ToolConfig(command="claude")
        container_type = ContainerTypeConfig(
            image="agenttree-agent:latest",
            env={"NODE_ENV": "development", "DEBUG": "true"},
            allow_dangerous=True,
        )

        cmd = build_container_command(
            runtime="docker",
            worktree_path=tmp_path,
            container_type=container_type,
            container_name="test",
            tool_config=tool,
            role="developer",
        )

        cmd_str = " ".join(cmd)
        assert "NODE_ENV=development" in cmd_str
        assert "DEBUG=true" in cmd_str

    def test_build_container_command_no_type_specific_conditionals(
        self, tmp_path: Path
    ) -> None:
        """Test that the same function works for all container types.

        This verifies the critical requirement: build_container_command has
        ZERO type-specific conditionals. Manager, issue, and sandbox containers
        all use the same code path with different configs.
        """
        from agenttree.config import ToolConfig, ContainerTypeConfig
        from agenttree.container import build_container_command

        tool = ToolConfig(command="claude")

        # "Manager" config
        manager_type = ContainerTypeConfig(
            image="agenttree-agent:latest",
            mounts=["~/.ssh:/home/agent/.ssh:ro"],
        )

        # "Issue" config
        issue_type = ContainerTypeConfig(
            image="agenttree-agent:latest",
        )

        # "Sandbox" config
        sandbox_type = ContainerTypeConfig(
            image="agenttree-agent:latest",
        )

        # All three should work with the same function
        for container_type, name in [
            (manager_type, "manager-test"),
            (issue_type, "issue-test"),
            (sandbox_type, "sandbox-test"),
        ]:
            cmd = build_container_command(
                runtime="docker",
                worktree_path=tmp_path,
                container_type=container_type,
                container_name=name,
                tool_config=tool,
                role="developer",
            )
            assert "docker" in cmd
            assert name in cmd

    def test_build_container_command_allow_dangerous_false(
        self, tmp_path: Path
    ) -> None:
        """Test that allow_dangerous=False disables dangerous mode."""
        from agenttree.config import ToolConfig, ContainerTypeConfig
        from agenttree.container import build_container_command

        tool = ToolConfig(command="claude")
        container_type = ContainerTypeConfig(
            image="agenttree-agent:latest",
            allow_dangerous=False,
        )

        cmd = build_container_command(
            runtime="docker",
            worktree_path=tmp_path,
            container_type=container_type,
            container_name="test",
            tool_config=tool,
            role="developer",
        )

        assert "--dangerously-skip-permissions" not in cmd


class TestDevServerUrl:
    """Tests for dev server URL functionality."""

    def test_get_dev_server_url_basic(self) -> None:
        """Test basic dev server URL generation."""
        from agenttree.config import Config

        config = Config(port_range="9000-9100")
        url = config.get_dev_server_url(42)
        assert url == "http://localhost:9042"

    def test_get_dev_server_url_custom_host(self) -> None:
        """Test dev server URL with custom host."""
        from agenttree.config import Config

        config = Config(port_range="9000-9100")
        url = config.get_dev_server_url(42, host="0.0.0.0")
        assert url == "http://0.0.0.0:9042"

    def test_get_dev_server_url_wrapping(self) -> None:
        """Test dev server URL with port wrapping."""
        from agenttree.config import Config

        config = Config(port_range="9000-9100")
        # Issue #100 wraps to 9100
        url = config.get_dev_server_url(100)
        assert url == "http://localhost:9100"
        # Issue #101 wraps to 9001
        url = config.get_dev_server_url(101)
        assert url == "http://localhost:9001"

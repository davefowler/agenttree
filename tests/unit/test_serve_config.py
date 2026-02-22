"""Tests for serve architecture configuration (Phase 1).

Tests for:
- SessionConfig model
- ContainerTypeConfig model
- resolve_container_type (extends resolution, mount accumulation, env merge)
- render_template (Jinja template rendering)
- infer_issue_id (environment variable inference)
"""

import os
import pytest

from agenttree.config import (
    Config,
    SessionConfig,
    ContainerTypeConfig,
    resolve_container_type,
    render_template,
)


class TestSessionConfig:
    """Tests for SessionConfig model."""

    def test_session_config_basic(self) -> None:
        """Test basic SessionConfig creation."""
        session = SessionConfig(command="npm run dev --port $PORT")
        assert session.command == "npm run dev --port $PORT"
        assert session.name_template is None
        assert session.ports == []
        assert session.pre_start == []
        assert session.post_stop == []

    def test_session_config_with_ports(self) -> None:
        """Test SessionConfig with port configuration."""
        session = SessionConfig(
            command="npm run dev --port {{ port }}",
            ports=["{{ port }}", "{{ port + 100 }}"],
        )
        assert session.ports == ["{{ port }}", "{{ port + 100 }}"]

    def test_session_config_with_hooks(self) -> None:
        """Test SessionConfig with lifecycle hooks."""
        session = SessionConfig(
            command="npm run dev",
            pre_start=[{"run": "npm install"}],
            post_stop=[{"run": "./scripts/cleanup.sh"}],
        )
        assert session.pre_start == [{"run": "npm install"}]
        assert session.post_stop == [{"run": "./scripts/cleanup.sh"}]

    def test_session_config_with_name_template(self) -> None:
        """Test SessionConfig with custom name template."""
        session = SessionConfig(
            command="npm run dev",
            name_template="{project}-web-{issue_id}",
        )
        assert session.name_template == "{project}-web-{issue_id}"


class TestContainerTypeConfig:
    """Tests for ContainerTypeConfig model."""

    def test_container_type_config_defaults(self) -> None:
        """Test ContainerTypeConfig default values."""
        config = ContainerTypeConfig()
        assert config.extends is None
        assert config.image == "agenttree-agent:latest"
        assert config.roles == []
        assert config.sessions == []
        assert config.interactive is False
        assert config.mounts == []
        assert config.env == {}
        assert config.allow_dangerous is True
        assert config.pre_start == []
        assert config.post_start == []
        assert config.pre_stop == []
        assert config.post_stop == []

    def test_container_type_config_with_values(self) -> None:
        """Test ContainerTypeConfig with explicit values."""
        config = ContainerTypeConfig(
            extends="_base",
            image="custom-image:latest",
            roles=["developer", "reviewer"],
            sessions=["serve", "worker"],
            interactive=True,
            mounts=["~/.ssh:/home/agent/.ssh:ro"],
            env={"NODE_ENV": "development"},
            allow_dangerous=False,
            post_start=[{"run": "npm install"}],
        )
        assert config.extends == "_base"
        assert config.image == "custom-image:latest"
        assert config.roles == ["developer", "reviewer"]
        assert config.sessions == ["serve", "worker"]
        assert config.interactive is True
        assert config.mounts == ["~/.ssh:/home/agent/.ssh:ro"]
        assert config.env == {"NODE_ENV": "development"}
        assert config.allow_dangerous is False
        assert config.post_start == [{"run": "npm install"}]


class TestResolveContainerType:
    """Tests for resolve_container_type function."""

    def test_resolve_simple_type(self) -> None:
        """Test resolving a container type with no extends."""
        containers = {
            "sandbox": ContainerTypeConfig(
                image="sandbox:latest",
                roles=["developer"],
            )
        }
        resolved = resolve_container_type("sandbox", containers)
        assert resolved.image == "sandbox:latest"
        assert resolved.roles == ["developer"]
        assert resolved.extends is None  # Resolved config has no extends

    def test_resolve_single_extends(self) -> None:
        """Test resolving with single inheritance."""
        containers = {
            "_base": ContainerTypeConfig(
                image="base:latest",
                post_start=[{"run": "setup.sh"}],
            ),
            "issue": ContainerTypeConfig(
                extends="_base",
                roles=["developer", "reviewer"],
                sessions=["serve"],
            ),
        }
        resolved = resolve_container_type("issue", containers)
        assert resolved.image == "base:latest"  # Inherited from _base
        assert resolved.roles == ["developer", "reviewer"]
        assert resolved.sessions == ["serve"]
        assert resolved.post_start == [{"run": "setup.sh"}]  # Inherited

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

    def test_resolve_hooks_replace(self) -> None:
        """Test that hooks are replaced, not accumulated."""
        containers = {
            "_base": ContainerTypeConfig(
                post_start=[{"run": "base-setup.sh"}],
            ),
            "issue": ContainerTypeConfig(
                extends="_base",
                post_start=[{"run": "issue-setup.sh"}],
            ),
        }
        resolved = resolve_container_type("issue", containers)
        # Child hooks replace parent hooks entirely
        assert resolved.post_start == [{"run": "issue-setup.sh"}]

    def test_resolve_hooks_inherited_when_child_empty(self) -> None:
        """Test that hooks are inherited when child has none."""
        containers = {
            "_base": ContainerTypeConfig(
                post_start=[{"run": "base-setup.sh"}],
            ),
            "issue": ContainerTypeConfig(
                extends="_base",
                roles=["developer"],
            ),
        }
        resolved = resolve_container_type("issue", containers)
        # Parent hooks are inherited
        assert resolved.post_start == [{"run": "base-setup.sh"}]

    def test_resolve_roles_replace(self) -> None:
        """Test that roles are replaced, not accumulated."""
        containers = {
            "_base": ContainerTypeConfig(
                roles=["developer"],
            ),
            "reviewer": ContainerTypeConfig(
                extends="_base",
                roles=["reviewer"],  # Replaces, not adds
            ),
        }
        resolved = resolve_container_type("reviewer", containers)
        assert resolved.roles == ["reviewer"]

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
        containers = {}
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


class TestInferIssueId:
    """Tests for infer_issue_id function."""

    def test_infer_issue_id_returns_none_when_not_set(self) -> None:
        """Test that infer_issue_id returns None when env var not set."""
        from agenttree.cli._utils import infer_issue_id

        # Clear the env var if set
        os.environ.pop("AGENTTREE_ISSUE_ID", None)
        result = infer_issue_id()
        assert result is None

    def test_infer_issue_id_parses_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that infer_issue_id parses the env var correctly."""
        from agenttree.cli._utils import infer_issue_id

        monkeypatch.setenv("AGENTTREE_ISSUE_ID", "42")
        result = infer_issue_id()
        assert result == 42

    def test_infer_issue_id_parses_padded_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that infer_issue_id handles zero-padded IDs."""
        from agenttree.cli._utils import infer_issue_id

        monkeypatch.setenv("AGENTTREE_ISSUE_ID", "007")
        result = infer_issue_id()
        assert result == 7


class TestConfigWithServeFields:
    """Tests for Config with new sessions/containers fields."""

    def test_config_has_sessions_field(self) -> None:
        """Test that Config has sessions field."""
        config = Config()
        assert config.sessions == {}

    def test_config_has_containers_field(self) -> None:
        """Test that Config has containers field."""
        config = Config()
        assert config.containers == {}

    def test_config_with_sessions(self) -> None:
        """Test Config with sessions configured."""
        config = Config(
            sessions={
                "serve": SessionConfig(
                    command="npm run dev --port {{ port }}",
                    ports=["{{ port }}"],
                ),
                "worker": SessionConfig(
                    command="python manage.py celery_worker",
                ),
            }
        )
        assert "serve" in config.sessions
        assert "worker" in config.sessions
        assert config.sessions["serve"].command == "npm run dev --port {{ port }}"

    def test_config_with_containers(self) -> None:
        """Test Config with containers configured."""
        config = Config(
            containers={
                "_base": ContainerTypeConfig(
                    image="agenttree-agent:latest",
                    post_start=[{"run": "npm install"}],
                ),
                "issue": ContainerTypeConfig(
                    extends="_base",
                    roles=["developer", "reviewer"],
                    sessions=["serve"],
                ),
            }
        )
        assert "_base" in config.containers
        assert "issue" in config.containers
        assert config.containers["issue"].extends == "_base"

"""Tests for configuration management."""

import tempfile
from pathlib import Path
import pytest
import yaml

from agenttree.config import Config, ToolConfig, load_config, find_config_file


class TestConfig:
    """Tests for Config model."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = Config()
        assert config.project == "myapp"
        assert config.worktrees_dir == Path.home() / "Projects" / "worktrees"
        assert config.port_range == "8001-8009"
        assert config.default_tool == "claude"

    def test_config_from_dict(self) -> None:
        """Test creating config from dictionary."""
        data = {
            "project": "testproject",
            "worktrees_dir": "/tmp/worktrees",
            "port_range": "9001-9009",
            "default_tool": "aider",
        }
        config = Config(**data)
        assert config.project == "testproject"
        assert config.worktrees_dir == Path("/tmp/worktrees")
        assert config.port_range == "9001-9009"
        assert config.default_tool == "aider"

    def test_config_with_tools(self) -> None:
        """Test config with tool configurations."""
        data = {
            "project": "test",
            "tools": {
                "claude": {
                    "command": "claude",
                    "startup_prompt": "Check TASK.md and start working.",
                },
                "aider": {
                    "command": "aider --model sonnet",
                    "startup_prompt": "/read TASK.md",
                },
            },
        }
        config = Config(**data)
        assert "claude" in config.tools
        assert "aider" in config.tools
        assert config.tools["claude"].command == "claude"
        assert config.tools["aider"].startup_prompt == "/read TASK.md"

    def test_get_port_for_agent(self) -> None:
        """Test getting port number for an agent."""
        config = Config(port_range="8001-8009")
        assert config.get_port_for_agent(1) == 8001
        assert config.get_port_for_agent(5) == 8005
        assert config.get_port_for_agent(9) == 8009

    def test_get_port_for_agent_out_of_range(self) -> None:
        """Test error when agent number exceeds port range."""
        config = Config(port_range="8001-8003")
        with pytest.raises(ValueError, match="Agent number 5 exceeds port range"):
            config.get_port_for_agent(5)

    def test_get_worktree_path(self) -> None:
        """Test getting worktree path for an agent."""
        config = Config(worktrees_dir="/tmp/worktrees")
        path = config.get_worktree_path(1)
        assert path == Path("/tmp/worktrees/agent-1")

    def test_get_tmux_session_name(self) -> None:
        """Test getting tmux session name for an agent."""
        config = Config(project="myapp")
        assert config.get_tmux_session_name(1) == "myapp-agent-1"
        assert config.get_tmux_session_name(3) == "myapp-agent-3"

    def test_get_tool_config(self) -> None:
        """Test getting tool configuration."""
        config = Config(
            tools={
                "claude": ToolConfig(
                    command="claude", startup_prompt="Start working"
                )
            }
        )
        tool = config.get_tool_config("claude")
        assert tool is not None
        assert tool.command == "claude"

    def test_get_tool_config_default(self) -> None:
        """Test getting default tool config when not found."""
        config = Config()
        tool = config.get_tool_config("nonexistent")
        assert tool is not None
        assert tool.command == "nonexistent"


class TestLoadConfig:
    """Tests for loading configuration from files."""

    def test_load_config_from_file(self, tmp_path: Path) -> None:
        """Test loading config from YAML file."""
        config_file = tmp_path / ".agenttree.yaml"
        config_data = {
            "project": "testproject",
            "worktrees_dir": str(tmp_path / "worktrees"),
            "default_tool": "aider",
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_config(tmp_path)
        assert config.project == "testproject"
        assert config.default_tool == "aider"

    def test_load_config_not_found(self, tmp_path: Path) -> None:
        """Test loading config when file doesn't exist (uses defaults)."""
        config = load_config(tmp_path)
        assert config.project == "myapp"  # Default value

    def test_find_config_file_in_current_dir(self, tmp_path: Path) -> None:
        """Test finding config file in current directory."""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text("project: test")

        found = find_config_file(tmp_path)
        assert found == config_file

    def test_find_config_file_in_parent_dir(self, tmp_path: Path) -> None:
        """Test finding config file in parent directory."""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text("project: test")

        subdir = tmp_path / "subdir"
        subdir.mkdir()

        found = find_config_file(subdir)
        assert found == config_file

    def test_find_config_file_not_found(self, tmp_path: Path) -> None:
        """Test when config file is not found."""
        found = find_config_file(tmp_path)
        assert found is None


class TestToolConfig:
    """Tests for ToolConfig model."""

    def test_tool_config_defaults(self) -> None:
        """Test default tool config values."""
        tool = ToolConfig(command="claude")
        assert tool.command == "claude"
        assert tool.startup_prompt == "Check TASK.md and start working."

    def test_tool_config_custom_prompt(self) -> None:
        """Test custom startup prompt."""
        tool = ToolConfig(
            command="aider --model sonnet", startup_prompt="/read TASK.md"
        )
        assert tool.command == "aider --model sonnet"
        assert tool.startup_prompt == "/read TASK.md"

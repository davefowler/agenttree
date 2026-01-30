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
        assert config.worktrees_dir == Path(".worktrees")
        assert config.port_range == "9001-9099"
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
        config = Config(project="myapp", worktrees_dir="/tmp/worktrees")
        path = config.get_worktree_path(1)
        assert path == Path("/tmp/worktrees/myapp-agent-1")

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

    def test_load_config_with_none_path(self, tmp_path: Path) -> None:
        """Test loading config with None path (uses current directory)."""
        # This test ensures line 123 is covered: path = Path.cwd()
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            config = load_config(None)
            # Should use defaults when no config file exists
            assert config.project == "myapp"
        finally:
            os.chdir(original_cwd)

    def test_load_config_with_empty_yaml(self, tmp_path: Path) -> None:
        """Test loading config from empty YAML file."""
        # This test ensures line 134 is covered: return Config() when data is None
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text("")  # Empty YAML file

        config = load_config(tmp_path)
        # Should use defaults when YAML is empty
        assert config.project == "myapp"


class TestToolConfig:
    """Tests for ToolConfig model."""

    def test_tool_config_defaults(self) -> None:
        """Test default tool config values."""
        tool = ToolConfig(command="claude")
        assert tool.command == "claude"
        assert tool.startup_prompt == "Check tasks/ folder and start working on the oldest task."

    def test_tool_config_custom_prompt(self) -> None:
        """Test custom startup prompt."""
        tool = ToolConfig(
            command="aider --model sonnet", startup_prompt="/read TASK.md"
        )
        assert tool.command == "aider --model sonnet"
        assert tool.startup_prompt == "/read TASK.md"


class TestHooksConfig:
    """Tests for HooksConfig model."""

    def test_hooks_config_empty_by_default(self) -> None:
        """HooksConfig should have empty lists by default."""
        from agenttree.config import HooksConfig

        hooks = HooksConfig()
        assert hooks.post_pr_create == []
        assert hooks.post_merge == []
        assert hooks.post_accepted == []

    def test_hooks_config_with_values(self) -> None:
        """HooksConfig should accept hook lists."""
        from agenttree.config import HooksConfig

        hooks = HooksConfig(
            post_pr_create=[{"command": "echo 'PR created'"}],
            post_merge=[{"command": "echo 'merged'"}],
            post_accepted=[{"command": "echo 'done'"}],
        )
        assert len(hooks.post_pr_create) == 1
        assert hooks.post_pr_create[0]["command"] == "echo 'PR created'"
        assert len(hooks.post_merge) == 1
        assert len(hooks.post_accepted) == 1


class TestMergeStrategyConfig:
    """Tests for merge_strategy config."""

    def test_merge_strategy_default_is_squash(self) -> None:
        """Default merge strategy should be squash."""
        config = Config()
        assert config.merge_strategy == "squash"

    def test_merge_strategy_configurable(self) -> None:
        """Merge strategy should be configurable."""
        config = Config(merge_strategy="rebase")
        assert config.merge_strategy == "rebase"

        config = Config(merge_strategy="merge")
        assert config.merge_strategy == "merge"

    def test_merge_strategy_from_yaml(self, tmp_path: Path) -> None:
        """Merge strategy should be loadable from YAML."""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text("merge_strategy: rebase")

        config = load_config(tmp_path)
        assert config.merge_strategy == "rebase"


class TestConfigHooksIntegration:
    """Tests for hooks config integration with main Config."""

    def test_config_has_hooks_by_default(self) -> None:
        """Config should have empty HooksConfig by default."""
        from agenttree.config import HooksConfig

        config = Config()
        assert isinstance(config.hooks, HooksConfig)
        assert config.hooks.post_pr_create == []

    def test_config_hooks_from_yaml(self, tmp_path: Path) -> None:
        """Hooks should be loadable from YAML."""
        config_file = tmp_path / ".agenttree.yaml"
        config_data = {
            "hooks": {
                "post_pr_create": [
                    {"command": "gh pr comment {{pr_number}} --body 'review please'", "host_only": True}
                ],
                "post_merge": [
                    {"command": "echo 'merged'"}
                ],
            }
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_config(tmp_path)
        assert len(config.hooks.post_pr_create) == 1
        assert config.hooks.post_pr_create[0]["host_only"] is True
        assert len(config.hooks.post_merge) == 1


class TestStageHookNaming:
    """Tests for pre_completion/post_start hook naming."""

    def test_substage_config_has_pre_completion(self) -> None:
        """SubstageConfig should have pre_completion field (renamed from on_exit)."""
        from agenttree.config import SubstageConfig

        substage = SubstageConfig(
            name="test",
            pre_completion=[{"type": "file_exists", "file": "test.md"}],
        )
        assert len(substage.pre_completion) == 1
        assert substage.pre_completion[0]["type"] == "file_exists"

    def test_substage_config_has_post_start(self) -> None:
        """SubstageConfig should have post_start field (renamed from on_enter)."""
        from agenttree.config import SubstageConfig

        substage = SubstageConfig(
            name="test",
            post_start=[{"command": "echo 'starting'"}],
        )
        assert len(substage.post_start) == 1
        assert substage.post_start[0]["command"] == "echo 'starting'"

    def test_stage_config_has_pre_completion(self) -> None:
        """StageConfig should have pre_completion field."""
        from agenttree.config import StageConfig

        stage = StageConfig(
            name="implement",
            pre_completion=[{"type": "create_pr"}],
        )
        assert len(stage.pre_completion) == 1

    def test_stage_config_has_post_start(self) -> None:
        """StageConfig should have post_start field."""
        from agenttree.config import StageConfig

        stage = StageConfig(
            name="research",
            post_start=[{"type": "create_file", "template": "research.md", "dest": "research.md"}],
        )
        assert len(stage.post_start) == 1

    def test_hooks_for_uses_new_names(self) -> None:
        """hooks_for() should work with pre_completion/post_start."""
        from agenttree.config import StageConfig, SubstageConfig

        stage = StageConfig(
            name="implement",
            pre_completion=[{"type": "create_pr"}],
            post_start=[{"type": "setup"}],
            substages={
                "code": SubstageConfig(
                    name="code",
                    pre_completion=[{"type": "has_commits"}],
                    post_start=[{"command": "echo 'coding'"}],
                ),
            },
        )

        # Stage-level hooks
        assert stage.hooks_for(None, "pre_completion") == [{"type": "create_pr"}]
        assert stage.hooks_for(None, "post_start") == [{"type": "setup"}]

        # Substage-level hooks
        assert stage.hooks_for("code", "pre_completion") == [{"type": "has_commits"}]
        assert stage.hooks_for("code", "post_start") == [{"command": "echo 'coding'"}]

    # DEFAULT_STAGES removed - config now comes entirely from .agenttree.yaml


class TestCommandsConfig:
    """Tests for commands config field."""

    def test_commands_field_defaults_to_empty_dict(self) -> None:
        """Commands field should default to empty dict."""
        config = Config()
        assert config.commands == {}

    def test_commands_field_accepts_dict(self) -> None:
        """Commands field should accept dict of name to command."""
        config = Config(
            commands={
                "test": "pytest",
                "lint": "ruff check .",
            }
        )
        assert config.commands["test"] == "pytest"
        assert config.commands["lint"] == "ruff check ."

    def test_commands_supports_list_values(self) -> None:
        """Commands field should accept list of commands."""
        config = Config(
            commands={
                "lint": ["ruff check .", "mypy src/"],
            }
        )
        assert config.commands["lint"] == ["ruff check .", "mypy src/"]

    def test_commands_from_yaml(self, tmp_path: Path) -> None:
        """Commands should be loadable from YAML config."""
        config_file = tmp_path / ".agenttree.yaml"
        config_data = {
            "commands": {
                "test": "pytest",
                "lint": "ruff check .",
                "git_branch": "git branch --show-current",
            }
        }
        config_file.write_text(yaml.dump(config_data))

        config = load_config(tmp_path)
        assert config.commands["test"] == "pytest"
        assert config.commands["git_branch"] == "git branch --show-current"

    def test_commands_from_yaml_with_list(self, tmp_path: Path) -> None:
        """Commands with list values should be loadable from YAML."""
        config_file = tmp_path / ".agenttree.yaml"
        config_content = """
commands:
  test: pytest
  lint:
    - ruff check .
    - mypy src/
"""
        config_file.write_text(config_content)

        config = load_config(tmp_path)
        assert config.commands["test"] == "pytest"
        assert config.commands["lint"] == ["ruff check .", "mypy src/"]

    def test_commands_mixed_string_and_list(self) -> None:
        """Commands field should support mixed string and list values."""
        config = Config(
            commands={
                "test": "pytest",
                "lint": ["ruff check .", "mypy src/"],
                "git_branch": "git branch --show-current",
            }
        )
        assert isinstance(config.commands["test"], str)
        assert isinstance(config.commands["lint"], list)


class TestRedirectOnlyStages:
    """Tests for redirect_only stage behavior."""

    def test_redirect_only_stage_skipped_in_normal_progression(self) -> None:
        """Stages with redirect_only=True should be skipped in normal stage progression."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages=[
                StageConfig(name="implement"),
                StageConfig(name="independent_code_review"),
                StageConfig(name="address_independent_review", redirect_only=True),  # Should be skipped
                StageConfig(name="implementation_review"),
                StageConfig(name="accepted", terminal=True),
            ]
        )

        # From independent_code_review, should go to implementation_review, skipping address_independent_review
        next_stage, next_substage, is_terminal = config.get_next_stage("independent_code_review")
        assert next_stage == "implementation_review"
        assert next_substage is None
        assert is_terminal is False

    def test_redirect_only_stage_not_included_in_normal_order(self) -> None:
        """redirect_only stages should be accessible but skipped during normal progression."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages=[
                StageConfig(name="implement"),
                StageConfig(name="review", redirect_only=True),
                StageConfig(name="accepted", terminal=True),
            ]
        )

        # From implement, should go directly to accepted, skipping redirect_only review
        next_stage, next_substage, is_terminal = config.get_next_stage("implement")
        assert next_stage == "accepted"
        assert is_terminal is True

    def test_redirect_only_stage_can_still_be_entered_directly(self) -> None:
        """redirect_only stages should still be retrievable and configurable."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages=[
                StageConfig(name="implement"),
                StageConfig(
                    name="address_review",
                    redirect_only=True,
                    host="agent",
                    output="response.md"
                ),
                StageConfig(name="accepted", terminal=True),
            ]
        )

        # Stage should exist and be retrievable
        stage = config.get_stage("address_review")
        assert stage is not None
        assert stage.redirect_only is True
        assert stage.host == "agent"
        assert stage.output == "response.md"

    def test_multiple_consecutive_redirect_only_stages_skipped(self) -> None:
        """Multiple consecutive redirect_only stages should all be skipped."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages=[
                StageConfig(name="implement"),
                StageConfig(name="address_review1", redirect_only=True),
                StageConfig(name="address_review2", redirect_only=True),
                StageConfig(name="final_review"),
                StageConfig(name="accepted", terminal=True),
            ]
        )

        # From implement, should skip both redirect_only stages
        next_stage, next_substage, is_terminal = config.get_next_stage("implement")
        assert next_stage == "final_review"

    def test_redirect_only_defaults_to_false(self) -> None:
        """StageConfig redirect_only should default to False."""
        from agenttree.config import StageConfig

        stage = StageConfig(name="test")
        assert stage.redirect_only is False

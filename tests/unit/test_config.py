"""Tests for configuration management."""

import tempfile
from pathlib import Path
import pytest
import yaml

from agenttree.config import (
    Config,
    ToolConfig,
    load_config,
    find_config_file,
    StageConfig,
    SubstageConfig,
    RoleConfig,
)


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

    def test_get_port_for_agent_raises_when_exceeding_range(self) -> None:
        """Test get_port_for_agent raises ValueError when agent num exceeds range."""
        config = Config(port_range="8001-8009")
        # Range is 9 ports (8001-8009). Agent 10 exceeds the range.
        with pytest.raises(ValueError, match="Agent number 10 exceeds port range"):
            config.get_port_for_agent(10)
        with pytest.raises(ValueError, match="exceeds port range"):
            config.get_port_for_agent(19)

    def test_get_port_for_issue(self) -> None:
        """Test getting port number for an issue ID."""
        config = Config(port_range="9001-9099")
        assert config.get_port_for_issue("001") == 9001
        assert config.get_port_for_issue("042") == 9042
        assert config.get_port_for_issue("99") == 9099

    def test_get_port_for_issue_custom_range(self) -> None:
        """Test port for issue uses configured port_range."""
        config = Config(port_range="8001-8009")
        assert config.get_port_for_issue("1") == 8001
        assert config.get_port_for_issue("5") == 8005

    def test_get_port_for_issue_returns_none_when_exceeding_range(self) -> None:
        """Test get_port_for_issue returns None when issue num exceeds port range."""
        config = Config(port_range="9001-9099")
        # Range is 99 ports. Issue 100 exceeds (port 9100 > 9099).
        assert config.get_port_for_issue("100") is None
        assert config.get_port_for_issue("999") is None

    def test_get_port_for_issue_returns_port_for_valid_id_in_range(self) -> None:
        """Test that valid numeric issue IDs in range get a port."""
        config = Config(port_range="9001-9009")
        # IDs 1-9 map to ports 9001-9009
        assert config.get_port_for_issue("1") == 9001
        assert config.get_port_for_issue("9") == 9009

    def test_get_port_for_issue_invalid_id(self) -> None:
        """Test returns None for non-numeric issue IDs."""
        config = Config(port_range="9001-9099")
        assert config.get_port_for_issue("invalid") is None
        assert config.get_port_for_issue("abc") is None
        assert config.get_port_for_issue("") is None

    def test_get_worktree_path(self) -> None:
        """Test getting worktree path for an agent."""
        config = Config(project="myapp", worktrees_dir="/tmp/worktrees")
        path = config.get_worktree_path(1)
        assert path == Path("/tmp/worktrees/myapp-agent-1")

    def test_get_tmux_session_name(self) -> None:
        """Test getting tmux session name for an agent."""
        config = Config(project="myapp")
        # Standardized on -developer- naming pattern
        assert config.get_tmux_session_name(1) == "myapp-developer-1"
        assert config.get_tmux_session_name(3) == "myapp-developer-3"

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


class TestModelPerStageConfig:
    """Tests for model-per-stage configuration."""

    def test_stage_config_has_model_field(self) -> None:
        """StageConfig should accept optional model field."""
        from agenttree.config import StageConfig

        stage = StageConfig(name="research", model="haiku")
        assert stage.model == "haiku"

    def test_stage_config_model_defaults_to_none(self) -> None:
        """StageConfig model should default to None."""
        from agenttree.config import StageConfig

        stage = StageConfig(name="research")
        assert stage.model is None

    def test_substage_config_has_model_field(self) -> None:
        """SubstageConfig should accept optional model field."""
        from agenttree.config import SubstageConfig

        substage = SubstageConfig(name="code_review", model="opus")
        assert substage.model == "opus"

    def test_substage_config_model_defaults_to_none(self) -> None:
        """SubstageConfig model should default to None."""
        from agenttree.config import SubstageConfig

        substage = SubstageConfig(name="code")
        assert substage.model is None

    def test_model_for_returns_default_when_not_specified(self) -> None:
        """model_for() should return default_model when stage has no model."""
        from agenttree.config import StageConfig

        config = Config(
            default_model="opus",
            stages={"research": StageConfig(name="research")}
        )
        assert config.model_for("research") == "opus"

    def test_model_for_returns_stage_model(self) -> None:
        """model_for() should return stage-level model when specified."""
        from agenttree.config import StageConfig

        config = Config(
            default_model="opus",
            stages={"research": StageConfig(name="research", model="haiku")}
        )
        assert config.model_for("research") == "haiku"

    def test_model_for_returns_substage_model(self) -> None:
        """model_for() should return substage model when specified (overrides stage)."""
        from agenttree.config import StageConfig, SubstageConfig

        config = Config(
            default_model="opus",
            stages={
                "implement": StageConfig(
                    name="implement",
                    model="sonnet",
                    substages={
                        "code_review": SubstageConfig(name="code_review", model="opus")
                    }
                )
            }
        )
        assert config.model_for("implement.code_review") == "opus"

    def test_model_for_substage_inherits_from_stage(self) -> None:
        """When substage has no model but stage does, use stage model."""
        from agenttree.config import StageConfig, SubstageConfig

        config = Config(
            default_model="opus",
            stages={
                "implement": StageConfig(
                    name="implement",
                    model="sonnet",
                    substages={
                        "code": SubstageConfig(name="code")
                    }
                )
            }
        )
        assert config.model_for("implement.code") == "sonnet"

    def test_model_for_unknown_stage(self) -> None:
        """model_for() should return default_model for unknown stage name."""
        config = Config(default_model="opus", stages={})
        assert config.model_for("nonexistent") == "opus"

    def test_model_from_yaml(self, tmp_path: Path) -> None:
        """model config should load correctly from YAML file."""
        config_file = tmp_path / ".agenttree.yaml"
        config_content = """
default_model: sonnet
flows:
  default:
    stages:
      research:
        model: haiku
      implement:
        model: opus
        substages:
          code_review:
            model: gpt-5.2
"""
        config_file.write_text(config_content)

        config = load_config(tmp_path)
        assert config.default_model == "sonnet"
        assert config.model_for("research") == "haiku"
        assert config.model_for("implement") == "opus"
        assert config.model_for("implement.code_review") == "gpt-5.2"


class TestRedirectOnlyStages:
    """Tests for redirect_only stage behavior."""

    def test_redirect_only_stage_skipped_in_normal_progression(self) -> None:
        """Stages with redirect_only=True should be skipped in normal stage progression."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages={
                "implement": StageConfig(name="implement"),
                "independent_code_review": StageConfig(name="independent_code_review"),
                "address_independent_review": StageConfig(name="address_independent_review", redirect_only=True),  # Should be skipped
                "implementation_review": StageConfig(name="implementation_review"),
                "accepted": StageConfig(name="accepted", is_parking_lot=True),
            }
        )

        # From independent_code_review, should go to implementation_review, skipping address_independent_review
        next_dot_path, is_human_review = config.get_next_stage("independent_code_review")
        assert next_dot_path == "implementation_review"
        assert is_human_review is False

    def test_redirect_only_stage_not_included_in_normal_order(self) -> None:
        """redirect_only stages should be accessible but skipped during normal progression."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages={
                "implement": StageConfig(name="implement"),
                "review": StageConfig(name="review", redirect_only=True),
                "accepted": StageConfig(name="accepted", is_parking_lot=True),
            }
        )

        # From implement, should go directly to accepted, skipping redirect_only review
        # Note: get_next_stage returns (dot_path, is_human_review)
        next_dot_path, human_review = config.get_next_stage("implement")
        assert next_dot_path == "accepted"
        # accepted is parking_lot but human_review is False
        assert human_review is False
        # Verify accepted is indeed a parking lot
        assert config.is_parking_lot("accepted") is True
        # Check human_review via config lookup
        assert config.get_stage("accepted").human_review is False

    def test_redirect_only_stage_can_still_be_entered_directly(self) -> None:
        """redirect_only stages should still be retrievable and configurable."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages={
                "implement": StageConfig(name="implement"),
                "address_review": StageConfig(
                    name="address_review",
                    redirect_only=True,
                    role="developer",
                    output="response.md"
                ),
                "accepted": StageConfig(name="accepted", is_parking_lot=True),
            }
        )

        # Stage should exist and be retrievable
        stage = config.get_stage("address_review")
        assert stage is not None
        assert stage.redirect_only is True
        assert stage.role == "developer"
        assert stage.output == "response.md"

    def test_multiple_consecutive_redirect_only_stages_skipped(self) -> None:
        """Multiple consecutive redirect_only stages should all be skipped."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages={
                "implement": StageConfig(name="implement"),
                "address_review1": StageConfig(name="address_review1", redirect_only=True),
                "address_review2": StageConfig(name="address_review2", redirect_only=True),
                "final_review": StageConfig(name="final_review"),
                "accepted": StageConfig(name="accepted", is_parking_lot=True),
            }
        )

        # From implement, should skip both redirect_only stages
        next_dot_path, is_human_review = config.get_next_stage("implement")
        assert next_dot_path == "final_review"

    def test_redirect_only_defaults_to_false(self) -> None:
        """StageConfig redirect_only should default to False."""
        from agenttree.config import StageConfig

        stage = StageConfig(name="test")
        assert stage.redirect_only is False


class TestSaveTmuxHistoryConfig:
    """Tests for save_tmux_history config option."""

    def test_save_tmux_history_defaults_to_false(self) -> None:
        """save_tmux_history should default to False."""
        config = Config()
        assert config.save_tmux_history is False

    def test_save_tmux_history_can_be_enabled(self) -> None:
        """save_tmux_history should be configurable to True."""
        config = Config(save_tmux_history=True)
        assert config.save_tmux_history is True

    def test_save_tmux_history_from_yaml(self, tmp_path: Path) -> None:
        """save_tmux_history should be loadable from YAML config."""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text("save_tmux_history: true")

        config = load_config(tmp_path)
        assert config.save_tmux_history is True

    def test_save_tmux_history_false_from_yaml(self, tmp_path: Path) -> None:
        """save_tmux_history: false should be loadable from YAML config."""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text("save_tmux_history: false")

        config = load_config(tmp_path)
        assert config.save_tmux_history is False


class TestConditionalStages:
    """Tests for conditional stage execution."""

    def test_stage_config_has_condition_field(self) -> None:
        """StageConfig should accept optional condition field."""
        from agenttree.config import StageConfig

        stage = StageConfig(name="ui_review", condition="{{ needs_ui_review }}")
        assert stage.condition == "{{ needs_ui_review }}"

    def test_stage_config_condition_defaults_to_none(self) -> None:
        """StageConfig condition should default to None."""
        from agenttree.config import StageConfig

        stage = StageConfig(name="research")
        assert stage.condition is None

    def test_get_next_stage_skips_false_condition(self) -> None:
        """Stage with condition evaluating to false should be skipped."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages={
                "implement": StageConfig(name="implement"),
                "ui_review": StageConfig(name="ui_review", condition="{{ needs_ui_review }}"),
                "final_review": StageConfig(name="final_review"),
                "accepted": StageConfig(name="accepted", terminal=True),
            }
        )

        # Context where needs_ui_review is False
        context = {"needs_ui_review": False}

        # From implement, should skip ui_review (condition is false) and go to final_review
        next_dot_path, is_human_review = config.get_next_stage(
            "implement", issue_context=context
        )
        assert next_dot_path == "final_review"

    def test_get_next_stage_runs_true_condition(self) -> None:
        """Stage with condition evaluating to true should be entered."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages={
                "implement": StageConfig(name="implement"),
                "ui_review": StageConfig(name="ui_review", condition="{{ needs_ui_review }}"),
                "final_review": StageConfig(name="final_review"),
                "accepted": StageConfig(name="accepted", terminal=True),
            }
        )

        # Context where needs_ui_review is True
        context = {"needs_ui_review": True}

        # From implement, should go to ui_review (condition is true)
        next_dot_path, is_human_review = config.get_next_stage(
            "implement", issue_context=context
        )
        assert next_dot_path == "ui_review"

    def test_get_next_stage_no_condition_runs(self) -> None:
        """Stage without condition field should always run (backward compatible)."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages={
                "implement": StageConfig(name="implement"),
                "review": StageConfig(name="review"),  # No condition - should always run
                "accepted": StageConfig(name="accepted", terminal=True),
            }
        )

        # Even with empty context, stage without condition should run
        next_dot_path, is_human_review = config.get_next_stage(
            "implement", issue_context={}
        )
        assert next_dot_path == "review"

    def test_get_next_stage_no_context_skips_condition(self) -> None:
        """Stage with condition should be skipped when no context provided."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages={
                "implement": StageConfig(name="implement"),
                "ui_review": StageConfig(name="ui_review", condition="{{ needs_ui_review }}"),
                "final_review": StageConfig(name="final_review"),
                "accepted": StageConfig(name="accepted", terminal=True),
            }
        )

        # No context provided - condition should evaluate to falsy, stage skipped
        next_dot_path, is_human_review = config.get_next_stage(
            "implement"
        )
        assert next_dot_path == "final_review"

    def test_get_next_stage_missing_context_var_skips(self) -> None:
        """Condition referencing undefined variable should evaluate to falsy."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages={
                "implement": StageConfig(name="implement"),
                "ui_review": StageConfig(name="ui_review", condition="{{ some_undefined_var }}"),
                "final_review": StageConfig(name="final_review"),
                "accepted": StageConfig(name="accepted", terminal=True),
            }
        )

        # Context without the variable referenced in condition
        context = {"other_var": True}

        # Missing variable should evaluate to falsy, stage skipped
        next_dot_path, is_human_review = config.get_next_stage(
            "implement", issue_context=context
        )
        assert next_dot_path == "final_review"

    def test_get_next_stage_invalid_condition_raises(self) -> None:
        """Invalid Jinja in condition should raise - config errors crash loudly."""
        from jinja2 import TemplateSyntaxError

        from agenttree.config import Config, StageConfig

        config = Config(
            stages={
                "implement": StageConfig(name="implement"),
                "ui_review": StageConfig(name="ui_review", condition="{{ invalid {{ syntax }}"),
                "final_review": StageConfig(name="final_review"),
                "accepted": StageConfig(name="accepted", terminal=True),
            }
        )

        with pytest.raises(TemplateSyntaxError):
            config.get_next_stage("implement", issue_context={})

    def test_condition_and_redirect_only_combined(self) -> None:
        """redirect_only should take precedence over condition in normal progression."""
        from agenttree.config import Config, StageConfig

        config = Config(
            stages={
                "implement": StageConfig(name="implement"),
                "address_review": StageConfig(name="address_review", redirect_only=True, condition="{{ True }}"),
                "final_review": StageConfig(name="final_review"),
                "accepted": StageConfig(name="accepted", terminal=True),
            }
        )

        # redirect_only stages are always skipped in normal progression, regardless of condition
        next_dot_path, is_human_review = config.get_next_stage(
            "implement", issue_context={"something": True}
        )
        assert next_dot_path == "final_review"

    def test_condition_from_yaml(self, tmp_path: Path) -> None:
        """condition config should load correctly from YAML file."""
        config_file = tmp_path / ".agenttree.yaml"
        config_content = """
flows:
  default:
    stages:
      implement: {}
      ui_review:
        condition: "{{ needs_ui_review }}"
      accepted:
        terminal: true
"""
        config_file.write_text(config_content)

        config = load_config(tmp_path)
        ui_review = config.get_stage("ui_review")
        assert ui_review is not None
        assert ui_review.condition == "{{ needs_ui_review }}"


class TestModelTiers:
    """Tests for model tier abstraction feature."""

    # Tier mapping configuration tests

    def test_model_tiers_default_empty(self) -> None:
        """model_tiers should default to empty dict."""
        config = Config()
        assert config.model_tiers == {}

    def test_model_tiers_from_yaml(self, tmp_path: Path) -> None:
        """model_tiers should load correctly from YAML config."""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text("""
model_tiers:
  high: opus
  medium: sonnet
  low: haiku
""")
        config = load_config(tmp_path)
        assert config.model_tiers == {"high": "opus", "medium": "sonnet", "low": "haiku"}

    # Tier resolution in model_for() tests

    def test_model_for_with_tier_returns_mapped_model(self) -> None:
        """model_for() should return the mapped model when tier is specified."""
        config = Config(
            default_model="opus",
            model_tiers={"high": "opus", "medium": "sonnet", "low": "haiku"},
            stages={"research": StageConfig(name="research", model_tier="low")}
        )
        assert config.model_for("research") == "haiku"

    def test_model_for_model_overrides_tier(self) -> None:
        """Explicit model should take precedence over model_tier."""
        config = Config(
            default_model="opus",
            model_tiers={"high": "opus", "medium": "sonnet", "low": "haiku"},
            stages={"research": StageConfig(name="research", model="gpt-5", model_tier="low")}
        )
        assert config.model_for("research") == "gpt-5"

    def test_model_for_tier_overrides_default(self) -> None:
        """model_tier should take precedence over default_model."""
        config = Config(
            default_model="opus",
            model_tiers={"fast": "haiku"},
            stages={"research": StageConfig(name="research", model_tier="fast")}
        )
        assert config.model_for("research") == "haiku"

    def test_model_for_unknown_tier_returns_default(self) -> None:
        """Unknown tier should fall back to default_model."""
        config = Config(
            default_model="opus",
            model_tiers={"high": "opus"},
            stages={"research": StageConfig(name="research", model_tier="ultra")}  # Not in model_tiers
        )
        assert config.model_for("research") == "opus"

    def test_model_for_substage_tier_overrides_stage_tier(self) -> None:
        """Substage tier should override stage tier."""
        config = Config(
            default_model="opus",
            model_tiers={"high": "opus", "low": "haiku"},
            stages={
                "implement": StageConfig(
                    name="implement",
                    model_tier="high",
                    substages={
                        "code_review": SubstageConfig(name="code_review", model_tier="low")
                    }
                )
            }
        )
        assert config.model_for("implement") == "opus"  # Stage tier
        assert config.model_for("implement.code_review") == "haiku"  # Substage tier

    # Stage/Substage tier field tests

    def test_stage_config_has_model_tier_field(self) -> None:
        """StageConfig should have model_tier field."""
        stage = StageConfig(name="research", model_tier="high")
        assert stage.model_tier == "high"

    def test_substage_config_has_model_tier_field(self) -> None:
        """SubstageConfig should have model_tier field."""
        substage = SubstageConfig(name="code", model_tier="low")
        assert substage.model_tier == "low"

    def test_role_config_has_model_tier_field(self) -> None:
        """RoleConfig should have model_tier field for future use."""
        role = RoleConfig(name="reviewer", model_tier="medium")
        assert role.model_tier == "medium"

    # Edge cases

    def test_model_for_empty_model_tiers_ignores_tier(self) -> None:
        """Empty model_tiers should cause tier to be ignored."""
        config = Config(
            default_model="opus",
            model_tiers={},  # No tier mappings
            stages={"research": StageConfig(name="research", model_tier="high")}
        )
        assert config.model_for("research") == "opus"  # Falls through to default

    def test_model_tier_none_uses_model(self) -> None:
        """None model_tier should not override model field."""
        config = Config(
            default_model="opus",
            model_tiers={"high": "opus"},
            stages={"research": StageConfig(name="research", model="sonnet", model_tier=None)}
        )
        assert config.model_for("research") == "sonnet"

    def test_substage_model_overrides_substage_tier(self) -> None:
        """Substage model should override substage tier."""
        config = Config(
            default_model="opus",
            model_tiers={"low": "haiku"},
            stages={
                "implement": StageConfig(
                    name="implement",
                    substages={
                        "code_review": SubstageConfig(
                            name="code_review",
                            model="sonnet",
                            model_tier="low"
                        )
                    }
                )
            }
        )
        assert config.model_for("implement.code_review") == "sonnet"

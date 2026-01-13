"""Configuration management for AgentTree."""

from pathlib import Path
from typing import Dict, Optional
import yaml
from pydantic import BaseModel, ConfigDict, Field


class ToolConfig(BaseModel):
    """Configuration for an AI tool."""

    command: str
    startup_prompt: str = "Check tasks/ folder and start working on the oldest task."
    skip_permissions: bool = False  # Add --dangerously-skip-permissions to command


class SubstageConfig(BaseModel):
    """Configuration for a workflow substage."""

    name: str
    output: Optional[str] = None  # Document created by this substage
    skill: Optional[str] = None   # Override skill file path
    validators: list[str] = Field(default_factory=list)


class StageConfig(BaseModel):
    """Configuration for a workflow stage."""

    name: str
    output: Optional[str] = None  # Document created by this stage
    skill: Optional[str] = None   # Override skill file path
    human_review: bool = False
    triggers_merge: bool = False
    terminal: bool = False  # Cannot progress from here
    substages: Dict[str, SubstageConfig] = Field(default_factory=dict)

    def substage_order(self) -> list[str]:
        """Get ordered list of substage names."""
        return list(self.substages.keys())

    def get_substage(self, name: str) -> Optional[SubstageConfig]:
        """Get a substage by name."""
        return self.substages.get(name)


# Default stages if not configured in .agenttree.yaml
DEFAULT_STAGES = [
    StageConfig(name="backlog"),
    StageConfig(
        name="define",
        output="problem.md",
        substages={
            "draft": SubstageConfig(name="draft"),
            "refine": SubstageConfig(name="refine"),
        }
    ),
    StageConfig(name="problem_review", human_review=True),
    StageConfig(
        name="research",
        output="research.md",
        substages={
            "explore": SubstageConfig(name="explore"),
            "document": SubstageConfig(name="document"),
        }
    ),
    StageConfig(
        name="plan",
        output="spec.md",
        substages={
            "draft": SubstageConfig(name="draft"),
            "refine": SubstageConfig(name="refine"),
        }
    ),
    StageConfig(name="plan_assess", output="spec_review.md"),
    StageConfig(name="plan_revise", output="spec.md"),
    StageConfig(name="plan_review", human_review=True),
    StageConfig(
        name="implement",
        substages={
            "setup": SubstageConfig(name="setup"),
            "test": SubstageConfig(name="test"),
            "code": SubstageConfig(name="code"),
            "debug": SubstageConfig(name="debug"),
            "code_review": SubstageConfig(name="code_review", output="review.md", validators=["require_commits"]),
            "address_review": SubstageConfig(name="address_review"),
            "wrapup": SubstageConfig(name="wrapup", validators=["require_wrapup_score"]),
        }
    ),
    StageConfig(name="implementation_review", human_review=True),
    StageConfig(name="accepted", triggers_merge=True),
    StageConfig(name="not_doing", terminal=True),
]


class SecurityConfig(BaseModel):
    """Security configuration for agents.

    NOTE: Containers are MANDATORY. There is no option to disable them.
    This config exists for future security settings, not to bypass containers.
    """

    # Reserved for future security settings
    # Containers are always required - this is not configurable


class Config(BaseModel):
    """AgentTree configuration."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    project: str = "myapp"
    worktrees_dir: Path = Field(default_factory=lambda: Path(".worktrees"))
    scripts_dir: Path = Field(default_factory=lambda: Path("scripts"))
    port_range: str = "9001-9099"
    default_tool: str = "claude"
    default_model: str = "opus"  # Model to use for Claude CLI (opus, sonnet)
    refresh_interval: int = 10
    tools: Dict[str, ToolConfig] = Field(default_factory=dict)
    stages: list[StageConfig] = Field(default_factory=lambda: DEFAULT_STAGES.copy())
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    def get_port_for_agent(self, agent_num: int) -> int:
        """Get port number for a specific agent.

        Args:
            agent_num: Agent number (1-based)

        Returns:
            Port number for the agent

        Raises:
            ValueError: If agent number exceeds port range
        """
        start_port, end_port = map(int, self.port_range.split("-"))
        port = start_port + (agent_num - 1)

        if port > end_port:
            raise ValueError(
                f"Agent number {agent_num} exceeds port range {self.port_range}"
            )

        return port

    def get_worktree_path(self, agent_num: int) -> Path:
        """Get worktree path for a specific agent (legacy numbered agents).

        Args:
            agent_num: Agent number

        Returns:
            Path to the agent's worktree
        """
        expanded_dir = Path(self.worktrees_dir).expanduser()
        return expanded_dir / f"{self.project}-agent-{agent_num}"

    def get_issue_worktree_path(self, issue_id: str, slug: str) -> Path:
        """Get worktree path for an issue-bound agent.

        Args:
            issue_id: Issue ID (e.g., "023")
            slug: Issue slug (e.g., "fix-login-bug")

        Returns:
            Path to the issue's worktree
        """
        expanded_dir = Path(self.worktrees_dir).expanduser()
        short_slug = slug[:30] if len(slug) > 30 else slug
        return expanded_dir / f"issue-{issue_id}-{short_slug}"

    def get_tmux_session_name(self, agent_num: int) -> str:
        """Get tmux session name for a specific agent (legacy numbered agents).

        Args:
            agent_num: Agent number

        Returns:
            Tmux session name
        """
        return f"{self.project}-agent-{agent_num}"

    def get_issue_tmux_session(self, issue_id: str) -> str:
        """Get tmux session name for an issue-bound agent.

        Args:
            issue_id: Issue ID

        Returns:
            Tmux session name
        """
        return f"{self.project}-issue-{issue_id}"

    def get_issue_container_name(self, issue_id: str) -> str:
        """Get container name for an issue-bound agent.

        Args:
            issue_id: Issue ID

        Returns:
            Container name
        """
        return f"{self.project}-issue-{issue_id}"

    def get_tool_config(self, tool_name: str) -> ToolConfig:
        """Get configuration for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool configuration (creates default if not found)
        """
        if tool_name in self.tools:
            return self.tools[tool_name]

        # Return default config for unknown tools
        return ToolConfig(command=tool_name)

    def get_ci_script(self, script_name: str = "ci.sh") -> Path:
        """Get path to a CI script.

        Args:
            script_name: Name of the script (ci.sh, quick_ci.sh, extensive_ci.sh)

        Returns:
            Path to the script
        """
        return self.scripts_dir / script_name

    def get_stage(self, stage_name: str) -> Optional[StageConfig]:
        """Get configuration for a stage.

        Args:
            stage_name: Name of the stage

        Returns:
            Stage configuration, or None if not found
        """
        for stage in self.stages:
            if stage.name == stage_name:
                return stage
        return None

    def get_stage_names(self) -> list[str]:
        """Get list of all stage names in order.

        Returns:
            List of stage names
        """
        return [stage.name for stage in self.stages]

    def get_human_review_stages(self) -> list[str]:
        """Get list of stages that require human review.

        Returns:
            List of stage names that require human review
        """
        return [stage.name for stage in self.stages if stage.human_review]

    def substages_for(self, stage_name: str) -> list[str]:
        """Get ordered list of substage names for a stage.

        Args:
            stage_name: Name of the stage

        Returns:
            List of substage names (empty if no substages)
        """
        stage = self.get_stage(stage_name)
        if stage is None:
            return []
        return stage.substage_order()

    def skill_path(self, stage_name: str, substage: Optional[str] = None) -> str:
        """Get the skill file path for a stage/substage.

        Convention: skills/{stage}.md or skills/{stage}/{substage}.md
        Can be overridden with explicit skill property in config.

        Args:
            stage_name: Name of the stage
            substage: Optional substage name

        Returns:
            Relative path to skill file (from _agenttree/)
        """
        stage = self.get_stage(stage_name)

        # Check for explicit override
        if substage and stage:
            substage_config = stage.get_substage(substage)
            if substage_config and substage_config.skill:
                return f"skills/{substage_config.skill}"
        if stage and stage.skill:
            return f"skills/{stage.skill}"

        # Use convention: skills/{stage}/{substage}.md or skills/{stage}.md
        if substage:
            return f"skills/{stage_name}/{substage}.md"
        return f"skills/{stage_name}.md"

    def output_for(self, stage_name: str, substage: Optional[str] = None) -> Optional[str]:
        """Get the output document name for a stage/substage.

        Args:
            stage_name: Name of the stage
            substage: Optional substage name

        Returns:
            Document name (e.g., "problem.md") or None
        """
        stage = self.get_stage(stage_name)
        if stage is None:
            return None

        # Check substage output first
        if substage:
            substage_config = stage.get_substage(substage)
            if substage_config and substage_config.output:
                return substage_config.output

        # Fall back to stage output
        return stage.output

    def validators_for(self, stage_name: str, substage: Optional[str] = None) -> list[str]:
        """Get validators for a stage/substage.

        Args:
            stage_name: Name of the stage
            substage: Optional substage name

        Returns:
            List of validator names
        """
        stage = self.get_stage(stage_name)
        if stage is None:
            return []

        if substage:
            substage_config = stage.get_substage(substage)
            if substage_config:
                return substage_config.validators

        return []

    def is_terminal(self, stage_name: str) -> bool:
        """Check if a stage is terminal (cannot progress further).

        Args:
            stage_name: Name of the stage

        Returns:
            True if terminal, False otherwise
        """
        stage = self.get_stage(stage_name)
        return stage.terminal if stage else False

    def get_next_stage(
        self,
        current_stage: str,
        current_substage: Optional[str] = None,
    ) -> tuple[str, Optional[str], bool]:
        """Calculate the next stage/substage.

        Args:
            current_stage: Current stage name
            current_substage: Current substage (if any)

        Returns:
            Tuple of (next_stage, next_substage, is_human_review)
        """
        stage_config = self.get_stage(current_stage)
        # Terminal stages and stages that trigger merge don't progress further
        if stage_config is None or stage_config.terminal or stage_config.triggers_merge:
            return current_stage, current_substage, False

        substages = stage_config.substage_order()

        # If we have substages, try to advance within them
        if substages and current_substage:
            try:
                idx = substages.index(current_substage)
                if idx < len(substages) - 1:
                    # Move to next substage
                    return current_stage, substages[idx + 1], False
            except ValueError:
                pass  # substage not found, move to next stage

        # Move to next stage
        stage_names = self.get_stage_names()
        try:
            stage_idx = stage_names.index(current_stage)
            if stage_idx < len(stage_names) - 1:
                next_stage_name = stage_names[stage_idx + 1]
                next_stage = self.get_stage(next_stage_name)
                if next_stage:
                    next_substages = next_stage.substage_order()
                    next_substage = next_substages[0] if next_substages else None
                    return next_stage_name, next_substage, next_stage.human_review
        except ValueError:
            pass

        # Already at end
        return current_stage, current_substage, False

    def format_stage(self, stage: str, substage: Optional[str] = None) -> str:
        """Format stage/substage as a display string.

        Args:
            stage: Stage name
            substage: Optional substage name

        Returns:
            Formatted string like "implement/code_review" or "backlog"
        """
        if substage:
            return f"{stage}/{substage}"
        return stage

    def parse_stage(self, stage_str: str) -> tuple[str, Optional[str]]:
        """Parse a stage string into stage and substage.

        Args:
            stage_str: String like "implement/code_review" or "backlog"

        Returns:
            Tuple of (stage, substage) where substage may be None
        """
        if "/" in stage_str:
            parts = stage_str.split("/", 1)
            return parts[0], parts[1]
        return stage_str, None


def find_config_file(start_path: Path) -> Optional[Path]:
    """Find .agenttree.yaml file by walking up directory tree.

    Args:
        start_path: Directory to start searching from

    Returns:
        Path to config file, or None if not found
    """
    current = start_path.resolve()

    # Walk up the directory tree
    while True:
        config_file = current / ".agenttree.yaml"
        if config_file.exists():
            return config_file

        # Check if we've reached the root
        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def load_config(path: Optional[Path] = None) -> Config:
    """Load configuration from .agenttree.yaml file.

    Args:
        path: Path to directory containing config file (default: current directory)

    Returns:
        Loaded configuration (or default if file not found)
    """
    if path is None:
        path = Path.cwd()

    config_file = find_config_file(path)

    if config_file is None:
        return Config()

    with open(config_file, "r") as f:
        data = yaml.safe_load(f)

    if data is None:
        return Config()

    return Config(**data)

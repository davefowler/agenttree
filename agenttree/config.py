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


class StageConfig(BaseModel):
    """Configuration for a workflow stage."""

    name: str
    substages: list[str] = Field(default_factory=list)
    human_review: bool = False
    triggers_merge: bool = False


# Default stages if not configured
DEFAULT_STAGES = [
    StageConfig(name="backlog"),
    StageConfig(name="problem", substages=["draft", "refine"]),
    StageConfig(name="problem_review", human_review=True),
    StageConfig(name="research", substages=["explore", "plan", "spec"]),
    StageConfig(name="plan_review", human_review=True),
    StageConfig(name="implement", substages=["setup", "test", "code", "debug", "code_review", "address_review"]),
    StageConfig(name="implementation_review", human_review=True),
    StageConfig(name="accepted", triggers_merge=True),
    StageConfig(name="not_doing"),
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

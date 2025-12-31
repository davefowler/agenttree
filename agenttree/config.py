"""Configuration management for AgentTree."""

from pathlib import Path
from typing import Dict, Optional
import yaml
from pydantic import BaseModel, ConfigDict, Field


class ToolConfig(BaseModel):
    """Configuration for an AI tool."""

    command: str
    startup_prompt: str = "Check TASK.md and start working."


class Config(BaseModel):
    """AgentTree configuration."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    project: str = "myapp"
    worktrees_dir: Path = Field(default_factory=lambda: Path.home() / "Projects" / "worktrees")
    port_range: str = "8001-8009"
    default_tool: str = "claude"
    tools: Dict[str, ToolConfig] = Field(default_factory=dict)

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
        """Get worktree path for a specific agent.

        Args:
            agent_num: Agent number

        Returns:
            Path to the agent's worktree
        """
        return self.worktrees_dir / f"agent-{agent_num}"

    def get_tmux_session_name(self, agent_num: int) -> str:
        """Get tmux session name for a specific agent.

        Args:
            agent_num: Agent number

        Returns:
            Tmux session name
        """
        return f"{self.project}-agent-{agent_num}"

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

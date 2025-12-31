"""Base agent interface and implementations."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class BaseAgent(ABC):
    """Base class for AI agent adapters."""

    def __init__(self, name: str, command: str, startup_prompt: str):
        """Initialize the agent.

        Args:
            name: Agent name
            command: Command to start the agent
            startup_prompt: Initial prompt to send to the agent
        """
        self.name = name
        self.command = command
        self.startup_prompt = startup_prompt

    @abstractmethod
    def get_start_command(self, worktree_path: Path) -> str:
        """Get the command to start this agent.

        Args:
            worktree_path: Path to the worktree

        Returns:
            Command string
        """
        pass

    @abstractmethod
    def format_task_prompt(self, task_file: Path) -> str:
        """Format the initial task prompt for this agent.

        Args:
            task_file: Path to TASK.md

        Returns:
            Formatted prompt string
        """
        pass

    def prepare_environment(self, worktree_path: Path) -> Optional[str]:
        """Prepare the environment before starting the agent.

        This can be overridden to set up virtual environments,
        environment variables, etc.

        Args:
            worktree_path: Path to the worktree

        Returns:
            Optional shell commands to run before starting agent
        """
        return None


class ClaudeAgent(BaseAgent):
    """Agent adapter for Claude Code."""

    def __init__(self):
        """Initialize Claude Code agent."""
        super().__init__(
            name="claude",
            command="claude",
            startup_prompt="Check TASK.md and start working on it.",
        )

    def get_start_command(self, worktree_path: Path) -> str:
        """Get the command to start Claude Code.

        Args:
            worktree_path: Path to the worktree

        Returns:
            Command string
        """
        return self.command

    def format_task_prompt(self, task_file: Path) -> str:
        """Format the initial task prompt.

        Args:
            task_file: Path to TASK.md

        Returns:
            Formatted prompt
        """
        return self.startup_prompt

    def prepare_environment(self, worktree_path: Path) -> Optional[str]:
        """Prepare environment for Claude Code.

        Args:
            worktree_path: Path to the worktree

        Returns:
            Shell commands to activate venv
        """
        venv_activate = worktree_path / ".venv" / "bin" / "activate"
        if venv_activate.exists():
            return f"source {venv_activate}"
        return None


class AiderAgent(BaseAgent):
    """Agent adapter for Aider."""

    def __init__(self, model: str = "sonnet"):
        """Initialize Aider agent.

        Args:
            model: Model to use (default: sonnet)
        """
        super().__init__(
            name="aider",
            command=f"aider --model {model}",
            startup_prompt="/read TASK.md",
        )
        self.model = model

    def get_start_command(self, worktree_path: Path) -> str:
        """Get the command to start Aider.

        Args:
            worktree_path: Path to the worktree

        Returns:
            Command string
        """
        return self.command

    def format_task_prompt(self, task_file: Path) -> str:
        """Format the initial task prompt for Aider.

        Args:
            task_file: Path to TASK.md

        Returns:
            Formatted prompt
        """
        return self.startup_prompt

    def prepare_environment(self, worktree_path: Path) -> Optional[str]:
        """Prepare environment for Aider.

        Args:
            worktree_path: Path to the worktree

        Returns:
            Shell commands to activate venv
        """
        venv_activate = worktree_path / ".venv" / "bin" / "activate"
        if venv_activate.exists():
            return f"source {venv_activate}"
        return None


def get_agent(tool_name: str, **kwargs) -> BaseAgent:
    """Get an agent instance by name.

    Args:
        tool_name: Name of the tool
        **kwargs: Additional arguments for the agent

    Returns:
        Agent instance

    Raises:
        ValueError: If tool is not recognized
    """
    if tool_name == "claude":
        return ClaudeAgent()
    elif tool_name == "aider":
        model = kwargs.get("model", "sonnet")
        return AiderAgent(model=model)
    else:
        # Return a generic agent for custom tools
        return BaseAgent.__new__(BaseAgent)

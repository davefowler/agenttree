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

    def __init__(self) -> None:
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


class GeminiAgent(BaseAgent):
    """Agent adapter for Google Gemini Code Assist."""

    def __init__(self, model: str = "gemini-2.0-flash-exp"):
        """Initialize Gemini agent.

        Args:
            model: Model to use (default: gemini-2.0-flash-exp)
        """
        super().__init__(
            name="gemini",
            command=f"gemini --model {model}",
            startup_prompt="Read TASK.md and start working on the task described.",
        )
        self.model = model

    def get_start_command(self, worktree_path: Path) -> str:
        """Get the command to start Gemini.

        Args:
            worktree_path: Path to the worktree

        Returns:
            Command string
        """
        return self.command

    def format_task_prompt(self, task_file: Path) -> str:
        """Format the initial task prompt for Gemini.

        Args:
            task_file: Path to TASK.md

        Returns:
            Formatted prompt
        """
        return self.startup_prompt

    def prepare_environment(self, worktree_path: Path) -> Optional[str]:
        """Prepare environment for Gemini.

        Args:
            worktree_path: Path to the worktree

        Returns:
            Shell commands to activate venv and set API key
        """
        commands = []

        venv_activate = worktree_path / ".venv" / "bin" / "activate"
        if venv_activate.exists():
            commands.append(f"source {venv_activate}")

        # Gemini needs API key
        env_file = worktree_path / ".env"
        if env_file.exists():
            commands.append("set -a")
            commands.append(f"source {env_file}")
            commands.append("set +a")

        return " && ".join(commands) if commands else None


class CustomAgent(BaseAgent):
    """Agent adapter for custom CLI tools."""

    def __init__(self, name: str, command: str, startup_prompt: str = ""):
        """Initialize custom agent.

        Args:
            name: Tool name
            command: Command to start the tool
            startup_prompt: Initial prompt (optional)
        """
        super().__init__(
            name=name,
            command=command,
            startup_prompt=startup_prompt or "Check TASK.md and start working.",
        )

    def get_start_command(self, worktree_path: Path) -> str:
        """Get the command to start custom agent.

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


def get_agent(tool_name: str, **kwargs: str) -> BaseAgent:
    """Get an agent instance by name.

    Args:
        tool_name: Name of the tool
        **kwargs: Additional arguments for the agent
            - model: Model name (for aider, gemini)
            - command: Custom command (for custom agents)
            - startup_prompt: Custom startup prompt

    Returns:
        Agent instance

    Examples:
        >>> get_agent("claude")
        >>> get_agent("aider", model="opus")
        >>> get_agent("gemini", model="gemini-2.0-flash-exp")
        >>> get_agent("cursor", command="cursor", startup_prompt="Start coding")
    """
    if tool_name == "claude":
        return ClaudeAgent()
    elif tool_name == "aider":
        model = kwargs.get("model", "sonnet")
        return AiderAgent(model=model)
    elif tool_name == "gemini":
        model = kwargs.get("model", "gemini-2.0-flash-exp")
        return GeminiAgent(model=model)
    else:
        # Custom agent
        command = kwargs.get("command", tool_name)
        startup_prompt = kwargs.get("startup_prompt", "")
        return CustomAgent(
            name=tool_name,
            command=command,
            startup_prompt=startup_prompt,
        )


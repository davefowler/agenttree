"""Tmux session management for AgentTree."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING
from dataclasses import dataclass

from agenttree.config import Config

if TYPE_CHECKING:
    from agenttree.container import ContainerRuntime


@dataclass
class TmuxSession:
    """Information about a tmux session."""

    name: str
    windows: int
    attached: bool


def session_exists(session_name: str) -> bool:
    """Check if a tmux session exists.

    Args:
        session_name: Name of the session

    Returns:
        True if session exists
    """
    try:
        subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def create_session(
    session_name: str, working_dir: Path, start_command: Optional[str] = None
) -> None:
    """Create a new tmux session.

    Args:
        session_name: Name for the new session
        working_dir: Working directory for the session
        start_command: Optional command to run in the session
    """
    cmd = [
        "tmux",
        "new-session",
        "-d",
        "-s",
        session_name,
        "-c",
        str(working_dir),
    ]
    subprocess.run(cmd, check=True)

    if start_command:
        send_keys(session_name, start_command)


def kill_session(session_name: str) -> None:
    """Kill a tmux session.

    Args:
        session_name: Name of the session to kill
    """
    try:
        subprocess.run(
            ["tmux", "kill-session", "-t", session_name],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        # Session doesn't exist or already killed
        pass


def send_keys(session_name: str, keys: str, submit: bool = True) -> None:
    """Send keystrokes to a tmux session.

    Args:
        session_name: Name of the session
        keys: Keys to send
        submit: Whether to send Enter to submit (default True)
    """
    import time

    # Always send text using literal mode to avoid interpretation
    subprocess.run(
        ["tmux", "send-keys", "-t", session_name, "-l", keys],
        check=True,
    )
    if submit:
        # Small delay to let the terminal process the text
        time.sleep(0.1)
        # Send Enter separately - Claude CLI needs this as a separate command
        # to properly submit (it's in multi-line mode where Enter adds newlines)
        subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "Enter"],
            check=True,
        )


def send_message(session_name: str, message: str) -> bool:
    """Send a message to a tmux session if it's alive.

    This is the preferred way to send messages to agents - it checks
    if the session exists before sending and handles errors gracefully.

    Args:
        session_name: Name of the tmux session
        message: Message to send

    Returns:
        True if message was sent, False if session doesn't exist
    """
    if not session_exists(session_name):
        return False

    try:
        send_keys(session_name, message, submit=True)
        return True
    except subprocess.CalledProcessError:
        return False


def attach_session(session_name: str) -> None:
    """Attach to a tmux session (interactive).

    Args:
        session_name: Name of the session to attach to
    """
    subprocess.run(["tmux", "attach", "-t", session_name])


def capture_pane(session_name: str, lines: int = 50) -> str:
    """Capture the contents of a tmux pane.

    Args:
        session_name: Name of the session
        lines: Number of lines to capture from history

    Returns:
        The captured pane contents
    """
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return ""


def wait_for_prompt(
    session_name: str,
    prompt_char: str = "❯",
    timeout: float = 30.0,
    poll_interval: float = 0.5,
) -> bool:
    """Wait for a prompt to appear in a tmux session.

    Args:
        session_name: Name of the session
        prompt_char: Character to look for (default: Claude CLI prompt)
        timeout: Maximum time to wait in seconds
        poll_interval: Time between checks in seconds

    Returns:
        True if prompt found, False if timeout
    """
    import time

    start = time.time()
    while time.time() - start < timeout:
        pane_content = capture_pane(session_name, lines=20)
        if prompt_char in pane_content:
            return True
        time.sleep(poll_interval)
    return False


def list_sessions() -> List[TmuxSession]:
    """List all tmux sessions.

    Returns:
        List of TmuxSession objects
    """
    try:
        result = subprocess.run(
            ["tmux", "list-sessions"],
            capture_output=True,
            text=True,
            check=True,
        )

        sessions = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            # Parse: session_name: 1 windows (created ...) (attached)
            parts = line.split(":")
            if len(parts) >= 2:
                name = parts[0].strip()
                info = parts[1].strip()

                # Extract number of windows
                windows = 1
                if "windows" in info:
                    try:
                        windows = int(info.split()[0])
                    except (ValueError, IndexError):
                        pass

                # Check if attached
                attached = "(attached)" in line

                sessions.append(
                    TmuxSession(name=name, windows=windows, attached=attached)
                )

        return sessions
    except subprocess.CalledProcessError:
        return []


class TmuxManager:
    """Manages tmux sessions for agents."""

    def __init__(self, config: Config):
        """Initialize the tmux manager.

        Args:
            config: AgentTree configuration
        """
        self.config = config

    def get_session_name(self, agent_num: int) -> str:
        """Get tmux session name for an agent.

        Args:
            agent_num: Agent number

        Returns:
            Session name
        """
        return self.config.get_tmux_session_name(agent_num)

    def start_agent(
        self,
        agent_num: int,
        worktree_path: Path,
        tool_name: str,
        startup_script: Optional[Path] = None,
    ) -> None:
        """DEPRECATED: Use start_agent_in_container instead.
        
        This method is kept for backwards compatibility but will raise an error.
        AgentTree requires containers - there is no non-container mode.
        """
        raise RuntimeError(
            "start_agent() is deprecated. Use start_agent_in_container() instead. "
            "AgentTree requires containers for security - there is no non-container mode."
        )

    def start_agent_in_container(
        self,
        agent_num: int,
        worktree_path: Path,
        tool_name: str,
        container_runtime: "ContainerRuntime",
    ) -> None:
        """Start an agent in a container within a tmux session.

        Args:
            agent_num: Agent number
            worktree_path: Path to the agent's worktree
            tool_name: Name of the AI tool to use
            container_runtime: Container runtime instance
        """
        session_name = self.get_session_name(agent_num)

        # Kill existing session if it exists
        if session_exists(session_name):
            kill_session(session_name)

        # Get tool config
        tool_config = self.config.get_tool_config(tool_name)

        # Ensure container system is running (Apple Container)
        container_runtime.ensure_system_running()

        # Build container command with model from config
        # The container runs the AI tool with --dangerously-skip-permissions
        # since it's already isolated in a container
        container_cmd = container_runtime.build_run_command(
            worktree_path=worktree_path,
            ai_tool=tool_name,
            dangerous=True,  # Safe because we're in a container
            model=self.config.default_model,
        )

        # Join command for shell execution
        container_cmd_str = " ".join(container_cmd)

        # Create tmux session running the container
        create_session(session_name, worktree_path, container_cmd_str)

        # Wait for Claude CLI prompt before sending startup message
        if wait_for_prompt(session_name, prompt_char="❯", timeout=30.0):
            send_keys(session_name, tool_config.startup_prompt)

    def stop_agent(self, agent_num: int) -> None:
        """Stop an agent's tmux session.

        Args:
            agent_num: Agent number
        """
        session_name = self.get_session_name(agent_num)
        kill_session(session_name)

    def send_message(self, agent_num: int, message: str) -> None:
        """Send a message to an agent.

        Args:
            agent_num: Agent number
            message: Message to send
        """
        session_name = self.get_session_name(agent_num)
        send_keys(session_name, message)

    def attach(self, agent_num: int) -> None:
        """Attach to an agent's tmux session.

        Args:
            agent_num: Agent number
        """
        session_name = self.get_session_name(agent_num)
        if not session_exists(session_name):
            raise RuntimeError(f"Agent {agent_num} session does not exist")
        attach_session(session_name)

    def is_running(self, agent_num: int) -> bool:
        """Check if an agent's tmux session is running.

        Args:
            agent_num: Agent number

        Returns:
            True if session is running
        """
        session_name = self.get_session_name(agent_num)
        return session_exists(session_name)

    def list_agent_sessions(self) -> List[TmuxSession]:
        """List all agent tmux sessions.

        Returns:
            List of agent sessions
        """
        all_sessions = list_sessions()
        project_prefix = f"{self.config.project}-agent-"

        return [s for s in all_sessions if s.name.startswith(project_prefix)]

    # Issue-based agent methods

    def start_issue_agent_in_container(
        self,
        issue_id: str,
        session_name: str,
        worktree_path: Path,
        tool_name: str,
        container_runtime: "ContainerRuntime",
        model: Optional[str] = None,
    ) -> None:
        """Start an issue-bound agent in a container within a tmux session.

        Args:
            issue_id: Issue ID (e.g., "023")
            session_name: Tmux session name
            worktree_path: Path to the issue's worktree
            tool_name: Name of the AI tool to use
            container_runtime: Container runtime instance
            model: Model to use (defaults to config.default_model if not specified)
        """
        # Kill existing session if it exists
        if session_exists(session_name):
            kill_session(session_name)

        # Get tool config
        tool_config = self.config.get_tool_config(tool_name)

        # Ensure container system is running (Apple Container)
        container_runtime.ensure_system_running()

        # Build container command with resolved model
        resolved_model = model or self.config.default_model
        container_cmd = container_runtime.build_run_command(
            worktree_path=worktree_path,
            ai_tool=tool_name,
            dangerous=True,  # Safe because we're in a container
            model=resolved_model,
        )

        # Join command for shell execution
        container_cmd_str = " ".join(container_cmd)

        # Create tmux session running the container
        create_session(session_name, worktree_path, container_cmd_str)

        # Wait for Claude CLI prompt before sending startup message
        if wait_for_prompt(session_name, prompt_char="❯", timeout=30.0):
            # Build issue-specific startup prompt
            startup_prompt = (
                f"You are working on issue #{issue_id}. "
                f"Read your task: cat _agenttree/issues/{issue_id}-*/problem.md && "
                f"agenttree status --issue {issue_id}"
            )
            send_keys(session_name, startup_prompt)

    def stop_issue_agent(self, session_name: str) -> None:
        """Stop an issue-bound agent's tmux session.

        Args:
            session_name: Tmux session name
        """
        kill_session(session_name)

    def send_message_to_issue(self, session_name: str, message: str) -> None:
        """Send a message to an issue-bound agent.

        Args:
            session_name: Tmux session name
            message: Message to send
        """
        send_keys(session_name, message)

    def attach_to_issue(self, session_name: str) -> None:
        """Attach to an issue-bound agent's tmux session.

        Args:
            session_name: Tmux session name
        """
        if not session_exists(session_name):
            raise RuntimeError(f"Session {session_name} does not exist")
        attach_session(session_name)

    def is_issue_running(self, session_name: str) -> bool:
        """Check if an issue-bound agent's tmux session is running.

        Args:
            session_name: Tmux session name

        Returns:
            True if session is running
        """
        return session_exists(session_name)

    def list_issue_sessions(self) -> List[TmuxSession]:
        """List all issue-bound agent tmux sessions.

        Returns:
            List of issue agent sessions
        """
        all_sessions = list_sessions()
        project_prefix = f"{self.config.project}-issue-"

        return [s for s in all_sessions if s.name.startswith(project_prefix)]

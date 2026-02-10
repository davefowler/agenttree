"""Tmux session management for AgentTree."""

from __future__ import annotations

import subprocess
import sys
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


# =============================================================================
# Session Naming - Single Source of Truth
# =============================================================================

def get_issue_session_name(project: str, issue_id: str, role: str = "developer") -> str:
    """Get the tmux session name for an issue agent.
    
    Args:
        project: Project name (from config.project)
        issue_id: Issue ID (e.g., "128" or "000" for manager)
        role: Agent role - "developer", "reviewer", or "manager"
    
    Returns:
        Session name like "agenttree-developer-128"
    """
    return f"{project}-{role}-{issue_id}"


def get_manager_session_name(project: str) -> str:
    """Get the tmux session name for the manager agent.
    
    Args:
        project: Project name (from config.project)
    
    Returns:
        Session name like "agenttree-manager-000"
    """
    return f"{project}-manager-000"


# Session name slugs in priority order: {project}-{slug}-{issue_id}
SESSION_SLUGS = ("manager", "developer", "reviewer", "issue", "agent")


def get_session_patterns(project: str, issue_id: str) -> list[str]:
    """All possible tmux session names for an issue, preferred first."""
    return [f"{project}-{slug}-{issue_id}" for slug in SESSION_SLUGS]


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


def send_keys(session_name: str, keys: str, submit: bool = True, interrupt: bool = False) -> None:
    """Send keystrokes to a tmux session.

    Args:
        session_name: Name of the session
        keys: Keys to send
        submit: Whether to send Enter to submit (default True)
        interrupt: Whether to send Ctrl+C first to interrupt current task (default False)
    """
    import time

    # If interrupt=True, send Ctrl+C first to stop any running command/thinking
    if interrupt:
        subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "C-c"],
            check=True,
        )
        time.sleep(0.5)  # Wait for Claude to process the interrupt

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


def is_claude_running(session_name: str) -> bool:
    """Check if Claude CLI is running in a tmux session.

    Looks for the Claude prompt character in the pane content.
    This distinguishes between "tmux session exists" and "Claude is actually running".

    Args:
        session_name: Name of the tmux session

    Returns:
        True if Claude CLI appears to be running (prompt visible)
    """
    if not session_exists(session_name):
        return False

    # Check recent pane content for Claude prompt
    pane_content = capture_pane(session_name, lines=30)

    # Look for Claude prompt at end of content (recent lines)
    # Claude CLI shows "❯" when ready for input
    # Also check it's not at a shell prompt (➜ or $ at start of line)
    lines = pane_content.strip().split('\n')

    for line in reversed(lines[-10:]):  # Check last 10 non-empty lines
        line = line.strip()
        if not line:
            continue
        # Claude prompt
        if line.startswith('❯') or '❯' in line:
            return True
        # Shell prompts indicate Claude exited
        if line.startswith('➜') or line.startswith('$') or line.endswith('$'):
            return False

    return False


def send_message(session_name: str, message: str, check_claude: bool = True, interrupt: bool = False) -> str:
    """Send a message to a tmux session if it's alive.

    This is the preferred way to send messages to agents - it checks
    if the session exists before sending and handles errors gracefully.

    Args:
        session_name: Name of the tmux session
        message: Message to send
        check_claude: If True, verify Claude CLI is running (not just tmux session)
        interrupt: If True, send Ctrl+C first to interrupt current task

    Returns:
        "sent" if message was sent successfully
        "no_session" if tmux session doesn't exist
        "claude_exited" if session exists but Claude CLI isn't running
        "error" if send failed
    """
    if not session_exists(session_name):
        return "no_session"

    if check_claude and not is_claude_running(session_name):
        return "claude_exited"

    try:
        send_keys(session_name, message, submit=True, interrupt=interrupt)
        return "sent"
    except subprocess.CalledProcessError:
        return "error"


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


def save_tmux_history_to_file(session_name: str, output_path: Path, stage: str) -> bool:
    """Save tmux session history to a file with timestamp header.

    Captures the full scrollback buffer and appends it to the output file.

    Args:
        session_name: Name of the tmux session
        output_path: Path to the output file (e.g., issue_dir/tmux_history.log)
        stage: Current stage name for the header

    Returns:
        True if history was saved, False if session doesn't exist or capture failed
    """
    from datetime import datetime

    if not session_exists(session_name):
        return False

    # Capture full scrollback buffer (use - for all history)
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-"],
            capture_output=True,
            text=True,
            check=True,
        )
        history = result.stdout
    except subprocess.CalledProcessError:
        return False

    if not history.strip():
        return False

    # Create timestamp header
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"\n{'='*60}\n"
    header += f"Stage: {stage}\n"
    header += f"Captured: {timestamp}\n"
    header += f"{'='*60}\n\n"

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Append to file
    with open(output_path, "a") as f:
        f.write(header)
        f.write(history)
        f.write("\n")

    return True


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
        if wait_for_prompt(session_name, prompt_char="❯", timeout=180.0):
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
        # Check for both -issue- (standard) and -agent- (legacy) patterns
        issue_prefix = f"{self.config.project}-issue-"
        agent_prefix = f"{self.config.project}-agent-"

        return [s for s in all_sessions if s.name.startswith(issue_prefix) or s.name.startswith(agent_prefix)]

    # Issue-based agent methods

    def start_issue_agent_in_container(
        self,
        issue_id: str,
        session_name: str,
        worktree_path: Path,
        tool_name: str,
        container_runtime: "ContainerRuntime",
        model: str | None = None,
        role: str = "developer",
        has_merge_conflicts: bool = False,
        is_restart: bool = False,
        force_api_key: bool = False,
    ) -> bool:
        """Start an issue-bound agent in a container within a tmux session.

        Args:
            issue_id: Issue ID (e.g., "023")
            session_name: Tmux session name
            worktree_path: Path to the issue's worktree
            tool_name: Name of the AI tool to use
            container_runtime: Container runtime instance
            model: Model to use (defaults to config.default_model if not specified)
            role: Agent role for the stage (e.g., "developer", "reviewer")
            has_merge_conflicts: Whether there are unresolved merge conflicts
            is_restart: Whether this is a restart (worktree already existed)
            force_api_key: Force API key mode (skip OAuth subscription)

        Returns:
            True if agent started successfully, False if startup failed
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

        # Calculate port for dev server if serve command is configured
        port = None
        if self.config.commands.get("serve"):
            try:
                issue_num = int(issue_id)
                port = self.config.get_port_for_agent(issue_num)
            except (ValueError, TypeError):
                pass  # Skip port exposure if issue_id is not a valid number

        # Generate container name: agenttree-{project}-{issue_id}
        container_name = f"agenttree-{self.config.project}-{issue_id}"
        
        # Clean up any existing container with this name (from previous runs)
        if container_runtime.runtime:
            from agenttree.container import cleanup_container
            cleanup_container(container_runtime.runtime, container_name)

        container_cmd = container_runtime.build_run_command(
            worktree_path=worktree_path,
            ai_tool=tool_name,
            dangerous=True,  # Safe because we're in a container
            model=resolved_model,
            role=role,
            port=port,
            container_name=container_name,
            force_api_key=force_api_key,
        )

        # Join command for shell execution
        container_cmd_str = " ".join(container_cmd)

        # Create tmux session running the container
        create_session(session_name, worktree_path, container_cmd_str)

        # Start serve session if serve command is configured and port is available
        serve_command = self.config.commands.get("serve")
        if serve_command and port:
            serve_session_name = f"{self.config.project}-serve-{issue_id}"
            try:
                # Kill existing serve session if it exists (for agent restarts)
                if session_exists(serve_session_name):
                    kill_session(serve_session_name)
                # Build command with PORT env var
                serve_cmd = f"PORT={port} {serve_command}"
                create_session(serve_session_name, worktree_path, serve_cmd)
            except subprocess.CalledProcessError as e:
                # Serve session failure should not block agent startup
                print(f"[warning] Could not start serve session: {e}", file=sys.stderr)

        # Wait for Claude CLI prompt before sending startup message
        if wait_for_prompt(session_name, prompt_char="❯", timeout=180.0):
            # Build issue-specific startup prompt based on state
            if has_merge_conflicts:
                startup_prompt = (
                    f"You are working on issue #{issue_id}. "
                    f"IMPORTANT: Your branch was rebased onto latest main and there are MERGE CONFLICTS. "
                    f"Run 'git status' to see conflicted files and resolve them FIRST before any other work. "
                    f"After resolving conflicts and committing, run: agenttree next"
                )
            elif is_restart:
                startup_prompt = (
                    f"SESSION RESTARTED - Issue #{issue_id}. "
                    f"Your branch was rebased onto latest main to get CLI updates. "
                    f"Any uncommitted work was auto-committed. "
                    f"Run 'agenttree next' to see your current stage and resume work."
                )
            else:
                startup_prompt = "Run 'agenttree next' to see your workflow instructions and current stage."
            send_keys(session_name, startup_prompt)
            return True
        else:
            # Startup failed - session may have crashed or container didn't start
            # Clean up the tmux session if it exists
            if session_exists(session_name):
                kill_session(session_name)
            return False

    def start_manager(
        self,
        session_name: str,
        repo_path: Path,
        tool_name: str,
        model: str | None = None,
    ) -> None:
        """Start the manager agent on the host (not in a container).

        The manager runs on the main branch and orchestrates other agents.

        Args:
            session_name: Tmux session name (typically {project}-manager-000)
            repo_path: Path to the repository root
            tool_name: Name of the AI tool to use
            model: Model to use (e.g., "sonnet", "opus"). If None, uses tool default.
        """
        # Kill existing session if it exists
        if session_exists(session_name):
            kill_session(session_name)

        # Get tool config
        tool_config = self.config.get_tool_config(tool_name)

        # Build command to run the AI tool directly (not in container)
        # Manager runs on the host with full access
        ai_command = tool_config.command
        if model:
            ai_command = f"{ai_command} --model {model}"

        # Create tmux session running the AI tool
        create_session(session_name, repo_path, ai_command)

        # Wait for prompt before sending startup message
        if wait_for_prompt(session_name, prompt_char="❯", timeout=30.0):
            # Load manager instructions
            send_keys(session_name, "cat _agenttree/skills/manager.md")

    def stop_issue_agent(self, session_name: str) -> None:
        """Stop an issue-bound agent's tmux session.

        Args:
            session_name: Tmux session name
        """
        kill_session(session_name)

    def send_message_to_issue(self, session_name: str, message: str, interrupt: bool = False) -> str:
        """Send a message to an issue-bound agent.

        Args:
            session_name: Tmux session name
            message: Message to send
            interrupt: Whether to send Ctrl+C first to interrupt current task

        Returns:
            "sent" if message was sent successfully
            "no_session" if tmux session doesn't exist
            "claude_exited" if session exists but Claude CLI isn't running
            "error" if send failed
        """
        return send_message(session_name, message, check_claude=True, interrupt=interrupt)

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
        return [s for s in all_sessions if self.config.is_project_session(s.name)]

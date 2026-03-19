"""Tmux session management for AgentTree.

Only the messenger (interactive claude session) uses tmux now.
Sub-agents run as `claude -p` subprocesses without tmux.
Serve sessions also use tmux for dev server processes.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from dataclasses import dataclass

from agenttree.config import Config, DEFAULT_ROLE

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger("agenttree.tmux")

# Default timeout for tmux commands (seconds)
TMUX_COMMAND_TIMEOUT = 30


@dataclass
class TmuxSession:
    """Information about a tmux session."""

    name: str
    windows: int
    attached: bool


# =============================================================================
# Session Naming
# =============================================================================

SESSION_SLUGS = ("messenger", "manager", "developer", "reviewer", "issue")


def get_session_patterns(project: str, issue_id: str) -> list[str]:
    """All possible tmux session names for an issue, preferred first."""
    return [f"{project}-{slug}-{issue_id}" for slug in SESSION_SLUGS]


# =============================================================================
# Core Session Operations
# =============================================================================


def session_exists(session_name: str) -> bool:
    """Check if a tmux session exists."""
    try:
        subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            check=True,
            capture_output=True,
            timeout=TMUX_COMMAND_TIMEOUT,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def create_session(
    session_name: str, working_dir: Path, start_command: str | None = None
) -> None:
    """Create a new tmux session."""
    if session_exists(session_name):
        kill_session(session_name)

    cmd = [
        "tmux",
        "new-session",
        "-d",
        "-s",
        session_name,
        "-c",
        str(working_dir),
        "-e", "DISABLE_AUTOUPDATER=1",
    ]
    if start_command:
        cmd.append(start_command)
    subprocess.run(cmd, check=True, timeout=TMUX_COMMAND_TIMEOUT)


def kill_session(session_name: str) -> None:
    """Kill a tmux session."""
    try:
        subprocess.run(
            ["tmux", "kill-session", "-t", session_name],
            check=True,
            capture_output=True,
            timeout=TMUX_COMMAND_TIMEOUT,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass


def send_keys(session_name: str, keys: str, submit: bool = True, interrupt: bool = False) -> None:
    """Send keystrokes to a tmux session."""
    import time

    if interrupt:
        subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "C-c"],
            check=True,
            timeout=TMUX_COMMAND_TIMEOUT,
        )
        time.sleep(0.5)

    subprocess.run(
        ["tmux", "send-keys", "-t", session_name, "-l", keys],
        check=True,
        timeout=TMUX_COMMAND_TIMEOUT,
    )
    if submit:
        time.sleep(0.1)
        subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "Enter"],
            check=True,
            timeout=TMUX_COMMAND_TIMEOUT,
        )


def is_claude_running(session_name: str) -> bool:
    """Check if Claude CLI is running in a tmux session."""
    if not session_exists(session_name):
        return False

    pane_content = capture_pane(session_name, lines=30)
    lines = pane_content.strip().split('\n')

    for line in reversed(lines[-10:]):
        line = line.strip()
        if not line:
            continue
        if line.startswith('❯') or '❯' in line:
            return True
        if line.startswith('➜') or line.startswith('$') or line.endswith('$'):
            return False

    return False


def send_message(session_name: str, message: str, check_claude: bool = True, interrupt: bool = False) -> str:
    """Send a message to a tmux session.

    Returns:
        "sent", "no_session", "claude_exited", or "error"
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
    """Attach to a tmux session (interactive)."""
    subprocess.run(["tmux", "attach", "-t", session_name])


def capture_pane(session_name: str, lines: int = 50) -> str:
    """Capture the contents of a tmux pane."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=TMUX_COMMAND_TIMEOUT,
        )
        return result.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def save_tmux_history_to_file(session_name: str, output_path: Path, stage: str) -> bool:
    """Save tmux session history to a file."""
    from datetime import datetime

    if not session_exists(session_name):
        return False

    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-"],
            capture_output=True,
            text=True,
            check=True,
            timeout=TMUX_COMMAND_TIMEOUT,
        )
        history = result.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False

    if not history.strip():
        return False

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"\n{'='*60}\n"
    header += f"Stage: {stage}\n"
    header += f"Captured: {timestamp}\n"
    header += f"{'='*60}\n\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
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
    progress_callback: "Callable[[float, float], None] | None" = None,
) -> bool:
    """Wait for a prompt to appear in a tmux session."""
    import time

    start = time.time()
    last_progress_time = start
    progress_interval = 30.0

    while time.time() - start < timeout:
        pane_content = capture_pane(session_name, lines=20)
        if prompt_char in pane_content:
            return True

        current_time = time.time()
        if progress_callback and (current_time - last_progress_time >= progress_interval):
            elapsed = current_time - start
            progress_callback(elapsed, timeout)
            last_progress_time = current_time

        time.sleep(poll_interval)
    return False


def list_sessions() -> list[TmuxSession]:
    """List all tmux sessions."""
    try:
        result = subprocess.run(
            ["tmux", "list-sessions"],
            capture_output=True,
            text=True,
            check=True,
            timeout=TMUX_COMMAND_TIMEOUT,
        )

        sessions = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split(":")
            if len(parts) >= 2:
                name = parts[0].strip()
                info = parts[1].strip()
                windows = 1
                if "windows" in info:
                    try:
                        windows = int(info.split()[0])
                    except (ValueError, IndexError):
                        pass
                attached = "(attached)" in line
                sessions.append(TmuxSession(name=name, windows=windows, attached=attached))

        return sessions
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []


# =============================================================================
# TmuxManager - kept for messenger and serve sessions
# =============================================================================


class TmuxManager:
    """Manages tmux sessions for messenger and serve processes."""

    def __init__(self, config: Config):
        self.config = config

    def start_host_role(
        self,
        session_name: str,
        repo_path: Path,
        tool_name: str,
        model: str | None = None,
        skill_file: str | None = None,
    ) -> None:
        """Start a host-level role agent (messenger, architect) in tmux.

        These run as interactive claude sessions (NOT claude -p).
        """
        if session_exists(session_name):
            kill_session(session_name)

        tool_config = self.config.get_tool_config(tool_name)
        ai_command = tool_config.command
        if model:
            ai_command = f"{ai_command} --model {model}"

        create_session(session_name, repo_path, ai_command)

        if skill_file and wait_for_prompt(session_name, prompt_char="❯", timeout=30.0):
            role_prompt_path = f"_agenttree/roles/{skill_file}"
            legacy_prompt_path = f"_agenttree/skills/{skill_file}"
            if (repo_path / role_prompt_path).exists():
                send_keys(session_name, f"cat {role_prompt_path}")
            elif (repo_path / legacy_prompt_path).exists():
                send_keys(session_name, f"cat {legacy_prompt_path}")
            else:
                send_keys(session_name, f"cat {role_prompt_path}")

    def is_issue_running(self, session_name: str) -> bool:
        """Check if a tmux session is running (for serve sessions)."""
        return session_exists(session_name)

    def send_message_to_issue(self, session_name: str, message: str, interrupt: bool = False) -> str:
        """Send a message to a tmux session (messenger only)."""
        return send_message(session_name, message, check_claude=True, interrupt=interrupt)

    def attach_to_issue(self, session_name: str) -> None:
        """Attach to a tmux session."""
        if not session_exists(session_name):
            raise RuntimeError(f"Session {session_name} does not exist")
        attach_session(session_name)

    def list_issue_sessions(self) -> list[TmuxSession]:
        """List all project tmux sessions."""
        all_sessions = list_sessions()
        return [s for s in all_sessions if self.config.is_project_session(s.name)]

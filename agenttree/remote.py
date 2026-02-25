"""Remote agent execution via SSH and Tailscale."""

import json
import subprocess
import shutil
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class RemoteHost:
    """Remote host configuration."""

    name: str  # Friendly name
    host: str  # Hostname or IP (can be Tailscale name)
    user: str  # SSH user
    ssh_key: Optional[str] = None  # Path to SSH key
    is_tailscale: bool = False  # Whether this is a Tailscale host


def is_tailscale_available() -> bool:
    """Check if Tailscale CLI is available.

    Returns:
        True if tailscale is installed
    """
    return shutil.which("tailscale") is not None


def get_tailscale_hosts() -> List[str]:
    """Get list of Tailscale hosts.

    Returns:
        List of host names
    """
    if not is_tailscale_available():
        return []

    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )

        data = json.loads(result.stdout)

        hosts = []
        for peer in data.get("Peer", {}).values():
            if peer.get("Online"):
                hostname = peer.get("HostName", "")
                if hostname:
                    hosts.append(hostname)

        return hosts
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []


def ssh_command(
    host: RemoteHost,
    command: str,
    capture_output: bool = True
) -> subprocess.CompletedProcess:
    """Execute a command on a remote host via SSH.

    Args:
        host: Remote host configuration
        command: Command to execute
        capture_output: Whether to capture output

    Returns:
        CompletedProcess result
    """
    ssh_cmd = ["ssh"]

    # Add SSH key if specified
    if host.ssh_key:
        ssh_cmd.extend(["-i", host.ssh_key])

    # Add host
    ssh_cmd.append(f"{host.user}@{host.host}")

    # Add command
    ssh_cmd.append(command)

    return subprocess.run(
        ssh_cmd,
        capture_output=capture_output,
        text=True,
        check=False,
    )


def check_remote_git_repo(host: RemoteHost, repo_path: str) -> bool:
    """Check if git repo exists on remote host.

    Args:
        host: Remote host
        repo_path: Path to repo on remote host

    Returns:
        True if repo exists
    """
    result = ssh_command(
        host,
        f"test -d {repo_path}/.git && echo 'exists'"
    )

    return "exists" in result.stdout


def clone_agents_repo_remote(
    host: RemoteHost,
    agents_repo_url: str,
    target_path: str
) -> bool:
    """Clone agents repository on remote host.

    Args:
        host: Remote host
        agents_repo_url: Git URL of agents repo
        target_path: Where to clone on remote host

    Returns:
        True if successful
    """
    # Check if already cloned
    if check_remote_git_repo(host, target_path):
        # Already exists, just pull
        result = ssh_command(
            host,
            f"cd {target_path} && git pull"
        )
        return result.returncode == 0

    # Clone it
    result = ssh_command(
        host,
        f"git clone {agents_repo_url} {target_path}"
    )

    return result.returncode == 0


def notify_remote_agent(
    host: RemoteHost,
    agent_num: int,
    project_name: str,
    message: str = "New task available"
) -> bool:
    """Notify a remote agent of a new task via tmux.

    This sends a message to the agent's tmux session.

    Args:
        host: Remote host
        agent_num: Agent number
        project_name: Project name (for tmux session naming)
        message: Message to send

    Returns:
        True if notification sent successfully
    """
    session_name = f"{project_name}-issue-{agent_num}"

    # Send keys to tmux session (simulates typing the message)
    # The agent should be configured to check for new tasks
    command = f"""
        tmux send-keys -t {session_name} '{message}' Enter
    """

    result = ssh_command(host, command.strip())

    return result.returncode == 0


def dispatch_task_to_remote_agent(
    host: RemoteHost,
    agent_num: int,
    project_name: str,
    agents_repo_path: str,
) -> bool:
    """Dispatch a task to a remote agent.

    This will:
    1. SSH into the remote host
    2. Pull latest from agents/ repo
    3. Notify the agent's tmux session

    Args:
        host: Remote host
        agent_num: Agent number
        project_name: Project name
        agents_repo_path: Path to agents repo on remote host

    Returns:
        True if task dispatched successfully
    """
    # First, ensure the agent pulls latest from agents repo
    pull_command = f"cd {agents_repo_path} && git pull"

    result = ssh_command(host, pull_command)

    if result.returncode != 0:
        return False

    # Now notify the agent
    return notify_remote_agent(
        host,
        agent_num,
        project_name,
        "New task available! Pull from agents/ repo and check tasks/"
    )


def start_remote_tmux_session(
    host: RemoteHost,
    session_name: str,
    working_directory: str,
    command: str
) -> bool:
    """Start a tmux session on a remote host.

    Args:
        host: Remote host
        session_name: Name for the tmux session
        working_directory: Working directory for the session
        command: Command to run in the session

    Returns:
        True if session started successfully
    """
    # Create tmux session and run command
    tmux_cmd = f"""
        cd {working_directory} && \
        tmux new-session -d -s {session_name} '{command}'
    """

    result = ssh_command(host, tmux_cmd.strip())

    return result.returncode == 0


def attach_to_remote_tmux(
    host: RemoteHost,
    session_name: str
) -> None:
    """Attach to a remote tmux session (interactive).

    This will SSH into the host and attach to the tmux session.

    Args:
        host: Remote host
        session_name: Tmux session name
    """
    ssh_cmd = ["ssh", "-t"]  # -t for interactive terminal

    if host.ssh_key:
        ssh_cmd.extend(["-i", host.ssh_key])

    ssh_cmd.append(f"{host.user}@{host.host}")
    ssh_cmd.append(f"tmux attach-session -t {session_name}")

    # This is interactive, so don't capture output
    subprocess.run(ssh_cmd)


def get_remote_agent_status(
    host: RemoteHost,
    session_name: str
) -> dict:
    """Get status of a remote agent.

    Args:
        host: Remote host
        session_name: Tmux session name

    Returns:
        Status dictionary with:
        - online: bool - whether host is reachable
        - tmux_active: bool - whether tmux session exists
        - last_activity: str - last tmux activity
    """
    status = {
        "online": False,
        "tmux_active": False,
        "last_activity": None
    }

    # Check if host is reachable
    ping_result = ssh_command(host, "echo 'pong'")

    if ping_result.returncode != 0:
        return status

    status["online"] = True

    # Check tmux session
    tmux_check = ssh_command(
        host,
        f"tmux has-session -t {session_name} 2>/dev/null && echo 'active'"
    )

    if "active" in tmux_check.stdout:
        status["tmux_active"] = True

        # Get last activity
        activity = ssh_command(
            host,
            f"tmux display-message -t {session_name} -p '#{{session_activity}}'"
        )

        if activity.returncode == 0:
            status["last_activity"] = activity.stdout.strip()

    return status

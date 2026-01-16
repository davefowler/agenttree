"""Command execution module for AgentTree.

This module provides utilities for executing shell commands defined in
the config's `commands` section. Commands can be used for:
- CLI commands (lint, test)
- Template variables (git_branch, files_changed, etc.)
- Hook actions

Commands are executed lazily and their outputs can be injected into
Jinja templates.
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional, Union

from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)


def execute_command(
    cmd: str,
    cwd: Optional[Path] = None,
    timeout: int = 5,
) -> str:
    """Execute a single shell command and return its output.

    Args:
        cmd: Shell command to execute
        cwd: Working directory for the command (defaults to current directory)
        timeout: Timeout in seconds (default 5)

    Returns:
        stdout from the command (stripped). Returns empty string on failure.
    """
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )

        if result.returncode != 0:
            logger.warning(f"Command failed (exit {result.returncode}): {cmd}")
            logger.debug(f"stderr: {result.stderr}")
            return ""

        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        logger.warning(f"Command timed out after {timeout}s: {cmd}")
        return ""
    except Exception as e:
        logger.warning(f"Command execution error: {e}")
        return ""


def execute_commands(
    cmds: list[str],
    cwd: Optional[Path] = None,
    timeout: int = 5,
) -> str:
    """Execute multiple commands and concatenate their outputs.

    Args:
        cmds: List of shell commands to execute
        cwd: Working directory for the commands
        timeout: Timeout in seconds per command

    Returns:
        Outputs joined with newlines. Empty strings for failed commands.
    """
    outputs = []
    for cmd in cmds:
        output = execute_command(cmd, cwd=cwd, timeout=timeout)
        outputs.append(output)

    return "\n".join(outputs)


def get_command_output(
    commands: dict[str, Union[str, list[str]]],
    name: str,
    cwd: Optional[Path] = None,
    timeout: int = 5,
) -> str:
    """Get the output of a named command from the config.

    Args:
        commands: Dict of command name to command string or list
        name: Name of the command to execute
        cwd: Working directory for the command
        timeout: Timeout in seconds

    Returns:
        Command output (or empty string if command not found or failed)
    """
    if name not in commands:
        return ""

    cmd = commands[name]

    if isinstance(cmd, list):
        return execute_commands(cmd, cwd=cwd, timeout=timeout)
    else:
        return execute_command(cmd, cwd=cwd, timeout=timeout)


def get_referenced_commands(template: str, commands: dict[str, Union[str, list[str]]]) -> set[str]:
    """Find command names referenced in a Jinja template.

    Scans the template for {{variable}} patterns and returns those
    that exist in the commands dict.

    Args:
        template: Jinja template string
        commands: Dict of available commands

    Returns:
        Set of command names that are referenced in the template
    """
    import re

    # Match {{ variable }} patterns (allowing whitespace)
    pattern = r'\{\{\s*(\w+)\s*\}\}'
    matches = re.findall(pattern, template)

    return {m for m in matches if m in commands}

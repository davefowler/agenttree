"""Shared utilities for CLI commands."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

# Shared console instance for all CLI output
console = Console()


def get_repo_path() -> Path:
    """Get the repository root path."""
    return Path.cwd()

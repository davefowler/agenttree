"""Dependency checking module for AgentTree init.

This module provides batch checking of all required dependencies at init time,
reporting all issues at once rather than failing on the first problem.
"""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from rich.console import Console

from agenttree.container import ContainerRuntime

# Shared installation instructions for GitHub CLI
GH_CLI_INSTALL_INSTRUCTIONS = (
    "Install from https://cli.github.com/\n"
    "  macOS:   brew install gh\n"
    "  Linux:   See https://github.com/cli/cli#installation\n"
    "  Windows: See https://github.com/cli/cli#installation"
)


@dataclass
class DependencyResult:
    """Result of a single dependency check.

    Attributes:
        name: Identifier for the dependency check
        passed: Whether the check passed
        description: Human-readable description of the result
        fix_instructions: Instructions for fixing the issue (if failed)
        required: If True, failure blocks init. If False, it's just a warning.
    """

    name: str
    passed: bool
    description: str
    fix_instructions: Optional[str] = None
    required: bool = True


def check_git_repo(path: Path) -> DependencyResult:
    """Check if the given path is inside a git repository.

    Args:
        path: Directory path to check

    Returns:
        DependencyResult indicating whether .git exists
    """
    git_dir = path / ".git"

    if git_dir.exists():
        return DependencyResult(
            name="git_repo",
            passed=True,
            description="Git repository detected",
        )
    else:
        return DependencyResult(
            name="git_repo",
            passed=False,
            description="Not a git repository",
            fix_instructions="Run `git init` to create a repository, or navigate to an existing git repo",
        )


def check_gh_installed() -> DependencyResult:
    """Check if the GitHub CLI (gh) is installed.

    Returns:
        DependencyResult indicating whether gh is found in PATH
    """
    gh_path = shutil.which("gh")

    if gh_path:
        return DependencyResult(
            name="gh_installed",
            passed=True,
            description="GitHub CLI installed",
        )
    else:
        return DependencyResult(
            name="gh_installed",
            passed=False,
            description="GitHub CLI not installed",
            fix_instructions=GH_CLI_INSTALL_INSTRUCTIONS,
        )


def check_gh_authenticated() -> DependencyResult:
    """Check if the GitHub CLI is authenticated.

    Uses a 5-second timeout to avoid hanging on network issues.

    Returns:
        DependencyResult indicating whether gh auth status succeeds
    """
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            return DependencyResult(
                name="gh_authenticated",
                passed=True,
                description="GitHub CLI authenticated",
            )
        else:
            return DependencyResult(
                name="gh_authenticated",
                passed=False,
                description="GitHub CLI not authenticated",
                fix_instructions=(
                    "Run `gh auth login` to authenticate.\n"
                    "This will open your browser to log in to GitHub."
                ),
            )
    except subprocess.TimeoutExpired:
        return DependencyResult(
            name="gh_authenticated",
            passed=False,
            description="GitHub CLI auth check timed out (network issue?)",
            fix_instructions="Check your network connection and try `gh auth status` manually",
        )
    except FileNotFoundError:
        return DependencyResult(
            name="gh_authenticated",
            passed=False,
            description="GitHub CLI not found (cannot check auth)",
            fix_instructions="Install gh CLI first",
        )
    except Exception as e:
        return DependencyResult(
            name="gh_authenticated",
            passed=False,
            description=f"GitHub CLI auth check failed: {e}",
            fix_instructions="Try running `gh auth status` manually to diagnose",
        )


def check_container_runtime() -> DependencyResult:
    """Check if a container runtime is available.

    This is a non-blocking check (required=False) since agents can still
    work without containers in some scenarios.

    Returns:
        DependencyResult with required=False (warning only)
    """
    runtime = ContainerRuntime()

    if runtime.is_available():
        runtime_name = runtime.get_runtime_name()
        return DependencyResult(
            name="container_runtime",
            passed=True,
            description=f"Container runtime available ({runtime_name})",
            required=False,
        )
    else:
        return DependencyResult(
            name="container_runtime",
            passed=False,
            description="No container runtime found",
            fix_instructions=runtime.get_recommended_action(),
            required=False,  # Warning only, doesn't block init
        )


def check_all_dependencies(repo_path: Path) -> Tuple[bool, List[DependencyResult]]:
    """Run all dependency checks and collect results.

    Checks are run in order:
    1. Git repository (required)
    2. gh CLI installed (required)
    3. gh CLI authenticated (required, but skipped if gh not installed)
    4. Container runtime (warning only)

    Args:
        repo_path: Path to the repository being initialized

    Returns:
        Tuple of (success, results) where success is False only if a
        required check fails
    """
    results: List[DependencyResult] = []

    # Check git repo
    git_result = check_git_repo(repo_path)
    results.append(git_result)

    # Check gh installed
    gh_result = check_gh_installed()
    results.append(gh_result)

    # Check gh authenticated (only if gh is installed)
    if gh_result.passed:
        auth_result = check_gh_authenticated()
        results.append(auth_result)
    else:
        # Skip auth check but note it was skipped
        results.append(
            DependencyResult(
                name="gh_authenticated",
                passed=False,
                description="Skipped (gh not installed)",
                fix_instructions="Install gh CLI first",
                required=True,
            )
        )

    # Check container runtime (warning only)
    container_result = check_container_runtime()
    results.append(container_result)

    # Determine overall success - only required checks matter
    required_checks = [r for r in results if r.required]
    success = all(r.passed for r in required_checks)

    return success, results


def print_dependency_report(results: List[DependencyResult]) -> None:
    """Print a formatted report of dependency check results.

    Shows all checks (passed and failed) with status indicators.
    Failed checks include fix instructions.
    Warnings (required=False) use different styling.

    Args:
        results: List of DependencyResult objects to display
    """
    console = Console()

    # Separate required failures, warnings, and passed
    required_failures = [r for r in results if r.required and not r.passed]
    warnings = [r for r in results if not r.required and not r.passed]
    passed = [r for r in results if r.passed]

    if required_failures or warnings:
        console.print("\n[bold]AgentTree requires the following dependencies:[/bold]\n")

    # Show required failures first
    for result in required_failures:
        console.print(f"[red]\u2717[/red] [bold]{result.description}[/bold]")
        if result.fix_instructions:
            console.print(f"  [dim]Why:[/dim] AgentTree needs this to manage issues and PRs")
            console.print(f"  [dim]Fix:[/dim] {result.fix_instructions}")
        console.print()

    # Show warnings
    for result in warnings:
        console.print(f"[yellow]\u26A0[/yellow] [bold]{result.description}[/bold] [dim](warning)[/dim]")
        if result.fix_instructions:
            console.print(f"  [dim]Why:[/dim] Agents run in sandboxed containers for safety")
            console.print(f"  [dim]Fix:[/dim] {result.fix_instructions}")
        console.print()

    # Show passed checks
    for result in passed:
        console.print(f"[green]\u2713[/green] {result.description}")

    if required_failures:
        console.print("\n[yellow]Please resolve the issues above and run `agenttree init` again.[/yellow]")

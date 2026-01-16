"""Preflight check system for agenttree.

This module provides environment validation before agents start working.
It checks critical requirements like Python version, dependencies, git,
CLI tools, and test runners.

Usage:
    from agenttree.preflight import run_preflight, get_default_registry

    # Run all checks
    results = run_preflight()
    if all(r.passed for r in results):
        print("Environment ready!")
    else:
        for r in results:
            if not r.passed:
                print(f"FAIL: {r.name} - {r.message}")
"""

import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class PreflightResult:
    """Result of a single preflight check.

    Attributes:
        name: Name of the check that was run
        passed: Whether the check passed
        message: Human-readable message describing the result
        fix_hint: Optional suggestion for how to fix a failure
    """

    name: str
    passed: bool
    message: str
    fix_hint: Optional[str] = None


class PreflightCheck(ABC):
    """Base class for preflight checks.

    Subclasses must define name, description, and implement check().
    """

    name: str = ""
    description: str = ""

    @abstractmethod
    def check(self) -> PreflightResult:
        """Run the preflight check.

        Returns:
            PreflightResult with the outcome of the check
        """
        pass


class PreflightRegistry:
    """Registry for collecting and running preflight checks."""

    def __init__(self) -> None:
        """Initialize empty registry."""
        self.checks: List[PreflightCheck] = []

    def register(self, check: PreflightCheck) -> None:
        """Register a preflight check.

        Args:
            check: PreflightCheck instance to register
        """
        self.checks.append(check)

    def run_all(self) -> List[PreflightResult]:
        """Run all registered checks and return results.

        Continues running checks even if some fail or raise exceptions.

        Returns:
            List of PreflightResult for all checks
        """
        results: List[PreflightResult] = []
        for check in self.checks:
            try:
                result = check.check()
                results.append(result)
            except Exception as e:
                # Check crashed - treat as failure
                results.append(
                    PreflightResult(
                        name=check.name,
                        passed=False,
                        message=f"Check error: {e}",
                        fix_hint="Check implementation may have a bug",
                    )
                )
        return results


# Built-in checks


class PythonVersionCheck(PreflightCheck):
    """Check that Python version meets minimum requirement."""

    name = "python_version"
    description = "Verify Python version >= 3.10"

    def __init__(self, min_version: Tuple[int, int] = (3, 10)) -> None:
        """Initialize with minimum version.

        Args:
            min_version: Minimum Python version as (major, minor) tuple
        """
        self.min_version = min_version

    def check(self) -> PreflightResult:
        """Check Python version."""
        # Use index access to handle both real sys.version_info and mocked tuples
        current = (sys.version_info[0], sys.version_info[1])
        version_str = f"{current[0]}.{current[1]}"

        if current >= self.min_version:
            return PreflightResult(
                name=self.name,
                passed=True,
                message=f"Python {version_str} meets minimum requirement {self.min_version[0]}.{self.min_version[1]}",
            )
        else:
            return PreflightResult(
                name=self.name,
                passed=False,
                message=f"Python {version_str} is below minimum {self.min_version[0]}.{self.min_version[1]}",
                fix_hint=f"Install Python {self.min_version[0]}.{self.min_version[1]} or higher",
            )


class DependenciesCheck(PreflightCheck):
    """Check that project dependencies are installed."""

    name = "dependencies"
    description = "Verify project dependencies are installed"

    def check(self) -> PreflightResult:
        """Check dependencies using detected package manager."""
        # Check for uv first (preferred for this project)
        pyproject = Path("pyproject.toml")
        if pyproject.exists():
            content = pyproject.read_text()
            if "[tool.uv]" in content or "uv" in content:
                return self._check_uv()

        # Fallback to pip check
        return self._check_pip()

    def _check_uv(self) -> PreflightResult:
        """Check dependencies using uv."""
        try:
            result = subprocess.run(
                ["uv", "sync", "--check"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return PreflightResult(
                    name=self.name,
                    passed=True,
                    message="Dependencies are in sync",
                )
            else:
                return PreflightResult(
                    name=self.name,
                    passed=False,
                    message=f"Dependencies out of sync: {result.stderr or result.stdout}",
                    fix_hint="Run 'uv sync' to install dependencies",
                )
        except FileNotFoundError:
            # uv not available, try pip
            return self._check_pip()
        except subprocess.TimeoutExpired:
            return PreflightResult(
                name=self.name,
                passed=False,
                message="Dependency check timed out",
                fix_hint="Check network connectivity or run 'uv sync' manually",
            )

    def _check_pip(self) -> PreflightResult:
        """Check dependencies using pip."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "check"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return PreflightResult(
                    name=self.name,
                    passed=True,
                    message="Dependencies OK (pip check passed)",
                )
            else:
                return PreflightResult(
                    name=self.name,
                    passed=False,
                    message=f"Dependency issues: {result.stdout}",
                    fix_hint="Run 'pip install -e .' or 'uv sync'",
                )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return PreflightResult(
                name=self.name,
                passed=False,
                message=f"Could not check dependencies: {e}",
                fix_hint="Ensure Python and pip are installed",
            )


class GitCheck(PreflightCheck):
    """Check that git is available and working."""

    name = "git"
    description = "Verify git is available and this is a repository"

    def check(self) -> PreflightResult:
        """Check git status."""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return PreflightResult(
                    name=self.name,
                    passed=True,
                    message="Git is working",
                )
            else:
                return PreflightResult(
                    name=self.name,
                    passed=False,
                    message=f"Git error: {result.stderr}",
                    fix_hint="Ensure you're in a git repository",
                )
        except FileNotFoundError:
            return PreflightResult(
                name=self.name,
                passed=False,
                message="Git not found",
                fix_hint="Install git",
            )
        except subprocess.TimeoutExpired:
            return PreflightResult(
                name=self.name,
                passed=False,
                message="Git command timed out",
            )


class AgenttreeCliCheck(PreflightCheck):
    """Check that agenttree CLI is accessible."""

    name = "agenttree_cli"
    description = "Verify agenttree CLI is accessible"

    def check(self) -> PreflightResult:
        """Check agenttree CLI."""
        try:
            result = subprocess.run(
                ["agenttree", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return PreflightResult(
                    name=self.name,
                    passed=True,
                    message=f"agenttree CLI available: {result.stdout.strip()}",
                )
            else:
                return PreflightResult(
                    name=self.name,
                    passed=False,
                    message=f"agenttree CLI error: {result.stderr}",
                    fix_hint="Ensure agenttree is in PATH",
                )
        except FileNotFoundError:
            return PreflightResult(
                name=self.name,
                passed=False,
                message="agenttree CLI not found",
                fix_hint="Add agenttree to PATH or install with 'pip install agenttree'",
            )
        except subprocess.TimeoutExpired:
            return PreflightResult(
                name=self.name,
                passed=False,
                message="agenttree command timed out",
            )


class TestRunnerCheck(PreflightCheck):
    """Check that a test runner is available."""

    name = "test_runner"
    description = "Verify test runner (pytest) is available"

    def check(self) -> PreflightResult:
        """Check for pytest."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                version_line = result.stdout.strip().split("\n")[0]
                return PreflightResult(
                    name=self.name,
                    passed=True,
                    message=f"pytest available: {version_line}",
                )
            else:
                return PreflightResult(
                    name=self.name,
                    passed=False,
                    message=f"pytest error: {result.stderr}",
                    fix_hint="Install pytest with 'pip install pytest' or 'uv sync'",
                )
        except FileNotFoundError:
            return PreflightResult(
                name=self.name,
                passed=False,
                message="pytest not found",
                fix_hint="Install pytest with 'pip install pytest' or 'uv sync'",
            )
        except subprocess.TimeoutExpired:
            return PreflightResult(
                name=self.name,
                passed=False,
                message="pytest command timed out",
            )


def get_default_registry() -> PreflightRegistry:
    """Get a registry with all default preflight checks.

    Returns:
        PreflightRegistry populated with built-in checks
    """
    registry = PreflightRegistry()
    registry.register(PythonVersionCheck())
    registry.register(DependenciesCheck())
    registry.register(GitCheck())
    registry.register(AgenttreeCliCheck())
    registry.register(TestRunnerCheck())
    return registry


def run_preflight() -> List[PreflightResult]:
    """Run all default preflight checks.

    Returns:
        List of PreflightResult for all checks
    """
    registry = get_default_registry()
    return registry.run_all()

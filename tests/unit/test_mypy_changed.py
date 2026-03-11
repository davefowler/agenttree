"""Tests for scripts/mypy_changed.py timeout handling."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.mypy_changed import main


@patch("scripts.mypy_changed._changed_python_files")
@patch("scripts.mypy_changed._repo_root")
def test_main_timeout_returns_zero(
    mock_root: MagicMock, mock_changed: MagicMock
) -> None:
    """When mypy times out, main() should return 0 and print a warning."""
    mock_root.return_value = Path("/fake")
    mock_changed.return_value = ["agenttree/foo.py"]

    with patch("scripts.mypy_changed.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="mypy", timeout=120)
        result = main()

    assert result == 0


@patch("scripts.mypy_changed._changed_python_files")
@patch("scripts.mypy_changed._repo_root")
def test_main_normal_completion(
    mock_root: MagicMock, mock_changed: MagicMock
) -> None:
    """When mypy completes normally, main() returns its exit code."""
    mock_root.return_value = Path("/fake")
    mock_changed.return_value = ["agenttree/bar.py"]

    with patch("scripts.mypy_changed.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        result = main()

    assert result == 1


@patch("scripts.mypy_changed._changed_python_files")
@patch("scripts.mypy_changed._repo_root")
def test_main_no_changed_files(
    mock_root: MagicMock, mock_changed: MagicMock
) -> None:
    """When no files changed, main() should skip mypy and return 0."""
    mock_root.return_value = Path("/fake")
    mock_changed.return_value = []

    result = main()

    assert result == 0

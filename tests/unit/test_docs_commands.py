"""Tests for agenttree docs CLI commands."""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from agenttree.cli import main


class TestDocsInit:
    """Test agenttree docs init command."""

    @pytest.fixture
    def runner(self):
        """Create a CLI runner."""
        return CliRunner()

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp)

    def test_docs_init_creates_structure(self, runner, temp_dir):
        """Test that docs init creates the expected directory structure."""
        with runner.isolated_filesystem(temp_dir=str(temp_dir)):
            # Create minimal _agenttree structure
            Path("_agenttree").mkdir()

            result = runner.invoke(main, ["docs", "init"])

            assert result.exit_code == 0, f"Command failed: {result.output}"
            assert Path("_agenttree/docs").exists()
            assert Path("_agenttree/docs/modules").exists()
            assert Path("_agenttree/docs/decisions").exists()
            assert Path("_agenttree/notes").exists()
            assert Path("_agenttree/docs/index.md").exists()
            assert Path("_agenttree/docs/architecture.md").exists()

    def test_docs_init_idempotent(self, runner, temp_dir):
        """Test that docs init doesn't overwrite existing docs."""
        with runner.isolated_filesystem(temp_dir=str(temp_dir)):
            # Create existing docs structure
            Path("_agenttree/docs").mkdir(parents=True)
            Path("_agenttree/docs/index.md").write_text("Existing content")

            result = runner.invoke(main, ["docs", "init"])

            assert result.exit_code == 0
            assert "already exists" in result.output
            # Original content should be preserved
            assert Path("_agenttree/docs/index.md").read_text() == "Existing content"

    def test_docs_init_detects_existing_notes(self, runner, temp_dir):
        """Test that docs init detects existing notes directories."""
        with runner.isolated_filesystem(temp_dir=str(temp_dir)):
            Path("_agenttree").mkdir()
            Path("notes").mkdir()
            Path("notes/research.md").write_text("Some notes")

            result = runner.invoke(main, ["docs", "init"])

            assert result.exit_code == 0
            assert "notes" in result.output.lower()
            assert "import" in result.output.lower()


class TestDocsImport:
    """Test agenttree docs import command."""

    @pytest.fixture
    def runner(self):
        """Create a CLI runner."""
        return CliRunner()

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp = tempfile.mkdtemp()
        yield Path(temp)
        shutil.rmtree(temp)

    def test_docs_import_moves_directory(self, runner, temp_dir):
        """Test that docs import moves a directory."""
        with runner.isolated_filesystem(temp_dir=str(temp_dir)):
            # Create structure
            Path("_agenttree/notes").mkdir(parents=True)
            Path("research").mkdir()
            Path("research/notes.md").write_text("Research notes")

            result = runner.invoke(main, ["docs", "import", "research"])

            assert result.exit_code == 0
            assert Path("_agenttree/notes/research").exists()
            assert Path("_agenttree/notes/research/notes.md").exists()
            assert not Path("research").exists()

    def test_docs_import_dry_run(self, runner, temp_dir):
        """Test that docs import --dry-run doesn't move files."""
        with runner.isolated_filesystem(temp_dir=str(temp_dir)):
            Path("_agenttree/notes").mkdir(parents=True)
            Path("research").mkdir()
            Path("research/notes.md").write_text("Research notes")

            result = runner.invoke(main, ["docs", "import", "--dry-run", "research"])

            assert result.exit_code == 0
            assert "Would move" in result.output
            # Files should not be moved
            assert Path("research").exists()
            assert not Path("_agenttree/notes/research").exists()

    def test_docs_import_skips_existing(self, runner, temp_dir):
        """Test that docs import skips already imported items."""
        with runner.isolated_filesystem(temp_dir=str(temp_dir)):
            Path("_agenttree/notes/research").mkdir(parents=True)
            Path("research").mkdir()
            Path("research/notes.md").write_text("Research notes")

            result = runner.invoke(main, ["docs", "import", "research"])

            assert result.exit_code == 0
            assert "Skipping" in result.output
            # Original should still exist since we skipped
            assert Path("research").exists()

    def test_docs_import_no_paths_scans(self, runner, temp_dir):
        """Test that docs import with no paths scans for notes."""
        with runner.isolated_filesystem(temp_dir=str(temp_dir)):
            Path("_agenttree/notes").mkdir(parents=True)

            result = runner.invoke(main, ["docs", "import"])

            assert result.exit_code == 0
            # Should report no notes found
            assert "No notes found" in result.output or result.output == ""

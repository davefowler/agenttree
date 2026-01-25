"""Tests for documentation structure."""

from pathlib import Path

import pytest


class TestDocsStructure:
    """Test that the documentation structure is properly set up."""

    def test_docs_directory_exists(self):
        """Test that _agenttree/docs/ directory exists."""
        docs_dir = Path("_agenttree/docs")
        assert docs_dir.exists(), "Documentation directory should exist"
        assert docs_dir.is_dir(), "_agenttree/docs should be a directory"

    def test_index_exists(self):
        """Test that index.md exists and has content."""
        index_path = Path("_agenttree/docs/index.md")
        assert index_path.exists(), "index.md should exist"
        content = index_path.read_text()
        assert len(content) > 100, "index.md should have substantial content"
        assert "Architecture" in content, "index.md should reference architecture"
        assert "Module" in content, "index.md should reference modules"

    def test_architecture_exists(self):
        """Test that architecture.md exists and has content."""
        arch_path = Path("_agenttree/docs/architecture.md")
        assert arch_path.exists(), "architecture.md should exist"
        content = arch_path.read_text()
        assert len(content) > 100, "architecture.md should have substantial content"
        assert "AgentTree" in content, "architecture.md should mention AgentTree"

    def test_modules_directory_exists(self):
        """Test that modules/ directory exists."""
        modules_dir = Path("_agenttree/docs/modules")
        assert modules_dir.exists(), "modules/ directory should exist"
        assert modules_dir.is_dir(), "modules should be a directory"

    def test_module_docs_exist(self):
        """Test that expected module documentation files exist."""
        modules_dir = Path("_agenttree/docs/modules")
        expected_modules = ["hooks.md", "stages.md", "config.md", "cli.md", "web.md"]

        for module in expected_modules:
            module_path = modules_dir / module
            assert module_path.exists(), f"{module} should exist in modules/"
            content = module_path.read_text()
            assert len(content) > 50, f"{module} should have content"

    def test_decisions_directory_exists(self):
        """Test that decisions/ directory exists."""
        decisions_dir = Path("_agenttree/docs/decisions")
        assert decisions_dir.exists(), "decisions/ directory should exist"
        assert decisions_dir.is_dir(), "decisions should be a directory"

    def test_docs_system_decision_exists(self):
        """Test that the docs system decision record exists."""
        decision_path = Path("_agenttree/docs/decisions/2026-01-docs-system.md")
        assert decision_path.exists(), "docs-system decision record should exist"
        content = decision_path.read_text()
        assert "#115" in content or "115" in content, "Should reference issue #115"

    def test_notes_directory_exists(self):
        """Test that notes/ directory exists for imported notes."""
        notes_dir = Path("_agenttree/notes")
        assert notes_dir.exists(), "notes/ directory should exist"
        assert notes_dir.is_dir(), "notes should be a directory"

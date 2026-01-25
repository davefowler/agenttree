"""Tests for docs_update stage configuration."""

from pathlib import Path

import pytest
import yaml


class TestDocsUpdateStage:
    """Test that the docs_update stage is properly configured."""

    @pytest.fixture
    def config(self):
        """Load the agenttree configuration."""
        config_path = Path(".agenttree.yaml")
        with open(config_path) as f:
            return yaml.safe_load(f)

    def test_docs_update_stage_exists(self, config):
        """Test that docs_update stage is defined."""
        stages = config.get("stages", [])
        stage_names = [s.get("name") for s in stages]
        assert "docs_update" in stage_names, "docs_update stage should be defined"

    def test_closed_stage_exists(self, config):
        """Test that closed stage is defined."""
        stages = config.get("stages", [])
        stage_names = [s.get("name") for s in stages]
        assert "closed" in stage_names, "closed stage should be defined"

    def test_closed_stage_is_terminal(self, config):
        """Test that closed stage is terminal."""
        stages = config.get("stages", [])
        closed_stage = next((s for s in stages if s.get("name") == "closed"), None)
        assert closed_stage is not None, "closed stage should exist"
        assert closed_stage.get("terminal") is True, "closed stage should be terminal"

    def test_accepted_stage_not_terminal(self, config):
        """Test that accepted stage is no longer terminal."""
        stages = config.get("stages", [])
        accepted_stage = next((s for s in stages if s.get("name") == "accepted"), None)
        assert accepted_stage is not None, "accepted stage should exist"
        # terminal should be False or not present (defaults to False)
        assert accepted_stage.get("terminal") is not True, "accepted stage should not be terminal"

    def test_docs_update_has_output(self, config):
        """Test that docs_update stage has output defined."""
        stages = config.get("stages", [])
        docs_update = next((s for s in stages if s.get("name") == "docs_update"), None)
        assert docs_update is not None, "docs_update stage should exist"
        assert docs_update.get("output") == "docs_update.md", "docs_update should output docs_update.md"

    def test_docs_update_has_create_file_hook(self, config):
        """Test that docs_update stage creates the template file."""
        stages = config.get("stages", [])
        docs_update = next((s for s in stages if s.get("name") == "docs_update"), None)
        assert docs_update is not None, "docs_update stage should exist"

        post_start = docs_update.get("post_start", [])
        has_create_file = any(
            "create_file" in hook for hook in post_start
        )
        assert has_create_file, "docs_update should have create_file in post_start"

    def test_stage_order(self, config):
        """Test that stages are in correct order: accepted -> docs_update -> closed."""
        stages = config.get("stages", [])
        stage_names = [s.get("name") for s in stages]

        accepted_idx = stage_names.index("accepted")
        docs_update_idx = stage_names.index("docs_update")
        closed_idx = stage_names.index("closed")

        assert accepted_idx < docs_update_idx < closed_idx, \
            "Stage order should be: accepted -> docs_update -> closed"


class TestDocsUpdateSkill:
    """Test that docs_update skill file exists and is valid."""

    def test_skill_file_exists(self):
        """Test that docs_update skill file exists."""
        skill_path = Path("_agenttree/skills/docs_update.md")
        assert skill_path.exists(), "docs_update.md skill should exist"

    def test_skill_has_content(self):
        """Test that docs_update skill has content."""
        skill_path = Path("_agenttree/skills/docs_update.md")
        content = skill_path.read_text()
        assert len(content) > 200, "docs_update.md should have substantial content"
        assert "Documentation" in content, "Should mention documentation"
        assert "agenttree next" in content, "Should mention agenttree next"


class TestDocsUpdateTemplate:
    """Test that docs_update template file exists and is valid."""

    def test_template_file_exists(self):
        """Test that docs_update template file exists."""
        template_path = Path("_agenttree/templates/docs_update.md")
        assert template_path.exists(), "docs_update.md template should exist"

    def test_template_has_sections(self):
        """Test that docs_update template has expected sections."""
        template_path = Path("_agenttree/templates/docs_update.md")
        content = template_path.read_text()
        assert "Files Changed" in content, "Template should have Files Changed section"
        assert "Documentation Review" in content, "Template should have Documentation Review section"

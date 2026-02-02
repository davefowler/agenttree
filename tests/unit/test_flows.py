"""Tests for workflow flows feature."""

import pytest
import tempfile
from pathlib import Path

import yaml

from agenttree.config import Config, FlowConfig, StageConfig, load_config
from agenttree.issues import Issue, create_issue, Priority


class TestFlowConfig:
    """Tests for FlowConfig model."""

    def test_flow_config_creation(self):
        """Test creating a FlowConfig."""
        flow = FlowConfig(name="quick", stages=["define", "implement", "accepted"])
        assert flow.name == "quick"
        assert flow.stages == ["define", "implement", "accepted"]

    def test_flow_config_empty_stages(self):
        """Test FlowConfig with empty stages list."""
        flow = FlowConfig(name="empty", stages=[])
        assert flow.stages == []


class TestConfigFlows:
    """Tests for Config with flows."""

    def test_config_flows_field(self):
        """Test Config has flows field."""
        config = Config()
        assert hasattr(config, "flows")
        assert config.flows == {}

    def test_config_default_flow_field(self):
        """Test Config has default_flow field."""
        config = Config()
        assert hasattr(config, "default_flow")
        assert config.default_flow == "default"

    def test_get_flow(self):
        """Test get_flow method."""
        flow = FlowConfig(name="quick", stages=["define", "implement"])
        config = Config(flows={"quick": flow})

        assert config.get_flow("quick") == flow
        assert config.get_flow("nonexistent") is None

    def test_get_flow_stage_names(self):
        """Test get_flow_stage_names returns correct stages."""
        flow = FlowConfig(name="quick", stages=["define", "implement", "accepted"])
        config = Config(flows={"quick": flow})

        assert config.get_flow_stage_names("quick") == ["define", "implement", "accepted"]

    def test_get_flow_stage_names_nonexistent(self):
        """Test get_flow_stage_names for nonexistent flow."""
        config = Config()
        assert config.get_flow_stage_names("nonexistent") == []

    def test_get_flow_stage_names_default_fallback(self):
        """Test get_flow_stage_names falls back to stages list for default."""
        stages = [
            StageConfig(name="backlog"),
            StageConfig(name="define"),
            StageConfig(name="accepted", terminal=True),
        ]
        config = Config(stages=stages)  # No flows defined

        # Should fall back to stages list order
        assert config.get_flow_stage_names("default") == ["backlog", "define", "accepted"]


class TestGetNextStageWithFlows:
    """Tests for get_next_stage with flow parameter."""

    def test_get_next_stage_default_flow(self):
        """Test get_next_stage uses default flow."""
        stages = [
            StageConfig(name="define"),
            StageConfig(name="research"),
            StageConfig(name="plan"),
            StageConfig(name="accepted", terminal=True),
        ]
        default_flow = FlowConfig(name="default", stages=["define", "research", "plan", "accepted"])
        config = Config(stages=stages, flows={"default": default_flow})

        next_stage, _, _ = config.get_next_stage("define", flow="default")
        assert next_stage == "research"

    def test_get_next_stage_quick_flow(self):
        """Test get_next_stage uses quick flow that skips stages."""
        stages = [
            StageConfig(name="define"),
            StageConfig(name="research"),
            StageConfig(name="plan"),
            StageConfig(name="implement"),
            StageConfig(name="accepted", terminal=True),
        ]
        default_flow = FlowConfig(name="default", stages=["define", "research", "plan", "implement", "accepted"])
        quick_flow = FlowConfig(name="quick", stages=["define", "implement", "accepted"])
        config = Config(stages=stages, flows={"default": default_flow, "quick": quick_flow})

        # Default flow: define -> research
        next_stage, _, _ = config.get_next_stage("define", flow="default")
        assert next_stage == "research"

        # Quick flow: define -> implement (skips research and plan)
        next_stage, _, _ = config.get_next_stage("define", flow="quick")
        assert next_stage == "implement"

    def test_get_next_stage_terminal_stage(self):
        """Test get_next_stage stays at terminal stage."""
        stages = [
            StageConfig(name="define"),
            StageConfig(name="accepted", terminal=True),
        ]
        flow = FlowConfig(name="default", stages=["define", "accepted"])
        config = Config(stages=stages, flows={"default": flow})

        next_stage, _, _ = config.get_next_stage("accepted", flow="default")
        assert next_stage == "accepted"

    def test_get_next_stage_respects_substages(self):
        """Test get_next_stage respects substages within a flow."""
        from agenttree.config import SubstageConfig

        stages = [
            StageConfig(name="define", substages={
                "draft": SubstageConfig(name="draft"),
                "refine": SubstageConfig(name="refine"),
            }),
            StageConfig(name="implement"),
        ]
        flow = FlowConfig(name="default", stages=["define", "implement"])
        config = Config(stages=stages, flows={"default": flow})

        # Should advance within substages first
        next_stage, next_substage, _ = config.get_next_stage("define", "draft", flow="default")
        assert next_stage == "define"
        assert next_substage == "refine"

        # Then advance to next stage
        next_stage, next_substage, _ = config.get_next_stage("define", "refine", flow="default")
        assert next_stage == "implement"


class TestLoadConfigWithFlows:
    """Tests for load_config with flows."""

    def test_load_config_with_flows_section(self, tmp_path):
        """Test loading config with flows section."""
        config_content = """
stages:
  - name: backlog
  - name: define
  - name: implement
  - name: accepted
    terminal: true

flows:
  default:
    stages: [backlog, define, implement, accepted]
  quick:
    stages: [backlog, define, accepted]

default_flow: default
"""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text(config_content)

        config = load_config(tmp_path)

        assert "default" in config.flows
        assert "quick" in config.flows
        assert config.flows["default"].stages == ["backlog", "define", "implement", "accepted"]
        assert config.flows["quick"].stages == ["backlog", "define", "accepted"]
        assert config.default_flow == "default"

    def test_load_config_implicit_default_flow(self, tmp_path):
        """Test load_config creates implicit default flow when none defined."""
        config_content = """
stages:
  - name: backlog
  - name: define
  - name: accepted
    terminal: true
"""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text(config_content)

        config = load_config(tmp_path)

        assert "default" in config.flows
        assert config.flows["default"].stages == ["backlog", "define", "accepted"]

    def test_load_config_invalid_flow_reference(self, tmp_path):
        """Test load_config raises error for invalid stage reference in flow."""
        config_content = """
stages:
  - name: define
  - name: accepted
    terminal: true

flows:
  default:
    stages: [define, nonexistent, accepted]
"""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text(config_content)

        with pytest.raises(ValueError) as exc_info:
            load_config(tmp_path)

        assert "references unknown stage" in str(exc_info.value)
        assert "nonexistent" in str(exc_info.value)

    def test_load_config_empty_flow_stages(self, tmp_path):
        """Test load_config raises error for flow with empty stages."""
        config_content = """
stages:
  - name: define
  - name: accepted
    terminal: true

flows:
  empty:
    stages: []
"""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text(config_content)

        with pytest.raises(ValueError) as exc_info:
            load_config(tmp_path)

        assert "has no stages" in str(exc_info.value)


class TestIssueFlowField:
    """Tests for Issue.flow field."""

    def test_issue_has_flow_field(self):
        """Test Issue model has flow field."""
        issue = Issue(
            id="001",
            slug="test",
            title="Test Issue",
            created="2024-01-01T00:00:00Z",
            updated="2024-01-01T00:00:00Z",
        )
        assert hasattr(issue, "flow")
        assert issue.flow == "default"

    def test_issue_flow_field_custom(self):
        """Test Issue flow field can be set."""
        issue = Issue(
            id="001",
            slug="test",
            title="Test Issue",
            created="2024-01-01T00:00:00Z",
            updated="2024-01-01T00:00:00Z",
            flow="quick",
        )
        assert issue.flow == "quick"

    def test_issue_flow_serialization(self):
        """Test Issue flow field is serialized correctly."""
        issue = Issue(
            id="001",
            slug="test",
            title="Test Issue",
            created="2024-01-01T00:00:00Z",
            updated="2024-01-01T00:00:00Z",
            flow="quick",
        )
        data = issue.model_dump()
        assert data["flow"] == "quick"


class TestCreateIssueWithFlow:
    """Tests for create_issue with flow parameter."""

    def test_create_issue_default_flow(self, tmp_path, monkeypatch):
        """Test create_issue uses default flow."""
        # Set up mock _agenttree directory
        agenttree_dir = tmp_path / "_agenttree"
        agenttree_dir.mkdir()
        (agenttree_dir / "issues").mkdir()

        monkeypatch.setattr("agenttree.issues.get_agenttree_path", lambda: agenttree_dir)
        monkeypatch.setattr("agenttree.issues.sync_agents_repo", lambda *args, **kwargs: None)

        issue = create_issue(title="Test Issue")
        assert issue.flow == "default"

    def test_create_issue_custom_flow(self, tmp_path, monkeypatch):
        """Test create_issue with custom flow."""
        # Set up mock _agenttree directory
        agenttree_dir = tmp_path / "_agenttree"
        agenttree_dir.mkdir()
        (agenttree_dir / "issues").mkdir()

        monkeypatch.setattr("agenttree.issues.get_agenttree_path", lambda: agenttree_dir)
        monkeypatch.setattr("agenttree.issues.sync_agents_repo", lambda *args, **kwargs: None)

        issue = create_issue(title="Test Issue", flow="quick")
        assert issue.flow == "quick"

    def test_create_issue_flow_persisted(self, tmp_path, monkeypatch):
        """Test create_issue persists flow in issue.yaml."""
        # Set up mock _agenttree directory
        agenttree_dir = tmp_path / "_agenttree"
        agenttree_dir.mkdir()
        (agenttree_dir / "issues").mkdir()

        monkeypatch.setattr("agenttree.issues.get_agenttree_path", lambda: agenttree_dir)
        monkeypatch.setattr("agenttree.issues.sync_agents_repo", lambda *args, **kwargs: None)

        issue = create_issue(title="Test Issue", flow="quick")

        # Read the issue.yaml file
        issue_dir = agenttree_dir / "issues" / f"{issue.id}-{issue.slug}"
        yaml_file = issue_dir / "issue.yaml"
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        assert data["flow"] == "quick"

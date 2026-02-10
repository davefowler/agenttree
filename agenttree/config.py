"""Configuration management for AgentTree."""

from pathlib import Path
from typing import Dict, List, Optional, Union
import yaml
from pydantic import BaseModel, ConfigDict, Field


class ToolConfig(BaseModel):
    """Configuration for an AI tool."""

    command: str
    startup_prompt: str = "Check tasks/ folder and start working on the oldest task."
    skip_permissions: bool = False  # Add --dangerously-skip-permissions to command


class ContainerConfig(BaseModel):
    """Configuration for container settings.

    Defines how a host runs in a container (or doesn't).
    """

    enabled: bool = True  # Whether to run in a container
    image: str = "agenttree-agent:latest"  # Container image to use
    # Future: additional container options (memory limits, env vars, etc.)


class RoleConfig(BaseModel):
    """Configuration for a role in the workflow.

    Roles define who handles stages. Built-in roles:
    - manager: Human-driven orchestration (runs on host machine, no container)
    - developer: Default AI agent that writes code (runs in container)

    Custom roles can be defined for specialized agents (e.g., reviewer).
    """

    name: str  # Role name (e.g., "manager", "developer", "reviewer")
    description: str = ""  # Human-readable description

    # Container configuration (None = no container, runs on host)
    container: Optional[ContainerConfig] = None

    # AI agent settings (only for AI roles, not manager)
    tool: Optional[str] = None  # AI tool to use (e.g., "claude", "codex")
    model: str | None = None  # Explicit model (e.g., "opus"). Overrides model_tier.
    model_tier: str | None = None  # Tier name (e.g., "high", "medium", "low") → resolved via model_tiers
    skill: Optional[str] = None  # Skill file path for custom agents

    # Process to run (for manager, this could be "agenttree watch")
    process: Optional[str] = None

    def is_containerized(self) -> bool:
        """Check if this role runs in a container."""
        return self.container is not None and self.container.enabled

    def is_agent(self) -> bool:
        """Check if this role is an AI agent (has tool configured)."""
        return self.tool is not None


class HooksConfig(BaseModel):
    """Configuration for host action hooks."""

    post_pr_create: list[dict] = Field(default_factory=list)  # After PR created
    post_merge: list[dict] = Field(default_factory=list)  # After merge
    post_accepted: list[dict] = Field(default_factory=list)  # After issue accepted


class ActionConfig(BaseModel):
    """Configuration for a single action with optional rate limiting.
    
    Actions can be specified as:
    - Simple string: "sync"
    - Dict with config: {"check_ci_status": {"min_interval_s": 60}}
    """
    
    name: str
    min_interval_s: int | None = None  # Time-based rate limit
    every_n: int | None = None  # Count-based rate limit (every Nth heartbeat)
    optional: bool = False  # If true, failure doesn't block


class HeartbeatConfig(BaseModel):
    """Configuration for heartbeat events."""
    
    interval_s: int = 10  # Seconds between heartbeats
    actions: list[str | dict] = Field(default_factory=list)


class OnConfig(BaseModel):
    """Configuration for event-driven hooks.
    
    The `on:` config defines what actions run when events fire.
    
    Example:
        on:
          startup:
            - start_manager
            - auto_start_agents
          
          heartbeat:
            interval_s: 10
            actions:
              - sync
              - check_stalled_agents: { min_interval_s: 60 }
          
          shutdown:
            - sync
            - stop_all_agents
    """
    
    startup: list[str | dict] = Field(default_factory=list)
    shutdown: list[str | dict] = Field(default_factory=list)
    heartbeat: HeartbeatConfig | dict | None = None


class SubstageConfig(BaseModel):
    """Configuration for a workflow substage."""

    name: str
    output: Optional[str] = None  # Document created by this substage
    output_optional: bool = False  # If True, missing output file doesn't error
    skill: Optional[str] = None   # Override skill file path
    model: str | None = None   # Explicit model (overrides model_tier and stage model)
    model_tier: str | None = None  # Tier name (e.g., "high") → resolved via model_tiers
    redirect_only: bool = False   # Only reachable via StageRedirect, skipped in normal progression
    validators: list[str] = Field(default_factory=list)  # Legacy format
    pre_completion: list[dict] = Field(default_factory=list)  # Hooks before completing
    post_start: list[dict] = Field(default_factory=list)  # Hooks after starting


class StageConfig(BaseModel):
    """Configuration for a workflow stage."""

    name: str
    output: Optional[str] = None  # Document created by this stage
    output_optional: bool = False  # If True, missing output file doesn't error
    skill: Optional[str] = None   # Override skill file path
    model: str | None = None   # Explicit model (overrides model_tier)
    model_tier: str | None = None  # Tier name (e.g., "high") → resolved via model_tiers
    human_review: bool = False    # Requires human approval to exit
    is_parking_lot: bool = False  # No agent auto-starts here (backlog, accepted, not_doing)
    redirect_only: bool = False   # Only reachable via StageRedirect, skipped in normal progression
    role: str = "developer"       # Who executes this stage: "developer", "manager", or custom role name
    review_doc: str | None = None  # Document to show by default when viewing issue in this stage
    substages: Dict[str, SubstageConfig] = Field(default_factory=dict)
    pre_completion: list[dict] = Field(default_factory=list)  # Stage-level hooks before completing
    post_start: list[dict] = Field(default_factory=list)  # Stage-level hooks after starting

    def substage_order(self) -> list[str]:
        """Get ordered list of substage names."""
        return list(self.substages.keys())

    def get_substage(self, name: str) -> Optional[SubstageConfig]:
        """Get a substage by name."""
        return self.substages.get(name)

    def hooks_for(self, substage: Optional[str], event: str) -> list[dict]:
        """Get hooks for a substage or stage.

        Args:
            substage: Substage name, or None for stage-level hooks
            event: "pre_completion" or "post_start"

        Returns:
            List of hook configurations
        """
        if substage:
            substage_config = self.get_substage(substage)
            if substage_config:
                return getattr(substage_config, event, [])
            return []
        return getattr(self, event, [])


class FlowConfig(BaseModel):
    """Configuration for a workflow flow.

    A flow defines an ordered list of stage names that issues following
    this flow will progress through. Stage definitions are shared across
    flows - this just controls the order and which stages are included.
    """

    name: str  # Flow name (e.g., "default", "quick")
    stages: list[str] = Field(default_factory=list)  # Ordered list of stage names


class ManagerConfig(BaseModel):
    """Configuration for the manager's stall monitoring.

    These settings control how the manager detects and handles stalled agents.
    """

    stall_threshold_min: int = 20  # Minutes before agent considered stalled
    nudge_cooldown_min: int = 30  # Minutes between nudges for same agent
    max_nudges_before_escalate: int = 3  # Escalate after N failed nudges


class SecurityConfig(BaseModel):
    """Security configuration for agents.

    NOTE: Containers are MANDATORY. There is no option to disable them.
    This config exists for future security settings, not to bypass containers.
    """

    # Reserved for future security settings
    # Containers are always required - this is not configurable


class RateLimitFallbackConfig(BaseModel):
    """Configuration for automatic rate limit fallback to API key mode.
    
    When Claude Code Max subscription hits its usage limit, this feature
    automatically switches agents to API key mode until the limit resets.
    
    Example:
        rate_limit_fallback:
          enabled: true
          api_key_env: ANTHROPIC_API_KEY
          model: claude-sonnet-4-20250514
          switch_back_buffer_min: 5
    """
    
    enabled: bool = False  # Off by default
    api_key_env: str = "ANTHROPIC_API_KEY"  # Name of env var (NOT the key itself!)
    model: str = "claude-sonnet-4-20250514"  # Cheaper model for API mode
    switch_back_buffer_min: int = 5  # Minutes after reset to wait before switching back


class Config(BaseModel):
    """AgentTree configuration."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    project: str = "myapp"
    worktrees_dir: Path = Field(default_factory=lambda: Path(".worktrees"))
    scripts_dir: Path = Field(default_factory=lambda: Path("scripts"))
    port_range: str = "9001-9099"
    default_tool: str = "claude"
    default_model: str = "opus"  # Model to use for Claude CLI (opus, sonnet)
    model_tiers: dict[str, str] = Field(default_factory=dict)  # Tier name -> model name mapping
    refresh_interval: int = 10
    tools: Dict[str, ToolConfig] = Field(default_factory=dict)
    roles: Dict[str, RoleConfig] = Field(default_factory=dict)  # Role configurations
    commands: Dict[str, Union[str, list[str]]] = Field(default_factory=dict)  # Named shell commands
    stages: list[StageConfig] = Field(default_factory=list)  # Must be defined in .agenttree.yaml
    flows: dict[str, FlowConfig] = Field(default_factory=dict)  # Named workflow flows
    default_flow: str = "default"  # Which flow to use when not specified
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    merge_strategy: str = "squash"  # squash, merge, or rebase
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    save_tmux_history: bool = False  # Save tmux session history on stage transitions
    manager: ManagerConfig = Field(default_factory=ManagerConfig)
    show_issue_yaml: bool = True  # Show issue.yaml in web UI file tabs
    on: Optional[OnConfig] = None  # Event-driven hooks configuration
    rate_limit_fallback: RateLimitFallbackConfig = Field(default_factory=RateLimitFallbackConfig)
    allow_self_approval: bool = False  # Skip PR approval check when approving own PRs (solo projects)

    def get_port_for_agent(self, agent_num: int) -> int:
        """Get port number for a specific agent.

        Args:
            agent_num: Agent number (1-based)

        Returns:
            Port number for the agent

        Raises:
            ValueError: If agent number exceeds port range
        """
        start_port, end_port = map(int, self.port_range.split("-"))
        port = start_port + (agent_num - 1)

        if port > end_port:
            raise ValueError(
                f"Agent number {agent_num} exceeds port range {self.port_range}"
            )

        return port

    def get_port_for_issue(self, issue_id: str) -> Optional[int]:
        """Get port number for a specific issue.

        Port is calculated from issue ID using the configured port_range.
        Returns None if issue_id is not a valid integer or if the port
        would exceed the configured range.

        Args:
            issue_id: Issue ID (string, typically numeric like "001", "042")

        Returns:
            Port number, or None if issue_id is invalid or exceeds range
        """
        try:
            issue_num = int(issue_id)
            return self.get_port_for_agent(issue_num)
        except (ValueError, TypeError):
            return None

    def get_worktree_path(self, agent_num: int) -> Path:
        """Get worktree path for a specific agent (legacy numbered agents).

        Args:
            agent_num: Agent number

        Returns:
            Path to the agent's worktree
        """
        expanded_dir = Path(self.worktrees_dir).expanduser()
        return expanded_dir / f"{self.project}-agent-{agent_num}"

    def get_issue_worktree_path(self, issue_id: str, slug: str) -> Path:
        """Get worktree path for an issue-bound agent.

        Args:
            issue_id: Issue ID (e.g., "023")
            slug: Issue slug (e.g., "fix-login-bug")

        Returns:
            Path to the issue's worktree
        """
        expanded_dir = Path(self.worktrees_dir).expanduser()
        short_slug = slug[:30] if len(slug) > 30 else slug
        return expanded_dir / f"issue-{issue_id}-{short_slug}"

    def get_tmux_session_name(self, agent_num: int) -> str:
        """Get tmux session name for a specific agent (legacy numbered agents).

        Args:
            agent_num: Agent number

        Returns:
            Tmux session name
        """
        return f"{self.project}-developer-{agent_num}"

    def get_issue_tmux_session(self, issue_id: str, role: str = "developer") -> str:
        """Get tmux session name for an issue-bound agent.

        Args:
            issue_id: Issue ID
            role: Agent role - "developer", "reviewer", or "manager"

        Returns:
            Tmux session name like "agenttree-developer-128"
        """
        return f"{self.project}-{role}-{issue_id}"

    def get_manager_tmux_session(self) -> str:
        """Get tmux session name for the manager agent.

        Returns:
            Session name like "agenttree-manager-000"
        """
        return f"{self.project}-manager-000"

    def get_issue_session_patterns(self, issue_id: str) -> list[str]:
        """Get all possible tmux session names for an issue.

        Delegates to tmux.get_session_patterns() - the single source of truth.

        Args:
            issue_id: Issue ID

        Returns:
            List of possible session names, current patterns first
        """
        from agenttree.tmux import get_session_patterns
        return get_session_patterns(self.project, issue_id)

    def is_project_session(self, session_name: str) -> bool:
        """Check if a session name belongs to this project.
        
        Args:
            session_name: Tmux session name to check
            
        Returns:
            True if session belongs to this project
        """
        return session_name.startswith(f"{self.project}-")

    def get_issue_container_name(self, issue_id: str) -> str:
        """Get container name for an issue-bound agent.

        Args:
            issue_id: Issue ID

        Returns:
            Container name
        """
        return f"{self.project}-issue-{issue_id}"

    def get_tool_config(self, tool_name: str) -> ToolConfig:
        """Get configuration for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool configuration (creates default if not found)
        """
        if tool_name in self.tools:
            return self.tools[tool_name]

        # Return default config for unknown tools
        return ToolConfig(command=tool_name)

    def get_ci_script(self, script_name: str = "ci.sh") -> Path:
        """Get path to a CI script.

        Args:
            script_name: Name of the script (ci.sh, quick_ci.sh, extensive_ci.sh)

        Returns:
            Path to the script
        """
        return self.scripts_dir / script_name

    def get_stage(self, stage_name: str) -> Optional[StageConfig]:
        """Get configuration for a stage.

        Args:
            stage_name: Name of the stage

        Returns:
            Stage configuration, or None if not found
        """
        for stage in self.stages:
            if stage.name == stage_name:
                return stage
        return None

    def get_stage_names(self) -> list[str]:
        """Get list of all stage names in order.

        Returns:
            List of stage names
        """
        return [stage.name for stage in self.stages]

    def get_human_review_stages(self) -> list[str]:
        """Get list of stages that require human review.

        Returns:
            List of stage names that require human review
        """
        return [stage.name for stage in self.stages if stage.human_review]

    def get_manager_stages(self) -> list[str]:
        """Get list of stages executed by the manager (host), not developer.

        Returns:
            List of stage names where role=manager
        """
        return [stage.name for stage in self.stages if stage.role == "manager"]

    def get_all_roles(self) -> Dict[str, RoleConfig]:
        """Get all roles including built-in defaults.

        Returns dict with:
        - Built-in 'manager' role (no container)
        - Built-in 'developer' role (containerized, uses default tool/model)
        - Any custom roles from config

        Returns:
            Dict of role name -> RoleConfig
        """
        # Start with built-in defaults
        all_roles: Dict[str, RoleConfig] = {
            "manager": RoleConfig(
                name="manager",
                description="Human-driven manager (runs on host)",
                container=None,  # No container
                process=None,  # Could be "agenttree watch" in future
                model_tier="low",  # Manager just runs CLI commands
            ),
            "developer": RoleConfig(
                name="developer",
                description="Default AI agent that writes code",
                container=ContainerConfig(enabled=True),
                tool=self.default_tool,
                model=self.default_model,
            ),
        }

        # Merge in roles from config (can override defaults)
        all_roles.update(self.roles)

        return all_roles

    def get_role(self, role_name: str) -> Optional[RoleConfig]:
        """Get configuration for a role (including built-in defaults).

        Args:
            role_name: Name of the role

        Returns:
            RoleConfig or None if not found
        """
        return self.get_all_roles().get(role_name)

    def get_custom_role_stages(self) -> list[str]:
        """Get list of stages that use custom roles.

        Custom role stages have a role value that is neither "developer" nor "manager"
        and exists in the roles configuration.

        Returns:
            List of stage names where role is a custom role
        """
        all_roles = self.get_all_roles()
        return [
            stage.name for stage in self.stages
            if stage.role not in ("developer", "manager") and stage.role in all_roles
        ]

    def get_custom_role(self, role_name: str) -> Optional[RoleConfig]:
        """Get configuration for a custom role.

        Args:
            role_name: Name of the role

        Returns:
            RoleConfig or None if not found
        """
        return self.roles.get(role_name)

    def is_custom_role(self, role_name: str) -> bool:
        """Check if a role name is a custom role (not manager or default developer).

        Args:
            role_name: Name to check

        Returns:
            True if it's a custom role, False otherwise
        """
        if role_name in ("manager", "developer"):
            return False
        return role_name in self.roles

    def get_non_developer_stages(self) -> list[str]:
        """Get list of stages NOT executed by the default developer.

        This includes manager stages and custom role stages.
        Used to determine which stages the default developer should block on.

        Returns:
            List of stage names where role != "developer"
        """
        return [stage.name for stage in self.stages if stage.role != "developer"]

    def role_is_containerized(self, role_name: str) -> bool:
        """Check if a role runs in a container.

        Args:
            role_name: Name of the role

        Returns:
            True if containerized, False otherwise
        """
        role = self.get_role(role_name)
        if role:
            return role.is_containerized()
        # Default: assume custom roles are containerized
        return role_name != "manager"

    def substages_for(self, stage_name: str) -> list[str]:
        """Get ordered list of substage names for a stage.

        Args:
            stage_name: Name of the stage

        Returns:
            List of substage names (empty if no substages)
        """
        stage = self.get_stage(stage_name)
        if stage is None:
            return []
        return stage.substage_order()

    def skill_path(self, stage_name: str, substage: Optional[str] = None) -> str:
        """Get the skill file path for a stage/substage.

        Convention: skills/{stage}.md or skills/{stage}/{substage}.md
        Can be overridden with explicit skill property in config.

        Args:
            stage_name: Name of the stage
            substage: Optional substage name

        Returns:
            Relative path to skill file (from _agenttree/)
        """
        stage = self.get_stage(stage_name)

        # Check for explicit override
        if substage and stage:
            substage_config = stage.get_substage(substage)
            if substage_config and substage_config.skill:
                return f"skills/{substage_config.skill}"
        if stage and stage.skill:
            return f"skills/{stage.skill}"

        # Use convention: skills/{stage}/{substage}.md or skills/{stage}.md
        if substage:
            return f"skills/{stage_name}/{substage}.md"
        return f"skills/{stage_name}.md"

    def output_for(self, stage_name: str, substage: Optional[str] = None) -> Optional[str]:
        """Get the output document name for a stage/substage.

        Args:
            stage_name: Name of the stage
            substage: Optional substage name

        Returns:
            Document name (e.g., "problem.md") or None
        """
        stage = self.get_stage(stage_name)
        if stage is None:
            return None

        # Check substage output first
        if substage:
            substage_config = stage.get_substage(substage)
            if substage_config and substage_config.output:
                return substage_config.output

        # Fall back to stage output
        return stage.output

    def model_for(self, stage_name: str, substage: Optional[str] = None, role: Optional[str] = None) -> str:
        """Get the model to use. Checks substage → stage → role → default.

        At each level, explicit `model` beats `model_tier`.
        """
        tiers = self.model_tiers

        # Check each config in priority order: substage, stage, role
        configs: list[object] = []
        stage = self.get_stage(stage_name)
        if stage:
            if substage:
                sc = stage.get_substage(substage)
                if sc:
                    configs.append(sc)
            configs.append(stage)
        if role:
            rc = self.get_role(role)
            if rc:
                configs.append(rc)

        for cfg in configs:
            m: str | None = getattr(cfg, "model", None)
            if m:
                return m
            t: str | None = getattr(cfg, "model_tier", None)
            if t and t in tiers:
                return tiers[t]

        return self.default_model

    def validators_for(self, stage_name: str, substage: Optional[str] = None) -> list[str]:
        """Get validators for a stage/substage.

        Args:
            stage_name: Name of the stage
            substage: Optional substage name

        Returns:
            List of validator names
        """
        stage = self.get_stage(stage_name)
        if stage is None:
            return []

        if substage:
            substage_config = stage.get_substage(substage)
            if substage_config:
                return substage_config.validators

        return []

    def is_parking_lot(self, stage_name: str) -> bool:
        """Check if a stage is a parking lot (no agent auto-starts).

        Parking lot stages are stages where issues can sit without active agents.
        Examples: backlog (waiting to start), accepted (done), not_doing (abandoned).

        Args:
            stage_name: Name of the stage

        Returns:
            True if parking lot, False otherwise
        """
        stage = self.get_stage(stage_name)
        return stage.is_parking_lot if stage else False

    def get_parking_lot_stages(self) -> set[str]:
        """Get names of all parking lot stages.

        Returns:
            Set of stage names where is_parking_lot is True
        """
        return {stage.name for stage in self.stages if stage.is_parking_lot}

    def get_flow(self, flow_name: str) -> Optional[FlowConfig]:
        """Get configuration for a flow.

        Args:
            flow_name: Name of the flow

        Returns:
            FlowConfig or None if not found
        """
        return self.flows.get(flow_name)

    def get_flow_stage_names(self, flow_name: str = "default") -> list[str]:
        """Get ordered list of stage names for a flow.

        When no flows are defined (e.g., direct Config instantiation in tests
        or legacy configs), falls back to using all stages in definition order.

        Args:
            flow_name: Name of the flow (default: "default")

        Returns:
            List of stage names in flow order
        """
        flow = self.get_flow(flow_name)
        if flow:
            return flow.stages

        # Fallback for configs without flows defined (tests, legacy configs)
        if flow_name == "default" and not self.flows:
            return self.get_stage_names()

        return []

    def get_next_stage(
        self,
        current_stage: str,
        current_substage: Optional[str] = None,
        flow: str = "default",
    ) -> tuple[str, Optional[str], bool]:
        """Calculate the next stage/substage.

        Args:
            current_stage: Current stage name
            current_substage: Current substage (if any)
            flow: Flow name to use for stage progression (default: "default")

        Returns:
            Tuple of (next_stage, next_substage, is_human_review)
        """
        stage_config = self.get_stage(current_stage)
        if stage_config is None:
            return current_stage, current_substage, False

        substages = stage_config.substage_order()

        # If we have substages, try to advance within them
        if substages and current_substage:
            try:
                idx = substages.index(current_substage)
                # Look for next non-redirect_only substage
                for next_idx in range(idx + 1, len(substages)):
                    next_sub_name = substages[next_idx]
                    next_sub = stage_config.get_substage(next_sub_name)
                    if next_sub and next_sub.redirect_only:
                        continue  # Skip redirect_only substages in normal progression
                    return current_stage, next_sub_name, False
                # All remaining substages are redirect_only, move to next stage
            except ValueError:
                pass  # substage not found, move to next stage

        # Move to next stage (skip redirect_only stages)
        # Use the flow's stage order instead of global stages
        stage_names = self.get_flow_stage_names(flow)
        try:
            stage_idx = stage_names.index(current_stage)
            # Look for next non-redirect_only stage
            for next_idx in range(stage_idx + 1, len(stage_names)):
                next_stage_name = stage_names[next_idx]
                next_stage = self.get_stage(next_stage_name)
                if next_stage:
                    # Skip redirect_only stages in normal progression
                    if next_stage.redirect_only:
                        continue
                    next_substages = next_stage.substage_order()
                    next_substage = next_substages[0] if next_substages else None
                    return next_stage_name, next_substage, next_stage.human_review
        except ValueError:
            pass

        # Already at end
        return current_stage, current_substage, False

    def format_stage(self, stage: str, substage: Optional[str] = None) -> str:
        """Format stage/substage as a display string.

        Args:
            stage: Stage name
            substage: Optional substage name

        Returns:
            Formatted string like "implement/code_review" or "backlog"
        """
        if substage:
            return f"{stage}/{substage}"
        return stage

    def parse_stage(self, stage_str: str) -> tuple[str, Optional[str]]:
        """Parse a stage string into stage and substage.

        Args:
            stage_str: String like "implement/code_review" or "backlog"

        Returns:
            Tuple of (stage, substage) where substage may be None
        """
        if "/" in stage_str:
            parts = stage_str.split("/", 1)
            return parts[0], parts[1]
        return stage_str, None


def find_config_file(start_path: Path) -> Optional[Path]:
    """Find .agenttree.yaml file by walking up directory tree.

    Args:
        start_path: Directory to start searching from

    Returns:
        Path to config file, or None if not found
    """
    current = start_path.resolve()

    # Walk up the directory tree
    while True:
        config_file = current / ".agenttree.yaml"
        if config_file.exists():
            return config_file

        # Check if we've reached the root
        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def load_config(path: Optional[Path] = None) -> Config:
    """Load configuration from .agenttree.yaml file.

    Args:
        path: Path to directory containing config file (default: current directory)

    Returns:
        Loaded configuration (or default if file not found)
    """
    if path is None:
        path = Path.cwd()

    config_file = find_config_file(path)

    if config_file is None:
        return Config()

    with open(config_file, "r") as f:
        data = yaml.safe_load(f)

    if data is None:
        return Config()

    # Auto-populate 'name' field for substages from the key
    if "stages" in data:
        for stage in data["stages"]:
            if "substages" in stage and isinstance(stage["substages"], dict):
                for substage_name, substage_config in stage["substages"].items():
                    if substage_config is None:
                        stage["substages"][substage_name] = {"name": substage_name}
                    elif "name" not in substage_config:
                        substage_config["name"] = substage_name

    # Auto-populate 'name' field for roles from the key
    if "roles" in data and isinstance(data["roles"], dict):
        for role_name, role_config in data["roles"].items():
            if role_config is None:
                data["roles"][role_name] = {"name": role_name}
            elif isinstance(role_config, dict):
                if "name" not in role_config:
                    role_config["name"] = role_name
                # Ensure container config is properly structured
                if "container" in role_config and role_config["container"] is True:
                    role_config["container"] = {"enabled": True}
                elif "container" in role_config and role_config["container"] is False:
                    role_config["container"] = None

    # Auto-populate 'name' field for flows from the key
    if "flows" in data and isinstance(data["flows"], dict):
        for flow_name, flow_config in data["flows"].items():
            if flow_config is None:
                data["flows"][flow_name] = {"name": flow_name, "stages": []}
            elif isinstance(flow_config, dict):
                if "name" not in flow_config:
                    flow_config["name"] = flow_name

    # Get stage names for validation
    stage_names = set()
    if "stages" in data:
        for stage in data["stages"]:
            if isinstance(stage, dict) and "name" in stage:
                stage_names.add(stage["name"])

    # Create implicit default flow if no flows defined
    if "flows" not in data or not data["flows"]:
        if stage_names:
            data["flows"] = {
                "default": {
                    "name": "default",
                    "stages": [s["name"] for s in data.get("stages", []) if isinstance(s, dict) and "name" in s]
                }
            }

    # Validate flow stage references
    if "flows" in data and isinstance(data["flows"], dict):
        for flow_name, flow_config in data["flows"].items():
            if flow_config and isinstance(flow_config, dict):
                flow_stages = flow_config.get("stages", [])
                # Validate empty flows
                if not flow_stages:
                    raise ValueError(f"Flow '{flow_name}' has no stages defined")
                # Validate stage references
                for stage_name in flow_stages:
                    if stage_name not in stage_names:
                        raise ValueError(
                            f"Flow '{flow_name}' references unknown stage '{stage_name}'"
                        )

    # Handle YAML 'on:' being parsed as boolean True
    # In YAML 1.1, 'on', 'off', 'yes', 'no' are reserved boolean keywords
    # Users can either quote "on": or we handle True -> "on" here
    if True in data:
        data["on"] = data.pop(True)

    return Config(**data)

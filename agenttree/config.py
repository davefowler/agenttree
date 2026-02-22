"""Configuration management for AgentTree."""

import logging
from pathlib import Path
from typing import Optional, Union
import yaml
from jinja2 import Template, UndefinedError
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class ToolConfig(BaseModel):
    """Configuration for an AI tool.

    Tools define the AI CLI that runs inside containers. The tool config
    provides methods for generating container mounts, env vars, and the
    entry command. This keeps tool-specific logic in the tool config,
    not scattered in the container builder.
    """

    command: str
    startup_prompt: str = "Check tasks/ folder and start working on the oldest task."
    skip_permissions: bool = False  # Add --dangerously-skip-permissions to command

    def container_mounts(
        self,
        worktree_path: Path,
        role: str,
        home: Path | None = None,
    ) -> list[tuple[str, str, str]]:
        """Get tool-specific container mounts.

        Returns list of (host_path, container_path, mode) tuples.
        These are mounts needed by the tool itself (config dirs, session storage).

        Args:
            worktree_path: Path to the worktree being mounted
            role: Agent role (used for session storage separation)
            home: Home directory (defaults to Path.home())

        Returns:
            List of mount tuples (host, container, mode)
        """
        if home is None:
            home = Path.home()

        mounts: list[tuple[str, str, str]] = []

        # Claude config directory (contains settings.json)
        claude_config_dir = home / ".claude"
        if claude_config_dir.exists():
            mounts.append((str(claude_config_dir), "/home/agent/.claude-host", "ro"))

        # Session storage for conversation persistence across restarts
        # Each role gets its own session directory to keep conversations separate
        sessions_dir = worktree_path / f".claude-sessions-{role}"
        sessions_dir.mkdir(exist_ok=True)
        mounts.append((str(sessions_dir), "/home/agent/.claude/projects/-workspace", "rw"))

        return mounts

    def container_env(
        self,
        home: Path | None = None,
        force_api_key: bool = False,
    ) -> dict[str, str]:
        """Get tool-specific container environment variables.

        Returns dict of env vars needed by the tool (auth tokens, API keys).

        Args:
            home: Home directory (defaults to Path.home())
            force_api_key: Skip OAuth token, use API key only

        Returns:
            Dict of env var name to value
        """
        import os

        if home is None:
            home = Path.home()

        env: dict[str, str] = {}

        def get_credential(env_var: str, file_key: str) -> str | None:
            # Check environment first
            if os.environ.get(env_var):
                return os.environ[env_var]
            # Fall back to credentials file
            creds_file = home / ".config" / "agenttree" / "credentials"
            if creds_file.exists():
                for line in creds_file.read_text().splitlines():
                    if line.startswith(f"{file_key}="):
                        return line.split("=", 1)[1].strip()
            return None

        # OAuth token for subscription auth (from `claude setup-token`)
        if not force_api_key:
            oauth_token = get_credential("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
            if oauth_token:
                env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token

        # Always pass API key if available (for rate limit fallback)
        api_key = get_credential("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key

        return env

    def container_entry_command(
        self,
        model: str | None = None,
        dangerous: bool = True,
        continue_session: bool = False,
    ) -> list[str]:
        """Get the command to run the tool inside the container.

        Args:
            model: Model to use (e.g., "opus", "sonnet")
            dangerous: Whether to skip permission prompts
            continue_session: Whether to continue a previous session (-c flag)

        Returns:
            Command list to append to container run command
        """
        cmd = [self.command]

        if continue_session:
            cmd.append("-c")

        if model:
            cmd.extend(["--model", model])

        if dangerous or self.skip_permissions:
            cmd.append("--dangerously-skip-permissions")

        return cmd


class ContainerConfig(BaseModel):
    """Configuration for container settings.

    Defines how a host runs in a container (or doesn't).
    """

    enabled: bool = True  # Whether to run in a container
    image: str = "agenttree-agent:latest"  # Container image to use


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
    container: ContainerConfig | None = None

    # AI agent settings (only for AI roles, not manager)
    tool: str | None = None  # AI tool to use (e.g., "claude", "codex")
    model: str | None = None  # Explicit model (e.g., "opus"). Overrides model_tier.
    model_tier: str | None = None  # Tier name (e.g., "high", "medium", "low") → resolved via model_tiers
    skill: str | None = None  # Skill file path for custom agents

    # Process to run (for manager, this could be "agenttree watch")
    process: str | None = None

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
    """Configuration for a single action with optional rate limiting."""

    name: str
    min_interval_s: int | None = None
    every_n: int | None = None
    optional: bool = False


class HeartbeatConfig(BaseModel):
    """Configuration for heartbeat events."""

    interval_s: int = 10
    actions: list[str | dict] = Field(default_factory=list)


class OnConfig(BaseModel):
    """Configuration for event-driven hooks."""

    startup: list[str | dict] = Field(default_factory=list)
    shutdown: list[str | dict] = Field(default_factory=list)
    heartbeat: HeartbeatConfig | dict | None = None


class SubstageConfig(BaseModel):
    """Configuration for a workflow substage."""

    name: str
    output: str | None = None  # Document created by this substage
    output_optional: bool = False  # If True, missing output file doesn't error
    skill: str | None = None  # Override skill file path
    model: str | None = None  # Explicit model (overrides model_tier and stage model)
    model_tier: str | None = None  # Tier name (e.g., "high") → resolved via model_tiers
    redirect_only: bool = False  # Only reachable via StageRedirect, skipped in normal progression
    human_review: bool = False  # Requires human approval to exit
    condition: str | None = None  # Jinja expression - skip when false
    role: str | None = None  # Override stage role (None = inherit from stage)
    review_doc: str | None = None  # Document to show by default
    validators: list[str] = Field(default_factory=list)  # Legacy format
    pre_completion: list[dict] = Field(default_factory=list)
    post_start: list[dict] = Field(default_factory=list)
    post_completion: list[dict] = Field(default_factory=list)


class StageConfig(BaseModel):
    """Configuration for a workflow stage (group of substages)."""

    name: str
    color: str | None = None  # UI color for this stage group
    output: str | None = None  # Document created by this stage (stages without substages)
    output_optional: bool = False
    skill: str | None = None  # Override skill file path
    model: str | None = None
    model_tier: str | None = None
    human_review: bool = False
    is_parking_lot: bool = False  # No agent auto-starts here (backlog, accepted, not_doing)
    redirect_only: bool = False  # Only reachable via StageRedirect
    condition: str | None = None  # Jinja expression - skip stage when false
    role: str = "developer"  # Who executes this stage
    review_doc: str | None = None
    substages: dict[str, SubstageConfig] = Field(default_factory=dict)
    pre_completion: list[dict] = Field(default_factory=list)
    post_start: list[dict] = Field(default_factory=list)
    post_completion: list[dict] = Field(default_factory=list)

    def substage_order(self) -> list[str]:
        """Get ordered list of substage names."""
        return list(self.substages.keys())

    def get_substage(self, name: str) -> SubstageConfig | None:
        """Get a substage by name."""
        return self.substages.get(name)

    def hooks_for(self, substage: str | None, event: str) -> list[dict]:
        """Get hooks for a substage or stage.

        Args:
            substage: Substage name, or None for stage-level hooks
            event: "pre_completion", "post_start", or "post_completion"
        """
        if substage:
            substage_config = self.get_substage(substage)
            if substage_config:
                return getattr(substage_config, event, [])
            return []
        return getattr(self, event, [])

    def effective_role(self, substage: str | None = None) -> str:
        """Get effective role for a substage (substage role overrides stage role)."""
        if substage:
            sub = self.get_substage(substage)
            if sub and sub.role:
                return sub.role
        return self.role


class FlowConfig(BaseModel):
    """Configuration for a workflow flow.

    A flow defines an ordered list of dot paths (e.g., "explore.define",
    "implement.code") that issues following this flow progress through.
    """

    name: str
    stages: list[str] = Field(default_factory=list)  # Ordered list of dot paths


class ManagerConfig(BaseModel):
    """Configuration for the manager's stall monitoring."""

    stall_threshold_min: int = 20
    nudge_cooldown_min: int = 30
    max_nudges_before_escalate: int = 3
    max_ci_bounces: int = 5


class SecurityConfig(BaseModel):
    """Security configuration for agents."""


class SessionConfig(BaseModel):
    """Configuration for a tmux session.

    Sessions are long-running processes (dev servers, workers, etc.) that run
    alongside the AI agent. Each session gets its own tmux window.
    """

    command: str  # The long-running command to execute
    name_template: str | None = None  # Override default naming: {project}-{session_name}-{issue_id}
    ports: list[str] = Field(default_factory=list)  # Ports to forward (Jinja templates)
    pre_start: list[dict] = Field(default_factory=list)  # Hooks before command starts
    post_stop: list[dict] = Field(default_factory=list)  # Hooks after session is killed


class ContainerTypeConfig(BaseModel):
    """Configuration for a container type.

    Container types are templates for creating container instances. Two types
    are reserved (manager, issue); all others are user-defined.
    """

    extends: str | None = None  # Parent container type to inherit from
    image: str = "agenttree-agent:latest"  # Container image
    roles: list[str] = Field(default_factory=list)  # Roles that can run in this container
    sessions: list[str] = Field(default_factory=list)  # Which sessions to start
    interactive: bool = False  # Attach terminal on creation
    mounts: list[str] = Field(default_factory=list)  # Additional mounts (host:container:mode)
    env: dict[str, str] = Field(default_factory=dict)  # Environment variables
    allow_dangerous: bool = True  # Allow --dangerously-skip-permissions

    # Lifecycle hooks
    pre_start: list[dict] = Field(default_factory=list)  # Before container starts (host)
    post_start: list[dict] = Field(default_factory=list)  # After container starts (inside)
    pre_stop: list[dict] = Field(default_factory=list)  # Before container stops (inside)
    post_stop: list[dict] = Field(default_factory=list)  # After container stops (host)


def resolve_container_type(
    name: str,
    containers: dict[str, ContainerTypeConfig],
) -> ContainerTypeConfig:
    """Resolve a container type by walking the extends chain.

    Merge semantics:
    - Scalar values: child wins
    - Hooks (pre_start, etc.): child replaces entirely
    - Roles: child replaces entirely
    - Sessions: child replaces entirely
    - Mounts: accumulate (child adds to parent)
    - Env: dict merge (child keys override parent)

    Args:
        name: Container type name to resolve
        containers: Dict of all container type configs

    Returns:
        Fully resolved ContainerTypeConfig

    Raises:
        ValueError: If container type not found or circular extends
    """
    if name not in containers:
        raise ValueError(f"Unknown container type: {name}")

    # Track visited types to detect cycles
    visited: set[str] = set()
    chain: list[ContainerTypeConfig] = []

    current_name: str | None = name
    while current_name is not None:
        if current_name in visited:
            raise ValueError(f"Circular extends detected: {current_name}")
        if current_name not in containers:
            raise ValueError(f"Unknown container type in extends chain: {current_name}")

        visited.add(current_name)
        chain.append(containers[current_name])
        current_name = containers[current_name].extends

    # Reverse chain so we go from base to derived
    chain.reverse()

    # Start with base values
    base = chain[0]
    result_image = base.image
    result_roles = list(base.roles)
    result_sessions = list(base.sessions)
    result_interactive = base.interactive
    result_mounts: list[str] = list(base.mounts)  # Accumulate mounts
    result_env: dict[str, str] = dict(base.env)  # Merge env
    result_allow_dangerous = base.allow_dangerous
    result_pre_start = list(base.pre_start)
    result_post_start = list(base.post_start)
    result_pre_stop = list(base.pre_stop)
    result_post_stop = list(base.post_stop)

    # Apply each child in order
    for cfg in chain[1:]:
        # Scalars: child wins if explicitly set (we check for non-default)
        if cfg.image != "agenttree-agent:latest":
            result_image = cfg.image
        if cfg.roles:
            result_roles = list(cfg.roles)
        if cfg.sessions:
            result_sessions = list(cfg.sessions)
        if cfg.interactive:
            result_interactive = cfg.interactive
        if not cfg.allow_dangerous:
            result_allow_dangerous = cfg.allow_dangerous

        # Mounts: accumulate
        result_mounts.extend(cfg.mounts)

        # Env: merge (child overrides)
        result_env.update(cfg.env)

        # Hooks: replace if child has any
        if cfg.pre_start:
            result_pre_start = list(cfg.pre_start)
        if cfg.post_start:
            result_post_start = list(cfg.post_start)
        if cfg.pre_stop:
            result_pre_stop = list(cfg.pre_stop)
        if cfg.post_stop:
            result_post_stop = list(cfg.post_stop)

    return ContainerTypeConfig(
        extends=None,  # Resolved config has no extends
        image=result_image,
        roles=result_roles,
        sessions=result_sessions,
        interactive=result_interactive,
        mounts=result_mounts,
        env=result_env,
        allow_dangerous=result_allow_dangerous,
        pre_start=result_pre_start,
        post_start=result_post_start,
        pre_stop=result_pre_stop,
        post_stop=result_post_stop,
    )


def render_template(template: str, context: dict[str, object]) -> str:
    """Render a Jinja template string with the given context.

    Args:
        template: Template string with {{ variable }} placeholders
        context: Dict of variables available in the template

    Returns:
        Rendered string
    """
    return Template(template).render(**context)


def evaluate_condition(condition: str, context: dict) -> bool:
    """Evaluate a Jinja condition expression."""
    try:
        template = Template(condition)
        result = template.render(**context)
        result = result.strip().lower()
        if result in ("", "false", "none", "0"):
            return False
        return bool(result)
    except UndefinedError:
        return False


class RateLimitFallbackConfig(BaseModel):
    """Configuration for automatic rate limit fallback to API key mode."""

    enabled: bool = False
    api_key_env: str = "ANTHROPIC_API_KEY"
    model: str = "claude-sonnet-4-20250514"
    switch_back_buffer_min: int = 5


class Config(BaseModel):
    """AgentTree configuration."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    project: str = "myapp"
    worktrees_dir: Path = Field(default_factory=lambda: Path(".worktrees"))
    scripts_dir: Path = Field(default_factory=lambda: Path("scripts"))
    port_range: str = "9000-9100"  # Manager on 9000, issues 9001-9100
    default_tool: str = "claude"
    default_model: str = "opus"
    model_tiers: dict[str, str] = Field(default_factory=dict)
    refresh_interval: int = 10
    tools: dict[str, ToolConfig] = Field(default_factory=dict)
    roles: dict[str, RoleConfig] = Field(default_factory=dict)
    commands: dict[str, Union[str, list[str]]] = Field(default_factory=dict)
    stages: dict[str, StageConfig] = Field(default_factory=dict)  # Stage name -> config
    flows: dict[str, FlowConfig] = Field(default_factory=dict)
    default_flow: str = "default"
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    merge_strategy: str = "squash"
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    save_tmux_history: bool = False
    manager: ManagerConfig = Field(default_factory=ManagerConfig)
    show_issue_yaml: bool = True
    on: OnConfig | None = None
    rate_limit_fallback: RateLimitFallbackConfig = Field(default_factory=RateLimitFallbackConfig)
    allow_self_approval: bool = False
    sessions: dict[str, SessionConfig] = Field(default_factory=dict)
    containers: dict[str, ContainerTypeConfig] = Field(default_factory=dict)

    # ── Port / path helpers ──────────────────────────────────────────

    @property
    def server_port(self) -> int:
        """Port for the AgentTree server (manager always gets port_min)."""
        port_min = int(self.port_range.split("-")[0])
        return port_min

    def get_port_for_issue(self, issue_id: int | str) -> int:
        """Get port for an issue using modulo wrapping.

        Formula:
            mod = port_max - port_min  (e.g., 100 for 9000-9100)
            remainder = issue_id % mod
            port = port_max if remainder == 0 else port_min + remainder

        This gives 100 issue slots (9001-9100) that wrap for high issue numbers.
        Manager always gets port_min (9000) via server_port property.

        Examples with port_range 9000-9100:
            Issue #1   → remainder=1   → 9001
            Issue #42  → remainder=42  → 9042
            Issue #99  → remainder=99  → 9099
            Issue #100 → remainder=0   → 9100 (0 → port_max)
            Issue #101 → remainder=1   → 9001 (wraps)
        """
        from agenttree.ids import parse_issue_id
        if isinstance(issue_id, str):
            issue_id = parse_issue_id(issue_id)

        port_min, port_max = map(int, self.port_range.split("-"))
        mod = port_max - port_min
        remainder = issue_id % mod
        if remainder == 0:
            return port_max
        return port_min + remainder

    def get_port_for_agent(self, agent_num: int) -> int:
        """Get port number for a specific agent (legacy, calls get_port_for_issue)."""
        return self.get_port_for_issue(agent_num)

    def get_dev_server_url(self, issue_id: int | str, host: str = "localhost") -> str:
        """Get dev server URL for an issue.

        Args:
            issue_id: Issue ID (int or string)
            host: Hostname (default: localhost)

        Returns:
            URL string (e.g., "http://localhost:9042")
        """
        port = self.get_port_for_issue(issue_id)
        return f"http://{host}:{port}"

    def get_worktree_path(self, agent_num: int) -> Path:
        """Get worktree path for a specific agent (legacy numbered agents)."""
        expanded_dir = Path(self.worktrees_dir).expanduser()
        return expanded_dir / f"{self.project}-agent-{agent_num}"

    def get_issue_worktree_path(self, issue_id: int) -> Path:
        """Get worktree path for an issue-bound agent."""
        from agenttree.ids import worktree_dir_name
        expanded_dir = Path(self.worktrees_dir).expanduser()
        return expanded_dir / worktree_dir_name(issue_id)

    def get_tmux_session_name(self, agent_num: int) -> str:
        """Get tmux session name for a specific agent (legacy numbered agents)."""
        return f"{self.project}-developer-{agent_num}"

    def get_issue_tmux_session(self, issue_id: int, role: str = "developer") -> str:
        """Get tmux session name for an issue-bound agent."""
        from agenttree.ids import tmux_session_name
        return tmux_session_name(self.project, issue_id, role)

    def get_manager_tmux_session(self) -> str:
        """Get tmux session name for the manager agent."""
        from agenttree.ids import manager_session_name
        return manager_session_name(self.project)

    def get_issue_session_patterns(self, issue_id: int) -> list[str]:
        """Get all possible tmux session names for an issue."""
        from agenttree.tmux import get_session_patterns
        from agenttree.ids import format_issue_id
        return get_session_patterns(self.project, format_issue_id(issue_id))

    def is_project_session(self, session_name: str) -> bool:
        """Check if a session name belongs to this project."""
        return session_name.startswith(f"{self.project}-")

    def get_issue_container_name(self, issue_id: int) -> str:
        """Get container name for an issue-bound agent."""
        from agenttree.ids import container_name
        return container_name(self.project, issue_id)

    def get_tool_config(self, tool_name: str) -> ToolConfig:
        """Get configuration for a tool."""
        if tool_name in self.tools:
            return self.tools[tool_name]
        return ToolConfig(command=tool_name)

    def get_ci_script(self, script_name: str = "ci.sh") -> Path:
        """Get path to a CI script."""
        return self.scripts_dir / script_name

    # ── Stage resolution ─────────────────────────────────────────────

    def parse_stage(self, dot_path: str) -> tuple[str, str | None]:
        """Parse a dot path into (stage, substage).

        "explore.define" -> ("explore", "define")
        "backlog" -> ("backlog", None)
        """
        if "." in dot_path:
            stage, substage = dot_path.split(".", 1)
            return stage, substage
        return dot_path, None

    def format_stage(self, stage: str, substage: str | None = None) -> str:
        """Format stage + substage as a dot path.

        ("explore", "define") -> "explore.define"
        ("backlog", None) -> "backlog"
        """
        if substage:
            return f"{stage}.{substage}"
        return stage

    def get_stage(self, name: str) -> StageConfig | None:
        """Get configuration for a stage by name.

        Args:
            name: Stage name (e.g., "explore", "implement"). NOT a dot path.
        """
        return self.stages.get(name)

    def resolve_stage(self, dot_path: str) -> tuple[StageConfig | None, SubstageConfig | None]:
        """Resolve a dot path to stage and substage configs.

        Args:
            dot_path: e.g., "explore.define" or "backlog"

        Returns:
            (StageConfig, SubstageConfig) or (StageConfig, None) or (None, None)
        """
        stage_name, substage_name = self.parse_stage(dot_path)
        stage = self.get_stage(stage_name)
        if stage is None:
            return None, None
        if substage_name:
            return stage, stage.get_substage(substage_name)
        return stage, None

    def get_stage_names(self) -> list[str]:
        """Get list of all top-level stage names in definition order."""
        return list(self.stages.keys())

    def get_all_dot_paths(self) -> list[str]:
        """Get all dot paths for all stages/substages in definition order."""
        paths: list[str] = []
        for name, stage in self.stages.items():
            if stage.substages:
                for sub_name in stage.substages:
                    paths.append(f"{name}.{sub_name}")
            else:
                paths.append(name)
        return paths

    def get_human_review_stages(self) -> list[str]:
        """Get list of dot paths that require human review."""
        result: list[str] = []
        for name, stage in self.stages.items():
            if stage.substages:
                for sub_name, sub in stage.substages.items():
                    if sub.human_review:
                        result.append(f"{name}.{sub_name}")
            elif stage.human_review:
                result.append(name)
        return result

    def is_human_review(self, dot_path: str) -> bool:
        """Check if a dot path is a human review stage."""
        stage, sub = self.resolve_stage(dot_path)
        if sub:
            return sub.human_review
        if stage:
            return stage.human_review
        return False

    def get_manager_stages(self) -> list[str]:
        """Get list of dot paths executed by the manager."""
        result: list[str] = []
        for name, stage in self.stages.items():
            if stage.substages:
                for sub_name, sub in stage.substages.items():
                    role = sub.role or stage.role
                    if role == "manager":
                        result.append(f"{name}.{sub_name}")
            elif stage.role == "manager":
                result.append(name)
        return result

    def get_all_roles(self) -> dict[str, RoleConfig]:
        """Get all roles including built-in defaults."""
        all_roles: dict[str, RoleConfig] = {
            "manager": RoleConfig(
                name="manager",
                description="Human-driven manager (runs on host)",
                container=None,
                process=None,
                model_tier="low",
            ),
            "developer": RoleConfig(
                name="developer",
                description="Default AI agent that writes code",
                container=ContainerConfig(enabled=True),
                tool=self.default_tool,
                model=self.default_model,
            ),
        }
        all_roles.update(self.roles)
        return all_roles

    def get_role(self, role_name: str) -> RoleConfig | None:
        """Get configuration for a role (including built-in defaults)."""
        return self.get_all_roles().get(role_name)

    def get_custom_role_stages(self) -> list[str]:
        """Get list of dot paths that use custom roles."""
        all_roles = self.get_all_roles()
        result: list[str] = []
        for name, stage in self.stages.items():
            if stage.substages:
                for sub_name, sub in stage.substages.items():
                    role = sub.role or stage.role
                    if role not in ("developer", "manager") and role in all_roles:
                        result.append(f"{name}.{sub_name}")
            else:
                if stage.role not in ("developer", "manager") and stage.role in all_roles:
                    result.append(name)
        return result

    def get_custom_role(self, role_name: str) -> RoleConfig | None:
        """Get configuration for a custom role."""
        return self.roles.get(role_name)

    def is_custom_role(self, role_name: str) -> bool:
        """Check if a role name is a custom role (not manager or default developer)."""
        if role_name in ("manager", "developer"):
            return False
        return role_name in self.roles

    def get_non_developer_stages(self) -> list[str]:
        """Get list of dot paths NOT executed by the default developer."""
        result: list[str] = []
        for name, stage in self.stages.items():
            if stage.substages:
                for sub_name, sub in stage.substages.items():
                    role = sub.role or stage.role
                    if role != "developer":
                        result.append(f"{name}.{sub_name}")
            elif stage.role != "developer":
                result.append(name)
        return result

    def role_is_containerized(self, role_name: str) -> bool:
        """Check if a role runs in a container."""
        role = self.get_role(role_name)
        if role:
            return role.is_containerized()
        return role_name != "manager"

    def role_for(self, dot_path: str) -> str:
        """Get the effective role for a dot path."""
        stage, sub = self.resolve_stage(dot_path)
        if sub and sub.role:
            return sub.role
        if stage:
            return stage.role
        return "developer"

    def substages_for(self, stage_name: str) -> list[str]:
        """Get ordered list of substage names for a stage."""
        stage = self.get_stage(stage_name)
        if stage is None:
            return []
        return stage.substage_order()

    def skill_path(self, dot_path: str) -> str:
        """Get the skill file path for a dot path.

        Convention: skills/{stage}/{substage}.md or skills/{stage}.md
        Can be overridden with explicit skill property in config.
        """
        stage_name, substage_name = self.parse_stage(dot_path)
        stage = self.get_stage(stage_name)

        # Check for explicit override on substage
        if substage_name and stage:
            sub = stage.get_substage(substage_name)
            if sub and sub.skill:
                return f"skills/{sub.skill}"
        # Check for explicit override on stage
        if stage and stage.skill:
            return f"skills/{stage.skill}"

        # Convention: skills/{stage}/{substage}.md or skills/{stage}.md
        if substage_name:
            return f"skills/{stage_name}/{substage_name}.md"
        return f"skills/{stage_name}.md"

    def output_for(self, dot_path: str) -> str | None:
        """Get the output document name for a dot path."""
        stage_name, substage_name = self.parse_stage(dot_path)
        stage = self.get_stage(stage_name)
        if stage is None:
            return None

        if substage_name:
            sub = stage.get_substage(substage_name)
            if sub and sub.output:
                return sub.output

        return stage.output

    def model_for(self, dot_path: str, role: str | None = None) -> str:
        """Get the model to use. Checks substage → stage → role → default."""
        tiers = self.model_tiers
        stage_name, substage_name = self.parse_stage(dot_path)

        configs: list[object] = []
        stage = self.get_stage(stage_name)
        if stage:
            if substage_name:
                sc = stage.get_substage(substage_name)
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

    def validators_for(self, dot_path: str) -> list[str]:
        """Get validators for a dot path."""
        stage_name, substage_name = self.parse_stage(dot_path)
        stage = self.get_stage(stage_name)
        if stage is None:
            return []
        if substage_name:
            sub = stage.get_substage(substage_name)
            if sub:
                return sub.validators
        return []

    def is_parking_lot(self, dot_path: str) -> bool:
        """Check if a dot path is a parking lot (no agent auto-starts)."""
        stage_name, _ = self.parse_stage(dot_path)
        stage = self.get_stage(stage_name)
        return stage.is_parking_lot if stage else False

    def get_parking_lot_stages(self) -> set[str]:
        """Get names of all parking lot stages."""
        return {name for name, stage in self.stages.items() if stage.is_parking_lot}

    def get_flow(self, flow_name: str) -> FlowConfig | None:
        """Get configuration for a flow."""
        return self.flows.get(flow_name)

    def get_flow_stage_names(self, flow_name: str = "default") -> list[str]:
        """Get ordered list of dot paths for a flow.

        When no flows are defined (e.g., direct Config instantiation in tests),
        falls back to using all stages in definition order.
        """
        flow = self.get_flow(flow_name)
        if flow:
            return flow.stages

        # Fallback for configs without flows defined (tests, legacy configs)
        if flow_name == "default" and not self.flows:
            return self.get_all_dot_paths()

        return []

    def get_next_stage(
        self,
        current: str,
        flow: str = "default",
        issue_context: dict | None = None,
    ) -> tuple[str, bool]:
        """Calculate the next stage from a dot path.

        Args:
            current: Current dot path (e.g., "explore.define")
            flow: Flow name for stage progression
            issue_context: Optional dict for condition evaluation

        Returns:
            Tuple of (next_dot_path, is_human_review)
        """
        dot_paths = self.get_flow_stage_names(flow)
        context = issue_context or {}

        try:
            idx = dot_paths.index(current)
        except ValueError:
            return current, False

        for next_idx in range(idx + 1, len(dot_paths)):
            next_path = dot_paths[next_idx]
            stage, sub = self.resolve_stage(next_path)
            if stage is None:
                continue

            # Check redirect_only
            if sub and sub.redirect_only:
                continue
            if not sub and stage.redirect_only:
                continue

            # Check condition on substage or stage
            cond = (sub.condition if sub else None) or stage.condition
            if cond and not evaluate_condition(cond, context):
                continue

            # Found the next valid stage
            is_review = (sub.human_review if sub else stage.human_review)
            return next_path, is_review

        # Already at end
        return current, False

    # ── Role helpers ─────────────────────────────────────────────────

    def get_flow_stage_names_for_role(self, role: str, flow: str = "default") -> list[str]:
        """Get dot paths in a flow that match a given role."""
        return [
            dp for dp in self.get_flow_stage_names(flow)
            if self.role_for(dp) == role
        ]

    # ── Display helpers ──────────────────────────────────────────────

    def stage_display_name(self, dot_path: str) -> str:
        """Get a human-readable display name for a dot path.

        "explore.define" -> "Define"
        "implement.code_review" -> "Code Review"
        "backlog" -> "Backlog"
        """
        _, substage = self.parse_stage(dot_path)
        name = substage or dot_path
        return name.replace("_", " ").title()

    def stage_group_name(self, dot_path: str) -> str:
        """Get the group (top-level stage) name for a dot path.

        "explore.define" -> "explore"
        "backlog" -> "backlog"
        """
        stage_name, _ = self.parse_stage(dot_path)
        return stage_name

    def stage_color(self, dot_path: str) -> str | None:
        """Get the color for a dot path (from its parent stage)."""
        stage_name, _ = self.parse_stage(dot_path)
        stage = self.get_stage(stage_name)
        return stage.color if stage else None


def find_config_file(start_path: Path) -> Path | None:
    """Find .agenttree.yaml file by walking up directory tree."""
    current = start_path.resolve()

    while True:
        config_file = current / ".agenttree.yaml"
        if config_file.exists():
            return config_file

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def _parse_substages(substages_data: dict) -> dict[str, dict]:
    """Parse substages dict from YAML, injecting name from key."""
    result: dict[str, dict] = {}
    for sub_name, sub_data in substages_data.items():
        if sub_data is None:
            sub_data = {}
        sub_data["name"] = sub_name
        result[sub_name] = sub_data
    return result


def _parse_inline_stages(stages_data: dict) -> tuple[dict[str, dict], list[str]]:
    """Parse inline stage definitions from a flow.

    Returns:
        (stages_dict, dot_paths) where stages_dict maps stage name to
        StageConfig data and dot_paths is the ordered list of dot paths.
    """
    all_stages: dict[str, dict] = {}
    dot_paths: list[str] = []

    for stage_name, stage_data in stages_data.items():
        if stage_data is None:
            stage_data = {}
        stage_data["name"] = stage_name

        if "substages" in stage_data and isinstance(stage_data["substages"], dict):
            stage_data["substages"] = _parse_substages(stage_data["substages"])
            for sub_name in stage_data["substages"]:
                dot_paths.append(f"{stage_name}.{sub_name}")
        else:
            dot_paths.append(stage_name)

        all_stages[stage_name] = stage_data

    return all_stages, dot_paths


def _expand_flow_references(
    flow_stages: list[str],
    all_stages: dict[str, dict],
) -> list[str]:
    """Expand bare stage names in a reference flow to their substage dot paths.

    If a flow lists "implement" and implement has substages, expand to
    ["implement.setup", "implement.code", ...] in substage order.
    """
    expanded: list[str] = []
    for entry in flow_stages:
        if "." in entry:
            # Already a dot path — validate it
            stage_name, sub_name = entry.split(".", 1)
            if stage_name not in all_stages:
                raise ValueError(f"Flow references unknown stage '{stage_name}' in '{entry}'")
            stage_data = all_stages[stage_name]
            subs = stage_data.get("substages", {})
            if subs and sub_name not in subs:
                raise ValueError(f"Flow references unknown substage '{sub_name}' in '{entry}'")
            expanded.append(entry)
        elif entry in all_stages:
            stage_data = all_stages[entry]
            subs = stage_data.get("substages", {})
            if subs:
                for sub_name in subs:
                    expanded.append(f"{entry}.{sub_name}")
            else:
                expanded.append(entry)
        else:
            raise ValueError(f"Flow references unknown stage '{entry}'")
    return expanded


_config_cache: dict[Path, tuple[float, "Config"]] = {}


def load_config(path: Path | None = None) -> "Config":
    """Load configuration from .agenttree.yaml file.

    Results are cached by resolved config file path and invalidated when
    the file's mtime changes, so repeated calls within the same request
    (or render pass) only hit the filesystem for a single stat().
    """
    if path is None:
        path = Path.cwd()

    config_file = find_config_file(path)

    if config_file is None:
        return Config()

    mtime = config_file.stat().st_mtime
    cached = _config_cache.get(config_file)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    with open(config_file, "r") as f:
        data = yaml.safe_load(f)

    if data is None:
        return Config()

    # Handle YAML 'on:' being parsed as boolean True
    if True in data:
        data["on"] = data.pop(True)

    # Auto-populate 'name' field for roles from the key
    if "roles" in data and isinstance(data["roles"], dict):
        for role_name, role_config in data["roles"].items():
            if role_config is None:
                data["roles"][role_name] = {"name": role_name}
            elif isinstance(role_config, dict):
                if "name" not in role_config:
                    role_config["name"] = role_name
                if "container" in role_config and role_config["container"] is True:
                    role_config["container"] = {"enabled": True}
                elif "container" in role_config and role_config["container"] is False:
                    role_config["container"] = None

    # ── Parse flows and stages ───────────────────────────────────────
    all_stages: dict[str, dict] = {}
    flow_configs: dict[str, dict] = {}

    if "flows" in data and isinstance(data["flows"], dict):
        for flow_name, flow_data in data["flows"].items():
            if flow_data is None:
                continue

            # Auto-populate name
            if isinstance(flow_data, dict) and "name" not in flow_data:
                flow_data["name"] = flow_name

            stages_data = flow_data.get("stages", {})

            if isinstance(stages_data, dict):
                # Inline stage definitions (primary flow)
                parsed_stages, dot_paths = _parse_inline_stages(stages_data)
                all_stages.update(parsed_stages)
                flow_configs[flow_name] = {"name": flow_name, "stages": dot_paths}

            elif isinstance(stages_data, list):
                # Reference flow — will be expanded after all stages are parsed
                flow_configs[flow_name] = {"name": flow_name, "stages": stages_data}

    # Expand reference flows (bare stage names -> dot paths)
    for flow_name, flow_cfg in flow_configs.items():
        stages_list = flow_cfg["stages"]
        if stages_list and isinstance(stages_list[0], str):
            # Check if any entry is a bare stage name that needs expansion
            needs_expansion = any(
                entry in all_stages and all_stages[entry].get("substages")
                for entry in stages_list
                if "." not in entry
            )
            if needs_expansion:
                flow_cfg["stages"] = _expand_flow_references(stages_list, all_stages)

    # Validate reference flows
    all_dot_paths = set()
    for stage_name, stage_data in all_stages.items():
        subs = stage_data.get("substages", {})
        if subs:
            for sub_name in subs:
                all_dot_paths.add(f"{stage_name}.{sub_name}")
        else:
            all_dot_paths.add(stage_name)

    for flow_name, flow_cfg in flow_configs.items():
        for dp in flow_cfg["stages"]:
            if dp not in all_dot_paths:
                raise ValueError(
                    f"Flow '{flow_name}' references unknown dot path '{dp}'"
                )

    # Replace raw data with parsed structures
    data["stages"] = all_stages
    data["flows"] = flow_configs

    # Remove old-style 'stages' if it was a list (backward compat not needed)
    # The new format always has stages extracted from flows

    result = Config(**data)
    _config_cache[config_file] = (mtime, result)
    return result

"""MCP server for AgentTree.

Exposes agenttree operations as MCP tools so external AI assistants
(Claude Desktop, ChatGPT via voice, etc.) can manage your agents.

Run with:
    agenttree mcp                     # stdio transport (for Claude Desktop)
    agenttree mcp --http              # HTTP transport (for remote/voice access)
    agenttree mcp --http --port 8100  # custom port
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING
from pathlib import Path

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from starlette.applications import Starlette

log = logging.getLogger("agenttree.mcp")

mcp = FastMCP(
    "AgentTree",
    instructions=(
        "You are a voice assistant for AgentTree, a multi-agent development framework. "
        "You help the user manage their AI coding agents. Keep responses concise and "
        "conversational — the user is likely on a walk listening via voice. "
        "Summarize status in plain language, not raw data. "
        "When listing issues, group by what needs attention (reviews, stuck agents) first."
    ),
)


def _get_repo_path() -> Path:
    """Get the repo path from env or cwd."""
    return Path(os.environ.get("AGENTTREE_REPO_PATH", Path.cwd()))


@mcp.tool()
def status() -> str:
    """Get the current status of all issues and agents.

    Returns a summary of all active issues, their stages, and whether
    agents are running. Use this to get an overview of what's happening.
    """
    from agenttree.config import load_config
    from agenttree.issues import list_issues
    from agenttree.tmux import list_sessions as tmux_list_sessions

    config = load_config(_get_repo_path())
    issues = list_issues(sync=False)

    if not issues:
        return "No issues found. The board is empty."

    # Check which tmux sessions are active
    try:
        active_sessions = {s.name for s in tmux_list_sessions()}
    except Exception:
        active_sessions = set()

    lines: list[str] = []
    needs_review: list[str] = []
    active: list[str] = []
    parked: list[str] = []

    for issue in issues:
        # Check if agent is running
        patterns = config.get_issue_session_patterns(issue.id)
        is_running = any(p in active_sessions for p in patterns)
        agent_status = "running" if is_running else "stopped"

        stage_name = config.stage_display_name(issue.stage)
        line = f"#{issue.id}: {issue.title} [{stage_name}] (agent: {agent_status})"

        if config.is_human_review(issue.stage):
            needs_review.append(line)
        elif config.is_parking_lot(issue.stage):
            parked.append(line)
        else:
            active.append(line)

    if needs_review:
        lines.append("NEEDS YOUR REVIEW:")
        lines.extend(f"  {r}" for r in needs_review)
        lines.append("")

    if active:
        lines.append("ACTIVE:")
        lines.extend(f"  {a}" for a in active)
        lines.append("")

    if parked:
        lines.append("PARKED:")
        lines.extend(f"  {p}" for p in parked)

    return "\n".join(lines) or "No issues found."


@mcp.tool()
def get_issue(issue_id: int) -> str:
    """Get detailed information about a specific issue.

    Args:
        issue_id: The issue number (e.g. 42)
    """
    from agenttree.config import load_config
    from agenttree.issues import get_issue as _get_issue, get_issue_dir

    config = load_config(_get_repo_path())
    issue = _get_issue(issue_id, sync=False)
    if not issue:
        return f"Issue #{issue_id} not found."

    stage_name = config.stage_display_name(issue.stage)
    lines = [
        f"Issue #{issue.id}: {issue.title}",
        f"Stage: {stage_name} (flow: {issue.flow})",
        f"Priority: {issue.priority.value}",
    ]

    if issue.pr_url:
        lines.append(f"PR: {issue.pr_url}")
    if issue.branch:
        lines.append(f"Branch: {issue.branch}")
    if issue.labels:
        lines.append(f"Labels: {', '.join(issue.labels)}")
    if issue.dependencies:
        lines.append(f"Blocked by: #{', #'.join(str(d) for d in issue.dependencies)}")

    # Load problem.md if it exists
    issue_dir = get_issue_dir(issue_id)
    if issue_dir:
        problem_file = issue_dir / "problem.md"
        if problem_file.exists():
            content = problem_file.read_text().strip()
            if content:
                # Truncate long descriptions
                if len(content) > 500:
                    content = content[:500] + "..."
                lines.append(f"\nDescription:\n{content}")

    return "\n".join(lines)


@mcp.tool()
def get_agent_output(issue_id: int, lines: int = 50) -> str:
    """Get recent terminal output from an agent.

    Shows what the agent is currently doing or its last output.

    Args:
        issue_id: The issue number
        lines: Number of lines to capture (default 50)
    """
    from agenttree.config import load_config
    from agenttree.tmux import capture_pane, session_exists

    config = load_config(_get_repo_path())
    patterns = config.get_issue_session_patterns(issue_id)

    for name in patterns:
        if session_exists(name):
            output = capture_pane(name, lines=lines)
            if output:
                # Strip the Claude input prompt separator
                import re
                separator = re.compile(r"^\s*─{20,}\s*$", re.MULTILINE)
                match = separator.search(output)
                if match:
                    output = output[:match.start()].rstrip()
                return f"Agent output for issue #{issue_id}:\n\n{output}"

    return f"No active agent session for issue #{issue_id}."


@mcp.tool()
def send_message(issue_id: int, message: str) -> str:
    """Send a message to an agent working on an issue.

    The agent will receive this as input in their terminal session.

    Args:
        issue_id: The issue number
        message: The message to send to the agent
    """
    from agenttree.api import send_message as api_send, IssueNotFoundError, ControllerNotRunningError

    try:
        result = api_send(issue_id, message, quiet=True)
        if result == "sent":
            return f"Message sent to agent for issue #{issue_id}."
        elif result == "restarted":
            return f"Agent was restarted and message sent for issue #{issue_id}."
        elif result == "no_agent":
            return f"No agent running for issue #{issue_id}. Use start_agent to start one."
        else:
            return f"Failed to send message to issue #{issue_id}: {result}"
    except IssueNotFoundError:
        return f"Issue #{issue_id} not found."
    except ControllerNotRunningError:
        return "Controller (issue 0) is not running. Start it with start_agent(0)."


@mcp.tool()
def create_issue(title: str, description: str) -> str:
    """Create a new issue and start an agent to work on it.

    Args:
        title: Short title for the issue (at least 10 characters)
        description: Detailed description of what needs to be done (at least 50 characters)
    """
    from agenttree.api import start_agent as api_start, AgentStartError
    from agenttree.issues import create_issue as _create_issue, Priority

    if len(title) < 10:
        return "Title must be at least 10 characters."
    if len(description) < 50:
        return "Description must be at least 50 characters. Be specific about what you want."

    try:
        issue = _create_issue(title=title, priority=Priority.MEDIUM, problem=description)
    except Exception as e:
        return f"Failed to create issue: {e}"

    # Auto-start agent
    try:
        api_start(issue.id, quiet=True)
        return f"Created issue #{issue.id}: {issue.title}. Agent started and working."
    except AgentStartError as e:
        return f"Created issue #{issue.id} but failed to start agent: {e}"
    except Exception as e:
        return f"Created issue #{issue.id} but agent start failed: {e}"


@mcp.tool()
def approve(issue_id: int) -> str:
    """Approve an issue that's waiting for human review.

    Advances the issue past its current review stage to the next workflow step.

    Args:
        issue_id: The issue number to approve
    """
    from agenttree.api import transition_issue
    from agenttree.config import load_config
    from agenttree.issues import get_issue as _get_issue

    config = load_config(_get_repo_path())
    issue = _get_issue(issue_id, sync=False)
    if not issue:
        return f"Issue #{issue_id} not found."

    if not config.is_human_review(issue.stage):
        stage_name = config.stage_display_name(issue.stage)
        return f"Issue #{issue_id} is at '{stage_name}', which is not a review stage."

    next_stage, _ = config.get_next_stage(issue.stage, issue.flow)

    try:
        transition_issue(issue_id, next_stage, trigger="mcp")
        next_name = config.stage_display_name(next_stage)
        return f"Approved issue #{issue_id}. Advanced to '{next_name}'."
    except Exception as e:
        return f"Failed to approve issue #{issue_id}: {e}"


@mcp.tool()
def start_agent(issue_id: int) -> str:
    """Start or restart an agent for an issue.

    Args:
        issue_id: The issue number
    """
    from agenttree.api import (
        start_agent as api_start,
        start_controller,
        AgentAlreadyRunningError,
        AgentStartError,
        IssueNotFoundError,
    )

    try:
        if issue_id == 0:
            start_controller(quiet=True)
            return "Controller started."
        api_start(issue_id, quiet=True, force=True)
        return f"Agent started for issue #{issue_id}."
    except IssueNotFoundError:
        return f"Issue #{issue_id} not found."
    except AgentAlreadyRunningError:
        return f"Agent already running for issue #{issue_id}."
    except AgentStartError as e:
        return f"Failed to start agent: {e}"
    except Exception as e:
        return f"Error starting agent: {e}"


@mcp.tool()
def stop_agent(issue_id: int) -> str:
    """Stop an agent working on an issue.

    Kills the tmux session and stops the container.

    Args:
        issue_id: The issue number
    """
    from agenttree.api import stop_all_agents_for_issue

    count = stop_all_agents_for_issue(issue_id, quiet=True)
    if count > 0:
        return f"Stopped {count} agent(s) for issue #{issue_id}."
    return f"No active agents for issue #{issue_id}."


def _get_api_key() -> str | None:
    """Get the MCP API key from environment."""
    return os.environ.get("AGENTTREE_MCP_KEY")


def _create_authed_app(api_key: str) -> "Starlette":
    """Wrap the MCP Starlette app with bearer token auth middleware."""
    import secrets

    from starlette.middleware import Middleware
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import JSONResponse
    from starlette.types import ASGIApp, Receive, Scope, Send

    class BearerTokenMiddleware:
        """Simple bearer token auth middleware."""

        def __init__(self, app: ASGIApp, token: str) -> None:
            self.app = app
            self.token = token

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            request = StarletteRequest(scope, receive)
            auth_header = request.headers.get("authorization", "")

            if not auth_header.startswith("Bearer "):
                response = JSONResponse({"error": "Missing Bearer token"}, status_code=401)
                await response(scope, receive, send)
                return

            token = auth_header[7:]
            if not secrets.compare_digest(token, self.token):
                response = JSONResponse({"error": "Invalid token"}, status_code=403)
                await response(scope, receive, send)
                return

            await self.app(scope, receive, send)

    # Get the base Starlette app from MCP
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = 8100
    base_app = mcp.streamable_http_app()

    # Wrap with auth middleware
    from starlette.applications import Starlette
    from starlette.routing import Mount

    app = Starlette(
        routes=[Mount("/", app=base_app)],
        middleware=[Middleware(BearerTokenMiddleware, token=api_key)],
    )
    return app


def run_mcp_server(
    *,
    http: bool = False,
    host: str = "0.0.0.0",
    port: int = 8100,
) -> None:
    """Run the MCP server.

    Args:
        http: If True, use streamable-http transport (for remote access).
              If False, use stdio transport (for Claude Desktop).
        host: Host to bind to (only for HTTP transport)
        port: Port to bind to (only for HTTP transport)
    """
    if http:
        api_key = _get_api_key()
        if api_key:
            import uvicorn

            app = _create_authed_app(api_key)
            config = uvicorn.Config(app, host=host, port=port, log_level="info")
            server = uvicorn.Server(config)

            import anyio
            anyio.run(server.serve)
        else:
            mcp.settings.host = host
            mcp.settings.port = port
            mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")

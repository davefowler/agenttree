"""Web dashboard for AgentTree using FastAPI + HTMX."""

from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from pathlib import Path
import subprocess
import asyncio
import secrets
import os
import re
from typing import List, Dict, Optional
from datetime import datetime
from contextlib import asynccontextmanager

from agenttree import __version__
from agenttree.config import load_config, Config
from agenttree.worktree import WorktreeManager

# Load config once at module level - server reload on .agenttree.yaml changes
_config: Config = load_config()
from agenttree import issues as issue_crud
from agenttree.agents_repo import sync_agents_repo
from agenttree.web.models import StageEnum, KanbanBoard, Issue as WebIssue, IssueMoveRequest

# Pattern to match Claude Code's input prompt separator line
# The separator is a line of U+2500 (BOX DRAWINGS LIGHT HORIZONTAL) characters: ─
# We match lines that are at least 20 of these characters (with optional whitespace)
_PROMPT_SEPARATOR_PATTERN = re.compile(r'^\s*─{20,}\s*$')


def _strip_claude_input_prompt(output: str) -> str:
    """Strip Claude Code's input prompt area from tmux output.

    Claude Code displays a separator (a line of ─ characters) before its input
    prompt. We truncate at the first such separator to show only the conversation.
    """
    lines = output.split('\n')

    for i, line in enumerate(lines):
        if _PROMPT_SEPARATOR_PATTERN.match(line):
            # Found the separator - return everything before it
            return '\n'.join(lines[:i]).rstrip()

    return output


# Get the directory where this file is located
BASE_DIR = Path(__file__).resolve().parent

# Background sync task handle
_sync_task: Optional[asyncio.Task] = None


async def background_sync_loop(interval: int = 10) -> None:
    """Background task that syncs _agenttree repo periodically.

    This runs syncs which:
    - Pull/push changes from remote
    - Spawn agents for issues in agent stages
    - Run hooks for controller stages
    - Check for merged PRs

    Args:
        interval: Seconds between syncs (default: 10)
    """
    agents_dir = Path.cwd() / "_agenttree"
    while True:
        try:
            # Run sync in executor to avoid blocking event loop
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sync_agents_repo(agents_dir, pull_only=True)
            )
        except Exception as e:
            print(f"Background sync error: {e}")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context - starts/stops background sync."""
    global _sync_task

    # Start background sync task
    config = load_config()
    interval = config.refresh_interval if hasattr(config, 'refresh_interval') else 10
    _sync_task = asyncio.create_task(background_sync_loop(interval))
    print(f"✓ Started background sync (every {interval}s)")

    yield  # Server runs here

    # Cleanup on shutdown
    if _sync_task:
        _sync_task.cancel()
        try:
            await _sync_task
        except asyncio.CancelledError:
            pass
    print("✓ Stopped background sync")


app = FastAPI(title="AgentTree Dashboard", lifespan=lifespan)


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Disable caching for HTML responses during development."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Disable cache for HTML responses
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(NoCacheMiddleware)

# Mount static files and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["version"] = __version__

# Optional authentication (auto_error=False allows requests without credentials)
security = HTTPBasic(auto_error=False)

# Auth configuration from environment variables
AUTH_ENABLED = os.getenv("AGENTTREE_WEB_AUTH", "false").lower() == "true"
AUTH_USERNAME = os.getenv("AGENTTREE_WEB_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AGENTTREE_WEB_PASSWORD", "changeme")


def verify_credentials(credentials: Optional[HTTPBasicCredentials] = Depends(security)) -> Optional[str]:
    """Verify HTTP Basic Auth credentials.

    This dependency is optional - only enforces auth if AUTH_ENABLED=true.
    """
    if not AUTH_ENABLED:
        return None

    # If auth is enabled but no credentials provided
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    # Constant-time comparison to prevent timing attacks
    username_correct = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        AUTH_USERNAME.encode("utf-8")
    )
    password_correct = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        AUTH_PASSWORD.encode("utf-8")
    )

    if not (username_correct and password_correct):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


# Favicon routes
@app.get("/favicon.ico")
async def favicon() -> FileResponse:
    """Serve favicon."""
    return FileResponse(BASE_DIR / "static" / "favicon.svg", media_type="image/svg+xml")


@app.get("/apple-touch-icon.png")
@app.get("/apple-touch-icon-precomposed.png")
@app.get("/apple-touch-icon-120x120.png")
@app.get("/apple-touch-icon-120x120-precomposed.png")
async def apple_touch_icon() -> RedirectResponse:
    """Redirect apple touch icon requests to favicon."""
    return RedirectResponse(url="/favicon.ico")


# Dependency for protected routes
def get_current_user(username: Optional[str] = Depends(verify_credentials)) -> Optional[str]:
    """Get current authenticated user (or None if auth disabled)."""
    return username


class AgentManager:
    """Manages agent tmux session checks."""

    def __init__(self, worktree_manager: Optional[WorktreeManager] = None):
        self.worktree_manager = worktree_manager
        self._active_sessions: Optional[set[str]] = None

    def _get_active_sessions(self) -> set[str]:
        """Get all active tmux session names in one call."""
        if self._active_sessions is not None:
            return self._active_sessions

        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                self._active_sessions = set(result.stdout.strip().split('\n'))
            else:
                self._active_sessions = set()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            self._active_sessions = set()

        return self._active_sessions

    def clear_session_cache(self) -> None:
        """Clear the cached session list (call at start of each request)."""
        self._active_sessions = None

    def _check_issue_tmux_session(self, issue_id: str) -> bool:
        """Check if tmux session exists for an issue-bound agent."""
        # Session names are: {project}-issue-{issue_id}
        session_name = f"{_config.project}-issue-{issue_id}"
        return session_name in self._get_active_sessions()


# Global agent manager - will be initialized in startup
agent_manager = AgentManager()


def convert_issue_to_web(issue: issue_crud.Issue, load_dependents: bool = False) -> WebIssue:
    """Convert an issue_crud.Issue to a web Issue model.

    Args:
        issue: The issue to convert
        load_dependents: If True, also load dependent issues (issues blocked by this one)
    """
    # Map stage string to StageEnum
    try:
        stage = StageEnum(issue.stage)
    except ValueError:
        stage = StageEnum.BACKLOG

    # Check if tmux session is active for this issue
    tmux_active = agent_manager._check_issue_tmux_session(issue.id)

    # Convert dependencies to ints
    dependencies = [int(d.lstrip("0") or "0") for d in issue.dependencies]

    # Load dependents if requested (issues blocked by this one)
    dependents: List[int] = []
    if load_dependents:
        dependent_issues = issue_crud.get_dependent_issues(issue.id)
        dependents = [int(d.id) for d in dependent_issues]

    return WebIssue(
        number=int(issue.id),
        title=issue.title,
        body="",  # Loaded separately from problem.md
        labels=issue.labels,
        assignees=[],
        stage=stage,
        substage=issue.substage,
        assigned_agent=issue.assigned_agent,
        tmux_active=tmux_active,
        pr_url=issue.pr_url,
        pr_number=issue.pr_number,
        created_at=datetime.fromisoformat(issue.created.replace("Z", "+00:00")),
        updated_at=datetime.fromisoformat(issue.updated.replace("Z", "+00:00")),
        dependencies=dependencies,
        dependents=dependents,
    )


def get_kanban_board() -> KanbanBoard:
    """Build a kanban board from issues."""
    # Initialize all stages with empty lists
    stages: Dict[StageEnum, List[WebIssue]] = {stage: [] for stage in StageEnum}

    # Get all issues and organize by stage (no sync for fast web reads)
    issues = issue_crud.list_issues(sync=False)
    for issue in issues:
        web_issue = convert_issue_to_web(issue)
        if web_issue.stage in stages:
            stages[web_issue.stage].append(web_issue)

    return KanbanBoard(stages=stages, total_issues=len(issues))


@app.get("/")
async def root() -> RedirectResponse:
    """Redirect root to kanban board."""
    return RedirectResponse(url="/kanban", status_code=302)


@app.get("/kanban", response_class=HTMLResponse)
async def kanban(
    request: Request,
    issue: Optional[str] = None,
    chat: Optional[str] = None,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Kanban board page."""
    agent_manager.clear_session_cache()  # Fresh session data per request
    board = get_kanban_board()

    # If issue param provided, load issue detail for modal
    selected_issue = None
    files: list[dict[str, str]] = []
    commits_behind = 0
    if issue:
        issue_obj = issue_crud.get_issue(issue, sync=False)
        if issue_obj:
            selected_issue = convert_issue_to_web(issue_obj, load_dependents=True)
            # Load all file contents upfront for CSS toggle tabs
            files = get_issue_files(issue, include_content=True)
            # Get commits behind for rebase button
            if selected_issue.assigned_agent and issue_obj.worktree_dir:
                from agenttree.hooks import get_commits_behind_main
                commits_behind = get_commits_behind_main(issue_obj.worktree_dir)

    return templates.TemplateResponse(
        "kanban.html",
        {
            "request": request,
            "board": board,
            "stages": list(StageEnum),
            "active_page": "kanban",
            "selected_issue": selected_issue,
            "files": files,
            "commits_behind": commits_behind,
            "chat_open": chat == "1",
        }
    )


def get_issue_files(issue_id: str, include_content: bool = False) -> list[dict[str, str]]:
    """Get list of markdown files for an issue.

    Returns list of dicts with keys: name, display_name, size, modified
    If include_content=True, also includes 'content' key with file contents.
    """
    issue_dir = issue_crud.get_issue_dir(issue_id)
    if not issue_dir:
        return []

    files: list[dict[str, str]] = []
    for f in sorted(issue_dir.glob("*.md")):
        file_info: dict[str, str] = {
            "name": f.name,
            "display_name": f.stem.replace("_", " ").title(),
            "size": str(f.stat().st_size),
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
        }
        if include_content:
            try:
                file_info["content"] = f.read_text()
            except Exception:
                file_info["content"] = ""
        files.append(file_info)
    return files


# Cache stage list for sorting efficiency
_STAGE_LIST = list(StageEnum)


def _sort_flow_issues(issues: list[WebIssue]) -> list[WebIssue]:
    """Sort issues for flow view: review stages first, higher stage order, then number."""
    return sorted(issues, key=lambda x: (not x.is_review, -_STAGE_LIST.index(x.stage), x.number))


@app.get("/flow", response_class=HTMLResponse)
async def flow(
    request: Request,
    issue: Optional[str] = None,
    chat: Optional[str] = None,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Flow view page."""
    agent_manager.clear_session_cache()  # Fresh session data per request
    issues = issue_crud.list_issues(sync=False)  # Skip sync for fast web reads
    web_issues = _sort_flow_issues([convert_issue_to_web(i) for i in issues])

    # Select issue from URL param or default to first
    selected_issue = None
    selected_issue_id = None
    if issue:
        for wi in web_issues:
            if str(wi.number) == issue or str(wi.number).zfill(3) == issue:
                selected_issue_id = str(wi.number).zfill(3)
                break
    if not selected_issue_id and web_issues:
        selected_issue_id = str(web_issues[0].number).zfill(3)

    # Reload selected issue with dependents for detail view
    if selected_issue_id:
        issue_obj = issue_crud.get_issue(selected_issue_id, sync=False)
        if issue_obj:
            selected_issue = convert_issue_to_web(issue_obj, load_dependents=True)

    # Load all file contents upfront for selected issue
    files: list[dict[str, str]] = []
    commits_behind = 0
    if selected_issue and selected_issue_id:
        # Load all file contents upfront for CSS toggle tabs
        files = get_issue_files(selected_issue_id, include_content=True)
        # Get commits behind for rebase button
        if selected_issue.assigned_agent:
            issue_obj = issue_crud.get_issue(selected_issue_id, sync=False)
            if issue_obj and issue_obj.worktree_dir:
                from agenttree.hooks import get_commits_behind_main
                commits_behind = get_commits_behind_main(issue_obj.worktree_dir)

    return templates.TemplateResponse(
        "flow.html",
        {
            "request": request,
            "issues": web_issues,
            "selected_issue": selected_issue,
            "issue": selected_issue,  # issue_detail.html expects 'issue'
            "files": files,
            "commits_behind": commits_behind,
            "active_page": "flow",
            "chat_open": chat == "1",
        }
    )


@app.get("/agent/{agent_num}/tmux", response_class=HTMLResponse)
async def agent_tmux(
    request: Request,
    agent_num: str,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Get tmux output for an issue's agent (HTMX endpoint).

    Note: agent_num parameter is actually the issue number - sessions are named by issue.
    """
    config = load_config()
    # Pad issue number to 3 digits to match tmux session naming
    padded_num = agent_num.zfill(3)
    session_name = f"{config.project}-issue-{padded_num}"

    # Capture tmux output
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p"],
            capture_output=True,
            text=True,
            timeout=2
        )

        if result.returncode == 0:
            # Strip Claude Code's input prompt separator from the output
            output = _strip_claude_input_prompt(result.stdout)
        else:
            output = "Tmux session not active"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        output = "Could not capture tmux output"

    return templates.TemplateResponse(
        "partials/tmux_output.html",
        {"request": request, "agent_num": agent_num, "output": output}
    )


@app.post("/agent/{agent_num}/send", response_class=HTMLResponse)
async def send_to_agent(
    request: Request,
    agent_num: str,
    message: str = Form(...),
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Send a message to an issue's agent via tmux.

    Note: agent_num parameter is actually the issue number - sessions are named by issue.
    """
    from agenttree.tmux import send_message

    config = load_config()
    # Pad issue number to 3 digits to match tmux session naming
    padded_num = agent_num.zfill(3)
    session_name = f"{config.project}-issue-{padded_num}"

    # Send message - result will appear in tmux output on next poll
    send_message(session_name, message)
    return HTMLResponse("")


@app.post("/api/issues/{issue_id}/start")
async def start_issue(
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Start an agent to work on an issue (calls agenttree start)."""
    try:
        # Use --force to restart stalled agents (tmux dead but state exists)
        subprocess.Popen(
            ["uv", "run", "agenttree", "start", issue_id, "--force"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=Path.cwd(),
            start_new_session=True  # Detach from parent process
        )
        return {"ok": True, "status": f"Starting agent for issue #{issue_id}..."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/issues/{issue_id}/agent-status")
async def get_agent_status(
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Check if an agent's tmux session is running for an issue."""
    # Normalize issue ID
    padded_id = issue_id.zfill(3)
    tmux_active = agent_manager._check_issue_tmux_session(padded_id)

    # Also check if agent is assigned
    issue = issue_crud.get_issue(issue_id, sync=False)
    assigned_agent = issue.assigned_agent if issue else None

    return {
        "tmux_active": tmux_active,
        "assigned_agent": assigned_agent,
        "status": "running" if tmux_active else ("stalled" if assigned_agent else "off")
    }


@app.post("/api/issues/{issue_id}/move")
async def move_issue(
    issue_id: str,
    move_request: IssueMoveRequest,
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Move an issue to a new stage.

    DEPRECATED: Use /approve for human review stages instead.
    This bypasses workflow validation and should only be used for backlog management.
    """
    # Only allow moving TO backlog or not_doing (safe operations)
    safe_targets = ["backlog", "not_doing"]
    if move_request.stage.value not in safe_targets:
        raise HTTPException(
            status_code=400,
            detail=f"Direct stage changes only allowed to: {', '.join(safe_targets)}. Use approve for workflow transitions."
        )

    # Get issue first to pass to cleanup
    issue = issue_crud.get_issue(issue_id, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    updated_issue = issue_crud.update_issue_stage(
        issue_id=issue_id,
        stage=move_request.stage.value,
        substage=None,
    )

    if not updated_issue:
        raise HTTPException(status_code=500, detail=f"Failed to update issue {issue_id}")

    # Clean up agent when moving to backlog or not_doing
    # backlog = pause work (stop agent, keep worktree for later)
    # not_doing = abandon work (stop agent, worktree can be cleaned up)
    if move_request.stage.value in ["backlog", "not_doing"]:
        from agenttree.hooks import cleanup_issue_agent
        cleanup_issue_agent(updated_issue)

    return {"success": True, "stage": move_request.stage.value}


@app.post("/api/issues/{issue_id}/approve")
async def approve_issue(
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Approve an issue at a human review stage.

    Runs the proper workflow: executes exit hooks, advances to next stage,
    executes enter hooks. Only works from human review stages.
    """
    from agenttree.config import load_config
    from agenttree.hooks import execute_exit_hooks, execute_enter_hooks, ValidationError

    HUMAN_REVIEW_STAGES = ["plan_review", "implementation_review"]

    # Get issue
    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = issue_crud.get_issue(issue_id_normalized, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Check if at human review stage
    if issue.stage not in HUMAN_REVIEW_STAGES:
        raise HTTPException(status_code=400, detail="Not at review stage")

    # Calculate next stage
    config = load_config()
    next_stage, next_substage, _ = config.get_next_stage(issue.stage, issue.substage)

    # Execute exit hooks (validation)
    try:
        execute_exit_hooks(issue, issue.stage, issue.substage)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Update issue stage
    updated = issue_crud.update_issue_stage(issue_id_normalized, next_stage, next_substage)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update")

    # Note: We intentionally DON'T call update_session_stage here because that would
    # sync last_stage with issue.stage, defeating the stage mismatch detection.
    # When the agent runs `next`, is_restart() will detect session.last_stage != issue.stage
    # and show them the current stage instructions instead of advancing.

    # Execute enter hooks
    try:
        execute_enter_hooks(updated, next_stage, next_substage)
    except Exception:
        pass  # Enter hooks shouldn't block

    # Notify agent to continue (if active)
    try:
        from agenttree.state import get_active_agent
        from agenttree.tmux import send_message, session_exists

        agent = get_active_agent(issue_id_normalized)
        if agent and agent.tmux_session:
            if session_exists(agent.tmux_session):
                message = "Your work was approved! Run `agenttree next` for instructions."
                send_message(agent.tmux_session, message)
    except Exception:
        pass  # Agent notification is best-effort

    return {"ok": True}


@app.post("/api/issues")
async def create_issue_api(
    request: Request,
    title: str = Form(...),
    priority: str = Form("medium"),
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Create a new issue via the web UI.

    Creates an issue in the 'define' stage with default substage 'refine'.
    """
    from agenttree.issues import Priority

    # Validate title length
    if len(title.strip()) < 10:
        raise HTTPException(status_code=400, detail="Title must be at least 10 characters")

    # Map priority string to enum
    try:
        priority_enum = Priority(priority.lower())
    except ValueError:
        priority_enum = Priority.MEDIUM

    try:
        issue = issue_crud.create_issue(
            title=title.strip(),
            priority=priority_enum,
        )
        return {"ok": True, "issue_id": issue.id, "title": issue.title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/issues/{issue_id}/rebase")
async def rebase_issue(
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Rebase an issue's branch onto the latest main.

    Performs the rebase and notifies the agent. Client reloads page after.
    """
    from agenttree.hooks import rebase_issue_branch

    # Get issue
    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = issue_crud.get_issue(issue_id_normalized, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    # Perform the rebase
    success, message = rebase_issue_branch(issue_id_normalized)

    if not success:
        raise HTTPException(status_code=400, detail=message)

    # Notify the agent if one is assigned and has an active tmux session
    if issue.assigned_agent:
        from agenttree.tmux import send_message

        config = load_config()
        padded_num = issue.assigned_agent.zfill(3)
        session_name = f"{config.project}-issue-{padded_num}"

        notification = (
            "Your branch has been rebased onto the latest main. "
            "Please review the recent changes and update your work if needed. "
            "Run 'git log --oneline -10' to see recent commits."
        )
        send_message(session_name, notification)

    return {"ok": True}


@app.websocket("/ws/agent/{agent_num}/tmux")
async def tmux_websocket(websocket: WebSocket, agent_num: int) -> None:
    """WebSocket for live tmux output streaming."""
    await websocket.accept()

    try:
        while True:
            # Capture tmux output every second
            try:
                result = subprocess.run(
                    ["tmux", "capture-pane", "-t", f"agent-{agent_num}", "-p"],
                    capture_output=True,
                    text=True,
                    timeout=1
                )

                if result.returncode == 0:
                    await websocket.send_text(result.stdout)
                else:
                    await websocket.send_text("[Tmux session not active]")

            except subprocess.TimeoutExpired:
                await websocket.send_text("[Timeout capturing tmux]")

            await asyncio.sleep(1)

    except WebSocketDisconnect:
        pass


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "healthy", "service": "agenttree-web"}


def run_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    config_path: Optional[Path] = None
) -> None:
    """Run the FastAPI server.

    Args:
        host: Host to bind to
        port: Port to bind to
        config_path: Path to agenttree config file (optional)
    """
    global agent_manager

    # Load config - find_config_file walks up directory tree to find .agenttree.yaml
    try:
        config = load_config(config_path)
        repo_path = Path.cwd()
        worktree_manager = WorktreeManager(repo_path, config)
        agent_manager = AgentManager(worktree_manager)
        print(f"✓ Loaded config for project: {config.project}")
    except Exception as e:
        print(f"⚠ Could not load config: {e}")
        print("  Run 'agenttree init' to create a config file")

    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()

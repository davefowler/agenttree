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
from typing import List, Dict, Optional
from datetime import datetime

from agenttree import __version__
from agenttree.config import load_config
from agenttree.worktree import WorktreeManager
from agenttree.github import get_issue as get_github_issue
from agenttree import issues as issue_crud
from agenttree.web.models import StageEnum, KanbanBoard, Issue as WebIssue, IssueMoveRequest
import re


def _strip_claude_input_prompt(output: str) -> str:
    """Strip Claude Code's input prompt area from tmux output.

    Claude Code displays a separator (multiple horizontal bar lines) before
    its input prompt. We truncate at this separator to show only the
    conversation content.
    """
    lines = output.split('\n')

    # Look for the separator pattern: 3+ consecutive lines that are mostly
    # horizontal bars (─), underscores (_), or spaces
    separator_pattern = re.compile(r'^[\s─_\-━]+$')

    consecutive_bars = 0
    cutoff_index = None

    for i, line in enumerate(lines):
        # Check if line is mostly horizontal bars/underscores (allowing some spaces)
        stripped = line.strip()
        if stripped and separator_pattern.match(line) and len(stripped) > 10:
            consecutive_bars += 1
            if consecutive_bars >= 3:
                # Found the separator - cut from where it started
                cutoff_index = i - 2  # Go back to first bar line
                break
        else:
            consecutive_bars = 0

    if cutoff_index is not None and cutoff_index > 0:
        return '\n'.join(lines[:cutoff_index]).rstrip()

    return output


# Get the directory where this file is located
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="AgentTree Dashboard")


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
    """Manages agent state for the dashboard."""

    def __init__(self, worktree_manager: Optional[WorktreeManager] = None):
        self.worktree_manager = worktree_manager
        self.agents: Dict[int, dict] = {}

    def _check_tmux_session(self, agent_num: int) -> bool:
        """Check if tmux session exists for agent (legacy numbered agents)."""
        try:
            result = subprocess.run(
                ["tmux", "has-session", "-t", f"agent-{agent_num}"],
                capture_output=True,
                timeout=1
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _check_issue_tmux_session(self, issue_id: str) -> bool:
        """Check if tmux session exists for an issue-bound agent."""
        # Session names are: {project}-issue-{issue_id}
        config = load_config()
        session_name = f"{config.project}-issue-{issue_id}"
        try:
            result = subprocess.run(
                ["tmux", "has-session", "-t", session_name],
                capture_output=True,
                timeout=1
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def get_agent_status(self, agent_num: int) -> dict:
        """Get status of an agent."""
        if self.worktree_manager:
            try:
                status = self.worktree_manager.get_status(agent_num)
                
                # Build task description
                task_desc = None
                if status.has_task and status.current_task:
                    task_desc = status.current_task
                    if status.task_count > 1:
                        task_desc += f" (+{status.task_count - 1} queued)"
                
                return {
                    "agent_num": agent_num,
                    "status": "working" if status.is_busy else "idle",
                    "current_task": task_desc,
                    "task_count": status.task_count,
                    "tmux_active": self._check_tmux_session(agent_num),
                    "last_activity": datetime.now().isoformat()
                }
            except Exception:
                # Agent not set up yet
                pass

        # Fallback to basic check
        return {
            "agent_num": agent_num,
            "status": "idle",
            "current_task": None,
            "task_count": 0,
            "tmux_active": self._check_tmux_session(agent_num),
            "last_activity": "Unknown"
        }

    def get_all_agents(self) -> List[dict]:
        """Get all configured agents by scanning for existing worktrees."""
        agents = []
        if self.worktree_manager:
            config = self.worktree_manager.config
            worktrees_dir = Path(config.worktrees_dir).expanduser()
            
            # Scan for existing agent directories matching project namespace
            for agent_num in range(1, 10):
                agent_path = worktrees_dir / f"{config.project}-agent-{agent_num}"
                if agent_path.exists():
                    agents.append(self.get_agent_status(agent_num))
        
        return agents


# Global agent manager - will be initialized in startup
agent_manager = AgentManager()


def convert_issue_to_web(issue: issue_crud.Issue) -> WebIssue:
    """Convert an issue_crud.Issue to a web Issue model."""
    # Map stage string to StageEnum
    try:
        stage = StageEnum(issue.stage)
    except ValueError:
        stage = StageEnum.BACKLOG

    # Check if tmux session is active for this issue
    tmux_active = agent_manager._check_issue_tmux_session(issue.id)

    return WebIssue(
        number=int(issue.id),
        title=issue.title,
        body="",  # Loaded separately from problem.md
        labels=issue.labels,
        assignees=[],
        stage=stage,
        assigned_agent=issue.assigned_agent,
        tmux_active=tmux_active,
        pr_url=issue.pr_url,
        pr_number=issue.pr_number,
        created_at=datetime.fromisoformat(issue.created.replace("Z", "+00:00")),
        updated_at=datetime.fromisoformat(issue.updated.replace("Z", "+00:00")),
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


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Main dashboard page."""
    agents = agent_manager.get_all_agents()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "agents": agents, "user": user, "active_page": "dashboard"}
    )


@app.get("/kanban", response_class=HTMLResponse)
async def kanban(
    request: Request,
    issue: Optional[str] = None,
    chat: Optional[str] = None,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Kanban board page."""
    board = get_kanban_board()

    # If issue param provided, load issue detail for modal
    selected_issue = None
    files: list[dict[str, str | int]] = []
    if issue:
        issue_obj = issue_crud.get_issue(issue, sync=False)
        if issue_obj:
            selected_issue = convert_issue_to_web(issue_obj)
            files = get_issue_files(issue)
            # Load last file content
            issue_dir = issue_crud.get_issue_dir(issue)
            if issue_dir and files:
                last_file = files[-1]
                file_path = issue_dir / last_file["name"]
                if file_path.exists():
                    selected_issue.body = file_path.read_text()

    return templates.TemplateResponse(
        "kanban.html",
        {
            "request": request,
            "board": board,
            "stages": list(StageEnum),
            "active_page": "kanban",
            "selected_issue": selected_issue,
            "files": files,
            "chat_open": chat == "1",
        }
    )


def get_issue_files(issue_id: str) -> list[dict[str, str | int]]:
    """Get list of markdown files for an issue.

    Returns list of dicts with keys: name, display_name, size, modified
    """
    issue_dir = issue_crud.get_issue_dir(issue_id)
    if not issue_dir:
        return []

    files: list[dict[str, str | int]] = []
    for f in sorted(issue_dir.glob("*.md")):
        files.append({
            "name": f.name,
            "display_name": f.stem.replace("_", " ").title(),
            "size": f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
        })
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
    issues = issue_crud.list_issues(sync=False)  # Skip sync for fast web reads
    web_issues = _sort_flow_issues([convert_issue_to_web(i) for i in issues])

    # Select issue from URL param or default to first
    selected_issue = None
    if issue:
        for wi in web_issues:
            if str(wi.number) == issue or str(wi.number).zfill(3) == issue:
                selected_issue = wi
                break
    if not selected_issue and web_issues:
        selected_issue = web_issues[0]

    # Load body content and files for selected issue
    files: list[dict[str, str | int]] = []
    if selected_issue:
        issue_id = str(selected_issue.number).zfill(3)
        issue_dir = issue_crud.get_issue_dir(issue_id)
        if issue_dir:
            # Get list of markdown files
            files = get_issue_files(issue_id)
            # Load last file content (rightmost tab selected by default)
            if files:
                last_file = files[-1]
                file_path = issue_dir / last_file["name"]
                if file_path.exists():
                    selected_issue.body = file_path.read_text()

    return templates.TemplateResponse(
        "flow.html",
        {
            "request": request,
            "issues": web_issues,
            "selected_issue": selected_issue,
            "issue": selected_issue,  # issue_detail.html expects 'issue'
            "files": files,
            "active_page": "flow",
            "chat_open": chat == "1",
        }
    )


@app.get("/flow/issues", response_class=HTMLResponse)
async def flow_issues(
    request: Request,
    issue: Optional[str] = None,
    chat: Optional[str] = None,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Flow issues list (HTMX endpoint)."""
    issues = issue_crud.list_issues(sync=False)  # Skip sync for fast web reads
    web_issues = _sort_flow_issues([convert_issue_to_web(i) for i in issues])

    # Find selected issue for active state
    selected_issue = None
    if issue:
        for wi in web_issues:
            if str(wi.number) == issue or str(wi.number).zfill(3) == issue:
                selected_issue = wi
                break

    return templates.TemplateResponse(
        "partials/flow_issues_list.html",
        {
            "request": request,
            "issues": web_issues,
            "selected_issue": selected_issue,
            "chat_open": chat == "1",
        }
    )


@app.get("/agents", response_class=HTMLResponse)
async def agents_list(
    request: Request,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Get agents list (HTMX endpoint)."""
    agents = agent_manager.get_all_agents()
    return templates.TemplateResponse(
        "partials/agents_list.html",
        {"request": request, "agents": agents}
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

        output = result.stdout if result.returncode == 0 else "Tmux session not active"

        # Strip Claude Code's input prompt area (appears as multiple horizontal bar lines)
        # Look for 3+ consecutive lines that are mostly horizontal bars/underscores
        output = _strip_claude_input_prompt(output)
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

    if send_message(session_name, message):
        status = "Sent"
        success = True
    else:
        status = "Agent not running - click the light to start"
        success = False

    return templates.TemplateResponse(
        "partials/send_status.html",
        {"request": request, "status": status, "success": success}
    )


@app.post("/agent/{agent_num}/start", response_class=HTMLResponse)
async def start_task(
    request: Request,
    agent_num: int,
    issue_number: int = Form(default=None),
    task_description: str = Form(default=None),
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Start a task on an agent (adds to queue)."""
    from agenttree.worktree import create_task_file

    try:
        if agent_manager.worktree_manager:
            worktree_path = agent_manager.worktree_manager.config.get_worktree_path(agent_num)

            # Create task content
            if issue_number:
                try:
                    issue = get_github_issue(issue_number)
                    task_content = f"""# Task: {issue.title}

**Issue:** [#{issue.number}]({issue.url})

## Description

{issue.body}
"""
                    task_path = create_task_file(
                        worktree_path, issue.title, task_content, issue_number
                    )
                    status = f"Task queued: {task_path.name}"
                except Exception as e:
                    status = f"Error fetching issue: {e}"
            else:
                task_title = task_description[:50] if task_description else "Ad-hoc Task"
                task_content = f"""# Task: {task_title}

## Description

{task_description or 'No description provided.'}
"""
                task_path = create_task_file(worktree_path, task_title, task_content)
                status = f"Task queued: {task_path.name}"
        else:
            status = "Error: No worktree manager configured"

    except Exception as e:
        status = f"Error: {str(e)}"

    return templates.TemplateResponse(
        "partials/start_status.html",
        {
            "request": request,
            "agent_num": agent_num,
            "status": status
        }
    )


@app.post("/api/issues/{issue_id}/start", response_class=HTMLResponse)
async def start_issue(
    request: Request,
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
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
        status = f"Starting agent for issue #{issue_id}..."
        success = True
    except Exception as e:
        status = f"Error: {str(e)}"
        success = False

    return templates.TemplateResponse(
        "partials/start_status.html",
        {"request": request, "status": status, "success": success, "agent_num": 0}
    )


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
    from agenttree.issues import update_session_stage

    HUMAN_REVIEW_STAGES = ["plan_review", "implementation_review"]

    # Get issue
    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = issue_crud.get_issue(issue_id_normalized, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    # Check if at human review stage
    if issue.stage not in HUMAN_REVIEW_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Issue is at '{issue.stage}', not a human review stage. Can only approve from: {', '.join(HUMAN_REVIEW_STAGES)}"
        )

    # Calculate next stage
    config = load_config()
    next_stage, next_substage, _ = config.get_next_stage(issue.stage, issue.substage)

    # Execute exit hooks (validation)
    try:
        execute_exit_hooks(issue, issue.stage, issue.substage)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Cannot approve: {str(e)}")

    # Update issue stage
    updated = issue_crud.update_issue_stage(issue_id_normalized, next_stage, next_substage)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update issue")

    # Update session
    try:
        update_session_stage(issue_id_normalized, next_stage, next_substage)
    except Exception:
        pass  # Session update is optional

    # Execute enter hooks
    try:
        execute_enter_hooks(updated, next_stage, next_substage)
    except Exception:
        pass  # Enter hooks shouldn't block

    return {
        "success": True,
        "message": f"Approved! Moved from {issue.stage} to {next_stage}",
        "new_stage": next_stage,
        "new_substage": next_substage
    }


@app.get("/api/issues/{issue_id}/commits-behind")
async def get_commits_behind(
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Get the number of commits the issue branch is behind main."""
    from agenttree.hooks import get_commits_behind_main

    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = issue_crud.get_issue(issue_id_normalized, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    commits_behind = get_commits_behind_main(issue_id_normalized)
    return {"commits_behind": commits_behind}


@app.get("/api/issues/{issue_id}/rebase-controls", response_class=HTMLResponse)
async def get_rebase_controls(
    request: Request,
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Get rebase controls HTML partial."""
    from agenttree.hooks import get_commits_behind_main

    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = issue_crud.get_issue(issue_id_normalized, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    commits_behind = get_commits_behind_main(issue_id_normalized)

    return templates.TemplateResponse(
        "partials/rebase_controls.html",
        {
            "request": request,
            "issue_number": issue.id,
            "commits_behind": commits_behind
        }
    )


@app.post("/api/issues/{issue_id}/rebase", response_class=HTMLResponse)
async def rebase_issue(
    request: Request,
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Rebase an issue's branch onto the latest main.

    Performs the rebase from the host and notifies the agent of the changes.
    Returns updated rebase controls HTML for HTMX.
    """
    from agenttree.hooks import rebase_issue_branch, get_commits_behind_main

    # Get issue
    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = issue_crud.get_issue(issue_id_normalized, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    # Perform the rebase
    success, message = rebase_issue_branch(issue_id_normalized)

    if not success:
        # Return error message in the controls area
        return HTMLResponse(
            content=f'<div class="rebase-controls"><span class="rebase-error" style="color: #dc2626; font-size: 12px;">{message}</span></div>',
            status_code=200  # Use 200 so HTMX still swaps content
        )

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
        send_message(session_name, notification)  # Best-effort, returns False if not running

    # Return updated rebase controls
    commits_behind = get_commits_behind_main(issue_id_normalized)
    return templates.TemplateResponse(
        "partials/rebase_controls.html",
        {
            "request": request,
            "issue_number": issue.id,
            "commits_behind": commits_behind
        }
    )


@app.get("/api/issues/{issue_id}/detail", response_class=HTMLResponse)
async def issue_detail(
    request: Request,
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Get issue detail HTML (for modal)."""
    issue = issue_crud.get_issue(issue_id, sync=False)  # Skip sync for fast web reads
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    # Get markdown files list
    files = get_issue_files(issue_id)

    # Load last file content (rightmost tab selected by default)
    issue_dir = issue_crud.get_issue_dir(issue_id)
    default_content = ""
    if issue_dir and files:
        last_file = files[-1]
        file_path = issue_dir / last_file["name"]
        if file_path.exists():
            default_content = file_path.read_text()

    web_issue = convert_issue_to_web(issue)
    web_issue.body = default_content

    return templates.TemplateResponse(
        "partials/issue_detail.html",
        {"request": request, "issue": web_issue, "files": files}
    )


@app.get("/flow/issue/{issue_id}", response_class=HTMLResponse)
async def flow_issue_detail(
    request: Request,
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Get issue detail for flow view (HTMX endpoint)."""
    issue = issue_crud.get_issue(issue_id, sync=False)  # Skip sync for fast web reads
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    # Get markdown files list
    files = get_issue_files(issue_id)

    # Load last file content (rightmost tab selected by default)
    issue_dir = issue_crud.get_issue_dir(issue_id)
    default_content = ""
    if issue_dir and files:
        last_file = files[-1]
        file_path = issue_dir / last_file["name"]
        if file_path.exists():
            default_content = file_path.read_text()

    web_issue = convert_issue_to_web(issue)
    web_issue.body = default_content

    return templates.TemplateResponse(
        "partials/flow_issue_detail.html",
        {"request": request, "issue": web_issue, "files": files}
    )


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


@app.get("/api/issues/{issue_id}/files")
async def list_issue_files(
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """List markdown files in an issue directory."""
    files = get_issue_files(issue_id)
    if not files and not issue_crud.get_issue_dir(issue_id):
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    return {"issue_id": issue_id, "files": files}


@app.get("/api/issues/{issue_id}/files/{filename}", response_class=HTMLResponse)
async def get_issue_file(
    request: Request,
    issue_id: str,
    filename: str,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Get content of a markdown file in an issue directory."""
    issue_dir = issue_crud.get_issue_dir(issue_id)
    if not issue_dir:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    # Security: ensure filename is safe (no path traversal)
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = issue_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File {filename} not found")

    content = file_path.read_text()

    return templates.TemplateResponse(
        "partials/markdown_content.html",
        {"request": request, "content": content, "filename": filename}
    )


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

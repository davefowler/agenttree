"""Web dashboard for AgentTree using FastAPI + HTMX."""

from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import subprocess
import asyncio
import secrets
import os
from typing import List, Dict, Optional
from datetime import datetime

from agenttree.config import load_config
from agenttree.worktree import WorktreeManager
from agenttree.github import get_issue as get_github_issue
from agenttree import issues as issue_crud
from agenttree.web.models import StageEnum, KanbanBoard, Issue as WebIssue, IssueMoveRequest

# Get the directory where this file is located
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="AgentTree Dashboard")

# Mount static files and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

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
async def favicon():
    """Serve favicon."""
    return FileResponse(BASE_DIR / "static" / "favicon.svg", media_type="image/svg+xml")


@app.get("/apple-touch-icon.png")
@app.get("/apple-touch-icon-precomposed.png")
@app.get("/apple-touch-icon-120x120.png")
@app.get("/apple-touch-icon-120x120-precomposed.png")
async def apple_touch_icon():
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
        """Check if tmux session exists for agent."""
        try:
            result = subprocess.run(
                ["tmux", "has-session", "-t", f"agent-{agent_num}"],
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

    return WebIssue(
        number=int(issue.id),
        title=issue.title,
        body="",  # Loaded separately from problem.md
        labels=issue.labels,
        assignees=[],
        stage=stage,
        assigned_agent=issue.assigned_agent,
        created_at=datetime.fromisoformat(issue.created.replace("Z", "+00:00")),
        updated_at=datetime.fromisoformat(issue.updated.replace("Z", "+00:00")),
    )


def get_kanban_board() -> KanbanBoard:
    """Build a kanban board from issues."""
    # Initialize all stages with empty lists
    stages: Dict[StageEnum, List[WebIssue]] = {stage: [] for stage in StageEnum}

    # Get all issues and organize by stage
    issues = issue_crud.list_issues()
    for issue in issues:
        web_issue = convert_issue_to_web(issue)
        if web_issue.stage in stages:
            stages[web_issue.stage].append(web_issue)

    return KanbanBoard(stages=stages, total_issues=len(issues))


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    user = get_current_user()  # Check auth if enabled
    agents = agent_manager.get_all_agents()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "agents": agents, "user": user}
    )


@app.get("/kanban", response_class=HTMLResponse)
async def kanban(request: Request):
    """Kanban board page."""
    get_current_user()  # Check auth if enabled
    board = get_kanban_board()
    return templates.TemplateResponse(
        "kanban.html",
        {"request": request, "board": board, "stages": list(StageEnum)}
    )


@app.get("/flow", response_class=HTMLResponse)
async def flow(request: Request):
    """Flow view page."""
    get_current_user()  # Check auth if enabled
    issues = issue_crud.list_issues()
    web_issues = [convert_issue_to_web(i) for i in issues]
    # Sort by stage order and then by number
    web_issues.sort(key=lambda x: (list(StageEnum).index(x.stage), x.number))
    selected_issue = web_issues[0] if web_issues else None

    # Load body content for selected issue
    if selected_issue and issues:
        raw_issue = issues[0]
        issue_dir = issue_crud.get_issue_dir(raw_issue.id)
        if issue_dir:
            problem_path = issue_dir / "problem.md"
            if problem_path.exists():
                selected_issue.body = problem_path.read_text()

    return templates.TemplateResponse(
        "flow.html",
        {
            "request": request,
            "issues": web_issues,
            "selected_issue": selected_issue,
            "issue": selected_issue,  # issue_detail.html expects 'issue'
        }
    )


@app.get("/flow/issues", response_class=HTMLResponse)
async def flow_issues(request: Request):
    """Flow issues list (HTMX endpoint)."""
    get_current_user()  # Check auth if enabled
    issues = issue_crud.list_issues()
    web_issues = [convert_issue_to_web(i) for i in issues]
    web_issues.sort(key=lambda x: (list(StageEnum).index(x.stage), x.number))
    return templates.TemplateResponse(
        "partials/flow_issues_list.html",
        {"request": request, "issues": web_issues}
    )


@app.get("/agents", response_class=HTMLResponse)
async def agents_list(request: Request):
    """Get agents list (HTMX endpoint)."""
    get_current_user()  # Check auth if enabled
    agents = agent_manager.get_all_agents()
    return templates.TemplateResponse(
        "partials/agents_list.html",
        {"request": request, "agents": agents}
    )


@app.get("/agent/{agent_num}/tmux", response_class=HTMLResponse)
async def agent_tmux(request: Request, agent_num: int):
    """Get tmux output for an agent (HTMX endpoint)."""
    get_current_user()  # Check auth if enabled
    # Capture tmux output
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", f"agent-{agent_num}", "-p"],
            capture_output=True,
            text=True,
            timeout=2
        )

        output = result.stdout if result.returncode == 0 else "Tmux session not active"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        output = "Could not capture tmux output"

    return templates.TemplateResponse(
        "partials/tmux_output.html",
        {"request": request, "agent_num": agent_num, "output": output}
    )


@app.post("/agent/{agent_num}/send", response_class=HTMLResponse)
async def send_to_agent(
    request: Request,
    agent_num: int,
    message: str = Form(...)
):
    """Send a message to an agent via tmux."""
    get_current_user()  # Check auth if enabled
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", f"agent-{agent_num}", message, "Enter"],
            check=True,
            timeout=2
        )

        status = "Message sent successfully"
    except subprocess.CalledProcessError:
        status = "Failed to send message"

    return templates.TemplateResponse(
        "partials/send_status.html",
        {"request": request, "status": status, "success": True}
    )


@app.post("/agent/{agent_num}/dispatch", response_class=HTMLResponse)
async def dispatch_task(
    request: Request,
    agent_num: int,
    issue_number: int = Form(default=None),
    task_description: str = Form(default=None),
    user: Optional[str] = Depends(get_current_user)
):
    """Dispatch a task to an agent (adds to queue)."""
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
        "partials/dispatch_status.html",
        {
            "request": request,
            "agent_num": agent_num,
            "status": status
        }
    )


@app.post("/api/issues/{issue_id}/start", response_class=HTMLResponse)
async def start_issue(request: Request, issue_id: str):
    """Start an agent to work on an issue (calls agenttree start)."""
    get_current_user()  # Check auth if enabled

    try:
        # Run agenttree start in background (don't wait for completion)
        subprocess.Popen(
            ["uv", "run", "agenttree", "start", issue_id],
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
        "partials/dispatch_status.html",
        {"request": request, "status": status, "success": success, "agent_num": 0}
    )


@app.post("/api/issues/{issue_id}/move")
async def move_issue(issue_id: str, move_request: IssueMoveRequest):
    """Move an issue to a new stage."""
    get_current_user()  # Check auth if enabled

    # Update the issue stage
    updated_issue = issue_crud.update_issue_stage(
        issue_id=issue_id,
        stage=move_request.stage.value,
        substage=None,  # Clear substage when moving manually
    )

    if not updated_issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    return {"success": True, "stage": move_request.stage.value}


@app.get("/api/issues/{issue_id}/detail", response_class=HTMLResponse)
async def issue_detail(request: Request, issue_id: str):
    """Get issue detail HTML (for modal)."""
    get_current_user()  # Check auth if enabled

    issue = issue_crud.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    # Load problem.md content
    issue_dir = issue_crud.get_issue_dir(issue_id)
    problem_content = ""
    if issue_dir:
        problem_path = issue_dir / "problem.md"
        if problem_path.exists():
            problem_content = problem_path.read_text()

    web_issue = convert_issue_to_web(issue)
    web_issue.body = problem_content

    return templates.TemplateResponse(
        "partials/issue_detail.html",
        {"request": request, "issue": web_issue}
    )


@app.get("/flow/issue/{issue_id}", response_class=HTMLResponse)
async def flow_issue_detail(request: Request, issue_id: str):
    """Get issue detail for flow view (HTMX endpoint)."""
    get_current_user()  # Check auth if enabled

    issue = issue_crud.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    # Load problem.md content
    issue_dir = issue_crud.get_issue_dir(issue_id)
    problem_content = ""
    if issue_dir:
        problem_path = issue_dir / "problem.md"
        if problem_path.exists():
            problem_content = problem_path.read_text()

    web_issue = convert_issue_to_web(issue)
    web_issue.body = problem_content

    return templates.TemplateResponse(
        "partials/issue_detail.html",
        {"request": request, "issue": web_issue}
    )


@app.websocket("/ws/agent/{agent_num}/tmux")
async def tmux_websocket(websocket: WebSocket, agent_num: int):
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
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "agenttree-web"}


def run_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    config_path: Optional[Path] = None
):
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

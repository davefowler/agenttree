"""Web dashboard for AgentTree using FastAPI + HTMX."""

# Force standard asyncio event loop instead of uvloop to avoid fork crashes
# uvloop's signal handlers aren't fork-safe, causing crashes when subprocess.run() forks
import asyncio
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from pathlib import Path
import logging
import subprocess
import secrets
import os
import re
from typing import Optional, AsyncIterator, Callable, Awaitable
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import yaml

from agenttree import __version__
from agenttree.config import load_config, Config
from agenttree.worktree import WorktreeManager

# Load config once at module level - server reload on .agenttree.yaml changes
_config: Config = load_config()
from agenttree import issues as issue_crud
from agenttree.agents_repo import sync_agents_repo
from agenttree.web.models import KanbanBoard, Issue as WebIssue, IssueMoveRequest, PriorityUpdateRequest

# Module-level logger for web app
logger = logging.getLogger("agenttree.web")

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

# Background heartbeat task handle
_heartbeat_task: Optional[asyncio.Task] = None
_heartbeat_count: int = 0

# Dedicated executor for heartbeat so it never competes with request handlers.
# Heartbeat actions (sync, check_ci, check_stalled) can take 10-15s and would
# starve asyncio.to_thread() calls in request handlers if sharing the default pool.
from concurrent.futures import ThreadPoolExecutor
_heartbeat_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="heartbeat")


async def heartbeat_loop(interval: int = 10) -> None:
    """Background task that fires heartbeat events periodically.

    The heartbeat event triggers configured actions like:
    - sync: Git pull/push _agenttree
    - check_stalled_agents: Nudge agents stuck too long
    - check_ci_status: Check GitHub CI status
    - check_merged_prs: Detect externally merged PRs

    Actions are configured in .agenttree.yaml under on.heartbeat.

    Args:
        interval: Seconds between heartbeats (default: 10)
    """
    global _heartbeat_count
    from agenttree.events import fire_event, HEARTBEAT

    agents_dir = Path.cwd() / "_agenttree"

    while True:
        try:
            _heartbeat_count += 1
            await asyncio.get_event_loop().run_in_executor(
                _heartbeat_executor,
                lambda: fire_event(HEARTBEAT, agents_dir, heartbeat_count=_heartbeat_count)
            )
        except Exception as e:
            print(f"Heartbeat error: {e}")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan context - starts heartbeat and manager.
    
    Note: The startup event is fired by 'agenttree run' before starting the server.
    This lifespan only handles the heartbeat loop and manager startup fallback.
    """
    global _heartbeat_task

    # Get heartbeat interval from config
    from agenttree.events import get_heartbeat_interval
    interval = get_heartbeat_interval()
    
    # Start heartbeat task
    _heartbeat_task = asyncio.create_task(heartbeat_loop(interval))
    print(f"✓ Started heartbeat events (every {interval}s)")

    # Auto-start manager if not running (fallback for direct server start)
    from agenttree.tmux import session_exists
    config = load_config()
    manager_session = config.get_manager_tmux_session()
    if not session_exists(manager_session):
        try:
            from agenttree.api import start_controller

            await asyncio.to_thread(start_controller, quiet=True)
            print("✓ Started controller agent")
        except Exception as e:
            print(f"⚠ Could not start controller: {e}")
    else:
        print("✓ Manager already running")

    yield  # Server runs here

    # Cleanup on shutdown
    if _heartbeat_task:
        _heartbeat_task.cancel()
        try:
            await _heartbeat_task
        except asyncio.CancelledError:
            pass
    print("✓ Stopped heartbeat events")


app = FastAPI(title="AgentTree Dashboard", lifespan=lifespan)


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Disable caching for HTML responses during development."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable["Response"]]
    ) -> "Response":
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


def stage_display_name(value: str) -> str:
    """Convert a dot-path stage to a human-readable display name."""
    return _config.stage_display_name(value)


templates.env.filters["stage_name"] = stage_display_name

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

    return str(credentials.username)


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
        """Check if tmux session exists for an issue-bound agent.

        Note: Manager is agent 0, so _check_issue_tmux_session("000") checks manager.
        Uses config.get_issue_session_patterns() for consistent naming.
        """
        active = self._get_active_sessions()
        patterns = _config.get_issue_session_patterns(issue_id)
        return any(name in active for name in patterns)


# Global agent manager - will be initialized in startup
agent_manager = AgentManager()


def convert_issue_to_web(issue: issue_crud.Issue, load_dependents: bool = False) -> WebIssue:
    """Convert an issue_crud.Issue to a web Issue model.

    Args:
        issue: The issue to convert
        load_dependents: If True, also load dependent issues (issues blocked by this one)
    """
    # Check if tmux session is active for this issue
    tmux_active = agent_manager._check_issue_tmux_session(issue.id)

    # Convert dependencies to ints
    dependencies = [int(d.lstrip("0") or "0") for d in issue.dependencies]

    # Load dependents if requested (issues blocked by this one)
    dependents: list[int] = []
    if load_dependents:
        dependent_issues = issue_crud.get_dependent_issues(issue.id)
        dependents = [int(d.id) for d in dependent_issues]

    return WebIssue(
        number=int(issue.id),
        title=issue.title,
        body="",  # Loaded separately from problem.md
        labels=issue.labels,
        assignees=[],
        stage=issue.stage,  # Dot path (e.g., "explore.define", "backlog")
        priority=issue.priority.value,
        tmux_active=tmux_active,
        has_worktree=bool(issue.worktree_dir),
        pr_url=issue.pr_url,
        pr_number=issue.pr_number,
        port=_config.get_port_for_issue(issue.id),
        created_at=datetime.fromisoformat(issue.created.replace("Z", "+00:00")),
        updated_at=datetime.fromisoformat(issue.updated.replace("Z", "+00:00")),
        dependencies=dependencies,
        dependents=dependents,
        processing=issue.processing,
        ci_escalated=issue.ci_escalated,
    )


def filter_issues(issues: list[WebIssue], search: Optional[str]) -> list[WebIssue]:
    """Filter issues by search query.

    Matches against issue number, title, and labels (case-insensitive).
    Returns all issues if search is None or empty.
    """
    if not search or not search.strip():
        return issues

    query = search.lower().strip()
    filtered = []
    for issue in issues:
        # Match against number
        if query in str(issue.number):
            filtered.append(issue)
            continue
        # Match against title
        if query in issue.title.lower():
            filtered.append(issue)
            continue
        # Match against labels
        if any(query in label.lower() for label in issue.labels):
            filtered.append(issue)
            continue
    return filtered


def get_kanban_board(search: Optional[str] = None) -> KanbanBoard:
    """Build a kanban board from issues.

    Each column is a dot-path substage (e.g., "explore.define", "implement.code").
    Stages without substages (e.g., "backlog", "accepted") get a single column.

    Args:
        search: Optional search query to filter issues
    """
    dot_paths = _config.get_all_dot_paths()
    stages: dict[str, list[WebIssue]] = {path: [] for path in dot_paths}

    issues = issue_crud.list_issues(sync=False)
    web_issues = [convert_issue_to_web(issue) for issue in issues]

    if search:
        web_issues = filter_issues(web_issues, search)

    for web_issue in web_issues:
        if web_issue.stage in stages:
            stages[web_issue.stage].append(web_issue)
        else:
            logger.warning("Issue #%s has unrecognized stage '%s', showing in backlog",
                        web_issue.number, web_issue.stage)
            if "backlog" in stages:
                stages["backlog"].append(web_issue)

    return KanbanBoard(stages=stages, total_issues=len(web_issues))


@app.get("/")
async def root() -> RedirectResponse:
    """Redirect root to kanban board."""
    return RedirectResponse(url="/kanban", status_code=302)


@app.get("/kanban", response_class=HTMLResponse)
async def kanban(
    request: Request,
    issue: Optional[str] = None,
    chat: Optional[str] = None,
    search: Optional[str] = None,
    view: Optional[str] = None,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Kanban board page."""
    import os
    from agenttree.actions import load_rate_limit_state
    
    agent_manager.clear_session_cache()  # Fresh session data per request
    board = await asyncio.to_thread(get_kanban_board, search)

    # If issue param provided, load issue detail for modal.
    # All disk I/O runs in a thread to keep the event loop free for polling.
    selected_issue = None
    files: list[dict[str, str]] = []
    commits_ahead = 0
    commits_behind = 0
    default_doc: str | None = None
    if issue:
        def _load_issue_detail() -> tuple[WebIssue | None, list[dict[str, str]], str | None, int, int]:
            issue_obj = issue_crud.get_issue(issue, sync=False)
            if not issue_obj:
                return None, [], None, 0, 0
            web_issue = convert_issue_to_web(issue_obj, load_dependents=True)
            issue_files = get_issue_files(issue, include_content=True, current_stage=issue_obj.stage)
            doc = get_default_doc(issue_obj.stage)
            ca, cb = 0, 0
            if web_issue.tmux_active and issue_obj.worktree_dir:
                from agenttree.hooks import get_commits_ahead_behind_main
                ca, cb = get_commits_ahead_behind_main(issue_obj.worktree_dir)
            return web_issue, issue_files, doc, ca, cb

        selected_issue, files, default_doc, commits_ahead, commits_behind = (
            await asyncio.to_thread(_load_issue_detail)
        )

    # Check rate limit status for warning banner
    config = load_config()
    agents_dir = Path("_agenttree")
    rate_limit_state = load_rate_limit_state(agents_dir)
    rate_limit_warning = None
    
    if rate_limit_state and rate_limit_state.get("rate_limited") and not rate_limit_state.get("dismissed"):
        # Parse reset time for display
        reset_time_str = rate_limit_state.get("reset_time", "")
        try:
            reset_time = datetime.fromisoformat(reset_time_str.replace("Z", "+00:00"))
            reset_display = reset_time.strftime("%I:%M %p UTC")
        except (ValueError, TypeError):
            reset_display = "unknown"
        
        rate_limit_warning = {
            "reset_time": reset_display,
            "mode": rate_limit_state.get("mode", "subscription"),
            "agent_count": len(rate_limit_state.get("affected_agents", [])),
            "can_switch": bool(os.environ.get(config.rate_limit_fallback.api_key_env)),
        }

    return templates.TemplateResponse(
        "kanban.html",
        {
            "request": request,
            "board": board,
            "stages": _config.get_all_dot_paths(),
            "parking_lot_stages": [p for p in _config.get_all_dot_paths() if _config.is_parking_lot(p)],
            "human_review_stages": _config.get_human_review_stages(),
            "active_page": "kanban",
            "selected_issue": selected_issue,
            "files": files,
            "default_doc": default_doc,
            "commits_ahead": commits_ahead,
            "commits_behind": commits_behind,
            "chat_open": chat == "1",
            "search": search or "",
            "current_view": view or "nonempty",
            "rate_limit_warning": rate_limit_warning,
        }
    )


# File ordering by workflow stage (problem first, then spec, etc.)
STAGE_FILE_ORDER = [
    "problem.md",
    "research.md",
    "spec.md",
    "spec_review.md",
    "review.md",
    "independent_review.md",
    "feedback.md",
]

# Mapping of filenames to their associated workflow dot path.
# Used to determine if a file's stage has been "passed" relative to the current stage.
FILE_TO_STAGE: dict[str, str] = {
    "problem.md": "explore.define",
    "research.md": "explore.research",
    "spec.md": "plan.draft",
    "spec_review.md": "plan.assess",
    "review.md": "implement.code_review",
    "independent_review.md": "implement.independent_review",
    "feedback.md": "implement.feedback",
}


def get_issue_files(
    issue_id: str,
    include_content: bool = False,
    current_stage: str | None = None,
) -> list[dict[str, str]]:
    """Get list of markdown files for an issue.

    Returns list of dicts with keys: name, display_name, size, modified, stage, is_passed, short_name
    If include_content=True, also includes 'content' key with file contents.

    Files are ordered by workflow stage (problem.md first, then spec.md, etc.),
    with any unknown files at the end sorted alphabetically.
    If config.show_issue_yaml is True, issue.yaml is included at the end.

    Args:
        issue_id: The issue ID to get files for
        include_content: Whether to include file content
        current_stage: Current stage of the issue (for calculating is_passed)
    """
    issue_dir = issue_crud.get_issue_dir(issue_id)
    if not issue_dir:
        return []

    # Build file list
    file_list = list(issue_dir.glob("*.md"))

    # Sort by stage order, then alphabetically for unknown files
    def file_sort_key(f: Path) -> tuple[int, str]:
        if f.name in STAGE_FILE_ORDER:
            return (STAGE_FILE_ORDER.index(f.name), f.name)
        return (len(STAGE_FILE_ORDER), f.name)  # Unknown files sorted after known ones

    # Get current stage index for is_passed calculation using flow ordering.
    dot_paths = _config.get_flow_stage_names()
    current_stage_index = -1
    if current_stage and current_stage in dot_paths:
        current_stage_index = dot_paths.index(current_stage)

    files: list[dict[str, str]] = []
    for f in sorted(file_list, key=file_sort_key):
        display_name = f.stem.replace("_", " ").title()
        file_stage = FILE_TO_STAGE.get(f.name)

        # Calculate is_passed: file's stage is earlier than current stage.
        is_passed = False
        if file_stage and current_stage_index >= 0 and file_stage in dot_paths:
            file_stage_index = dot_paths.index(file_stage)
            is_passed = file_stage_index < current_stage_index

        # Generate short_name for passed stages (first 3 chars + "...")
        short_name = display_name
        if is_passed:
            short_name = display_name[:3] + "..."

        stage_color = (_config.stage_color(file_stage) or "") if file_stage else ""
        file_info: dict[str, str] = {
            "name": f.name,
            "display_name": display_name,
            "size": str(f.stat().st_size),
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            "stage": file_stage or "",
            "stage_color": stage_color,
            "is_passed": str(is_passed).lower(),
            "short_name": short_name,
        }
        if include_content:
            try:
                file_info["content"] = f.read_text()
            except Exception:
                file_info["content"] = ""
        files.append(file_info)

    # Optionally include issue.yaml at the end
    if _config.show_issue_yaml:
        issue_yaml = issue_dir / "issue.yaml"
        if issue_yaml.exists():
            file_info = {
                "name": "issue.yaml",
                "display_name": "Issue YAML",
                "size": str(issue_yaml.stat().st_size),
                "modified": datetime.fromtimestamp(issue_yaml.stat().st_mtime).isoformat(),
                "stage": "",
                "stage_color": "",
                "is_passed": "false",
                "short_name": "Issue YAML",
            }
            if include_content:
                try:
                    file_info["content"] = issue_yaml.read_text()
                except Exception:
                    file_info["content"] = ""
            files.append(file_info)

    return files


def get_default_doc(dot_path: str) -> str | None:
    """Get the default document to show for a dot-path stage.

    Checks review_doc first (for human review stages), then output (the doc
    being produced), so the most relevant file is auto-selected.
    """
    stage_config, sub_config = _config.resolve_stage(dot_path)
    if sub_config and sub_config.review_doc:
        return sub_config.review_doc
    if stage_config and stage_config.review_doc:
        return stage_config.review_doc
    if sub_config and sub_config.output:
        return sub_config.output
    if stage_config and stage_config.output:
        return stage_config.output
    return None


# Maximum diff size in bytes (200KB - show more before truncating)
MAX_DIFF_SIZE = 200 * 1024


def get_issue_diff(issue_id: str) -> dict:
    """Get git diff for an issue's worktree.

    Returns dict with keys: diff, stat, has_changes, error, truncated
    """
    issue = issue_crud.get_issue(issue_id)
    if not issue:
        return {"diff": "", "stat": "", "has_changes": False, "error": "Issue not found", "truncated": False}

    if not issue.worktree_dir:
        return {"diff": "", "stat": "", "has_changes": False, "error": "No worktree for this issue", "truncated": False}

    worktree_path = Path(issue.worktree_dir)
    if not worktree_path.exists():
        return {"diff": "", "stat": "", "has_changes": False, "error": "Worktree not found", "truncated": False}

    try:
        # Get the diff (--no-color for speed, limit context lines)
        diff_result = subprocess.run(
            ["git", "diff", "--no-color", "-U3", "main...HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        diff_output = diff_result.stdout

        # Get the stat summary
        stat_result = subprocess.run(
            ["git", "diff", "--no-color", "--stat", "main...HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        stat_output = stat_result.stdout

        # Check for truncation
        truncated = False
        if len(diff_output) > MAX_DIFF_SIZE:
            diff_output = diff_output[:MAX_DIFF_SIZE]
            truncated = True

        has_changes = bool(diff_output.strip())

        # Count lines added/removed
        additions = 0
        deletions = 0
        files_changed = 0
        for line in diff_output.split('\n'):
            if line.startswith('+') and not line.startswith('+++'):
                additions += 1
            elif line.startswith('-') and not line.startswith('---'):
                deletions += 1
            elif line.startswith('diff --git'):
                files_changed += 1

        # Build PR diff URL if PR exists
        pr_diff_url = None
        if issue.pr_url:
            pr_diff_url = issue.pr_url + "/files"

        return {
            "diff": diff_output,
            "stat": stat_output,
            "has_changes": has_changes,
            "error": None,
            "truncated": truncated,
            "additions": additions,
            "deletions": deletions,
            "files_changed": files_changed,
            "pr_diff_url": pr_diff_url
        }
    except subprocess.TimeoutExpired:
        return {"diff": "", "stat": "", "has_changes": False, "error": "Diff generation timed out", "truncated": False, "pr_diff_url": None}
    except Exception as e:
        return {"diff": "", "stat": "", "has_changes": False, "error": str(e), "truncated": False, "pr_diff_url": None}


def _sort_flow_issues(issues: list[WebIssue], sort_by: Optional[str] = None) -> list[WebIssue]:
    """Sort issues for flow view based on sort parameter.

    Args:
        issues: List of WebIssue objects to sort
        sort_by: Sort method - 'stage' (default), 'updated', 'created', 'number'

    Returns:
        Sorted list of issues
    """
    if sort_by == "updated":
        # Newest updated first
        return sorted(issues, key=lambda x: x.updated_at, reverse=True)
    elif sort_by == "created":
        # Newest created first
        return sorted(issues, key=lambda x: x.created_at, reverse=True)
    elif sort_by == "number":
        # Issue number ascending
        return sorted(issues, key=lambda x: x.number)
    else:
        # Default: stage order with review stages first
        # Use flow dot paths for ordering; unknown stages sort last
        dot_paths = _config.get_flow_stage_names()

        def _stage_sort_key(x: WebIssue) -> tuple[bool, int, int]:
            try:
                idx = dot_paths.index(x.stage)
            except ValueError:
                idx = -1  # Unknown stages sort last (after negation: first in reverse)
            return (not x.is_review, -idx, x.number)

        return sorted(issues, key=_stage_sort_key)


def _filter_flow_issues(issues: list[WebIssue], filter_by: Optional[str] = None) -> list[WebIssue]:
    """Filter issues for flow view based on filter parameter.

    Args:
        issues: List of WebIssue objects to filter
        filter_by: Filter method - 'all' (default), 'review', 'running', 'open'

    Returns:
        Filtered list of issues
    """
    if filter_by == "review":
        # Only review stages
        return [i for i in issues if i.is_review]
    elif filter_by == "running":
        # Only issues with active agents
        return [i for i in issues if i.tmux_active]
    elif filter_by == "open":
        # Hide parking-lot stages (accepted, not_doing, etc.)
        parking_lots = _config.get_parking_lot_stages()
        return [i for i in issues if _config.stage_group_name(i.stage) not in parking_lots]
    else:
        # Default: show all
        return issues


def _get_flow_issues(
    search: str | None = None,
    sort: str | None = None,
    filter_by: str | None = None
) -> list[WebIssue]:
    """Sync helper that loads and converts issues for flow/mobile views.

    This function is called via asyncio.to_thread() to avoid blocking the event loop
    during subprocess calls in convert_issue_to_web().
    """
    agent_manager.clear_session_cache()  # Fresh session data per request
    issues = issue_crud.list_issues(sync=False)
    web_issues = [convert_issue_to_web(i) for i in issues]
    web_issues = _filter_flow_issues(web_issues, filter_by)
    web_issues = _sort_flow_issues(web_issues, sort)
    if search:
        web_issues = filter_issues(web_issues, search)
    return web_issues


@app.get("/flow", response_class=HTMLResponse)
async def flow(
    request: Request,
    issue: Optional[str] = None,
    chat: Optional[str] = None,
    search: Optional[str] = None,
    sort: Optional[str] = None,
    filter: Optional[str] = None,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Flow view page."""
    # Load and convert issues in thread pool to avoid blocking event loop
    web_issues = await asyncio.to_thread(_get_flow_issues, search, sort, filter)

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
    commits_ahead = 0
    commits_behind = 0
    default_doc: str | None = None
    if selected_issue and selected_issue_id:
        issue_obj = issue_crud.get_issue(selected_issue_id, sync=False)
        if issue_obj:
            # Load all file contents upfront for CSS toggle tabs
            files = get_issue_files(selected_issue_id, include_content=True, current_stage=issue_obj.stage)
            # Get default doc to show for this stage
            default_doc = get_default_doc(issue_obj.stage)
            # Get commits ahead/behind for rebase button
            if selected_issue.tmux_active and issue_obj.worktree_dir:
                from agenttree.hooks import get_commits_ahead_behind_main
                commits_ahead, commits_behind = await asyncio.to_thread(
                    get_commits_ahead_behind_main, issue_obj.worktree_dir
                )

    return templates.TemplateResponse(
        "flow.html",
        {
            "request": request,
            "issues": web_issues,
            "selected_issue": selected_issue,
            "issue": selected_issue,  # issue_detail.html expects 'issue'
            "files": files,
            "default_doc": default_doc,
            "commits_ahead": commits_ahead,
            "commits_behind": commits_behind,
            "active_page": "flow",
            "chat_open": chat == "1",
            "search": search or "",
            "current_sort": sort or "stage",
            "current_filter": filter or "all",
        }
    )


@app.get("/mobile", response_class=HTMLResponse)
async def mobile(
    request: Request,
    issue: str | None = None,
    tab: str | None = None,
    user: str | None = Depends(get_current_user)
) -> HTMLResponse:
    """Mobile-optimized view with bottom tab navigation."""
    # Load and convert issues in thread pool to avoid blocking event loop
    web_issues = await asyncio.to_thread(_get_flow_issues)

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
    commits_ahead = 0
    commits_behind = 0
    default_doc: str | None = None
    if selected_issue and selected_issue_id:
        issue_obj = issue_crud.get_issue(selected_issue_id, sync=False)
        if issue_obj:
            files = get_issue_files(selected_issue_id, include_content=True, current_stage=issue_obj.stage)
            default_doc = get_default_doc(issue_obj.stage)
            if selected_issue.tmux_active and issue_obj.worktree_dir:
                from agenttree.hooks import get_commits_ahead_behind_main
                commits_ahead, commits_behind = await asyncio.to_thread(
                    get_commits_ahead_behind_main, issue_obj.worktree_dir
                )

    # Determine active tab: default to 'issues' if no issue, 'detail' if issue specified
    active_tab = tab if tab in ["issues", "detail", "chat"] else None
    if not active_tab:
        active_tab = "detail" if selected_issue else "issues"

    return templates.TemplateResponse(
        "mobile.html",
        {
            "request": request,
            "issues": web_issues,
            "selected_issue": selected_issue,
            "issue": selected_issue,
            "files": files,
            "default_doc": default_doc,
            "commits_ahead": commits_ahead,
            "commits_behind": commits_behind,
            "active_page": "mobile",
            "active_tab": active_tab,
        }
    )


def _capture_tmux_output(session_names: list[str]) -> tuple[str | None, str | None]:
    """Sync helper that captures tmux output from session.

    This function is called via asyncio.to_thread() to avoid blocking the event loop
    during subprocess calls.

    Returns:
        Tuple of (output, session_name) or (None, None) if no session found.
    """
    for name in session_names:
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", name, "-p", "-S", "-100"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                return result.stdout, name
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
    return None, None


@app.get("/agent/{agent_num}/tmux", response_class=HTMLResponse)
async def agent_tmux(
    request: Request,
    agent_num: str,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Get tmux output for an issue's agent (HTMX endpoint).

    Note: agent_num parameter is actually the issue number - sessions are named by issue.
    """
    from agenttree.tmux import is_claude_running

    config = load_config()
    # Pad issue number to 3 digits to match tmux session naming
    padded_num = agent_num.zfill(3)
    # Use config for consistent session naming
    session_names = config.get_issue_session_patterns(padded_num)

    # Capture tmux output in thread pool to avoid blocking event loop
    raw_output, session_name = await asyncio.to_thread(_capture_tmux_output, session_names)

    if raw_output and session_name:
        # Strip Claude Code's input prompt separator from the output
        output = _strip_claude_input_prompt(raw_output)
        # Check if Claude is actually running (not just tmux session)
        is_running = await asyncio.to_thread(is_claude_running, session_name)
        claude_status = "running" if is_running else "exited"
    else:
        output = "Tmux session not active"
        claude_status = "no_session"

    return templates.TemplateResponse(
        "partials/tmux_output.html",
        {
            "request": request,
            "agent_num": agent_num,
            "output": output,
            "claude_status": claude_status,
        }
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
    import logging
    from datetime import datetime
    from agenttree.tmux import send_message

    # Log all messages sent via web UI for debugging mystery messages
    logger = logging.getLogger("agenttree.web")
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")[:100]
    logger.info(
        f"[SEND] issue={agent_num} msg={message!r} "
        f"ip={client_ip} ua={user_agent} time={datetime.now().isoformat()}"
    )

    config = load_config()
    # Pad issue number to 3 digits to match tmux session naming
    padded_num = agent_num.zfill(3)

    # Find the active session using config patterns
    from agenttree.tmux import session_exists
    session_patterns = config.get_issue_session_patterns(padded_num)
    session_name = next((n for n in session_patterns if session_exists(n)), session_patterns[0])

    # Send message - result will appear in tmux output on next poll
    result = send_message(session_name, message)

    # Log if Claude isn't running
    if result == "claude_exited":
        logger.warning(f"[SEND] Claude exited for issue={agent_num}, message went to shell")

    return HTMLResponse("")


# Manager routes removed - manager is now agent 0
# Use /agent/0/tmux, /agent/0/send, /api/issues/0/agent-status instead


@app.post("/api/issues/{issue_id}/start")
async def start_issue(
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Start an agent to work on an issue."""
    import asyncio
    from agenttree.api import start_agent, IssueNotFoundError, AgentStartError

    try:
        # Use force=True to restart stalled agents (tmux dead but state exists)
        await asyncio.to_thread(start_agent, issue_id, force=True, quiet=True)
        return {"ok": True, "status": f"Started agent for issue #{issue_id}"}
    except IssueNotFoundError:
        raise HTTPException(status_code=404, detail=f"Issue #{issue_id} not found")
    except AgentStartError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/issues/{issue_id}/stop")
async def stop_issue(
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Stop an agent working on an issue (kills tmux, stops container, cleans up state)."""
    import asyncio
    from agenttree.api import stop_all_agents_for_issue

    try:
        padded_id = issue_id.zfill(3)
        # Run in thread to avoid blocking event loop
        count = await asyncio.to_thread(stop_all_agents_for_issue, padded_id, quiet=True)
        if count > 0:
            return {"ok": True, "status": f"Stopped {count} agent(s) for issue #{issue_id}"}
        else:
            return {"ok": True, "status": f"No active agents for issue #{issue_id}"}
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
    # Check tmux session in thread pool to avoid blocking event loop
    tmux_active = await asyncio.to_thread(agent_manager._check_issue_tmux_session, padded_id)

    # Get processing state from issue
    issue = issue_crud.get_issue(padded_id, sync=False)
    processing = issue.processing if issue else None

    return {
        "tmux_active": tmux_active,
        "status": "running" if tmux_active else "off",
        "processing": processing,
    }


@app.get("/api/issues/{issue_id}/diff")
async def get_diff(
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Get git diff for an issue's worktree.

    Returns the raw diff output for rendering with diff2html on the client.
    """
    issue_id = issue_id.zfill(3)

    # Check issue exists
    issue = issue_crud.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Get diff in thread pool to avoid blocking event loop
    return await asyncio.to_thread(get_issue_diff, issue_id)


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
    # Only allow moving TO parking-lot stages (safe operations)
    parking_lots = _config.get_parking_lot_stages()
    if move_request.stage not in parking_lots:
        raise HTTPException(
            status_code=400,
            detail=f"Direct stage changes only allowed to: {', '.join(sorted(parking_lots))}. Use approve for workflow transitions."
        )

    # Get issue first to pass to cleanup
    issue = issue_crud.get_issue(issue_id, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    updated_issue = issue_crud.update_issue_stage(
        issue_id=issue_id,
        stage=move_request.stage,
    )

    if not updated_issue:
        raise HTTPException(status_code=500, detail=f"Failed to update issue {issue_id}")

    # Clean up agent when moving to parking-lot stages
    # backlog = pause work (stop agent, keep worktree for later)
    # not_doing = abandon work (stop agent, worktree can be cleaned up)
    if _config.is_parking_lot(move_request.stage):
        import asyncio
        from agenttree.hooks import cleanup_issue_agent
        # Run cleanup in thread to avoid blocking event loop
        await asyncio.to_thread(cleanup_issue_agent, updated_issue)

    return {"success": True, "stage": move_request.stage}


@app.post("/api/issues/{issue_id}/approve")
async def approve_issue(
    issue_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Approve an issue at a human review stage.

    Uses api.transition_issue() for consistent exit hooks -> stage update -> enter hooks.
    Only works from human review stages.
    """
    import asyncio
    from agenttree.config import load_config
    from agenttree.hooks import ValidationError, StageRedirect

    # Get issue
    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = issue_crud.get_issue(issue_id_normalized, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Load config from repo path (Path.cwd() can be wrong in uvicorn workers)
    config_path = Path(os.environ["AGENTTREE_REPO_PATH"]) if os.environ.get("AGENTTREE_REPO_PATH") else None
    config = load_config(config_path)

    # Check if at human review stage
    if not config.is_human_review(issue.stage):
        raise HTTPException(status_code=400, detail="Not at review stage")

    next_stage, _ = config.get_next_stage(issue.stage, issue.flow)

    try:
        # Set processing state
        issue_crud.set_processing(issue_id_normalized, "exit")

        # Use consolidated transition_issue() — handles exit hooks, stage update, enter hooks
        from agenttree.api import transition_issue
        try:
            updated = await asyncio.to_thread(
                transition_issue,
                issue_id_normalized,
                next_stage,
                skip_pr_approval=config.allow_self_approval,
                trigger="web",
            )
        except StageRedirect as redirect:
            # Redirect — retry with new target
            updated = await asyncio.to_thread(
                transition_issue,
                issue_id_normalized,
                redirect.target,
                skip_pr_approval=config.allow_self_approval,
                trigger="web",
            )
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Notify agent to continue (if active)
        try:
            from agenttree.state import get_active_agent
            from agenttree.tmux import send_message, session_exists

            agent = get_active_agent(issue_id_normalized)
            if agent and agent.tmux_session:
                if session_exists(agent.tmux_session):
                    message = "Your work was approved! Run `agenttree next` for instructions."
                    await asyncio.to_thread(send_message, agent.tmux_session, message)
        except Exception as e:
            logger.warning("Agent notification failed for issue %s: %s", issue_id_normalized, e)

        return {"ok": True}
    except HTTPException:
        raise  # Let FastAPI handle these with proper status codes
    except Exception as e:
        logger.exception(f"Error approving issue #{issue_id_normalized}")
        raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}: {e}")
    finally:
        # Always clear processing state
        issue_crud.set_processing(issue_id_normalized, None)


@app.post("/api/issues")
async def create_issue_api(
    request: Request,
    description: str = Form(""),
    title: str = Form(""),
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Create a new issue via the web UI.

    Creates a new issue with the default starting stage.
    If no title is provided, one is auto-generated from the description.
    """
    from agenttree.issues import Priority

    description = description.strip()
    title = title.strip()

    # Require at least a description
    if not description:
        raise HTTPException(status_code=400, detail="Please provide a description")

    # Use placeholder if no title - agent will fill it in during define stage
    if not title:
        title = "(untitled)"

    import asyncio
    from agenttree.api import start_agent

    try:
        issue = issue_crud.create_issue(
            title=title,
            priority=Priority.MEDIUM,
            problem=description,
        )

        # Auto-start agent for the new issue
        try:
            await asyncio.to_thread(start_agent, issue.id, quiet=True)
        except Exception as e:
            # Log but don't fail - issue was created, agent start is optional
            print(f"Warning: Could not auto-start agent for issue #{issue.id}: {e}")

        return {"ok": True, "issue_id": issue.id, "title": issue.title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/issues/{issue_id}/dependencies/{dep_id}")
async def remove_dependency(
    issue_id: str,
    dep_id: str,
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Remove a dependency from an issue."""
    from agenttree.issues import remove_dependency as remove_dep

    issue_id_normalized = issue_id.lstrip("0") or "0"
    dep_id_normalized = dep_id.lstrip("0") or "0"

    try:
        issue = remove_dep(issue_id_normalized, dep_id_normalized)
        if not issue:
            raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")
        return {"ok": True, "issue_id": issue.id, "dependencies": issue.dependencies}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/issues/{issue_id}/priority")
async def update_issue_priority(
    issue_id: str,
    request: PriorityUpdateRequest,
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Update an issue's priority."""
    from agenttree.issues import update_issue_priority as do_update_priority, Priority

    # Validate priority value
    valid_priorities = [p.value for p in Priority]
    if request.priority not in valid_priorities:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority '{request.priority}'. Must be one of: {', '.join(valid_priorities)}"
        )

    # Get and update issue
    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = issue_crud.get_issue(issue_id_normalized, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    updated = do_update_priority(issue.id, Priority(request.priority))
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update priority")

    return {"ok": True, "priority": request.priority}


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

    # Notify the agent if there's an active tmux session
    from agenttree.tmux import send_message, session_exists

    config = load_config()
    padded_id = issue_id.zfill(3)
    
    # Find active session using config patterns
    session_name = None
    for pattern in config.get_issue_session_patterns(padded_id):
        if session_exists(pattern):
            session_name = pattern
            break

    if session_name:
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
                    ["tmux", "capture-pane", "-t", f"agent-{agent_num}", "-p", "-S", "-100"],
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


# =============================================================================
# Rate Limit Endpoints
# =============================================================================


@app.get("/api/rate-limit-status")
async def get_rate_limit_status(
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Get current rate limit status.
    
    Returns:
        {
            "rate_limited": bool,
            "reset_time": str | None (ISO timestamp),
            "mode": "subscription" | "api_key",
            "affected_agents": list[{issue_id, session_name}],
            "can_switch_to_api": bool (True if ANTHROPIC_API_KEY is set)
        }
    """
    import os
    from agenttree.actions import load_rate_limit_state
    
    config = load_config()
    agents_dir = Path("_agenttree")
    
    state = load_rate_limit_state(agents_dir)
    
    # Check if API key is available for switching
    api_key_available = bool(os.environ.get(config.rate_limit_fallback.api_key_env))
    
    if not state:
        return {
            "rate_limited": False,
            "reset_time": None,
            "mode": "subscription",
            "affected_agents": [],
            "can_switch_to_api": api_key_available,
        }
    
    return {
        "rate_limited": state.get("rate_limited", False),
        "reset_time": state.get("reset_time"),
        "mode": state.get("mode", "subscription"),
        "affected_agents": state.get("affected_agents", []),
        "can_switch_to_api": api_key_available,
    }


@app.post("/api/rate-limit/switch-to-api")
async def switch_to_api_key_mode(
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Switch all rate-limited agents to API key mode.
    
    This is a manual trigger - user clicks button in UI when they want to
    start paying API costs to unblock their agents.
    """
    import os
    from agenttree.actions import load_rate_limit_state, save_rate_limit_state
    
    config = load_config()
    agents_dir = Path("_agenttree")
    
    # Check if API key is available
    api_key = os.environ.get(config.rate_limit_fallback.api_key_env)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"API key not configured. Set {config.rate_limit_fallback.api_key_env} environment variable."
        )
    
    # Load current state
    state = load_rate_limit_state(agents_dir)
    if not state or not state.get("rate_limited"):
        raise HTTPException(
            status_code=400,
            detail="No rate limit currently detected"
        )
    
    if state.get("mode") == "api_key":
        raise HTTPException(
            status_code=400,
            detail="Already running in API key mode"
        )
    
    # Restart all affected agents with --api-key flag
    affected_agents = state.get("affected_agents", [])
    restarted = 0
    failed = []
    
    for agent_info in affected_agents:
        issue_id = agent_info.get("issue_id")
        if not issue_id:
            continue
        
        result = subprocess.run(
            ["agenttree", "start", str(issue_id), "--api-key", "--skip-preflight", "--force"],
            capture_output=True,
            text=True,
            timeout=120,  # Container startup can be slow
        )
        if result.returncode == 0:
            restarted += 1
        else:
            failed.append({"issue_id": issue_id, "error": result.stderr[:200]})
    
    # Update state to reflect API key mode
    state["mode"] = "api_key"
    state["switched_at"] = datetime.now(timezone.utc).isoformat()
    save_rate_limit_state(agents_dir, state)
    
    return {
        "ok": True,
        "restarted": restarted,
        "failed": failed,
        "message": f"Switched {restarted} agent(s) to API key mode",
    }


@app.post("/api/rate-limit/dismiss")
async def dismiss_rate_limit(
    user: Optional[str] = Depends(get_current_user)
) -> dict:
    """Dismiss the rate limit warning without switching modes.

    Agents remain blocked but the UI warning is dismissed.
    The auto-recovery will still trigger after reset time.
    """
    from agenttree.actions import load_rate_limit_state, save_rate_limit_state

    agents_dir = Path("_agenttree")
    state = load_rate_limit_state(agents_dir)

    if state:
        state["dismissed"] = True
        save_rate_limit_state(agents_dir, state)

    return {"ok": True}


# =============================================================================
# Settings Page
# =============================================================================

# Simple settings that can be modified via the web UI
# These are basic config values, not complex structures like stages/flows/hooks
SIMPLE_SETTINGS: dict[str, dict[str, str]] = {
    "default_model": {"type": "select", "label": "Default Model", "description": "Model for new agents"},
    "default_tool": {"type": "select", "label": "Default Tool", "description": "AI tool for new agents"},
    "show_issue_yaml": {"type": "bool", "label": "Show issue.yaml", "description": "Display issue.yaml in file tabs"},
    "save_tmux_history": {"type": "bool", "label": "Save Tmux History", "description": "Save terminal history on stage transitions"},
    "allow_self_approval": {"type": "bool", "label": "Allow Self Approval", "description": "Skip PR approval check (solo projects)"},
    "refresh_interval": {"type": "int", "label": "Refresh Interval", "description": "Seconds between UI refreshes"},
}


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    saved: Optional[str] = None,
    user: Optional[str] = Depends(get_current_user)
) -> HTMLResponse:
    """Settings page - display current config values."""
    config = load_config()

    # Get current values for simple settings
    settings_values = {}
    for key in SIMPLE_SETTINGS:
        settings_values[key] = getattr(config, key, None)

    # Get available options for select fields
    options = {
        "default_tool": list(config.tools.keys()) if config.tools else ["claude"],
        "default_model": ["opus", "sonnet", "haiku"],
    }

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "active_page": "settings",
            "settings": SIMPLE_SETTINGS,
            "values": settings_values,
            "options": options,
            "saved": saved == "1",
        }
    )


@app.post("/settings", response_class=HTMLResponse)
async def save_settings(
    request: Request,
    user: Optional[str] = Depends(get_current_user)
) -> Response:
    """Save settings - update .agenttree.yaml with new values."""
    form_data = await request.form()
    config = load_config()

    # Find config file
    config_path = Path.cwd() / ".agenttree.yaml"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Config file not found")

    # Read current config
    with open(config_path) as f:
        config_data = yaml.safe_load(f) or {}

    # Build allowed options for select validation
    allowed_options: dict[str, list[str]] = {
        "default_tool": list(config.tools.keys()) if config.tools else ["claude"],
        "default_model": ["opus", "sonnet", "haiku"],
    }

    # Update only allowed settings
    for key, meta in SIMPLE_SETTINGS.items():
        if key in form_data:
            value = str(form_data[key])
            if meta["type"] == "bool":
                config_data[key] = True
            elif meta["type"] == "int":
                try:
                    config_data[key] = int(value)
                except (ValueError, TypeError):
                    raise HTTPException(
                        status_code=422,
                        detail=f"Invalid integer value for {meta['label']}: {value!r}"
                    )
            elif meta["type"] == "select":
                if key in allowed_options and value not in allowed_options[key]:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Invalid option for {meta['label']}: {value!r}"
                    )
                config_data[key] = value
            else:
                config_data[key] = value
        elif meta["type"] == "bool":
            config_data[key] = False

    # Write back atomically (write to temp file, then rename)
    temp_path = config_path.with_suffix(".yaml.tmp")
    try:
        with open(temp_path, "w") as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
        temp_path.rename(config_path)
    except Exception:
        # Clean up temp file on failure
        temp_path.unlink(missing_ok=True)
        raise

    # Redirect back to settings page with success message
    return RedirectResponse(url="/settings?saved=1", status_code=303)


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
        # Set env so uvicorn workers (which may have different cwd) can find config
        os.environ["AGENTTREE_REPO_PATH"] = str(repo_path)
        worktree_manager = WorktreeManager(repo_path, config)
        agent_manager = AgentManager(worktree_manager)
        print(f"✓ Loaded config for project: {config.project}")
    except Exception as e:
        print(f"⚠ Could not load config: {e}")
        print("  Run 'agenttree init' to create a config file")

    import uvicorn
    # Single worker — the heartbeat (sync, manager hooks, stall detection) must run
    # in exactly one process. Multiple workers cause 4x duplicate operations and race
    # conditions on YAML files. One async worker handles the dashboard just fine.
    uvicorn.run("agenttree.web.app:app", host=host, port=port, workers=1, loop="asyncio")


if __name__ == "__main__":
    run_server()

"""Page routes for the web application."""

import asyncio
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from agenttree import issues as issue_crud
from agenttree.actions import load_rate_limit_state
from agenttree.config import load_config
from agenttree.web.agent_manager import agent_manager
from agenttree.web.deps import BASE_DIR, get_current_user, templates
from agenttree.web.utils import (
    _get_flow_issues,
    convert_issue_to_web,
    get_default_doc,
    get_issue_files,
    get_kanban_board,
)

router = APIRouter()

# Load config at module level
_config = load_config()


# Favicon routes
@router.get("/favicon.ico")
async def favicon() -> FileResponse:
    """Serve favicon."""
    return FileResponse(BASE_DIR / "static" / "favicon.svg", media_type="image/svg+xml")


@router.get("/apple-touch-icon.png")
@router.get("/apple-touch-icon-precomposed.png")
@router.get("/apple-touch-icon-120x120.png")
@router.get("/apple-touch-icon-120x120-precomposed.png")
async def apple_touch_icon() -> RedirectResponse:
    """Redirect apple touch icon requests to favicon."""
    return RedirectResponse(url="/favicon.ico")


@router.get("/")
async def root() -> RedirectResponse:
    """Redirect root to kanban board."""
    return RedirectResponse(url="/kanban", status_code=302)


@router.get("/kanban", response_class=HTMLResponse)
async def kanban(
    request: Request,
    issue: str | None = None,
    chat: str | None = None,
    search: str | None = None,
    view: str | None = None,
    user: str | None = Depends(get_current_user),
) -> HTMLResponse:
    """Kanban board page."""
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

        def _load_issue_detail() -> (
            tuple[object | None, list[dict[str, str]], str | None, int, int]
        ):
            issue_obj = issue_crud.get_issue(issue, sync=False)
            if not issue_obj:
                return None, [], None, 0, 0
            web_issue = convert_issue_to_web(issue_obj, load_dependents=True)
            issue_files = get_issue_files(
                issue, include_content=True, current_stage=issue_obj.stage
            )
            doc = get_default_doc(issue_obj.stage, ci_escalated=issue_obj.ci_escalated)
            ca, cb = 0, 0
            if web_issue.tmux_active and issue_obj.worktree_dir:
                from agenttree.hooks import get_commits_ahead_behind_main

                ca, cb = get_commits_ahead_behind_main(issue_obj.worktree_dir)
            return web_issue, issue_files, doc, ca, cb

        selected_issue, files, default_doc, commits_ahead, commits_behind = (
            await asyncio.to_thread(_load_issue_detail)
        )

    # Check rate limit status for warning banner
    agents_dir = Path("_agenttree")
    rate_limit_state = load_rate_limit_state(agents_dir)
    rate_limit_warning = None

    if (
        rate_limit_state
        and rate_limit_state.get("rate_limited")
        and not rate_limit_state.get("dismissed")
    ):
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
            "can_switch": bool(os.environ.get(_config.rate_limit_fallback.api_key_env)),
        }

    return templates.TemplateResponse(
        "kanban.html",
        {
            "request": request,
            "board": board,
            "stages": _config.get_all_dot_paths(),
            "parking_lot_stages": [
                p for p in _config.get_all_dot_paths() if _config.is_parking_lot(p)
            ],
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
        },
    )


@router.get("/kanban/board", response_class=HTMLResponse)
async def kanban_board(
    request: Request,
    search: str | None = None,
    user: str | None = Depends(get_current_user),
) -> HTMLResponse:
    """Kanban board partial - returns just the columns for htmx polling refresh."""
    agent_manager.clear_session_cache()  # Fresh session data per request
    board = await asyncio.to_thread(get_kanban_board, search)

    return templates.TemplateResponse(
        "partials/kanban_board.html",
        {
            "request": request,
            "board": board,
            "stages": _config.get_all_dot_paths(),
        },
    )


@router.get("/flow", response_class=HTMLResponse)
async def flow(
    request: Request,
    issue: str | None = None,
    chat: str | None = None,
    search: str | None = None,
    sort: str | None = None,
    filter: str | None = None,
    user: str | None = Depends(get_current_user),
) -> HTMLResponse:
    """Flow view page."""
    # Load and convert issues in thread pool to avoid blocking event loop
    web_issues = await asyncio.to_thread(_get_flow_issues, search, sort, filter)

    # Select issue from URL param or default to first
    from agenttree.ids import parse_issue_id

    selected_issue = None
    selected_issue_id: int | None = None
    if issue:
        try:
            target_id = parse_issue_id(issue)
            for wi in web_issues:
                if wi.number == target_id:
                    selected_issue_id = wi.number
                    break
        except ValueError:
            pass
    if selected_issue_id is None and web_issues:
        selected_issue_id = web_issues[0].number

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
            files = get_issue_files(
                selected_issue_id, include_content=True, current_stage=issue_obj.stage
            )
            # Get default doc to show for this stage
            default_doc = get_default_doc(
                issue_obj.stage, ci_escalated=issue_obj.ci_escalated
            )
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
        },
    )


@router.get("/mobile", response_class=HTMLResponse)
async def mobile(
    request: Request,
    issue: str | None = None,
    tab: str | None = None,
    user: str | None = Depends(get_current_user),
) -> HTMLResponse:
    """Mobile-optimized view with bottom tab navigation."""
    # Load and convert issues in thread pool to avoid blocking event loop
    web_issues = await asyncio.to_thread(_get_flow_issues)

    # Select issue from URL param or default to first
    from agenttree.ids import parse_issue_id

    selected_issue = None
    selected_issue_id: int | None = None
    if issue:
        try:
            target_id = parse_issue_id(issue)
            for wi in web_issues:
                if wi.number == target_id:
                    selected_issue_id = wi.number
                    break
        except ValueError:
            pass
    if selected_issue_id is None and web_issues:
        selected_issue_id = web_issues[0].number

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
            files = get_issue_files(
                selected_issue_id, include_content=True, current_stage=issue_obj.stage
            )
            default_doc = get_default_doc(
                issue_obj.stage, ci_escalated=issue_obj.ci_escalated
            )
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
        },
    )


@router.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "healthy", "service": "agenttree-web"}

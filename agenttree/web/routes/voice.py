"""Voice chat routes using OpenAI Realtime API."""

import asyncio
import logging
import os
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from agenttree.web.deps import get_current_user, templates

router = APIRouter(tags=["voice"])
logger = logging.getLogger("agenttree.web")


@router.get("/voice", response_class=HTMLResponse)
async def voice_page(
    request: Request,
    user: str | None = Depends(get_current_user),
) -> HTMLResponse:
    """Voice chat page — standalone version (also embedded in mobile)."""
    has_openai_key = bool(os.environ.get("OPENAI_API_KEY"))
    return templates.TemplateResponse(
        "voice.html",
        {
            "request": request,
            "has_openai_key": has_openai_key,
        },
    )


@router.get("/api/voice/token")
async def voice_token(
    issue: int | None = None,
    user: str | None = Depends(get_current_user),
) -> dict:
    """Create an ephemeral OpenAI Realtime API token.

    The browser uses this to connect directly to OpenAI via WebRTC.
    Our API key stays server-side.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not configured")

    # Build context-aware instructions
    instructions = (
        "You are a concise voice assistant for AgentTree, a multi-agent AI development framework. "
        "The user manages AI coding agents that work on issues. Keep responses SHORT and conversational — "
        "the user is likely on their phone, maybe walking. Summarize data, don't dump it raw. "
        "Use the provided tools to check status, manage agents, and handle issues. "
        "When the user says 'approve' without specifying an issue, check status first to find review items."
    )

    if issue:
        # Add context about the issue the user is currently viewing
        from agenttree.mcp_server import get_issue as mcp_get_issue

        issue_detail = await asyncio.to_thread(mcp_get_issue, issue)
        instructions += f"\n\nThe user is currently viewing this issue:\n{issue_detail}"

    # Define tools for the Realtime session
    tools = [
        {
            "type": "function",
            "name": "status",
            "description": "Get status of all issues and agents. Call this when user asks what's happening, how things are going, etc.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        {
            "type": "function",
            "name": "get_issue",
            "description": "Get details about a specific issue by number",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "integer", "description": "Issue number"}
                },
                "required": ["issue_id"],
            },
        },
        {
            "type": "function",
            "name": "get_agent_output",
            "description": "See what an agent is currently doing — its recent terminal output",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "integer", "description": "Issue number"}
                },
                "required": ["issue_id"],
            },
        },
        {
            "type": "function",
            "name": "send_message",
            "description": "Send a message/instruction to an agent working on an issue",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "integer", "description": "Issue number"},
                    "message": {
                        "type": "string",
                        "description": "Message to send to the agent",
                    },
                },
                "required": ["issue_id", "message"],
            },
        },
        {
            "type": "function",
            "name": "create_issue",
            "description": "Create a new issue and start an agent on it",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short title (10+ chars)"},
                    "description": {
                        "type": "string",
                        "description": "What needs to be done (50+ chars)",
                    },
                },
                "required": ["title", "description"],
            },
        },
        {
            "type": "function",
            "name": "approve",
            "description": "Approve an issue that's waiting for human review",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "integer", "description": "Issue number"}
                },
                "required": ["issue_id"],
            },
        },
        {
            "type": "function",
            "name": "start_agent",
            "description": "Start or restart an agent for an issue",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "integer", "description": "Issue number"}
                },
                "required": ["issue_id"],
            },
        },
        {
            "type": "function",
            "name": "stop_agent",
            "description": "Stop an agent that's working on an issue",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "integer", "description": "Issue number"}
                },
                "required": ["issue_id"],
            },
        },
    ]

    # OpenAI Realtime API GA endpoints (released Dec 2025):
    #   Token: POST /v1/realtime/client_secrets
    #   WebRTC SDP: POST /v1/realtime/calls?model=gpt-realtime
    # These replaced the beta /v1/realtime/sessions endpoint.
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "session": {
                    "type": "realtime",
                    "model": "gpt-realtime",
                    "audio": {"output": {"voice": "ash"}},
                    "instructions": instructions,
                    "tools": tools,
                    "tool_choice": "auto",
                }
            },
        )
        if resp.status_code != 200:
            logger.error("OpenAI token error: %s %s", resp.status_code, resp.text)
            raise HTTPException(status_code=502, detail="Failed to create voice session")
        return dict(resp.json())


@router.post("/api/voice/tool-call")
async def voice_tool_call(
    request: Request,
    user: str | None = Depends(get_current_user),
) -> dict:
    """Execute an agenttree tool call from the Realtime API.

    The browser receives function_call events from OpenAI, POSTs them
    here, and we return the result to send back via the data channel.
    """
    from agenttree.mcp_server import (
        approve as mcp_approve,
        create_issue as mcp_create,
        get_agent_output as mcp_output,
        get_issue as mcp_get_issue,
        send_message as mcp_send,
        start_agent as mcp_start,
        status as mcp_status,
        stop_agent as mcp_stop,
    )

    body = await request.json()
    fn_name = str(body.get("name", ""))
    fn_args = dict(body.get("arguments", {}))

    def _run_tool(name: str, args: dict[str, object]) -> str:
        tools: dict[str, Callable[[dict[str, object]], object]] = {
            "status": lambda a: mcp_status(),
            "get_issue": lambda a: mcp_get_issue(a["issue_id"]),
            "get_agent_output": lambda a: mcp_output(a["issue_id"]),
            "send_message": lambda a: mcp_send(a["issue_id"], a["message"]),
            "create_issue": lambda a: mcp_create(a["title"], a["description"]),
            "approve": lambda a: mcp_approve(a["issue_id"]),
            "start_agent": lambda a: mcp_start(a["issue_id"]),
            "stop_agent": lambda a: mcp_stop(a["issue_id"]),
        }
        fn = tools.get(name)
        if not fn:
            return f"Unknown tool: {name}"
        return str(fn(args))

    result = await asyncio.to_thread(_run_tool, fn_name, fn_args)
    return {"result": result}

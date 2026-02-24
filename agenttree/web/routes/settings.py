"""Settings page routes."""

from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from agenttree.config import load_config
from agenttree.web.deps import get_current_user, templates

router = APIRouter(tags=["settings"])

# Simple settings that can be modified via the web UI
# These are basic config values, not complex structures like stages/flows/hooks
SIMPLE_SETTINGS: dict[str, dict[str, str]] = {
    "default_model": {
        "type": "select",
        "label": "Default Model",
        "description": "Model for new agents",
    },
    "default_tool": {
        "type": "select",
        "label": "Default Tool",
        "description": "AI tool for new agents",
    },
    "show_issue_yaml": {
        "type": "bool",
        "label": "Show issue.yaml",
        "description": "Display issue.yaml in file tabs",
    },
    "save_tmux_history": {
        "type": "bool",
        "label": "Save Tmux History",
        "description": "Save terminal history on stage transitions",
    },
    "allow_self_approval": {
        "type": "bool",
        "label": "Allow Self Approval",
        "description": "Skip PR approval check (solo projects)",
    },
    "refresh_interval": {
        "type": "int",
        "label": "Refresh Interval",
        "description": "Seconds between UI refreshes",
    },
}


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    saved: str | None = None,
    user: str | None = Depends(get_current_user),
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
        },
    )


@router.post("/settings", response_class=HTMLResponse)
async def save_settings(
    request: Request,
    user: str | None = Depends(get_current_user),
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
                        detail=f"Invalid integer value for {meta['label']}: {value!r}",
                    )
            elif meta["type"] == "select":
                if key in allowed_options and value not in allowed_options[key]:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Invalid option for {meta['label']}: {value!r}",
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

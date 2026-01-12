# AgentTree - Claude Instructions

## Quick Start

If you have a task file in `tasks/`, read the oldest one first and start working on it.

## Documentation Structure

**All documentation goes in `agents/` repository, NOT in the main codebase.**

| Type | Location |
|------|----------|
| Plans & Proposals | `agents/plans/` |
| Feature Specs | `agents/specs/` |
| RFCs & Decisions | `agents/rfcs/` |
| Gotchas & Patterns | `agents/knowledge/` |
| Task Logs | `agents/tasks/` |

See `agents/AGENTS.md` for full conventions.

## Task Workflow

1. Check `tasks/` directory for pending work
2. Work on the **oldest** task first (by filename date)
3. When complete, task moves to `tasks/archive/`
4. Run `./scripts/submit.sh` to create PR

## Container Security

All agents run in containers. There is no non-container mode.

## Testing

Use browser MCP tools to test web features:
```
mcp_cursor-ide-browser_browser_navigate
mcp_cursor-ide-browser_browser_snapshot
mcp_cursor-ide-browser_browser_click
```

## Key Files

- `.agenttree.yaml` - Project configuration
- `agents/AGENTS.md` - Full agent instructions
- `docs/SECURITY.md` - Security model
- `spec.md` - Full project specification


# AgentTree - Project Conventions

## ⛔ NEVER merge your own PRs without explicit approval. Create PR → request `@cursoragent review` → WAIT for review → ASK before merging.

## Tech Stack

- **Language:** Python 3.12+
- **Package Manager:** uv
- **Testing:** pytest with pytest-cov
- **CLI:** Click
- **Type Checking:** mypy (strict mode)
- **Container Runtime:** Apple Containers (default on macOS), Docker as fallback. Agents run sandboxed in containers.

## Architecture

- CLI entry point: `agenttree/cli.py`
- Hook system (stage transitions): `agenttree/hooks.py`
- Issue management: `agenttree/issues.py`
- Agent repository: `agenttree/agents_repo.py`
- Container support: `agenttree/container.py` (uses Apple Containers, not Docker)
- Agent state management: `agenttree/state.py`

## Commands

- `uv run pytest` - Run all tests
- `uv run pytest tests/unit` - Run unit tests only
- `uv run pytest tests/integration` - Run integration tests only
- `uv run mypy agenttree` - Type check the codebase
- `uv sync` - Install/sync dependencies

## Code Style

- Use type hints for all function signatures
- Follow existing patterns in the codebase
- Tests should be in `tests/unit/` or `tests/integration/`
- Use descriptive variable names
- Keep functions focused and single-purpose
- **No legacy/backward compatibility code** - This project is pre-launch. Don't add aliases, fallbacks, or compatibility shims for old behavior. Just change/remove the code directly.
- **Don't obscure errors** - Let errors surface clearly. No "graceful" failures that swallow exceptions or hide problems. If something breaks, it should break loudly so we can fix it.

## Testing

- Write tests for new features and bug fixes
- Use fixtures defined in `tests/conftest.py`
- Mock external dependencies (git, docker, filesystem)
- Aim for high coverage on core workflow logic

## Frontend Development

When working on web UI (HTML, CSS, templates):
- **Use Playwright MCP to review your work** - Don't commit CSS/layout changes without visually verifying them
- Run the web server: `uv run python -m agenttree.web.app`
- Use Playwright to screenshot pages: "use playwright to screenshot http://localhost:8080/kanban"
- Check for layout issues, color contrast, responsive behavior
- The web app uses a vintage green color palette - maintain consistency

## Workflow

1. Read existing code before making changes
2. Run tests after changes: `uv run pytest`
3. Type check before committing: `uv run mypy agenttree`
4. Keep changes focused and avoid over-engineering
5. Don't add features beyond what's requested

## Project-Specific Notes

- Issues are stored in `_agenttree/issues/` as YAML and markdown files
- Stage instructions use Jinja2 templates in `_agenttree/skills/`
- The workflow supports both local and containerized agent execution
- Hooks can be configured in `.agenttree.yaml` for stage transitions

---

## About AgentTree

This project uses AgentTree, a workflow system for AI agents working on software development tasks. It provides structured stages (define → research → plan → implement), automated validation, and human review checkpoints.

**For detailed workflow documentation, see:** [`_agenttree/skills/overview.md`](_agenttree/skills/overview.md)

**Key commands:**
- `agenttree issue create "title"` - Create a new issue
- `agenttree start <id>` - Start an agent to work on an issue
- `agenttree status` - Show status of issues and agents
- `agenttree next` - Get instructions for current stage (used by agents)

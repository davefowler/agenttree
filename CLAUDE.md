# AgentTree - Project Conventions

## Tech Stack

- **Language:** Python 3.12+
- **Package Manager:** uv
- **Testing:** pytest with pytest-cov
- **CLI:** Typer
- **Type Checking:** mypy (strict mode)

## Architecture

- CLI entry point: `agenttree/cli.py`
- Core workflow: `agenttree/workflow.py`
- Issue management: `agenttree/issues.py`
- Agent repository: `agenttree/agents_repo.py`
- Docker container support: `agenttree/container.py`

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

## Testing

- Write tests for new features and bug fixes
- Use fixtures defined in `tests/conftest.py`
- Mock external dependencies (git, docker, filesystem)
- Aim for high coverage on core workflow logic

## Workflow

1. Read existing code before making changes
2. Run tests after changes: `uv run pytest`
3. Type check before committing: `uv run mypy agenttree`
4. Keep changes focused and avoid over-engineering
5. Don't add features beyond what's requested

## Project-Specific Notes

- Issues are stored in `.agenttrees/issues/` as YAML and markdown files
- Stage instructions use Jinja2 templates in `.agenttrees/skills/`
- The workflow supports both local and containerized agent execution
- Hooks can be configured in `.agenttree.yaml` for stage transitions

---

## About AgentTree

This project uses AgentTree, a workflow system for AI agents working on software development tasks. It provides structured stages (define → research → plan → implement), automated validation, and human review checkpoints.

**For detailed workflow documentation, see:** [`.agenttrees/skills/overview.md`](.agenttrees/skills/overview.md)

**Key commands:**
- `agenttree issue create "title"` - Create a new issue
- `agenttree start <id>` - Dispatch an agent to work on an issue
- `agenttree status` - Show status of issues and agents
- `agenttree next` - Get instructions for current stage (used by agents)

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

- Use type hints for all function signatures (modern Python 3.10+ syntax)
  - Use `list[str]` not `List[str]`, `dict[str, Any]` not `Dict[str, Any]`
  - Use `X | None` not `Optional[X]`, `X | Y` not `Union[X, Y]`
- Follow existing patterns in the codebase
- Tests should be in `tests/unit/` or `tests/integration/`
- Use descriptive variable names
- Keep functions focused and single-purpose

## Anti-Slop Rules

**Write code like antirez (Redis creator) - minimal, direct, no unnecessary abstraction.**

Every line must earn its place. If you're adding complexity, you need a real reason.

### Instant Rejection Patterns
1. **Dead code** - new modules/classes added but not actually used
2. **Half-finished refactors** - new code exists alongside old code that should be deleted
3. **Slop** - multiple functions that differ only by a string parameter (make ONE generic function)
4. **Cowardly code** - try/except around our own imports, defensive checks for guaranteed fields
5. **Backwards compat cruft** - aliases, duplicate fields, deprecated code kept "just in case"
6. **Bare except** - `except:` or `except Exception:` without re-raising
7. **Type ignore abuse** - `# type: ignore` to hide errors instead of fixing them
8. **Old typing syntax** - `List`, `Dict`, `Optional`, `Union` from typing module
9. **Swallowed errors** - `except: pass` or logging without surfacing

### Before Writing Code, Ask
1. Can I solve this by changing 1 line instead of adding 10?
2. Am I about to write the same pattern multiple times? (If yes, STOP)
3. Would a reader understand this faster without the abstraction?
4. Is this "best practice" or just "more code"?

**The test:** If a senior engineer would ask "why didn't you just...", you've written slop.

### No Backwards Compatibility Cruft
**We are pre-launch. There is no backwards compatibility to maintain.**
- Do NOT add aliases "for backwards compatibility"
- Do NOT keep old field names alongside new ones
- Do NOT leave deprecated code "in case someone needs it"
- Clean up thoroughly - update ALL references

### No Cowardly Code
**Write confident code. If something should work, don't add fallbacks "just in case."**

```python
# BAD - cowardly code
try:
    from agenttree.hooks import ValidationError
except ImportError:
    ValidationError = None  # type: ignore

# GOOD - confident code (if our own file doesn't exist, CRASH LOUDLY)
from agenttree.hooks import ValidationError
```

**Reject:**
- `try/except ImportError` around our own modules
- `if hasattr(obj, 'field')` for fields that should always exist
- `getattr(obj, 'field', None)` when `obj.field` is guaranteed
- `# type: ignore` to silence errors instead of fixing them

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

## Use CLI Commands, Not Manual Operations

**Always use `agenttree` CLI commands** instead of manually editing YAML files or doing things "under the hood":

- `agenttree approve <id>` - Advance an issue past a review stage (runs hooks, notifies agent)
- `agenttree send <id> "message"` - Send a message to an agent
- `agenttree start <id>` - Start an agent for an issue
- `agenttree issue create "title" --problem "..."` - Create a new issue (title min 10 chars, problem min 50 chars, always follow with `agenttree start <id>`)

**Why:** CLI commands run the proper hooks and workflow logic. Manually editing `issue.yaml` or using raw commands bypasses hooks, breaks notifications, and causes state inconsistencies.

---

This project uses AgentTree. See `_agenttree/skills/overview.md` for workflow documentation.

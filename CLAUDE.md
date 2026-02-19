# AgentTree - Project Conventions

## ⛔ NEVER merge your own PRs without explicit approval. Create PR → request `@cursoragent review` → WAIT for review → ASK before merging.

## ⛔ NEVER USE RAW TMUX OR CONTAINER COMMANDS

**Use `agenttree` CLI instead of tmux/container. ALWAYS.**

| ❌ DON'T | ✅ DO |
|----------|-------|
| `tmux list-sessions` | `agenttree status` |
| `tmux capture-pane` | `agenttree output <id>` |
| `tmux send-keys` | `agenttree send <id> "msg"` |
| `tmux kill-session` | `agenttree stop <id>` |
| `tmux has-session` | `agenttree status` |
| `container run ...` | `agenttree start <id>` |
| `container exec ...` | `agenttree attach <id>` |
| `container list` | `agenttree status` |
| `container stop/delete` | `agenttree stop <id>` |

Raw tmux/container commands bypass the workflow, break state tracking, and cause bugs. The CLI handles everything properly.

**If you find yourself about to type `tmux` or `container`, STOP. Find the agenttree command instead.**

## Tech Stack

- **Language:** Python 3.12+
- **Package Manager:** uv
- **Testing:** pytest with pytest-cov
- **CLI:** Click
- **Type Checking:** mypy (strict mode)
- **Container Runtime:** Apple Containers (default on macOS), Docker as fallback. Agents run sandboxed in containers.

## Architecture

- CLI entry point: `agenttree/cli/`
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

- Use type hints for all function signatures (modern Python 3.10+ syntax) — mypy strict mode enforces this, and untyped code blocks the pipeline at code_review
  - Use `list[str]` not `List[str]`, `dict[str, Any]` not `Dict[str, Any]`
  - Use `X | None` not `Optional[X]`, `X | Y` not `Union[X, Y]`
- Follow existing patterns in the codebase — the independent reviewer checks for consistency and will send you back if you invent new conventions
- Tests should be in `tests/unit/` or `tests/integration/` — tests outside these dirs won't be picked up by CI
- Use descriptive variable names
- Keep functions focused and single-purpose

## Module Ownership — One Function, One Place

Every operation has ONE authoritative function. Don't reinvent, don't call lower-level primitives.

| Operation | Authoritative function | Module |
|-----------|----------------------|--------|
| Stop an agent | `stop_agent()` | `agenttree/api.py` |
| Stop all agents for issue | `stop_all_agents_for_issue()` | `agenttree/api.py` |
| Start an agent | `start_agent()` | `agenttree/api.py` |
| Send message to agent | `send_message()` | `agenttree/api.py` |
| Transition issue stage | `transition_issue()` | `agenttree/api.py` |
| Clean up orphaned containers | `cleanup_orphaned_containers()` | `agenttree/api.py` |
| Notify agent (best-effort) | `_notify_agent()` | `agenttree/api.py` |

**Never call `kill_session()` directly to stop an agent — use `stop_agent()`.**
**Never manually do exit_hooks + update_stage + enter_hooks — use `transition_issue()`.**

## No Silent Failures

- `ensure_pr_for_issue()` raises `RuntimeError` on failure, not `return False`
- `_action_merge_pr()` raises `RuntimeError` if no PR number, not silent return
- `check_manager_stages()` logs warnings on exceptions, not bare `continue`
- Manager heartbeat notifies agents on StageRedirect (via `_notify_agent()`)

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

- Write tests for new features and bug fixes — the code_review substage runs `uv run pytest` and rejects you if tests fail. Write them early to save yourself a round trip.
- Use fixtures defined in `tests/conftest.py` — there are already fixtures for config, issues, and temp directories. Creating new ones when existing ones work is slop.
- Mock external dependencies (git, docker, filesystem) — tests that hit real infrastructure pass locally but fail in CI, and then you get to debug a phantom failure. Fun.
- Aim for high coverage on core workflow logic
- **`@pytest.mark.local_only`** — Mark tests that need Playwright, tmux, Apple Containers, or other tools unavailable in CI. CI runs with `-m "not local_only"` to skip them. Forget this marker and CI fails on every PR with an unhelpful "fixture not found" error.

## Frontend Development

When working on web UI (HTML, CSS, templates):
- **Use Playwright MCP to review your work** — CSS bugs are invisible until someone looks at the page. The reviewer will look. You should look first.
- Run the web server: `uv run agenttree run`
- Use Playwright to screenshot pages: "use playwright to screenshot http://localhost:9000/kanban"
- Check for layout issues, color contrast, responsive behavior
- The web app uses a minimal, neutral gray color palette inspired by Linear/Cursor — maintain consistency. Keep the design clean and uncluttered with subtle accent colors.

## Workflow Flows

Issues follow a **flow** that determines which stages they pass through:

- **default** (the vast majority of issues): Full workflow — explore.define → explore.research → plan.draft → plan.assess → plan.revise → plan.review (human) → implement.setup → implement.code → implement.code_review → implement.independent_review → implement.ci_wait → implement.review (human) → accepted. Use for anything that requires thought, investigation, or touches non-trivial code.
- **quick** (very rare — truly trivial tasks only): Abbreviated — explore.define → implement → accepted. Skips research, planning, and human review. **Only** for tasks where the solution is already fully obvious and requires zero decision-making: typo fixes, color changes, config constant updates. If you have to think about it at all, it's not quick.

**When in doubt, use `default`.** The quick flow has no human review before coding starts. Misusing it wastes time when the implementation goes in the wrong direction.

## Workflow

1. Read existing code before making changes — the codebase already has patterns for most things. If you don't read first, you'll reinvent something that exists and the reviewer will send you back.
2. Run tests after changes: `uv run pytest` — catching failures early saves a full code_review → address_review cycle.
3. Type check before committing: `uv run mypy agenttree` — mypy runs in pre_completion hooks. Better to find the errors now than have the hook reject you after a 5-minute mypy run in a container.
4. Keep changes focused and avoid over-engineering — the Anti-Slop rules aren't suggestions. The independent reviewer actively checks for unnecessary abstraction.
5. Don't add features beyond what's requested — undocumented changes get flagged as "out of scope" in PR review and may be rejected entirely.

## Project-Specific Notes

### The `_agenttree/` Directory (Separate Repository)

The `_agenttree/` directory is a **separate git repository** that stores all AI workflow documentation:
- `issues/` - Issue tracking, state, and documents (problem.md, spec.md, review.md, etc.)
- `skills/` - Stage instructions and agent skill files
- `templates/` - Document templates for each stage

**This is gitignored from the main repo** because it's its own repo. When you update skills or templates in `_agenttree/`, those changes are tracked there, not in the main codebase commits.

### Other Notes
- The workflow supports both local and containerized agent execution
- Hooks can be configured in `.agenttree.yaml` for stage transitions

## Creating Pull Requests

**Multiple agents often work on the same branch.** Before creating a PR, always check for ALL changes in the branch, not just your own work.

### PR Creation Checklist

1. **Run `git diff main...HEAD --stat`** to see ALL files changed in the branch
2. **Look for changes you didn't make** - another agent may have added features
3. **Include ALL features in the PR description** - reviewers will reject "out of scope" changes if not documented
4. **Group related changes** under clear headings in the Summary section

### PR Description Template

```markdown
## Summary

### [Your Feature Name]
- Bullet points for your changes

### [Other Feature Name] (if other changes exist)
- Bullet points for changes made by other agents
- Note: "Added by parallel work on this branch"

## Test plan
- [ ] Tests for your feature
- [ ] Tests for other features (if applicable)
```

### Why This Matters

The automated reviewer will flag undocumented changes as "out of scope" and request they be removed. By documenting ALL branch changes upfront, you prevent:
- False "dead code" reports (code used by undocumented features)
- Requests to split into multiple PRs
- Rejection of legitimate work

## Slash Commands

- **`/pr`** — Create a PR from current changes and iterate until CI passes. Handles branching, pushing, PR creation, CI monitoring, and review feedback. See `.claude/commands/pr.md`. In Cursor, just say "run the pr command" and it will follow the same instructions.

## Use CLI Commands, Not Manual Operations

**Always use `agenttree` CLI commands** instead of manually editing YAML files or doing things "under the hood":

- `agenttree approve <id>` - Advance an issue past a review stage (runs hooks, notifies agent)
- `agenttree send <id> "message"` - Send a message to an agent
- `agenttree send <id> "message" --interrupt` - Send Ctrl+C first to interrupt, then send message
- `agenttree start <id>` - Start an agent for an issue
- `agenttree start <id> --force` - Restart an agent (kills existing, rebases, starts fresh)
- `agenttree issue create "title" --problem "..."` - Create a new issue (title min 10 chars, problem min 50 chars, always follow with `agenttree start <id>`)
- `agenttree output <id>` - View an agent's terminal output (use this instead of tmux capture-pane)
- `agenttree status` - Show all active issues with stage progress, time in stage, agent status (run/dead), and whether waiting on human

**Why:** CLI commands run the proper hooks and workflow logic. Manually editing `issue.yaml` or using raw commands bypasses hooks, breaks notifications, and causes state inconsistencies.

**Important:**
- Use `agenttree output <id>` to check on agents, NOT raw tmux commands like `tmux capture-pane`
- Use `agenttree status` to see all agents and their states, NOT `tmux list-sessions`
- Use `agenttree start/stop/send` to manage agents, NOT direct tmux commands

---

This project uses AgentTree. See `_agenttree/skills/overview.md` for workflow documentation.

# Serve Architecture Plan

**Date:** 2026-02-22
**Status:** Plan (not yet implemented)

## Problem Summary

When dogfooding agenttree-on-agenttree, each agent's container was recursively
starting more containers. `agenttree run` starts agents in containers, and inside
those containers the project is *also* agenttree — so any path that triggers
agent-starting logic spawns yet more containers.

This is **not** a bug in `agenttree run` — it's a missing `serve` config for our
project. Normal projects (web apps, APIs, etc.) don't have this problem because
their `serve` command is `npm run dev` or `python manage.py runserver`, not
`agenttree run`. The fix is architectural: make `serve` a first-class configurable
command, and for agenttree-on-agenttree, configure it to not start agents.

Additionally: serve sessions should run inside containers, naming should be
centralized, issue_id should be auto-inferred from the environment, the dev
server URL needs to be reliably surfaced in issue detail views, and the CLI
naming needs a rethink.

---

## Part 1: CLI Restructure — `start` vs `run`

**Files:** `agenttree/cli/__init__.py`, `agenttree/cli/server.py`,
`agenttree/cli/agents.py`, `agenttree/cli/dev.py`

### The Problem

- `agenttree run` is claimed by the orchestrator (start server + agents + manager)
- `agenttree test` / `agenttree lint` are hardcoded CLI commands, not driven by
  the `commands:` config
- There's no way to run custom commands from the config
- `agenttree serve` doesn't exist as a CLI command

### The Rename

| Old | New | Purpose |
|-----|-----|---------|
| `agenttree run` | `agenttree start` | Orchestrator: start everything |
| `agenttree start <id>` | `agenttree start <id>` | Start one agent (unchanged) |
| *(new)* | `agenttree run <cmd>` | Run any command from `commands:` config |
| `agenttree test` | `agenttree run test` | Run test command from config |
| `agenttree lint` | `agenttree run lint` | Run lint command from config |
| *(new)* | `agenttree run serve` | Run serve command from config |
| *(new)* | `agenttree server` | Start just the web server (internal) |

### How `agenttree start` Works (No Args)

```
agenttree start
  │
  ├─ 1. Start serve in {project}-serve-000 tmux session (port 9000)
  │     └─ runs: commands.serve (from .agenttree.yaml)
  │
  ├─ 2. Start agents for all active issues (in parallel)
  │     └─ for each issue: agenttree start <id>
  │        └─ creates container + worktree + tmux
  │           └─ inside container: starts serve tmux + AI tool
  │
  └─ 3. Start manager agent (agent 0, on host)
```

When `issue_id` is provided, it starts a single agent (existing behavior).
When omitted, it starts everything.

### How `agenttree run <cmd>` Works

```
agenttree run serve
  │
  ├─ 1. Look up "serve" in commands: config
  │     └─ commands.serve: "npm run dev --port $PORT"
  │
  ├─ 2. Inject env vars (PORT, AGENTTREE_ISSUE_ID, AGENTTREE_ROLE)
  │     └─ PORT from env, or inferred from issue_id, or server_port
  │
  └─ 3. Execute in current directory (the worktree)
```

Every key in the `commands:` section becomes a runnable command:

```bash
agenttree run serve           # Start dev server
agenttree run test            # Run tests
agenttree run lint            # Run linting
agenttree run duplicates      # Check for duplicate code
agenttree run my_custom_cmd   # Whatever you defined
```

### `agenttree server` — The Web Server

A thin command that starts just the agenttree web server (FastAPI/uvicorn). This
is what the dogfooding serve config calls. Not the orchestrator, not the command
runner — just the web server.

```bash
agenttree server --port 9042 --host 0.0.0.0
```

This exists because `agenttree start` is the orchestrator (starts agents too),
and `agenttree run serve` runs the user's configured serve command. For the
dogfooding case, we need a way to say "just start the web server" without
recursion:

```yaml
# Dogfooding: serve command starts just the web server
commands:
  serve: "uv run agenttree server --port $PORT"
```

For normal projects, `agenttree server` is irrelevant — their serve command
is `npm run dev` or `python manage.py runserver`.

### No Backwards Compatibility

Clean break. Remove the old commands entirely:

- `agenttree run` (old, no args) → removed. Use `agenttree start`.
- `agenttree test` → removed. Use `agenttree run test`.
- `agenttree lint` → removed. Use `agenttree run lint`.

---

## Part 2: `serve` as First-Class Configurable Command

**Files:** `.agenttree.yaml`, `agenttree/cli/server.py`

### The Architecture

Three distinct layers:

- **`agenttree start`** — Orchestrator. Starts the serve command (in a tmux
  session), starts agents in containers, starts the manager.

- **`agenttree run <cmd>`** — Command runner. Runs any command from the
  `commands:` config with env vars injected.

- **`commands.serve`** — User-configured command that runs in each agent's serve
  tmux session. For most projects it's their dev server. For agenttree it calls
  `agenttree server`.

### Host vs Container Serving

The `serve` command is user-configured, so users already control where/how
serving happens. By default, the manager runs on the host (not in a container),
so its serve session also runs on the host — same filesystem, same network,
easy to debug.

Agents run in containers, so their serve sessions run inside containers with
port forwarding. Users who want to debug an agent's serve output can:
- `agenttree attach <id> --serve` to see the serve tmux
- `agenttree output <id> --serve` to see serve logs
- Or just `agenttree run serve` directly on the host for local testing

### How Container Startup Works

When a container starts for an issue, it:

1. Starts `commands.serve` (or `commands.on_container_start` if set) in a
   serve tmux session inside the container
2. Starts the AI tool (claude) in the foreground

The serve command runs with `PORT`, `AGENTTREE_ISSUE_ID`, and `AGENTTREE_ROLE`
already set as container env vars.

### Recursion Protection (Config, Not Code)

For a **normal project** (web app, API, etc.):
```yaml
commands:
  serve: "npm run dev --port $PORT"
```
No recursion — the serve command is unrelated to agenttree.

For **agenttree-on-agenttree** (dogfooding):
```yaml
commands:
  serve: "uv run agenttree server --port $PORT"
```
`agenttree server` starts just the web server. No agents, no orchestration,
no recursion. Clean and explicit.

No hardcoded `is_running_in_container()` checks anywhere. The protection lives
in the serve config.

### Optional: `on_container_start` Hook

For projects that need more than just `serve` at container startup:

```yaml
commands:
  serve: "npm run dev --port $PORT"
  on_container_start: "./scripts/container-init.sh"
```

When `on_container_start` is set, it runs instead of `serve` at container startup.
When omitted, defaults to `serve`.

---

## Part 3: Container Environment Variables

**Files:** `agenttree/container.py`

### Current State

Containers currently get two env vars:
- `AGENTTREE_CONTAINER=1` — "I'm in a container"
- `AGENTTREE_ROLE=<role>` — "I'm a developer/reviewer/etc."

### Add `AGENTTREE_ISSUE_ID` and `PORT`

Add to `build_run_command()` (~line 488) and `start_container_detached()`
(~line 1034):

```python
cmd.extend(["-e", f"AGENTTREE_ISSUE_ID={issue_id}"])
cmd.extend(["-e", f"PORT={port}"])
```

The full set of agenttree env vars in every container:

| Env var | Example | Purpose |
|---------|---------|---------|
| `AGENTTREE_CONTAINER` | `1` | Container detection |
| `AGENTTREE_ISSUE_ID` | `42` | Which issue this agent is working on |
| `AGENTTREE_ROLE` | `developer` | Agent role |
| `PORT` | `9042` | Assigned port for this agent's serve |

`PORT` is set as a container-level env var so it's available **everywhere** inside
the container — not just in the serve tmux session. The AI tool, scripts, the
serve command, and any other process can all read `$PORT`.

Port assignment is deterministic with modulo wrapping. Range is **inclusive**.

```yaml
port_range: 9000-9100    # 100 issue slots (9001-9100), manager on 9000
```

Formula:
```
mod = port_max - port_min            # 100
remainder = issue_id % mod           # 0-99
port = port_max   if remainder == 0  # 0 → use max port
port = port_min + remainder          # otherwise: port_min + remainder
```

Manager always gets `port_min` (9000). Issues always start at 1, so
`remainder == 0` only occurs at issue 100, 200, etc. — never for the manager.
Port 9000 is exclusively the manager's. No conflict.

| Context | Remainder | Port |
|---------|-----------|------|
| Manager | — | 9000 (always `port_min`) |
| Issue #1 | 1 | 9001 |
| Issue #42 | 42 | 9042 |
| Issue #99 | 99 | 9099 |
| Issue #100 | 0 | 9100 (`0 → port_max`) |
| Issue #101 | 1 | 9001 (wraps — fine if #1 is archived) |

100 issue slots (9001-9100) that wrap for high issue numbers. Collisions only
happen when 100+ issues are actively running simultaneously.

### For Host Serve Sessions (Manager)

The manager's serve session runs on the host (not in a container). Set `PORT` as
an env prefix when launching the tmux session:

```python
serve_cmd = f"PORT={port} {serve_command}"
```

### Serve Command Uses `$PORT`

Users reference `$PORT` in their serve config:

```yaml
# Normal project
commands:
  serve: "npm run dev --port $PORT"

# Agenttree dogfooding
commands:
  serve: "uv run agenttree server --port $PORT"
```

`$PORT` is always available — set as a container env var in containers, set as
a shell prefix on the host.

---

## Part 4: Auto-Infer `issue_id` from Environment

**Files:** `agenttree/cli/_utils.py`, various CLI commands

When `issue_id` is not provided, resolve from environment:

```python
def infer_issue_id() -> int | None:
    """Infer issue_id from environment, or None if not in an agent context."""
    env_id = os.environ.get("AGENTTREE_ISSUE_ID")
    if env_id:
        return parse_issue_id(env_id)
    return None
```

**Important:** Do NOT default to 0. Being on the host with no env var doesn't
mean "I'm the manager." It means "I'm not in any agent's context." Commands
handle `None` appropriately:

- **`agenttree start`** (no args) — doesn't need an issue_id. It's the
  orchestrator.
- **`agenttree run serve`** — if issue_id is inferred from env, uses that issue's
  port. If None (on host), uses the server_port (9000).
- **`agenttree attach` / `output` / `send`** — if issue_id inferred from env,
  use it. If None, require it as an argument (or show an error listing available
  agents).

Put `infer_issue_id()` in `agenttree/cli/_utils.py` alongside `normalize_issue_id`.

---

## Part 5: Unified Session Naming with Templates

**Files:** `agenttree/ids.py`, `agenttree/config.py`, `agenttree/tmux.py`,
`agenttree/api.py`

### Current Problem

Session names are constructed inline in multiple places with slightly different
patterns. The serve session name `f"{self.config.project}-serve-{issue_id}"` is
in `tmux.py:565` and `api.py:644`. Role session names use a different pattern in
`ids.py`. There's no way for users to override the naming scheme.

### New Design: Template-Based Naming

Add a `default_session_name_template` to the config, always shown explicitly in
the default config file:

```yaml
# Session naming — always shown, never hidden
default_session_name_template: "{project}-{session_name}-{issue_id}"
```

Where `session_name` is the role name (for roles) or the session key (for
sessions). Examples with default template:

| Context | session_name | Result |
|---------|-------------|--------|
| Developer role, issue 42 | `developer` | `myapp-developer-042` |
| Serve session, issue 42 | `serve` | `myapp-serve-042` |
| Manager role, issue 0 | `manager` | `myapp-manager-000` |
| Worker session, issue 42 | `worker` | `myapp-worker-042` |

Individual sessions can override with `name_template`:

```yaml
sessions:
  serve:
    command: "npm run dev --port {{ port }}"
    name_template: "{project}-web-{issue_id}"   # custom name
```

### Implementation in `ids.py`

Keep `ids.py` pure — no config loading. Pass the template as a parameter:

```python
def session_name(
    project: str,
    session_type: str,
    issue_id: int,
    template: str = "{project}-{session_name}-{issue_id}",
) -> str:
    """Generate a tmux session name from a template."""
    return template.format(
        project=project,
        session_name=session_type,
        issue_id=format_issue_id(issue_id),
    )
```

This replaces all the individual `tmux_session_name()`, `serve_session_name()`,
`manager_session_name()` functions with one generic function. Callers in
`config.py` (which already have config access) pass the template through:

```python
def get_session_name(self, session_type: str, issue_id: int) -> str:
    template = self._get_session_template(session_type)
    return session_name(self.project, session_type, issue_id, template)
```

No performance concern — `ids.py` stays pure, config is only loaded by callers
that already have it.

### Replace Inline Construction

Replace all inline session name construction in:
- `tmux.py:565` (serve session)
- `api.py:644` (serve cleanup)
- `tmux.py` (role sessions)
- `config.py` (existing helpers)

---

## Part 6: Serve Sessions Inside Containers

**Files:** `agenttree/tmux.py`, container entrypoint

### Current State (Broken)

The serve session (`tmux.py:562-575`) runs on the **host** tmux. The host tmux
can't properly run commands inside the container's filesystem.

### New Design

Serve runs **inside** the container via a container-internal tmux session.

When an agent starts in a container:

1. Container entrypoint starts tmux inside the container
2. Creates sessions using the full naming template (e.g.,
   `{project}-serve-{issue_id}`) — full names make sessions accessible to the
   manager and other agents that need to inspect output
3. AI tool runs in the foreground (current behavior)

The port is already forwarded via `-p {port}:{port}` in the container run command.
`$PORT` is set as a container env var.

### Host-Side Serve (Manager / Agent 0)

Agent 0 (manager) runs on the host, not in a container. Its serve session runs
on the host tmux as `{project}-serve-000`. This is started by `agenttree start`
(no args) as step 1.

---

## Part 7: `agenttree start` Starts Server in Serve Tmux

**Files:** `agenttree/cli/server.py`

Currently `agenttree run` starts the web server in the foreground (blocks the
terminal with uvicorn). With the rename to `agenttree start`:

1. Start `commands.serve` in a dedicated tmux session:
   `{project}-serve-000` (the manager's serve session, port 9000)
2. Start agents in background (existing behavior)
3. Start the manager agent (existing behavior)

This way the server runs in a tmux session that agents (and humans) can inspect.

### CLI for Serve Logs

Add a `--serve` flag to the `output` and `attach` commands:

```bash
agenttree output <issue_id> --serve    # View serve session output
agenttree output 0 --serve             # View manager's server output
agenttree attach <issue_id> --serve    # Attach to serve session
```

### What Does `agenttree start` Print?

After starting everything, print a clear status summary with the commands to
interact:

```
✓ AgentTree started

  Server:  http://localhost:9000
  Agents:  3 started (issues #12, #42, #57), 2 in backlog
  Manager: agenttree-manager-000

  Commands:
    agenttree attach 0              # Attach to manager
    agenttree attach 42             # Attach to agent for issue #42
    agenttree output 0 --serve      # Watch server logs
    agenttree attach 42 --serve     # Attach to issue #42 serve session
    agenttree stop                  # Stop everything
```

Then exit (don't block). Users who want to tail logs use the commands shown.

---

## Part 8: Always Show Dev Server URL (with Status Color)

**Files:** `agenttree/web/templates/partials/issue_detail_content.html`,
`agenttree/web/app.py`

### Current State

The template conditionally hides the URL:

```html
{% if issue.port and issue.tmux_active %}
<span><a href="http://localhost:{{ issue.port }}" ...>Dev Server :{{ issue.port }}</a></span>
{% endif %}
```

### Problem

- `tmux_active` checks the *agent* tmux session, not the *serve* session.
- URL disappears entirely when agent stops, even if serve is still running.
- Users lose track of which port an issue maps to.

### Fix: Always Show, Color by Status

**Always** show the port when `issue.port` exists. Use green/gray to indicate
whether the dev server is actually running:

```html
{% if issue.port %}
<span class="dev-server-link {% if issue.serve_active %}active{% else %}inactive{% endif %}">
  <a href="http://localhost:{{ issue.port }}" target="_blank"
     title="{% if issue.serve_active %}Server running{% else %}Server not running{% endif %}">
    :{{ issue.port }}
  </a>
</span>
{% endif %}
```

CSS:
```css
.dev-server-link.active a { color: #22c55e; }    /* green — server running */
.dev-server-link.inactive a { color: #6b7280; }  /* gray — server stopped */
```

### Backend Changes

Add `serve_active` to `WebIssue`:

```python
# In convert_issue_to_web() (web/app.py):
serve_session = _config.get_serve_tmux_session(issue.id)
serve_active = serve_session in agent_manager._get_active_sessions()
```

---

## Part 9: Sessions as a First-Class Concept

**Files:** `agenttree/config.py`, `agenttree/tmux.py`, `agenttree/ids.py`

### Roles vs Sessions

Two distinct concepts:

- **Roles** = AI agent sessions. Have a `tool`, `model`, `skill`. They create a
  tmux session running an AI tool. Roles are a specialized type of session.
- **Sessions** = any tmux process. Have a `command`. They create a tmux session
  running a shell command. This is the general primitive.

A role implicitly creates a session. Sessions don't need a role. The naming
format is universal and uses the same template system (see Part 5).

### Config

Sessions have a `command` (the long-running process) and optional lifecycle hooks
using the same hook system as flows/stages:

```yaml
# Naming template — always explicit in default config
default_session_name_template: "{project}-{session_name}-{issue_id}"

sessions:
  serve:
    command: "npm run dev --port {{ port }}"
    pre_start:                          # hooks before command starts
      - run: "npm install"
    post_stop:                          # hooks after session is killed
      - run: "./scripts/cleanup.sh"
  worker:
    command: "python manage.py celery_worker"
    pre_start:
      - run: "python manage.py migrate --no-input"
  storybook:
    command: "npx storybook dev --port {{ port + 100 }}"
    name_template: "{project}-sb-{issue_id}"   # override naming
```

The `command` is the main process that runs for the lifetime of the session.
`pre_start` and `post_stop` hooks use the same action system as stage hooks
(`run`, `create_file`, etc.) — same syntax, same built-in actions.

The `setup-worktree` command was removed from here — worktree creation is
internal infrastructure, not a user-configurable hook (see Part 10).

When an agent starts for issue #42, all configured sessions start alongside it:

| Session | Tmux name | What runs |
|---------|-----------|-----------|
| developer (role) | `myapp-developer-042` | Claude CLI |
| serve | `myapp-serve-042` | `npm install` → `npm run dev --port 9042` |
| worker | `myapp-worker-042` | `migrate` → `celery_worker` |
| storybook | `myapp-sb-042` | `npx storybook dev --port 9142` |

### Session Commands Often Use `agenttree run`

Session commands can reference `agenttree run <cmd>` to invoke commands from the
`commands:` config. This keeps things DRY:

```yaml
commands:
  serve: "npm run dev --port $PORT"
  test_watch: "npm test -- --watch"

sessions:
  serve:
    command: "agenttree run serve"
  test_watch:
    command: "agenttree run test_watch"
```

Or use inline commands directly — whichever is cleaner for the use case.

### Migration from `commands.serve`

`commands.serve` currently defines what runs in the serve session. This migrates
to `sessions.serve.command`:

```yaml
# Old (still works as shorthand)
commands:
  serve: "npm run dev --port $PORT"

# New (explicit, with hooks and ports)
sessions:
  serve:
    command: "npm run dev --port {{ port }}"
    pre_start:
      - run: "npm install"
```

If `sessions.serve` is not defined but `commands.serve` exists, auto-create the
session from the command. Backwards compatible.

### Session Lifecycle

Uses the same hook system as flow stages (`post_start`, `pre_completion`, etc.):

1. **`pre_start` hooks** run sequentially (install deps, run migrations, etc.)
2. **`command`** starts as the long-running process in the tmux session
3. Session runs for the lifetime of the agent
4. When agent stops, `command` process is killed
5. **`post_stop` hooks** run sequentially (cleanup scripts, etc.)

Hooks use the same action system as stage hooks — `run`, `create_file`, etc.
Same syntax, same built-in actions, same `optional`/`timeout`/`context` options.

Sessions can be inspected: `agenttree output 42 --session serve`
Sessions can be attached: `agenttree attach 42 --session serve`

### Session Ports

Each session can declare `ports` it needs. At container startup, agenttree
collects all ports from all sessions and forwards them (`-p`). Ports support
Jinja so they stay deterministic per issue:

```yaml
sessions:
  serve:
    command: "npm run dev --port {{ port }}"
    ports: ["{{ port }}"]
  storybook:
    command: "npx storybook dev --port {{ port + 100 }}"
    ports: ["{{ port + 100 }}"]
  pgweb:
    command: "pgweb --bind=0.0.0.0 --listen={{ port + 200 }}"
    ports: ["{{ port + 200 }}"]
```

For issue #42, the container gets: `-p 9042:9042 -p 9142:9142 -p 9242:9242`.

The `serve` session's port defaults to `{{ port }}` if not specified (most common
case — no need to repeat it). Other sessions must declare their ports explicitly
if they need host access.

---

## Part 10: Containers Config — Generic, Extensible Types

**Files:** `agenttree/config.py`, `agenttree/container.py`, `agenttree/tmux.py`,
`agenttree/cli/agents.py`

### Motivation

Container config is currently scattered and hardcoded. The `sandbox` command is
baked into the CLI with no user configurability. But "sandbox" isn't fundamentally
different from any other container — it's just an ad-hoc container with certain
defaults. Users should be able to define their own container types for any purpose.

### Design: Container Types as Templates

A container type is a **template** for creating container instances. Two types are
reserved (`manager`, `issue`) because they have special lifecycle behavior. All
others are user-defined and created via `agenttree new`.

### Config

```yaml
containers:
  # Abstract base — underscore prefix means "not directly creatable"
  _base:
    image: agenttree-agent:latest
    post_start:                       # runs INSIDE container after startup
      - run: "uv pip install --system -e '/workspace[dev]'"

  # Abstract: adds git credentials for interactive git/gh access
  _with_credentials:
    extends: _base
    mounts:
      - ~/.ssh:/home/agent/.ssh:ro
      - ~/.gitconfig:/home/agent/.gitconfig:ro

  # Reserved: created automatically per-issue by `agenttree start`
  issue:
    extends: _base
    roles: [developer, reviewer]      # all roles that can run in this container
    sessions: [serve]                 # which sessions (from sessions: config) to start

  # Reserved: the manager's Claude agent (also containerized for safety)
  manager:
    extends: _with_credentials        # needs git creds for interactive git ops
    roles: [manager]

  # User-defined: `agenttree new sandbox my-sandbox`
  sandbox:
    extends: _with_credentials        # gets git creds via inheritance
    interactive: true                 # attach terminal on creation
    sessions: [serve]

  # User-defined: `agenttree new reviewer audit-42`
  reviewer:
    extends: _base
    roles: [reviewer]                 # AI agent with reviewer config
    sessions: [serve]

  # User-defined: `agenttree new perf-tester load-test`
  perf-tester:
    extends: _with_credentials
    image: perf-tools:latest          # override base image
    roles: [developer]
    sessions: [serve, monitoring]
    mounts:                           # ADDED to _with_credentials mounts
      - ~/datasets:/workspace/data:ro # inherits ~/.ssh + ~/.gitconfig from parent
    post_start:                       # REPLACES base post_start entirely
      - run: "pip install locust"
      - run: "setup-monitoring.sh"
```

### Implicit Mounts & Env Vars (system-managed)

The system always adds these — they're fundamental infrastructure and don't
appear in user config:

| What | How | Why |
|------|-----|-----|
| Worktree | `-v {worktree_path}:/workspace` | The code being worked on |
| Working dir | `-w /workspace` | Container starts in the project |
| Main `.git` | `-v {main_git_dir}:{main_git_dir}` | Git operations work in worktrees |
| `_agenttree` | `-v {repo}/_agenttree:/workspace/_agenttree` | Issue files, skills, state |
| `AGENTTREE_CONTAINER=1` | `-e` | Reliable container detection |
| `AGENTTREE_ROLE={role}` | `-e` | Current role for the agent |
| `AGENTTREE_ISSUE_ID={id}` | `-e` | Issue context (if applicable) |

These are handled by `build_container_command()` (the new generic version of
`build_run_command()`).

### Tool Mounts & Env Vars (tool-specific, driven by tool config)

These exist because the current AI tool is Claude. They're not hardcoded in the
container builder — they come from the tool config (`config.get_tool_config()`):

| What | How | Why |
|------|-----|-----|
| Claude config | `-v ~/.claude:/home/agent/.claude-host:ro` | Tool settings |
| Session storage | `-v {worktree}/.claude-sessions-{role}:/home/agent/.claude/projects/-workspace` | Conversation persistence |
| OAuth token | `-e CLAUDE_CODE_OAUTH_TOKEN=...` | Auth (subscription mode) |
| API key | `-e ANTHROPIC_API_KEY=...` | Auth (API key mode) |

Each tool config can define `mounts` and `env` that get added to the container.
This way if someone uses a different AI tool (Copilot, Aider, etc.), the
container builder doesn't need to change — the tool config drives it.

### User Mounts (from container type config)

The `mounts` field is for **additional** mounts the user needs. Mounts
accumulate through the inheritance chain — child adds to parent:

```yaml
containers:
  _with_credentials:
    mounts:
      - ~/.ssh:/home/agent/.ssh:ro
      - ~/.gitconfig:/home/agent/.gitconfig:ro

  data-science:
    extends: _with_credentials
    mounts:                              # appended to parent's mounts
      - ~/.aws:/home/agent/.aws:ro
      - ~/datasets:/workspace/data:ro
    # resolved: all 4 mounts
```

This replaces the current `--git` flag on `agenttree sandbox`.

### User Env Vars (from container type config)

Container types can also set environment variables:

```yaml
containers:
  issue:
    extends: _base
    env:
      NODE_ENV: development
      DEBUG: "true"
```

These are passed as `-e KEY=VALUE`. Jinja templates are supported:

```yaml
env:
  PORT: "{{ port }}"
  ISSUE_ID: "{{ issue_id }}"
```

### Permission Skipping (`--dangerously-skip-permissions`)

Two levels, both defaulting to `true`:

- **Container type**: `allow_dangerous: true` — the ceiling. Set to `false` to
  lock down a container type so no role can skip permissions in it.
- **Role**: `dangerous: true` — per-role opt-out. Set to `false` if a specific
  role shouldn't skip permissions even when the container allows it.

Effective: `allow_dangerous AND dangerous`. Both default `true`, so out-of-box
every containerized agent skips permissions (the whole point of containers).

```yaml
roles:
  developer:
    dangerous: true          # default — skip permissions in container
  safe-reviewer:
    dangerous: false         # never skip, even in a permissive container

containers:
  issue:
    allow_dangerous: true    # default — roles can skip if they want
  locked-down:
    allow_dangerous: false   # no role skips permissions here, period
```

### Generic Container Builder

The current `build_run_command()` mixes two concerns: (1) creating a container
with mounts/env/ports and (2) launching a specific AI tool (Claude) with its
flags (`-c`, `--model`, `--dangerously-skip-permissions`). These must separate.

The new `build_container_command()` takes a resolved `ContainerTypeConfig` and
builds a completely generic docker/container command:

```python
# Pseudocode for the new generic builder
def build_container_command(
    worktree_path: Path,
    container_type: ResolvedContainerType,
    container_name: str,
    role: str,
    issue_id: int | None,
    ports: list[int],
) -> list[str]:
    cmd = [runtime, "run", "-it"]
    
    # 1. Implicit mounts (always)
    cmd += ["-v", f"{worktree_path}:/workspace", "-w", "/workspace"]
    cmd += git_worktree_mounts(worktree_path)
    cmd += agenttree_dir_mount(worktree_path)
    
    # 2. Tool mounts & env (from tool config)
    tool = config.get_tool_config(container_type.tool or config.default_tool)
    cmd += tool.container_mounts(worktree_path, role)
    cmd += tool.container_env()
    
    # 3. User mounts (from container type config)
    for mount in container_type.mounts:
        cmd += ["-v", resolve_mount(mount)]
    
    # 4. User env vars (from container type config)
    for key, value in container_type.env.items():
        cmd += ["-e", f"{key}={render(value)}"]
    
    # 5. System env vars (always)
    cmd += ["-e", "AGENTTREE_CONTAINER=1"]
    cmd += ["-e", f"AGENTTREE_ROLE={role}"]
    if issue_id is not None:
        cmd += ["-e", f"AGENTTREE_ISSUE_ID={issue_id}"]
    
    # 6. Ports (collected from sessions)
    for port in ports:
        cmd += ["-p", f"{port}:{port}"]
    
    # 7. Container name & image
    cmd += ["--name", container_name]
    cmd += [container_type.image]
    
    # 8. Entry command (from tool config, NOT hardcoded)
    cmd += tool.container_entry_command(
        model=...,
        dangerous=container_type.allow_dangerous and role_config.dangerous,
        role=role,
    )
    
    return cmd
```

**No `if manager` / `if sandbox` / `if issue` branching.** The container type
config fully describes the container. The callers just do:

1. Resolve the container type config (walks `extends` chain)
2. Collect ports from sessions
3. Call `build_container_command()` with the resolved config
4. Create a tmux session running the command

The current three separate code paths (`start_manager`, `start_issue_agent_in_container`,
sandbox in `cli/agents.py`) all collapse into one generic flow.

### Worktree Creation is Internal

Worktree creation is **not** a config hook. It's core infrastructure handled by
the system before any container starts:

- **Issue containers**: system creates a git worktree based on `issue_id` and
  `branch` (current behavior in `api.py`)
- **Sandbox/custom containers**: system creates a worktree based on the
  container `name`
- **Manager**: uses the main repo directly (no worktree needed)

Users don't configure this. The `pre_start` and `post_start` hooks are for
custom setup ON TOP of the worktree (install deps, run migrations, etc.).

### `roles` — Multiple Roles Per Container

A container type lists all roles that can run inside it. For `issue` containers,
both `developer` and `reviewer` operate at different workflow stages within the
same container. Each role gets its own tmux session:

```yaml
containers:
  issue:
    roles: [developer, reviewer]    # both can operate in this container type
    sessions: [serve]
```

When `agenttree start` creates an issue container, the initial role comes from
the workflow stage. If the issue later transitions to a `reviewer` stage, a new
tmux session starts for the reviewer role in the same container.

For user-defined types, `roles` determines which AI agents start when the
container is created via `agenttree new`.

### Inheritance with `extends`

`extends` copies all fields from the parent, then child fields override.
Different fields have different merge semantics based on their nature:

**Replace** (child completely overrides parent):

- **Scalar values** (image, interactive, allow_dangerous): child wins
- **Hooks** (pre_start, post_start, pre_stop, post_stop): child owns the full
  list — ordering matters, so merging would be ambiguous
- **Roles**: child defines which roles it supports
- **Sessions**: child defines which sessions run

**Accumulate** (child adds to parent):

- **Mounts**: child mounts are appended to parent mounts. Mounts are additive
  ("give me access to X too") with no ordering concern.
- **Env**: dict merge — child keys override parent, parent keys are kept.

```yaml
containers:
  _with_credentials:
    extends: _base
    mounts:
      - ~/.ssh:/home/agent/.ssh:ro       # 2 mounts from parent
      - ~/.gitconfig:/home/agent/.gitconfig:ro

  data-science:
    extends: _with_credentials
    mounts:                              # appended — total is 4 mounts
      - ~/.aws:/home/agent/.aws:ro
      - ~/datasets:/workspace/data:ro

  # Resolved mounts for data-science:
  #   ~/.ssh:/home/agent/.ssh:ro              (from _with_credentials)
  #   ~/.gitconfig:/home/agent/.gitconfig:ro  (from _with_credentials)
  #   ~/.aws:/home/agent/.aws:ro              (from data-science)
  #   ~/datasets:/workspace/data:ro           (from data-science)
```

Hooks use replace semantics because ordering matters — merging is ambiguous
(before? after? interleaved?). Repeating parent hooks is explicit and
unambiguous, and bases typically have 1-2 hooks:

```yaml
containers:
  _base:
    post_start:
      - run: "npm install"

  issue:
    extends: _base
    post_start:
      - run: "npm install"          # repeated from base
      - run: "npm run db:migrate"   # added for issue containers
```

Abstract types (underscore prefix like `_base`) are not creatable — they exist
only to be extended. `agenttree new _base foo` would error.

### CLI: `agenttree new {type} {name}`

Replaces the current hardcoded `agenttree sandbox` with a generic command:

```bash
agenttree new sandbox my-sandbox       # ad-hoc exploration
agenttree new reviewer audit-42        # independent code reviewer
agenttree new perf-tester load-test    # performance testing
agenttree new sandbox                  # name defaults to "default"
```

What happens:

1. Look up `containers.{type}` config (error if not found or abstract)
2. Resolve inheritance chain (`extends`)
3. Create worktree (system handles this based on context — issue_id, name, etc.)
4. Run `pre_start` hooks on host
5. Create container: resolved image + implicit mounts + user `mounts` + env vars + ports
6. Run `post_start` hooks inside the container (e.g., install deps)
7. Start configured `sessions` inside the container
8. If `roles` is set: start the AI tool(s) in tmux sessions
9. If `interactive: true`: attach terminal to the container

Container naming: `{project}-{type}-{name}` (e.g., `agenttree-sandbox-my-sandbox`)

Management:

```bash
agenttree new --list                   # list all running containers by type
agenttree new sandbox my-sb --kill     # kill a specific container
agenttree attach sandbox my-sb         # attach to container's AI session
agenttree output sandbox my-sb         # view AI output
```

### Reserved Types: `issue` and `manager`

**`issue`** — created automatically by `agenttree start` for each issue. Lists
all roles that operate within it (`roles: [developer, reviewer]`). When the
workflow transitions between stages, the active role changes but the container
stays the same. Each role gets its own tmux session inside the container.

**`manager`** — the manager's Claude agent, also containerized. Uses
`_with_credentials` so Claude can do interactive git operations. Running the
manager in a container allows `--dangerously-skip-permissions` safely.

**Important distinction:** The manager *container* runs Claude. The
*orchestrator* (`agenttree start` / web server / heartbeat) runs on the host
and is NOT the same as the manager Claude. The orchestrator manages tmux
sessions, starts containers, runs heartbeat actions (`auto_start_agents`,
`sync`, `check_manager_stages`). It stays on the host because it needs to
manage host tmux sessions and the container runtime. The manager Claude is
just another AI agent that happens to have the manager skill.

```
Host
├── Orchestrator (web server + heartbeat)    ← runs on host
│   ├── auto_start_agents → creates containers
│   ├── sync → git pull/push _agenttree
│   ├── check_manager_stages → runs manager hooks
│   └── web UI on port 9000
├── tmux: {project}-manager-000 → docker run (manager container)
├── tmux: {project}-developer-042 → docker run (issue container)
├── tmux: {project}-serve-042 → serve command
└── ...
```

All tmux sessions remain on the host. All containers are started by the
host orchestrator. The manager container doesn't need Docker socket — it
just runs Claude with `--dangerously-skip-permissions` safely sandboxed.

### Relationship to Roles

Roles and container types are separate concerns:

- **Roles** define the AI agent: tool, model, skill
- **Container types** define the infrastructure: image, hooks, sessions, mounts

A container type lists roles via `roles: [developer, reviewer]`. The roles
determine *what AI runs*, the container type determines *where and how it runs*.

```yaml
roles:
  developer:
    tool: claude
    model: opus
  reviewer:
    tool: claude
    model: sonnet
    skill: independent_review.md

containers:
  issue:
    extends: _base
    roles: [developer, reviewer]   # both operate in issue containers
    sessions: [serve]
  reviewer:
    extends: _base
    roles: [reviewer]              # standalone reviewer container
    sessions: [serve]
```

Container type name and role name can differ — a container type `security-audit`
could use `roles: [reviewer]`.

### Hook Timing

```
pre_start  → runs on HOST before `container run` command
container starts
post_start → runs INSIDE the container after startup
... container runs ...
pre_stop   → runs INSIDE the container before `container stop`
container stops  +  all tmux sessions killed
post_stop  → runs on HOST after container is fully stopped
```

`pre_start` and `post_stop` execute on the host. `post_start` and `pre_stop`
execute inside the container.

### Container/Tmux Lifecycle Sync

Today, containers and tmux sessions are two separate things that can get out of
sync: a container dies but its tmux session lingers, or a tmux session is killed
but the container keeps running. This is infrastructure, not something users
should configure via hooks.

**The rule: containers own tmux sessions, not the other way around.**

When a container starts, the system creates tmux sessions for it (agent role
session + any configured sessions like serve). When a container stops, the
system kills ALL tmux sessions associated with it. When a tmux session dies
unexpectedly, the container continues — the session can be recreated.

**Start flow** (all handled by `start_container()`):

```
1. Resolve container type config
2. Create worktree (if needed)
3. Run pre_start hooks (on host)
4. Kill any existing container with this name (+ its tmux sessions)
5. docker run ... → creates container
6. Create tmux session for the container (host tmux → docker attach)
7. Wait for container ready
8. Run post_start hooks (inside container)
9. Start each session's tmux (host tmux → docker exec <session command>)
```

**Stop flow** (all handled by `stop_container()`):

```
1. Run pre_stop hooks (inside container, via docker exec)
2. Kill ALL tmux sessions for this container (agent + serve + any custom)
3. docker stop / docker rm
4. Run post_stop hooks (on host)
```

**Restart flow**: stop then start. The start flow kills stale tmux sessions
in step 4, so leftover sessions from crashes are always cleaned up.

**Heartbeat/health check** (existing `check_manager_stages()` loop):

The orchestrator's heartbeat loop already checks agent health. It can detect:
- Tmux session exists but container exited → kill stale tmux, mark agent dead
- Container running but no tmux session → recreate the tmux session
  (this happens when someone manually kills a tmux session)

This eliminates the two-sources-of-truth problem. The container is the source
of truth for "is this thing running". Tmux sessions are just the UI layer on
top — if they get out of sync, the heartbeat fixes them.

**`agenttree cleanup` still works** as a manual escape hatch for anything the
heartbeat misses (orphaned containers, ancient tmux sessions, etc.).

### Implementation

- `config.py`: `ContainerTypeConfig` model with `extends`, `image`, `roles`,
  `sessions`, `interactive`, `mounts`, `env`, `allow_dangerous`, lifecycle hooks.
  Resolution function that walks the `extends` chain and merges fields. Update
  manager default `RoleConfig` to `container=ContainerConfig(enabled=True)`.
  Tool configs gain `container_mounts()` and `container_env()` methods so
  tool-specific mounts (Claude config, session storage) are driven by the tool,
  not hardcoded in the container builder.
- `container.py`: Replace `build_run_command()` with generic
  `build_container_command()` that takes a resolved `ContainerTypeConfig`.
  It layers: (1) implicit system mounts, (2) tool mounts/env from tool config,
  (3) user mounts/env from container type config, (4) system env vars, (5) port
  forwarding from collected session ports. No role-specific or type-specific
  `if` branches. The AI tool entry command (e.g., `claude --model opus -c
  --dangerously-skip-permissions`) comes from the tool config, not hardcoded.
- `cli/agents.py`: Replace `sandbox` command with `new` command. Parse
  `{type} {name}`, resolve config, call generic builder, start sessions.
- `tmux.py`: Delete `start_manager()`, `start_issue_agent_in_container()`, and
  the sandbox code in `cli/agents.py`. Replace all three with a single
  `start_container()` that takes a resolved `ContainerTypeConfig`, calls the
  generic builder, creates the tmux session, and starts sessions. The only
  difference between manager/issue/sandbox is the config they're resolved from.
- `hooks.py`: The `host_only` concept changes meaning. Currently "host" means
  "not in a container" which implicitly means "manager". With the manager
  containerized, `host_only` hooks run from the orchestrator (web server
  heartbeat), not from any agent. The existing `check_manager_stages()` flow
  already handles this correctly — manager stage hooks are executed by the
  host orchestrator, not by the manager Claude.
- Hook execution reuses the existing `hooks.py` system.

---

## Part 11: Jinja Templates + Env Vars for Commands

### Both, Not Either

Commands support **both** Jinja templates (resolved at config time) and env vars
(available at runtime). Users pick whichever is natural for their use case.

### Env Vars (Runtime)

Set on the container and available to all processes:

| Env var | Example | Set in |
|---------|---------|--------|
| `PORT` | `9042` | Container env + host prefix |
| `AGENTTREE_ISSUE_ID` | `42` | Container env |
| `AGENTTREE_ROLE` | `developer` | Container env |
| `AGENTTREE_PROJECT` | `myapp` | Container env |
| `AGENTTREE_CONTAINER` | `1` | Container env |

Good for: simple commands, scripts that read env vars internally.

```yaml
commands:
  serve: "npm run dev --port $PORT"
sessions:
  serve:
    command: "./scripts/dev-server.sh"  # script reads $PORT
```

### Jinja Templates (Config Time)

Resolved before the command is executed. Same variables plus computation:

| Jinja variable | Value | Notes |
|----------------|-------|-------|
| `{{ port }}` | `9042` | Same as `$PORT` |
| `{{ issue_id }}` | `42` | Same as `$AGENTTREE_ISSUE_ID` |
| `{{ role }}` | `developer` | Same as `$AGENTTREE_ROLE` |
| `{{ project }}` | `myapp` | Same as `$AGENTTREE_PROJECT` |

Good for: computed values, port math, conditionals.

```yaml
sessions:
  serve:
    command: "npm run dev --port {{ port }}"
  storybook:
    command: "npx storybook dev --port {{ port + 100 }}"
  db:
    command: "pgweb --bind=0.0.0.0 --listen={{ port + 200 }}"
```

### Why Both?

- Env vars are **standard** — users already know `$PORT`. Scripts work out of
  the box. The whole process tree can read them.
- Jinja is **powerful** — `{{ port + 100 }}` can't be done with env vars alone.
  Already used elsewhere in agenttree config (`condition: "{{ needs_ui_review }}"`).
- They **coexist** — Jinja resolves first, then env vars are set. No conflict.

### Implementation

In the command execution path:

1. Render Jinja templates in the command string (using port, issue_id, role, etc.)
2. Set env vars (PORT, AGENTTREE_ISSUE_ID, etc.)
3. Execute the resolved command string with the env vars set

---

## Agenttree-on-Agenttree Config

For our dogfooding `.agenttree.yaml`:

```yaml
commands:
  test: uv run pytest
  lint: "uv run mypy agenttree || echo 'Lint warnings (optional)'"

sessions:
  serve:
    command: "uv run agenttree server --port {{ port }}"

containers:
  _base:
    image: agenttree-agent:latest
    post_start:
      - run: "uv pip install --system -e '/workspace[dev]'"

  _with_credentials:
    extends: _base
    mounts:
      - ~/.ssh:/home/agent/.ssh:ro
      - ~/.gitconfig:/home/agent/.gitconfig:ro

  manager:
    extends: _with_credentials
    roles: [manager]

  issue:
    extends: _base
    roles: [developer, reviewer]
    sessions: [serve]

  sandbox:
    extends: _with_credentials
    interactive: true
    sessions: [serve]
```

`agenttree server` starts just the web server (FastAPI/uvicorn) — no agents,
no orchestration. This is what each container runs via its serve tmux session.
No recursion possible. All container types share the same base image and setup
via `extends: _base`. Manager and sandbox get git creds via explicit `mounts`
in `_with_credentials`. Manager runs Claude in a container with
`--dangerously-skip-permissions`. Worktree creation is handled internally by
the system — issue containers get a worktree from `issue_id`, sandboxes from
their name, manager uses the main repo.

---

## Implementation Order

### Phase 1 — Config foundation (unit testable, no runtime needed)

| Priority | Part | Description | Effort |
|----------|------|-------------|--------|
| 1 | Config | `ContainerTypeConfig` + `extends` resolution + mount accumulation | Medium |
| 2 | Config | `SessionConfig` model with hooks and ports | Small |
| 3 | Part 11 | Jinja template rendering for commands | Small |
| 4 | Part 3 | Port allocation update (9000-9100, manager=9000) + env vars | Small |
| 5 | Part 4 | `infer_issue_id()` from env | Small |

### Phase 2 — Generic container builder (unit testable via command list)

| Priority | Part | Description | Effort |
|----------|------|-------------|--------|
| 6 | Part 10 | Tool config gains `container_mounts()`/`container_env()`/`container_entry_command()` | Medium |
| 7 | Part 10 | `build_container_command()` replaces `build_run_command()` | Medium |
| 8 | Part 10 | Single `start_container()` replaces 3 code paths | Medium |

### Phase 3 — CLI + sessions (partially testable, manual CLI verification)

| Priority | Part | Description | Effort |
|----------|------|-------------|--------|
| 9 | Part 1 | CLI restructure: `start` vs `run <cmd>` vs `server` | Medium |
| 10 | Part 5 | Centralize session naming in `ids.py` | Small |
| 11 | Part 9 | Sessions config with lifecycle hooks | Medium |
| 12 | Part 10 | `agenttree new {type} {name}` replacing `sandbox` | Medium |

### Phase 4 — Wire together + smoke tests (requires runtime)

| Priority | Part | Description | Effort |
|----------|------|-------------|--------|
| 13 | Smoke | Scaffold `tests/smoke/` with conftest, Dockerfile, cleanup | Small |
| 14 | Part 6 | Serve sessions inside containers | Medium |
| 15 | Part 7 | `agenttree start` starts server in tmux | Medium |
| 16 | Part 8 | Always show dev server URL with status color | Small |
| 17 | Smoke | Write smoke test cases, validate with both runtimes | Medium |
| 18 | Docs | Document commands, sessions, containers, env vars, CLI | Small (drafted) |

---

## Testing Strategy

### Unit Tests (run in CI, no runtime needed)

Pure logic — mock subprocess, assert data structures:

- **Config resolution**: `ContainerTypeConfig` extends chain, mount accumulation,
  env merge, `allow_dangerous` logic
- **Container command building**: `build_container_command()` returns `list[str]`.
  Assert correct `-v`, `-e`, `-p` flags for various configs. No container started.
- **Tool config**: `container_mounts()`, `container_env()`, `container_entry_command()`
  produce correct flags for Claude (and could test a hypothetical other tool)
- **Port allocation**: manager gets 9000, issues wrap via modulo
- **Jinja rendering**: `{{ port }}`, `{{ issue_id }}`, `{{ port + 100 }}`
- **`infer_issue_id()`**: returns `int` from env, `None` when unset
- **Session name generation**: templates produce correct names

These live in `tests/unit/` alongside existing tests.

### Smoke Tests (local only, requires container runtime + tmux)

Real containers, real tmux — verify end-to-end behavior. All sessions run in
tmux, so validation is just `capture_pane(session_name)` and assert output.

Located in `tests/smoke/`. Marked `@pytest.mark.local_only` so CI skips them.
Run manually with:

```bash
uv run pytest tests/smoke/ -v                    # all smoke tests
uv run pytest tests/smoke/ -v -k docker          # docker only
uv run pytest tests/smoke/ -v -k apple_container  # apple container only
```

Additional markers for runtime selection:

```python
# tests/smoke/conftest.py
import pytest
from agenttree.container import ContainerRuntime

@pytest.fixture(scope="session")
def available_runtimes():
    """Detect which container runtimes are available."""
    rt = ContainerRuntime()
    return rt.runtime  # "docker", "container", or None

@pytest.fixture
def require_docker(available_runtimes):
    if available_runtimes != "docker":
        pytest.skip("docker not available")

@pytest.fixture
def require_apple_container(available_runtimes):
    if available_runtimes != "container":
        pytest.skip("Apple Container not available")

@pytest.fixture
def require_any_runtime(available_runtimes):
    if available_runtimes is None:
        pytest.skip("no container runtime available")

@pytest.fixture
def smoke_config(tmp_path):
    """Create a minimal .agenttree.yaml for smoke testing."""
    # Uses a lightweight image (alpine or similar) instead of the
    # full agenttree-agent image, so tests don't depend on the
    # full image being built
    ...

@pytest.fixture(autouse=True)
def cleanup_smoke_containers():
    """Kill any containers/tmux sessions created during test."""
    yield
    # cleanup logic
```

#### Smoke Test Cases

Each test starts something real, captures tmux output, asserts, cleans up:

```python
# tests/smoke/test_container_lifecycle.py

class TestContainerStarts:
    """Test that containers actually start and run."""

    def test_basic_container_starts(self, require_any_runtime):
        """Start a minimal container, verify tmux session appears."""
        # agenttree new sandbox smoke-test
        # assert session_exists("...-sandbox-smoke-test")
        # output = capture_pane(session_name)
        # assert "ready" or container is running

    def test_mounts_are_accessible(self, require_any_runtime):
        """Start container with mounts, verify files visible inside."""
        # Create a file on host, mount it, check container can see it
        # via tmux: send_keys(session, "ls /home/agent/.ssh")
        # capture_pane → assert "id_rsa" or similar

    def test_env_vars_set(self, require_any_runtime):
        """Start container, verify AGENTTREE_* env vars are set."""
        # send_keys(session, "echo $AGENTTREE_CONTAINER")
        # capture_pane → assert "1"

    def test_post_start_hooks_run(self, require_any_runtime):
        """Start container with post_start hook, verify it executed."""
        # config with post_start: [{run: "touch /tmp/hook-ran"}]
        # send_keys(session, "ls /tmp/hook-ran")
        # capture_pane → assert file exists


class TestSessions:
    """Test that sessions start inside containers."""

    def test_serve_session_starts(self, require_any_runtime):
        """Start container with serve session, verify tmux session."""
        # assert session_exists("{project}-serve-{id}")
        # capture_pane → assert server output

    def test_session_port_forwarded(self, require_any_runtime):
        """Start serve session, verify port is accessible from host."""
        # curl localhost:{port} or similar check

    def test_multiple_sessions(self, require_any_runtime):
        """Container with multiple sessions, all start."""
        # config with sessions: [serve, monitoring]
        # assert both tmux sessions exist


class TestInheritance:
    """Test that extends resolution works end-to-end."""

    def test_child_inherits_parent_mounts(self, require_any_runtime):
        """Container extending _with_credentials gets ssh/git mounts."""
        # Start sandbox (extends _with_credentials)
        # send_keys → "ls /home/agent/.ssh"
        # capture_pane → assert mount exists

    def test_child_accumulates_mounts(self, require_any_runtime):
        """Child mounts are added to parent mounts, not replacing."""
        # Custom type extending _with_credentials with extra mount
        # Verify both parent and child mounts present


class TestRuntimes:
    """Test same scenarios on both Docker and Apple Container."""

    @pytest.mark.parametrize("runtime", ["docker", "apple_container"])
    def test_basic_lifecycle(self, runtime, available_runtimes):
        """Same container lifecycle works on both runtimes."""
        if runtime == "docker" and available_runtimes != "docker":
            pytest.skip("docker not available")
        if runtime == "apple_container" and available_runtimes != "container":
            pytest.skip("Apple Container not available")
        # ... same test logic ...
```

#### Smoke Test Image

Smoke tests use a lightweight test image rather than the full `agenttree-agent`
image. This keeps tests fast and avoids depending on the full image being built:

```dockerfile
# tests/smoke/Dockerfile.smoke
FROM alpine:latest
RUN apk add --no-cache bash tmux
WORKDIR /workspace
ENTRYPOINT ["/bin/bash"]
```

Build once before running smoke tests:

```bash
docker build -t agenttree-smoke:latest -f tests/smoke/Dockerfile.smoke .
```

The smoke test conftest overrides the image in the container type config.

---

## Files Changed Summary

| File | Changes |
|------|---------|
| `agenttree/cli/__init__.py` | Register `run` group, rename `run`→`start`, add `server` |
| `agenttree/cli/server.py` | Rename `run`→`start`, add `server` cmd, add `run <cmd>` group |
| `agenttree/cli/dev.py` | Remove `test`/`lint` in favor of `run test`/`run lint` |
| `agenttree/cli/agents.py` | Replace `sandbox` with `new {type} {name}`, `--serve` on output/attach |
| `agenttree/cli/_utils.py` | Add `infer_issue_id()` helper |
| `agenttree/ids.py` | Generic `session_name()` with template parameter |
| `agenttree/config.py` | `ContainerTypeConfig` with `extends` resolution, `SessionConfig` with hooks |
| `agenttree/container.py` | Set env vars, resolve inheritance, run lifecycle hooks, collect ports |
| `agenttree/tmux.py` | Session lifecycle (pre_start → command → post_stop), centralized naming |
| `agenttree/hooks.py` | Reuse existing hook execution for session/container lifecycle |
| `agenttree/api.py` | Use centralized serve naming |
| `agenttree/web/app.py` | Add `serve_active` to `WebIssue` conversion |
| `agenttree/web/templates/partials/issue_detail_content.html` | Always show port, green/gray by `serve_active` |
| `.agenttree.yaml` | Add `sessions`, `containers` config |
| `docs/commands-and-serving.md` | New doc: commands, sessions, containers, env vars |
| `docs/container-setup.md` | Updated env vars section |
| `docs/README.md` | Added link to new doc |
| `tests/smoke/conftest.py` | Runtime detection, cleanup, smoke config fixtures |
| `tests/smoke/Dockerfile.smoke` | Lightweight test image (alpine + bash + tmux) |
| `tests/smoke/test_container_lifecycle.py` | Container starts, mounts, env vars, hooks |
| `tests/smoke/test_sessions.py` | Session startup, port forwarding, multiple sessions |
| `tests/smoke/test_inheritance.py` | Extends resolution end-to-end |
| `tests/smoke/test_runtimes.py` | Same tests on Docker vs Apple Container |
| `pyproject.toml` | Add `smoke` marker |

---

## Open Questions

None currently — all major decisions resolved. See Resolved Decisions below.

## Resolved Decisions

- **No hardcoded container guards.** Recursion protection is a config concern
  (the `serve` command), not a code concern.

- **`infer_issue_id()` returns None, not 0.** Being on the host doesn't mean
  "I'm the manager."

- **Host serving needs no special flag.** Users run `agenttree run serve` on the
  host for debugging. The manager's serve session already runs on the host.

- **All `commands:` config entries are exposed via `agenttree run <cmd>`.** This
  replaces hardcoded `test`/`lint` CLI commands and makes the system extensible.

- **`start` replaces `run` as the orchestrator.** `run` is repurposed as the
  command runner namespace. `start` with no args starts everything; `start <id>`
  starts one agent.

- **`agenttree server` is the raw web server command.** Used by the dogfooding
  serve config to start just the web server without recursion. Not needed by
  normal projects.

- **Tmux naming uses `{project}-{name}-{issue_id}` everywhere.** Including inside
  containers. The full name makes sessions accessible to the manager and other
  agents that need to inspect output.

- **Sessions are a separate concept from roles.** Roles = AI agents (tool, model,
  skill). Sessions = any tmux process (command). Roles create sessions implicitly.
  Users define additional sessions via `sessions:` config.

- **Both Jinja templates and env vars for commands.** Jinja resolves at config
  time (good for computed values like `{{ port + 100 }}`). Env vars are set at
  runtime (good for scripts that read `$PORT`). They coexist.

- **Port range is inclusive with modulo wrapping.** `port_range: 9000-9100`.
  Manager always gets `port_min` (9000). Issues start at 1 and get
  `port_min + (id % mod)`, with `remainder == 0 → port_max`. Since issues
  never have id 0, port 9000 is exclusively the manager's — no conflict.
  100 issue slots (9001-9100) that wrap for high issue numbers.

- **`agenttree start` prints status and exits.** Shows server URL, agent count,
  and the commands to attach/watch. Doesn't block.

- **Session naming uses configurable templates.** Default:
  `{project}-{session_name}-{issue_id}`. Always shown in config. Per-session
  `name_template` overrides available. `ids.py` stays pure — templates passed
  as parameters.

- **No `port_offset` config.** Sessions use Jinja math (`{{ port + 100 }}`) for
  additional ports. Simple and expressive enough.

- **Session lifecycle uses hooks.** `pre_start` / `post_stop` hooks on sessions,
  using the same hook system as flow stages. Consistent syntax everywhere.

- **Container types are generic and user-defined.** Only `issue` and `manager`
  are reserved. Everything else (sandbox, reviewer, perf-tester, etc.) is a
  user-defined template created via `agenttree new {type} {name}`. Replaces the
  hardcoded `agenttree sandbox` command.

- **Container inheritance with `extends`.** Abstract base types (underscore
  prefix) define shared config. Merge semantics depend on field type: scalars,
  hooks, roles, and sessions are **replaced** by the child. Mounts and env are
  **accumulated** (child adds to parent). This matches natural semantics — hook
  ordering matters (replace), mounts are additive (accumulate).

- **Container types list `roles` (plural).** `issue` containers list all roles
  that can operate within them (`roles: [developer, reviewer]`). Each role gets
  its own tmux session. Roles define the AI, container types define the infra.

- **Explicit `mounts` instead of magic `shares`.** Container types list their
  extra mounts as explicit `host:container:mode` paths. No named groups, no
  hidden behavior. Mounts accumulate through `extends` — child adds to parent,
  no repetition needed. System implicit mounts (worktree, .git, _agenttree) and
  tool mounts (Claude config, session storage, auth) don't appear in user config.
  Replaces the `--git` CLI flag.

- **Worktree creation is internal infrastructure.** The system creates worktrees
  before container startup based on context (issue_id, sandbox name, etc.).
  This stays in `api.py`, not in user-configurable hooks. User hooks
  (`pre_start`, `post_start`) are for custom setup on top of the worktree.

- **Manager Claude runs in a container.** The manager is containerized like any
  other agent, allowing `--dangerously-skip-permissions`. The orchestrator (web
  server + heartbeat) stays on the host — it manages tmux sessions and the
  container runtime. These are separate concerns: the orchestrator is infra,
  the manager Claude is an AI agent.

- **Container hooks distinguish host vs container execution.** `pre_start` and
  `post_stop` run on the host. `post_start` and `pre_stop` run inside the
  container. Matches the natural mental model.

- **Session ports declared per-session.** Each session lists `ports` it needs.
  At container startup, all ports from all sessions are collected and forwarded.

- **Two-level permission skipping.** Container `allow_dangerous` (default true)
  sets the ceiling. Role `dangerous` (default true) is per-role. Effective =
  `allow_dangerous AND dangerous`. Both default true so all containerized agents
  skip permissions out of the box. Users can lock down a container type or
  restrict a specific role without needing to define new container types.

- **Generic container builder with no type-specific branching.** The current
  `build_run_command()` is replaced by `build_container_command()` which layers:
  (1) implicit system mounts, (2) tool-specific mounts/env from tool config,
  (3) user mounts/env from container type config, (4) system env vars,
  (5) session ports, (6) tool entry command. No `if manager` / `if sandbox` /
  `if issue` logic. `start_manager()`, `start_issue_agent_in_container()`, and
  the sandbox code all collapse into one `start_container()` function.
  Tool-specific mounts (Claude config, session storage, OAuth token) are driven
  by tool config, not hardcoded — supporting future non-Claude tools.

- **Containers own tmux sessions, not vice versa.** Tmux sessions are the UI
  layer; containers are the source of truth. Start creates both, stop kills
  both. If they get out of sync (crash, manual kill), the heartbeat loop
  detects and fixes it. No user-configurable hooks needed for cleanup — it's
  infrastructure. `agenttree cleanup` remains as a manual escape hatch.

# Commands & Serving

The `commands` section of `.agenttree.yaml` lets you define custom shell commands
that agenttree runs at various points in the workflow. **Every command you define
is automatically runnable via `agenttree run <name>`.**

## The `commands` Section

```yaml
commands:
  serve: "npm run dev --port $PORT"
  test: "npm test"
  lint: "npm run lint"
  git_branch: "git branch --show-current"
  files_changed: "git diff --stat main...HEAD | grep -c '|' || echo 0"
  lines_added: "git diff --stat main...HEAD | tail -1 | awk '{print $4}' || echo 0"
  lines_removed: "git diff --stat main...HEAD | tail -1 | awk '{print $6}' || echo 0"
  duplicates: "pylint --enable=duplicate-code src/ 2>&1 | head -50"
```

### Running Commands

Any command in the `commands:` section can be run directly:

```bash
agenttree run serve           # Start dev server
agenttree run test            # Run tests
agenttree run lint            # Run linting
agenttree run duplicates      # Check for duplicate code
agenttree run my_custom_cmd   # Whatever you defined
```

`agenttree run <cmd>` automatically injects environment variables (`PORT`,
`AGENTTREE_ISSUE_ID`, etc.) before executing the command.

### Built-in Command Keys

Some command names have special meaning — agenttree uses them automatically:

| Command | When it runs | Purpose |
|---------|-------------|---------|
| `serve` | Agent container startup | Starts your project's dev server |
| `test` | Pre-completion hooks, CI checks | Runs the test suite |
| `lint` | Pre-completion hooks | Runs linting/type checking |
| `git_branch` | Stats collection | Reports current branch name |
| `files_changed` | Stats collection | Counts files changed vs main |
| `lines_added` | Stats collection | Counts lines added vs main |
| `lines_removed` | Stats collection | Counts lines removed vs main |
| `duplicates` | Code quality checks | Detects duplicate code |

You can add any custom commands you like. They're shell strings executed in
the agent's worktree directory.

## The `serve` Command

The `serve` command is special — it defines how your project is served inside
each agent's container. When an agent starts, agenttree launches the serve
command in a dedicated tmux session alongside the AI tool.

### How It Works

```
Container for issue #42
┌─────────────────────────────────────────┐
│                                         │
│  tmux session: "serve"                  │
│  └─ PORT=9042 npm run dev --port $PORT  │
│                                         │
│  foreground: claude (AI tool)           │
│                                         │
│  Port 9042 forwarded to host            │
└─────────────────────────────────────────┘
```

1. The `serve` command runs in a tmux session named `serve` inside the container
2. The AI tool runs in the foreground (as before)
3. The port is forwarded from the container to the host

### Port Assignment

Ports are deterministic with modulo wrapping. The range is **inclusive**:

```yaml
port_range: 9000-9100
```

| Context | Port | Notes |
|---------|------|-------|
| Manager | 9000 | Always gets the first port |
| Issue #1 | 9001 | |
| Issue #42 | 9042 | |
| Issue #99 | 9099 | |
| Issue #100 | 9100 | Last port in range |
| Issue #101 | 9001 | Wraps around (reuses #1's port) |

The manager always gets `port_min` (9000). Issues (which always start at 1) use
`port_min + (issue_id % range_size)`, with `remainder == 0` mapping to
`port_max`. Since issues never have id 0, port 9000 is exclusively the
manager's — no conflict. 100 issue slots (9001-9100) that wrap for high issue
numbers.

### Environment Variables

Inside every container, agenttree sets these environment variables:

| Variable | Example | Description |
|----------|---------|-------------|
| `PORT` | `9042` | Assigned port for this agent's dev server |
| `AGENTTREE_CONTAINER` | `1` | Always `1` when inside a container |
| `AGENTTREE_ISSUE_ID` | `42` | Issue number this agent is working on |
| `AGENTTREE_ROLE` | `developer` | Agent role (developer, reviewer, etc.) |

These are available **everywhere** in the container — not just in the serve
command. The AI tool, scripts, hooks, and any process can read them.

### Examples

**Node.js project:**
```yaml
commands:
  serve: "npm run dev -- --port $PORT"
```

**Python Django:**
```yaml
commands:
  serve: "python manage.py runserver 0.0.0.0:$PORT"
```

**Python FastAPI:**
```yaml
commands:
  serve: "uvicorn app.main:app --host 0.0.0.0 --port $PORT --reload"
```

**Static site / Vite:**
```yaml
commands:
  serve: "npx vite --port $PORT --host"
```

**Rails:**
```yaml
commands:
  serve: "rails server -p $PORT -b 0.0.0.0"
```

**Custom script with setup:**
```yaml
commands:
  serve: "./scripts/dev-server.sh"
```

Where `scripts/dev-server.sh` might be:
```bash
#!/bin/bash
# Run migrations first
python manage.py migrate --no-input
# Then start the dev server
exec python manage.py runserver 0.0.0.0:$PORT
```

### Dogfooding: AgentTree on AgentTree

When using agenttree to develop agenttree itself, the serve command needs to
start the agenttree web server without recursively starting agents. Use
`agenttree server`, which starts just the web server:

```yaml
commands:
  serve: "uv run agenttree server --port $PORT"
```

`agenttree server` starts the web UI without launching any agents or the
manager. This avoids the recursion that would happen if each container
tried to start more containers.

## Accessing Serve Logs

The serve session runs in a tmux session named `{project}-serve-{issue_id}`.
You can access it directly via tmux:

```bash
# View serve output for issue #42
tmux capture-pane -t myapp-serve-042 -p

# Attach to the serve tmux session (interactive)
tmux attach -t myapp-serve-042
```

## CLI Quick Reference

| Command | Purpose |
|---------|---------|
| `agenttree start` | Start everything (server + agents + manager) |
| `agenttree start 42` | Start agent for issue #42 |
| `agenttree server` | Start just the web server (no agents) |
| `agenttree run serve` | Run the serve command from config |
| `agenttree run test` | Run the test command from config |
| `agenttree run <cmd>` | Run any command from the `commands:` config |

## Dev Server URL in the Dashboard

The web dashboard shows each issue's dev server port in the issue detail view.
The port link appears in green when the serve session is running, and gray when
it's stopped. You can click the link to open the dev server in your browser.

Since ports are deterministic, you always know which port to expect for a given
issue — even before starting the agent.

## Roles vs Sessions

Agenttree has two concepts for tmux processes:

**Roles** are AI agent sessions. They have a `tool`, `model`, and optionally a
`skill`. When a role starts, it creates a tmux session running an AI tool (like
Claude). Roles are defined in the `roles:` config:

```yaml
roles:
  developer:
    tool: claude
    model: opus
  reviewer:
    tool: claude
    model: sonnet
    skill: independent_review.md
```

**Sessions** are any tmux process alongside the AI tool. Currently, the `serve`
command is the built-in session type — it starts automatically when an agent
starts if the `serve` command is configured.

### Session Naming

Sessions use the naming pattern `{project}-{type}-{issue_id}`:

| Source | Tmux session |
|--------|--------------|
| Role: developer | `myapp-developer-042` |
| Role: reviewer | `myapp-reviewer-042` |
| Serve session | `myapp-serve-042` |

## No `serve` Command? No Problem

The `serve` command is optional. If you don't configure it:

- No dev server is started in containers
- No port is exposed
- The AI tool runs normally (just without a dev server alongside it)

This is fine for projects that don't need a running server during development
(CLI tools, libraries, etc.).

## Writing Custom Commands

Commands are shell strings executed in the agent's worktree directory. Tips:

- **Use `$PORT`** for port references — it's always set
- **Use `$AGENTTREE_ISSUE_ID`** for issue-specific logic
- **Use `$AGENTTREE_ROLE`** to vary behavior by role
- **Multiline commands** work with YAML `|` syntax
- **Scripts** are fine — reference a script file in your repo
- **Exit codes matter** — for `test` and `lint`, non-zero means failure
- **Stdout/stderr** are captured for hooks that check output

### Environment Variables Reference

Available in all commands (inside containers):

| Variable | Example | Available in |
|----------|---------|-------------|
| `PORT` | `9042` | All commands |
| `AGENTTREE_CONTAINER` | `1` | All commands (containers only) |
| `AGENTTREE_ISSUE_ID` | `42` | All commands (containers only) |
| `AGENTTREE_ROLE` | `developer` | All commands (containers only) |
| `GITHUB_TOKEN` | `ghp_xxx` | If configured |
| `ANTHROPIC_API_KEY` | `sk-ant-xxx` | If configured |

On the host (manager, agent 0), only `PORT` is set (as a prefix on the serve
command). The `AGENTTREE_*` vars are container-specific.

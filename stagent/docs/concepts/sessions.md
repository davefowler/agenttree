# Sessions

A *session* is a Claude session ID — the UUID Claude Code uses to persist conversation history across invocations. stagent generates these UUIDs itself, records them in the event log, and uses `claude --resume <uuid>` to continue conversations across stages, retries, and redirect loops.

This page covers how sessions are scoped, how the UUIDs are captured, and what `bound:` means.

## The scope decision: `bound:`

A role declares its session scope via the `bound:` field:

```yaml
roles:
  developer:
    model: opus
    bound: task        # one session per (task, role) — default

  reviewer:
    model: sonnet
    bound: stage       # fresh session each time the reviewer enters
```

| `bound:` | Session key | Behavior | Use when |
|---|---|---|---|
| `stage` | `(task, role, stage, entry_number)` | Fresh memory every time the role enters a stage. | Fresh-eyes reviewers, audit-style roles. |
| `task` *(default)* | `(task, role)` | One session per role per task. Continues across all stages, retries, and redirect loops for that role. | Developers, anyone who benefits from continuity across the work. |
| `run` | `(runner_id, role)` | One session per role across all tasks within one `stagent run` invocation. | **v1: errors if used** — deferred (see below). |
| `forever` | `(role)` | One session per role, persists across runner restarts. | **v1: errors if used** — deferred. |

`task` is the default because it preserves context where it matters (review loops, retries, multi-stage same-role work) while keeping tasks isolated from each other.

`stage` is the opt-in for roles where amnesia is a feature — typically reviewers, where you want each review pass to be independent of memory from prior reviews. (Note that even with `bound: stage`, the reviewer still **sees** prior passes by reading the task file. The bind controls memory, not visibility.)

### Why `run` and `forever` are deferred

Claude Code stores session JSONLs under the encoded current working directory: `~/.claude/projects/<cwd-encoded>/<uuid>.jsonl`. Each stagent task has a different CWD (its worktree), so sessions naturally key by worktree. Supporting `run`/`forever` would require either always invoking `claude` from a fixed CWD (and having the agent navigate via paths) or accepting that resume-across-CWDs has quirks. Doable; not v1.

The constants exist in the Go code so flags can be specified now and the runner will produce a clear error rather than silently misbehaving.

## How UUIDs are captured

stagent generates the session UUID itself rather than scanning Claude's project directory for it. The flow:

1. `uuid := uuid.NewV4()`
2. Emit `session.started` event with the UUID and the (eventual) PID.
3. Invoke:
   ```bash
   claude -p "<stage prompt>" \
     --session-id <uuid> \
     --system-prompt "$(cat .stagent/prompts/roles/<role>.md)" \
     --dangerously-skip-permissions
   ```
4. For subsequent invocations (same `(task, role)`):
   ```bash
   claude -p "<stage prompt + redirect message if any>" \
     --resume <uuid> \
     --dangerously-skip-permissions
   ```

Note that `--system-prompt` is only passed on the **first** invocation. After that, the role prompt is already baked into the session's transcript. Resuming with `--system-prompt` again would be ignored.

### Encoded CWD

Claude stores the JSONL at `~/.claude/projects/<encoded-cwd>/<uuid>.jsonl`. The encoding replaces `/` with `-`, prefixed by the leading dash from the leading slash:

```
/Users/dave/proj/.worktrees/task-042
→
-Users-dave-proj--worktrees-task-042
```

stagent doesn't read or write these files — Claude does. We only need the UUID, and we know it because we minted it.

## Resume semantics

`--resume <uuid>` re-attaches to the same conversation. The agent sees:

1. Its own system prompt (set originally).
2. All prior `claude -p` invocations' prompts.
3. All its prior responses (and tool calls).
4. The new prompt you just sent.

For a `code → review → code → review → ...` loop with `developer` bound to `task`, the developer sees its complete history across every cycle — what was implemented, what the reviewer pushed back on, what was changed. This is the whole point of `bound: task`.

For `reviewer` bound to `stage`, each entry generates a fresh UUID, so the reviewer has no memory of prior reviews. It still **reads** prior `### Pass N` blocks in the task file (which lives on disk) and uses them as input. The reviewer prompt explicitly tells it to do so.

## When sessions end

Sessions end in two ways:

1. **Stage completes normally.** The Claude process exited; the runner emits `session.ended(reason: "completed", exit_code: 0)`. The UUID is still valid — if the role is `bound: task` and re-enters another stage on the same task, the runner will `--resume` it.
2. **Stage fails terminally.** `stage.failed` was emitted (budget exhausted). The session is left as-is in Claude's project directory but no future runner invocation will resume it for this task. Manually you can `claude --resume <uuid>` from the worktree to debug.

The runner never invokes `--no-session-persistence`. We always want the JSONL to exist for inspection and resume.

## Crash recovery and sessions

If the runner dies mid-agent (OOM, kill, segfault), the Claude child process gets reparented to PID 1 and the runner loses its handle. On the next runner start:

1. The runner reads the event log: for any `session.started` without a matching `session.ended`, it has an orphan to deal with.
2. `kill(pid, 0)` to test liveness.
3. Regardless of alive/dead, the runner emits `session.ended` with `reason: "runner_restart_orphan"`. The retry budget handles the rest — typically the stage retries with `--resume <uuid>`, and the JSONL is intact so the agent picks up where it left off.

There's no special "reattach to a running child" code path. The model is "if you crashed, treat it as if the agent exited; let the hooks decide."

## Debugging sessions by hand

To resume a session in a real Claude Code terminal (e.g. to interactively debug what the agent was doing):

```bash
SID=$(stagent session <task-id> <role>)
cd <task's worktree>
claude --resume "$SID"
```

`stagent session <id> <role>` queries the `sessions` view and prints the UUID. The `.stagent.yaml` default config defines a `resume` command that wraps this:

```yaml
commands:
  resume:
    desc: Resume the developer's session in a real Claude Code terminal
    run: |
      SID=$(stagent session {{.Task.ID}} developer)
      cd {{.Task.WorktreeDir}} && claude --resume "$SID"
```

Invoke as `stagent resume 42`. The agent gets a fresh interactive prompt; whatever you type goes into the same JSONL the runner uses. When you `/exit`, the next runner tick will see the process is gone and run exit hooks.

This is the escape hatch for "the agent is stuck; let me drive."

## Verification

Verified against `claude` 2.1.143:

- `claude -p --session-id <uuid> "<prompt>"` accepts a caller-supplied UUID and writes the transcript to `~/.claude/projects/<encoded-cwd>/<that-uuid>.jsonl`.
- `claude --resume <uuid> -p "<msg>"` works in headless mode and appends to the same JSONL.
- `--dangerously-skip-permissions` is refused when running as root.
- `--no-session-persistence` exists if we ever want one-shot agents (we don't, currently).

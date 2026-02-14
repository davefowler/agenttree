# FormalTask: Deep Dive Analysis

**Repository:** [github.com/davidabeyer/formaltask](https://github.com/davidabeyer/formaltask)
**License:** MIT | **Language:** Python 3.11+ | **Published:** February 2026

---

## What It Is

FormalTask is a structured task management and orchestration system designed specifically for AI-assisted development workflows. It coordinates multiple parallel Claude Code agents, each working in isolated git worktrees, through a rigorous lifecycle of planning, implementation, code review, and completion.

The core problem it solves: **how do you coordinate multiple AI coding agents working in parallel on the same codebase without them stepping on each other, producing low-quality output, or going off the rails?**

Without something like FormalTask, running multiple AI agents simultaneously results in merge conflicts, inconsistent quality, no structured review process, and no way to track what each agent is doing. FormalTask provides the scaffolding -- epics, tasks, dependency graphs, quality gates, review cycles, and automated orchestration -- to make parallel AI development reliable and auditable.

---

## Core Concepts

### Epics
Top-level containers for related work. An epic has a name, description, optional feature branch, and contains multiple tasks. Epics go through a planning lifecycle (`plan` -> `critique` -> `revise` -> `decompose`) before tasks are created. This is an 8-stage planning state machine with critique loops, spec decomposition, and test strategy planning -- all before any code is written.

### Tasks
Individual units of work within an epic. Each task has:
- A **status** from a 9-state state machine: `open`, `in_progress`, `pending_merge`, `completed`, `pending_review`, `blocked_user`, `blocked`, `deferred`, `cancelled`
- **Acceptance criteria** -- plain text or executable shell commands (with a 300-second timeout)
- **Dependencies** on other tasks, preventing out-of-order execution
- **Metadata** (JSON), artifacts, review history, PR URL, session ID

### Workers
Isolated Claude Code sessions running in tmux, each operating in a dedicated git worktree (`~/.claude/worktrees/task-{id}`). Workers are fire-and-forget processes that follow a TDD methodology. Up to 10 can run in parallel.

### Completion Rules
A rules kernel with 22 built-in rules that evaluates whether a task is truly "done." Rules check for: review existence, blocking findings, PR status, documentation, acceptance criteria passing, and more. Uses a first-match-wins evaluation strategy with AND/OR/NOT combinators and dotted-path resolution.

### Reviews and Findings
Structured code review data stored per-task with round-based append-only semantics. Findings have priorities (P0/P1/P2) and dispositions (`wontfix`, `fixed`, `needshuman`). Blocking findings prevent task completion. Review freshness is tracked -- if code changes after a review, it's automatically marked stale.

### Formulas
YAML/Jinja2 templates for generating parameterized epic structures. Solves the problem of repeating identical task shapes across epics.

### Delta Handoff
A system that preserves critical context (decision rationale, failed approaches, user corrections) across conversation compaction events. When Claude's conversation history is compressed, delta handoff snapshots the transcript and extracts key decisions via LLM processing (using OpenRouter/Gemini 2.5 Pro), preventing context loss.

### Skill Spans
Database-backed tracking of which skill steps have been visited during a session. Enables step dependency enforcement and skill composition.

---

## Architecture

### Tech Stack
| Component | Choice |
|-----------|--------|
| Language | Python 3.11+ |
| Database | SQLite (WAL mode) at `.claude/formaltask.db` |
| Process Isolation | tmux 3.2+ sessions + git worktrees |
| TUI Framework | Textual (Rich-based) |
| LLM Integration | OpenRouter API (default: Gemini 2.5 Pro) via Instructor |
| Validation | Pydantic models |
| CLI | Click (`ft` command) |
| Templates | Jinja2 with StrictUndefined |
| Testing | pytest with coverage |
| Static Analysis | ruff + basedpyright |
| Git Integration | GitHub CLI (`gh`) |

### Layers (bottom to top)

1. **SQLite Database** (`formaltask/db/`) -- 10 tables including `epics`, `tasks`, `acceptance_criteria`, `task_reviews`, `finding_dispositions`, `commits`, `work_sessions`, `plan_documents`, `planning_state`, `schema_migrations`. Views for epic status, ready tasks, and blocked tasks.

2. **Core Domain** (`formaltask/core/`) -- The rules kernel, 22 built-in completion rules, completion state gathering, and completion checking.

3. **Task Management** (`formaltask/tasks/`) -- CRUD operations, lifecycle/state machine, dependency resolution, spawnability checks, guard rails.

4. **Worker Management** (`formaltask/workers/`) -- Spawner (worktree creation + tmux), orchestrator (auto-spawn cycles), health monitoring, crash detection, instructions builder, inbox (blocked worker messaging), disposition handling.

5. **Git Integration** (`formaltask/git/`) -- Worktree management with triple-verified safety cleanup, GitHub PR queries, git utilities.

6. **Epic Planning** (`formaltask/epics/`) -- Pydantic models, planning workflow state machine, YAML parsing, validation.

7. **Review System** (`formaltask/review/`) -- ReviewPacket schema with Pydantic validation and finding normalization.

8. **Hook System** (`formaltask/hooks/`) -- Six hook types (PreToolUse, PostToolUse, SessionStart, SessionEnd, SubagentStop, SubagentStart) registered in Claude Code's `settings.json`. 15+ validators for path enforcement, SQL injection prevention, bash file guarding, stub detection, tool redirection, and more.

9. **CLI** (`formaltask/cli/`) -- 40+ command files organized under noun-verb pattern (`ft epic list`, `ft task add`, `ft work spawn`).

10. **TUI Dashboard** (`formaltask/apps/dashboard/`) -- Textual app with task list, terminal pane, status bar, and inbox screen. Real-time polling at 400ms intervals.

11. **Agents** (`agents/`) -- 80+ markdown agent definition files for specialized review and analysis tasks.

---

## End-to-End Workflow

### Phase 1: Planning
1. User creates an epic via `ft epic create` or the planning skill.
2. The planning workflow progresses through 8 stages tracked in `planning_state`: `plan` -> `critique` -> `revise-plan` (loop) -> `plan-decompose` -> `critique-specs` -> `revise-specs` -> `plan-test-strategy` -> `epic-decompose`.
3. Each stage has round tracking. The `begin_stage()` function atomically increments the round counter.
4. Tasks are decomposed from the epic plan and created in batch, with position-based dependency resolution.

### Phase 2: Worker Spawning
1. `get_spawnable_tasks()` identifies tasks that are in non-archived epics, in `open` status, have all dependencies satisfied, and have no file conflicts with currently running workers.
2. `spawn_worker()` validates task ID (prevents path traversal and shell injection), auto-cleans stale worktrees, creates a git worktree with a dedicated branch, creates a `.task/` binding directory, initializes TDD Guard, and spawns a tmux session with Claude Code (`--permission-mode bypassPermissions`).
3. Retries up to 3 times if the pane dies immediately.
4. The orchestrator manages the overall spawn loop, respects worker caps (1-10), and handles errors.

### Phase 3: Implementation
1. Each worker receives injected instructions: task assignment, TDD methodology guidelines, quality standards, review resolution workflow, completion steps, and escalation procedures.
2. PreToolUse hook validators block deprecated paths, dangerous SQL, raw bash file operations, `--no-verify` flags, and more.
3. Workers create PRs against the target branch when implementation is complete.

### Phase 4: Review
1. Reviews are stored with round-based semantics. Each review has a type (code-quality, test-audit, etc.), severity, and findings list.
2. `ReviewPacket` validates and normalizes review data via Pydantic before database insertion.
3. 80+ specialized agent definitions provide narrow-expert reviewers (dead-code-function-hunter, test-bloat-mock-hunter, sqlite-reviewer, security-auditor, etc.).

### Phase 5: Completion
1. `fetch_completion_state()` gathers all state: task status, review presence, blocking findings, PR state, documentation, acceptance criteria results, review freshness.
2. `apply_completion_rules()` evaluates 22 built-in rules in order (first match wins).
3. Blocking conditions include: missing reviews, unresolved P0/P1 findings, stale reviews, failed acceptance criteria, missing or unmerged PR, missing documentation, critical findings marked `needshuman`.

### Phase 6: Cleanup
`cleanup_stale_worktrees()` runs automatically before each spawn, performing 8 safety checks before deletion (no uncommitted changes, no active tmux session, PR merged, no open PRs, no unpushed commits).

---

## Key Features

1. **Parallel AI Agent Orchestration** -- Up to 10 Claude Code agents simultaneously, each in isolated worktrees with automatic spawn/kill management.

2. **Interactive TUI Dashboard** -- Real-time monitoring with color-coded health states (LIVE, EXIT, HELP, FIX, queued), terminal pane, j/k navigation, attach/kill/spawn hotkeys, and an inbox for blocked workers.

3. **Rules Kernel** -- A unified condition evaluation engine (DSL with AND/OR/NOT, comparisons, dotted-path resolution) powering completion gating, tool redirection, orchestration rules, and worker templates.

4. **Hook-Based Enforcement** -- 15+ validators running as Claude Code hooks for path validation, SQL injection prevention, bash file guarding, `--no-verify` blocking, stub detection, and tool redirection.

5. **Structured Review Pipeline** -- Multi-round reviews with finding tracking, priority levels (P0/P1/P2), disposition management, review freshness checking (compares reviewed SHA to HEAD).

6. **Dependency-Aware Scheduling** -- Tasks declare dependencies; the spawner won't launch until all dependencies are satisfied. File-level conflict detection prevents two workers from editing the same files.

7. **Delta Handoff** -- Preserves conversation context across Claude's compaction events via LLM-powered transcript summarization.

8. **Formula System** -- Jinja2-based YAML templates for generating parameterized epic structures.

9. **80+ Specialized Reviewer Agents** -- Many narrow experts instead of one broad generalist (dead-code-hunter, test-bloat-detector, sqlite-reviewer, state-machine-reviewer, security-auditor, etc.).

10. **TDD Enforcement** -- Workers are instructed and hook-enforced to follow test-driven development.

---

## Design Philosophy

**Database as Source of Truth** -- Everything lives in SQLite (WAL mode). No in-memory state. Multiple independent processes (workers, hooks, dashboard) coordinate through the database without shared memory.

**Rules-Based Gating, Not Trust** -- Rather than trusting AI agents to self-assess completion, FormalTask enforces structural quality gates through a rules kernel. You cannot complete a task without reviews, passing acceptance criteria, and a PR.

**Many Narrow Experts** -- 80+ specialized agent definitions rather than one general-purpose reviewer. Each agent is tuned for a specific concern (dead code, test bloat, SQL patterns, security, etc.).

**Hook-Based Extension** -- Rather than modifying Claude Code, FormalTask uses its hook system to inject constraints. This avoids forking the underlying tool at the cost of being limited to what hooks can intercept.

**Fail-Open for Infrastructure, Fail-Closed for Quality** -- Infrastructure checks (tmux status, database locks, git operations) fail open. Quality checks (reviews, findings, PR status) fail closed.

**Antirez-Style Minimalism** -- Explicitly cited in project conventions. Minimal, direct code with no unnecessary abstraction. Dead code, half-finished refactors, and defensive "just in case" patterns are rejected.

---

## Notable Implementation Details

- **Custom SQLite wrapper** with WAL mode, foreign keys, busy timeout (5s), exclusive transactions with automatic commit/rollback. Skips WAL for test databases.
- **Task state machine** with 9 states and explicit valid transitions. Uses `COALESCE` in SQL updates to preserve timestamps. Supports idempotent and force modes.
- **Triple-verified worktree safety** -- 8 sequential checks before allowing deletion. Uses `gh pr list` to verify PR merge status, falls back to `git merge-base --is-ancestor`.
- **Spawn retry logic** -- 3 retries with 10-second waits, checking `is_pane_alive()` to detect immediate crashes.
- **Review freshness** -- Compares reviewed commit SHA against HEAD, checking if code files (`.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.sql`, `.sh`) changed. Non-code changes don't invalidate reviews.
- **Stale git lock cleanup** -- Checks for `index.lock` files older than 5 minutes and removes them.
- **SIGTERM trap in workers** -- Logs termination events to `~/.claude/worker_signals.log` for post-mortem analysis.
- **Schema migrations** tracked in a dedicated database table with named migrations.
- **Batch task creation** -- Two-phase approach: insert all tasks with empty deps, then resolve position-based dependencies to actual IDs. Avoids chicken-and-egg forward reference problems.

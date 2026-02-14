# AgentTree vs FormalTask: Similarities and Differences

Two projects, independently built, attacking the same problem: **orchestrating multiple AI coding agents in parallel on a single codebase**. Both emerged in early 2026 as developers realized that a single Claude Code session is a bottleneck, and that running multiple agents requires real infrastructure -- not just "open more terminal tabs."

This document breaks down where they converge, where they diverge, and what each project's choices reveal about its design philosophy.

---

## The Shared Problem

Both projects exist because of the same insight: AI coding agents are powerful but slow. A single agent working on a complex feature might take 30-60 minutes. If you have 5 features to build, you don't want to wait 5 hours -- you want 5 agents working in parallel for 1 hour. But parallel AI agents create real coordination problems:

- **Code conflicts** -- Two agents editing the same file
- **Quality control** -- No one reviewing the AI's output
- **State management** -- Tracking what each agent is doing
- **Lifecycle management** -- Starting, stopping, monitoring, restarting
- **Isolation** -- Preventing agents from interfering with each other

Both projects solve all five problems. How they solve them is where it gets interesting.

---

## Core Similarities

### 1. Git Worktrees as the Isolation Primitive
Both projects independently arrived at the same solution for code isolation: **git worktrees**. Each agent gets its own worktree (a separate checkout of the same repository), its own branch, and can commit/push without affecting other agents.

This is a significant shared insight. Neither project uses Docker volume mounts or copy-on-write filesystems for code isolation. Git worktrees are elegant because they provide filesystem isolation while maintaining shared git history, and merging is just a normal git operation.

### 2. tmux as the Process Manager
Both use **tmux** as the process management layer. Each agent runs in its own tmux session, which provides:
- Detached execution (agents run in the background)
- Session persistence (survives terminal disconnects)
- Output capture (read what the agent is doing)
- Interactive attachment (jump into an agent's session)
- Message passing (send keystrokes to a running agent)

Neither project built a custom process manager or used something like systemd/supervisord. tmux is the pragmatic choice -- it's ubiquitous, battle-tested, and provides exactly the right abstraction level.

### 3. Structured Stage-Based Workflows
Both enforce a **structured workflow** where work progresses through defined stages:

| AgentTree | FormalTask |
|-----------|-----------|
| `explore.define` -> `explore.research` -> `plan.draft` -> `plan.review` -> `implement.code` -> `implementation_review.code_review` -> `implementation_review.implementation_review` -> `accepted` | `plan` -> `critique` -> `revise` -> `decompose` -> `implement` -> `review` -> `complete` |

Both reject the "just let the AI code" approach. Both force planning before implementation and review before completion.

### 4. Human Review Gates
Both include **mandatory human checkpoints** where an AI agent cannot proceed without human approval. In AgentTree, stages like `plan.review` and `implementation_review.implementation_review` require human sign-off via `agenttree approve`. In FormalTask, the `blocked_user` and `needshuman` states route work back to a human.

### 5. Hook Systems for Enforcement
Both use **hook systems** to enforce quality gates at workflow transitions:
- AgentTree: YAML-configured validators (file_exists, section_check, has_commits, ci_check) that run on stage transitions
- FormalTask: Claude Code hooks (PreToolUse, PostToolUse, SessionStart) with 15+ validators for path enforcement, SQL injection prevention, etc.

Both reject trust-based quality -- they verify structurally.

### 6. Dependency Management Between Tasks
Both support **task/issue dependencies** where work items can declare dependencies on other work items, and the system won't start dependent work until prerequisites are complete.

### 7. PR Integration
Both integrate with **GitHub PRs** as a core part of the workflow. Both can create PRs automatically, monitor CI status, and track merge state.

### 8. Anti-Slop Design Philosophy
Both projects explicitly cite **antirez-style minimalism** in their project conventions. Both have "anti-slop" rules rejecting dead code, unnecessary abstraction, backwards compatibility cruft, and cowardly defensive coding. This is a shared aesthetic that likely reflects the same frustration: AI agents tend to generate bloated, over-abstracted code, and the projects that orchestrate them should be the opposite.

### 9. CLI-First Interface
Both provide **CLI tools** as the primary interface:
- AgentTree: `agenttree` command with subcommands (start, stop, send, status, approve, etc.)
- FormalTask: `ft` command with noun-verb pattern (ft epic list, ft task add, ft work spawn, etc.)

### 10. Worktree Safety
Both implement **multi-check safety systems** before deleting worktrees. Neither will remove a worktree with uncommitted changes, active sessions, or unmerged PRs.

---

## Key Differences

### 1. State Storage: Files vs Database

**AgentTree: File-based (YAML + git)**
- Issue state lives in YAML files in `_agenttree/issues/`
- `_agenttree/` is a separate git repository (gitignored from main repo)
- State changes are git commits -- you get a full audit trail for free
- Agent state is **derived from tmux sessions** at runtime, not stored

**FormalTask: SQLite database**
- Everything in `.claude/formaltask.db` with WAL mode
- 10 tables: epics, tasks, reviews, findings, planning_state, etc.
- Multiple processes coordinate through the database
- Schema migrations tracked in a dedicated table

**What this means:** AgentTree's approach is more transparent (you can `cat` any YAML file to see state) and more resilient (git handles conflicts, corruption recovery). FormalTask's approach is more performant for complex queries (find all blocked tasks with stale reviews) and provides stronger transactional guarantees. AgentTree bets on simplicity; FormalTask bets on queryability.

### 2. Hierarchy: Flat Issues vs Epic/Task

**AgentTree: Flat issue list**
- Issues are independent units of work
- Dependencies exist but there's no grouping concept
- Each issue goes through its own workflow independently
- Simpler mental model

**FormalTask: Two-level Epic/Task hierarchy**
- Epics contain multiple tasks
- Epics go through their own planning lifecycle before spawning tasks
- Tasks inherit context from their parent epic (feature branch, etc.)
- More structured decomposition of large features

**What this means:** AgentTree is simpler for "here are 5 independent things to do." FormalTask is more powerful for "here's a big feature -- decompose it into tasks, plan them, then execute." The epic planning workflow (8 stages of plan/critique/revise loops) is a distinctive FormalTask capability that has no AgentTree equivalent.

### 3. Container Support

**AgentTree: Full container sandboxing**
- Agents run inside containers (Apple Containers on macOS 26+, Docker, or Podman)
- Runtime abstraction layer hides container engine differences
- Mounts worktree, .git, and _agenttree into container
- Port allocation for dev servers
- Real security boundary between agents and host

**FormalTask: No containers**
- Agents run directly on the host in tmux sessions
- Isolation is at the git worktree level only (filesystem) + tmux (process)
- Hooks provide guardrails but not security boundaries

**What this means:** AgentTree provides stronger isolation -- a misbehaving agent can't access host files outside its mounts. FormalTask trades security for simplicity and lower overhead. For trusted environments (your own laptop), FormalTask's approach is pragmatic. For shared or production environments, AgentTree's containers matter.

### 4. Web UI vs TUI

**AgentTree: Web dashboard (FastAPI + HTMX)**
- Kanban board view with drag-and-drop
- Flow view for review-focused workflow
- WebSocket streaming of live terminal output
- Issue detail pages with all documents
- Runs on port 8080, accessible from any browser
- Optional HTTP Basic auth for public exposure

**FormalTask: Terminal TUI (Textual/Rich)**
- Real-time task list with color-coded health states
- Embedded terminal pane showing selected worker's output
- j/k navigation, hotkeys for attach/kill/spawn
- Inbox screen for blocked workers needing human input
- 400ms polling interval for live updates

**What this means:** AgentTree's web UI is more accessible (works in any browser, shareable) and visually richer (Kanban boards). FormalTask's TUI is faster (no network round-trips), more keyboard-driven, and works over SSH without port forwarding. Different ergonomic philosophies -- AgentTree optimizes for visual overview, FormalTask optimizes for hands-on-keyboard control.

### 5. Review System

**AgentTree: Human-centric reviews**
- Reviews are primarily human review stages (`plan_review`, `implementation_review`)
- Reviewer role can be a separate AI agent, but it's one agent
- Review output is freeform markdown documents
- Binary outcome: approve or send back

**FormalTask: Structured multi-agent reviews**
- 80+ specialized reviewer agent definitions (dead-code-hunter, test-bloat-detector, sqlite-reviewer, security-auditor, etc.)
- Reviews stored as structured data with typed findings (P0/P1/P2 priorities)
- Finding disposition tracking (wontfix, fixed, needshuman)
- Review freshness detection (stale if code changed since review)
- Round-based append-only semantics
- Multiple review types per task

**What this means:** FormalTask's review system is significantly more sophisticated. The "many narrow experts" approach means each reviewer agent is tuned for a specific concern. The structured finding/disposition system creates an auditable paper trail. AgentTree's reviews are simpler and more human-oriented -- the system doesn't try to automate the judgment, just the workflow around it.

### 6. Completion Gating

**AgentTree: Hook-based validators**
- Validators run on stage transitions (file_exists, section_check, has_commits, ci_check, pr_approved)
- Validators can block transitions or redirect to different stages
- Configured in YAML per stage
- Relatively simple conditions

**FormalTask: Rules kernel**
- 22 built-in completion rules evaluated in first-match-wins order
- DSL with AND/OR/NOT combinators and dotted-path resolution
- Rules check: review existence, blocking findings, PR state, documentation, acceptance criteria execution (shell commands with 300s timeout), review freshness
- Task-level custom rules can extend the kernel
- Completion state gathered from multiple sources before evaluation

**What this means:** FormalTask's completion system is more rigorous and more complex. The rules kernel is a real DSL that can express sophisticated conditions. AgentTree's validators are simpler but sufficient for most workflows. FormalTask pays for rigor with complexity -- the rules kernel has to be understood, ordered correctly, and debugged when things don't work as expected.

### 7. Planning Workflow

**AgentTree: Stage-integrated planning**
- Planning is stages in the workflow (explore.define -> explore.research -> plan.draft -> plan.review)
- Agent works through stages sequentially, producing documents (problem.md, research.md, spec.md)
- Human reviews plan before implementation begins
- Skills/templates guide agent through each stage

**FormalTask: Dedicated epic planning system**
- 8-stage planning state machine with critique loops
- LLM-powered planning (uses OpenRouter/Gemini 2.5 Pro, separate from the coding agents)
- Round tracking with atomic stage transitions
- Plan decomposition creates tasks in batch with dependency resolution
- Formula system for generating parameterized epic structures

**What this means:** FormalTask treats planning as a first-class subsystem with its own state machine, LLM integration, and data model. AgentTree treats planning as stages in the same workflow as implementation. FormalTask's approach enables more sophisticated plan-critique-revise cycles, but adds significant complexity. AgentTree's approach is simpler and keeps everything in one mental model.

### 8. Context Preservation

**AgentTree: Skills + templates**
- Jinja2-rendered skill files provide stage-specific instructions
- Templates generate starting documents with proper structure
- AGENTS.md system prompt loaded for all agents
- Role-specific personas (developer.md, reviewer.md)
- No explicit mechanism for preserving context across compaction

**FormalTask: Delta Handoff system**
- Explicit system for preserving context across Claude's conversation compaction events
- Snapshots transcripts and extracts key decisions/failures/corrections via LLM processing
- Prevents context loss when conversation history is compressed
- Also: skill spans track which steps have been visited in a session

**What this means:** Delta Handoff is a unique FormalTask innovation that addresses a real problem -- when Claude's context window fills up and older messages are compressed, important decisions can be lost. AgentTree doesn't have an equivalent mechanism, relying instead on the documents (research.md, spec.md) serving as persistent external memory.

### 9. Tool Flexibility

**AgentTree: Multi-tool support**
- Supports Claude Code, Aider, Codex, and custom tools
- Tools defined in `.agenttree.yaml` with custom commands and startup prompts
- Different tools can be assigned to different roles
- Tool-agnostic architecture

**FormalTask: Claude Code only**
- Tightly coupled to Claude Code's hook system (PreToolUse, PostToolUse, etc.)
- Workers spawned with `claude --permission-mode bypassPermissions`
- Hook validators are Claude Code-specific
- Uses OpenRouter for planning LLM calls (not for coding)

**What this means:** AgentTree is more flexible -- you could swap in a different AI coding tool without changing the orchestration layer. FormalTask is more deeply integrated with Claude Code, which enables powerful hook-based enforcement but creates lock-in.

### 10. Remote Execution

**AgentTree: Remote agent support**
- `agenttree remote list` / `agenttree remote start` commands
- Tailscale integration for discovering remote hosts
- Can distribute agents across multiple machines

**FormalTask: Local only**
- All workers run on the local machine
- No remote execution support

---

## Architecture Comparison Summary

| Aspect | AgentTree | FormalTask |
|--------|-----------|-----------|
| **State storage** | YAML files in git repo | SQLite database (WAL) |
| **Work hierarchy** | Flat issues | Epics containing tasks |
| **Agent isolation** | Container + worktree + tmux | Worktree + tmux |
| **UI** | Web (FastAPI + HTMX) | TUI (Textual/Rich) |
| **Reviews** | Human-centric, freeform | Multi-agent, structured findings |
| **Completion gating** | YAML-configured validators | 22-rule DSL kernel |
| **Planning** | Stages in workflow | Dedicated 8-stage subsystem |
| **Context preservation** | Skills + templates + docs | Delta Handoff + skill spans |
| **AI tool support** | Multi-tool (Claude, Aider, etc.) | Claude Code only |
| **Remote execution** | Yes (Tailscale) | No |
| **Hook system** | Stage transition hooks | Claude Code hooks |
| **Config format** | `.agenttree.yaml` | SQLite + `settings.json` |
| **Reviewer specialization** | Single reviewer role | 80+ specialized agents |
| **Agent limit** | Unlimited (practical ~4-8) | Configurable (1-10) |
| **Container runtimes** | Apple Containers, Docker, Podman | None |
| **Manager process** | Heartbeat loop (10s) | Orchestrator + auto-spawn |
| **Acceptance criteria** | Hook validators | Executable shell commands |

---

## Philosophical Differences

### AgentTree: "Workflow-first, tool-agnostic"
AgentTree thinks about the problem as a **workflow orchestration** challenge. The core abstraction is the issue lifecycle -- stages, transitions, hooks, human gates. The AI coding tool is pluggable. The container provides a security boundary. The web UI provides visibility. Everything serves the workflow.

### FormalTask: "Quality-gated, deeply integrated"
FormalTask thinks about the problem as a **quality assurance** challenge. The core abstraction is the completion rules kernel -- you define what "done" means structurally, and the system enforces it. The 80+ specialized reviewers, structured findings, review freshness tracking, and rules DSL all serve the goal of ensuring AI-generated code meets a quality bar. Deep integration with Claude Code (via hooks) enables enforcement at the tool level, not just the workflow level.

### What they share
Both reject the "just let the AI code" approach. Both enforce structure. Both value human oversight. Both are pre-launch projects built with antirez-style minimalism. Both solve a real problem that anyone running multiple AI agents has encountered.

The difference is where they put the complexity: AgentTree puts it in the workflow engine (stages, transitions, hooks, containers, remote execution). FormalTask puts it in the quality engine (rules kernel, structured reviews, 80+ reviewer agents, completion gating, delta handoff).

---

## Who Should Use Which?

**AgentTree is a better fit if you:**
- Want to use multiple AI coding tools (not just Claude)
- Need container-level isolation for security
- Want a visual web dashboard for monitoring
- Need remote agent execution across machines
- Prefer file-based state you can inspect with `cat` and `git log`
- Want a simpler mental model with fewer moving parts

**FormalTask is a better fit if you:**
- Are all-in on Claude Code
- Want rigorous, structured code review with specialized reviewers
- Need sophisticated completion gating with a rules DSL
- Are working on large features that benefit from epic-level planning
- Want context preservation across long agent sessions (delta handoff)
- Prefer a keyboard-driven TUI workflow
- Want to enforce coding standards via Claude Code hooks

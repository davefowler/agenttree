# Claude Code Agent Teams vs AgentTree

A comparison of Anthropic's new first-party Agent Teams feature with AgentTree's multi-agent orchestration system. Written April 2026.

---

## What Is Agent Teams?

Claude Code Agent Teams (experimental, v2.1.32+) is a first-party feature that lets you coordinate multiple Claude Code instances working together. One session acts as the "team lead" that spawns "teammates," each running in its own context window. Teammates share a task list, communicate via a mailbox system, and can message each other directly.

Key primitives:
- **Team lead**: the session that creates the team and coordinates work
- **Teammates**: independent Claude Code instances spawned by the lead
- **Shared task list**: pending → in progress → completed, with dependencies
- **Mailbox**: direct agent-to-agent messaging
- **Display modes**: in-process (Shift+Down to cycle) or split panes (tmux/iTerm2)

---

## Side-by-Side Comparison

| Dimension | Agent Teams | AgentTree |
|-----------|-------------|-----------|
| **Scope** | Single task/session | Full project lifecycle |
| **Orchestrator** | Lead Claude Code session | Manager agent (issue 0) + event system + web UI |
| **Work units** | Tasks in a shared list | Issues with stages, flows, gates |
| **Isolation** | Shared filesystem, own context window | Container + git worktree per agent |
| **Communication** | Built-in mailbox, direct messaging | tmux message sending, interrupt mode |
| **AI tool support** | Claude Code only | Claude, Aider, Cursor, Gemini, custom |
| **Workflow enforcement** | None (lead decides) | Stage gates, validators, human review, hooks |
| **CI/CD integration** | None | CI status monitoring, auto-escalate, PR management |
| **Web UI** | Terminal only (panes or in-process) | FastAPI + HTMX kanban board, real-time dashboard |
| **Persistence** | Ephemeral (one session) | Persistent issue tracking across sessions |
| **File conflicts** | Manual avoidance ("don't edit same file") | Impossible by design (separate worktrees) |
| **Container sandboxing** | None | Docker, Podman, Apple Containers |
| **Remote dispatch** | No | Yes (Tailscale-based remote agents) |
| **Human-in-the-loop** | Talk to lead or teammates directly | Review gates, approval stages, web UI controls |
| **Quality gates** | TeammateIdle / TaskCreated / TaskCompleted hooks | Pre/post-completion validators, field checks, section checks |
| **Session resumption** | Broken for in-process teammates | Persistent state, agents can restart |
| **Nesting** | No nested teams | Manager → developer/reviewer hierarchy |
| **Plan approval** | Lead approves teammate plans | Human review stages in workflow |
| **Setup** | Zero (built into Claude Code) | Install + configure `.agenttree.yaml` |

---

## What Agent Teams Does Better

### 1. Zero-friction startup
Agent Teams requires no setup. You say "create a team" and it happens. AgentTree requires installing the CLI, configuring `.agenttree.yaml`, setting up flows and stages, building container images. For ad-hoc parallel exploration, Agent Teams wins decisively.

### 2. Rich inter-agent communication
The mailbox system allows direct, named agent-to-agent messaging. Teammates can challenge each other's findings, share intermediate results, and converge on answers through debate. AgentTree's tmux-based messaging is one-directional fire-and-forget — you can send a message to an agent, but agents can't easily message each other.

### 3. Self-organizing task claims
Teammates can self-claim tasks from the shared list using file-locking. This creates an organic work distribution pattern without central assignment. AgentTree requires explicit `agenttree start <issue>` dispatching.

### 4. Conversational team control
You can talk to any teammate directly (Shift+Down in in-process, click pane in split mode). The interaction model is natural and immediate. AgentTree's `agenttree send <id> "message"` is functional but less fluid.

### 5. Built-in plan approval flow
Teammates can be required to plan before implementing. The lead reviews and approves/rejects plans. This is built into the coordination protocol, not bolted on via stages.

### 6. Subagent definition reuse
You can define a role once (security-reviewer, test-runner) as a subagent definition and reuse it as either a delegated subagent or a teammate. Clean separation of role definition from execution context.

---

## What AgentTree Does Better

### 1. True isolation (not just "avoid file conflicts")
Agent Teams' advice for preventing conflicts is "break the work so each teammate owns a different set of files." That's a social contract, not enforcement. AgentTree gives each agent its own git worktree and container. File conflicts are structurally impossible. This is a fundamental architectural advantage for anything beyond a single session.

### 2. Persistent workflow with gates and validation
Agent Teams has no concept of workflow stages, quality gates, or human review checkpoints. The lead decides when work is done. AgentTree enforces a stage pipeline: `explore.define → explore.research → plan.draft → implement.code → implement.code_review → implement.review → accepted`. Each transition can require validators (file exists, has commits, CI passes, PR approved, section quality checks). This is the difference between "hope the AI does good work" and "structurally prevent bad work from advancing."

### 3. CI/CD integration
Agent Teams has no CI awareness. AgentTree monitors GitHub CI status, auto-escalates after repeated failures, manages PR creation and merging, pushes branches, and detects externally merged PRs. This closes the loop between "code written" and "code shipped."

### 4. Multi-tool support
Agent Teams only works with Claude Code. AgentTree is tool-agnostic: Claude, Aider, Cursor, Gemini, or any CLI tool. You can have a Claude agent writing code while an Aider agent reviews it. This avoids vendor lock-in and lets you use the best tool for each role.

### 5. Production-grade monitoring
The web dashboard (kanban board, real-time agent output, flow views) provides visibility that terminal panes can't match. When you have 10+ agents running, you need a dashboard, not tmux panes.

### 6. Container sandboxing
Agents in containers can't accidentally damage the host system, leak credentials, or interfere with each other's environments. Agent Teams has no sandboxing — all teammates share the lead's permissions and filesystem.

### 7. Remote agent dispatch
AgentTree can dispatch work to remote machines via Tailscale. Agent Teams is local-only.

### 8. Event-driven architecture
AgentTree's heartbeat/event system with rate-limited actions (stall detection, CI monitoring, sync, PR management) provides autonomous operational capabilities that Agent Teams lacks entirely.

---

## What We Can Learn and Adopt

### Ideas worth stealing

**1. Direct agent-to-agent messaging protocol**
AgentTree's current communication is hub-and-spoke (manager → agent). Agent Teams' mailbox model where any agent can message any other by name is strictly better for certain patterns (code review debates, research convergence). We should add a messaging layer where agents can address each other.

**2. Self-claiming task queues**
Instead of requiring explicit `agenttree start <issue>`, agents could self-claim from a ready queue. When an agent finishes its current issue, it picks up the next unblocked one. This reduces manager overhead and improves throughput.

**3. Plan-before-implement as a first-class coordination primitive**
We already have plan stages in the default flow, but Agent Teams' pattern of "work in read-only mode until plan is approved" is cleaner. We could add a `plan_approval_required` flag to stage configs that locks the agent to read-only tools until the manager (or human) approves.

**4. Zero-config quick-start mode**
For simple parallel tasks, our setup overhead is a barrier. We could add an `agenttree quick-team "do X, Y, Z in parallel"` command that auto-creates ephemeral issues and starts agents without requiring full workflow configuration.

**5. Competing-hypothesis pattern**
The "spawn 5 agents to investigate different hypotheses and debate" pattern is powerful and not something our current workflow naturally supports. We could add a `debate` flow where multiple agents work the same issue with different directives and converge.

**6. TeammateIdle hook equivalent**
Agent Teams' `TeammateIdle` hook (exit code 2 sends feedback and keeps agent working) is a clean pattern. Our stall detection is heartbeat-based and slower. We could add an on-idle hook that fires immediately when an agent tries to go idle.

### Ideas to skip

- **Ephemeral teams**: Our persistent issue/stage model is a strength, not a limitation. Ephemeral teams are fine for one-off exploration but don't scale to project-level work.
- **In-process mode**: Running all agents in one terminal is clever for demos but impractical at scale. Our container + tmux + web UI approach is better for real work.
- **Lead-as-coordinator**: Having the lead AI session be the orchestrator is fragile — it can run out of context, decide to stop early, or make bad coordination decisions. Our event-driven manager with explicit hooks is more reliable.

---

## Has Agent Teams Made AgentTree Obsolete?

**No. They solve different problems at different scales.**

Agent Teams is a **session-level** tool. It's excellent for: "I have a complex task right now, let me throw 3-5 agents at it for the next hour." It's the right tool when you need parallel exploration within a single coding session and don't need persistence, workflow enforcement, or CI integration.

AgentTree is a **project-level** system. It's built for: "I have 20 issues to work through, each needs research, planning, implementation, code review, CI validation, and human approval before merging." It manages the full lifecycle from issue creation to merged PR, with structural guarantees at every stage.

The analogy: Agent Teams is like opening multiple browser tabs to research a question. AgentTree is like a project management system with CI/CD pipelines.

### Where Agent Teams competes directly

For **ad-hoc parallel coding tasks** within a single session — refactoring 4 modules, reviewing a PR from 3 angles, debugging with competing hypotheses — Agent Teams is now the simpler choice. It has lower overhead, richer communication, and zero setup cost. If you were using AgentTree solely for this kind of work, Agent Teams is arguably better.

### Where AgentTree remains essential

- **Multi-issue project orchestration** with dependencies and priorities
- **Enforced quality workflows** with gates, validators, and human review
- **CI/CD integration** and automated PR lifecycle management
- **Container isolation** for untrusted or parallel code execution
- **Multi-tool orchestration** (not just Claude Code)
- **Persistent state** across sessions and days
- **Remote dispatch** across machines
- **Dashboard visibility** at scale

### The real opportunity

Agent Teams and AgentTree are complementary. The best architecture might be:

> **AgentTree manages the project-level workflow (issues, stages, gates, CI, PRs), and individual agents within AgentTree use Agent Teams for intra-task parallelism.**

An AgentTree developer agent working on issue #7 could spawn an Agent Team internally to parallelize the implementation — one teammate on the API layer, one on tests, one on the frontend — while AgentTree manages the higher-level workflow of getting issue #7 from "plan approved" to "PR merged."

This layered approach combines AgentTree's structural guarantees with Agent Teams' fluid intra-task collaboration.

---

## Summary

| Question | Answer |
|----------|--------|
| Is AgentTree obsolete? | No. Different scope and scale. |
| Should we worry? | Only if we don't evolve. |
| What should we steal? | Direct messaging, self-claiming queues, quick-start mode, idle hooks |
| What's our moat? | Workflow enforcement, CI/CD, containers, persistence, multi-tool, remote dispatch |
| Best combined architecture? | AgentTree for project orchestration, Agent Teams for intra-task parallelism |

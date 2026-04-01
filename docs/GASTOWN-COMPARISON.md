# Gastown vs AgentTree: Comparison and Takeaways

A comparison of [Gastown](https://github.com/gastownhall/gastown) (by Steve Yegge) and AgentTree, two multi-agent AI orchestration systems. Both solve the same core problem -- coordinating multiple AI coding agents working in parallel -- but take notably different approaches.

## At a Glance

| Dimension | Gastown | AgentTree |
|-----------|---------|-----------|
| **Language** | Go 1.25+ | Python 3.12+ |
| **CLI framework** | Cobra + Charm (bubbletea/lipgloss) | Click |
| **Agent session mgmt** | tmux | tmux |
| **Isolation** | Git worktrees (no containers) | Containers (Apple/Docker/Podman) + worktrees |
| **Work tracking** | Dolt (git-for-data SQL DB) + Beads CLI | YAML files in `_agenttree/` git repo |
| **Web UI** | Charm-based TUI | FastAPI + HTMX dashboard |
| **Workflow system** | TOML "Formulas" with inheritance/aspects | YAML stages with hooks/validators |
| **Agent communication** | `gt nudge` (real-time) + `gt mail` (persistent) | `agenttree send` (tmux send-keys) |
| **Merge strategy** | Built-in Refinery merge queue (Bors-style) | Manager pushes, CI wait stage |
| **Scale target** | 20-30+ agents | Handful of agents |
| **Observability** | OpenTelemetry (metrics, traces, logs) | Web dashboard + `agenttree status` |
| **Multi-repo** | First-class (Town/Rig model) | Single repo focus |

## Where Gastown Excels

### 1. Structured Agent Hierarchy

Gastown defines a clear **role taxonomy** with separation of concerns:

- **Mayor** -- global coordinator, creates convoys, distributes work
- **Deacon** -- background daemon supervisor, watchdog over all agents
- **Witness** -- per-repo patrol agent managing worker lifecycle
- **Refinery** -- per-repo merge queue processor
- **Polecat** -- disposable transient workers (isolated worktrees, auto-cleaned)
- **Crew** -- persistent long-lived workers

AgentTree has roles (developer, reviewer, manager, architect) but they're flatter. Gastown's three-tier watchdog chain (Boot → Deacon → Witness → Polecats) is a more robust supervision model.

**Takeaway:** A layered supervision hierarchy would help AgentTree detect stuck agents more reliably and recover from failures autonomously.

### 2. Persistent Inter-Agent Communication

Gastown separates messaging into two channels:
- **`gt nudge`** -- real-time text to active sessions (like AgentTree's `send`)
- **`gt mail`** -- persistent messages that survive restarts and crashes

AgentTree only has `agenttree send`, which is fire-and-forget via tmux. If the agent isn't running or the session dies, the message is lost.

**Takeaway:** Adding a persistent mailbox system (even just files in the issue directory) would make agent communication crash-safe. Pattern: mail carries the payload, nudge alerts the recipient.

### 3. Dolt-Backed Work Tracking

Gastown uses Dolt -- a SQL database with git semantics -- to track all work ("Beads"). Every action is a permanent, auditable commit with full attribution. This gives:
- SQL queries over work history (`bd stats`, agent CVs)
- A/B testing of different models on comparable tasks
- Complete provenance chain

AgentTree uses YAML files in a git repo, which is simpler but makes querying and analytics harder.

**Takeaway:** We don't need to adopt Dolt, but structured analytics over agent performance (completion times, revision counts, success rates by model) would be valuable for optimizing our workflow. Even a simple SQLite DB alongside the YAML files could enable this.

### 4. Self-Cleaning Worker Lifecycle

Gastown's Polecats follow a strict lifecycle: work → submit to merge queue → nuke sandbox → exit session. The "GUPP" principle ("If there is work on your hook, YOU MUST RUN IT") means agents are autonomous pistons -- no waiting for confirmation.

AgentTree agents are more stateful and long-lived, which means more cleanup burden and potential for stale state.

**Takeaway:** Consider a "disposable agent" mode for well-defined tasks -- agent starts, does the work, submits, cleans up, exits. Reduces orphan cleanup overhead.

### 5. Session Continuity

Gastown has explicit mechanisms for context management:
- **`gt handoff`** -- transfers work state to a new session when context fills up
- **`gt seance`** -- query previous sessions for context and decisions
- **`gt prime`** -- full context reload after compaction

AgentTree doesn't have explicit session continuity tools. When an agent's context fills up or it crashes, context is lost.

**Takeaway:** Session handoff and context recovery are critical at scale. Even basic support (writing a summary file before exit, loading it on restart) would improve agent resilience significantly.

### 6. Built-in Merge Queue

Gastown's Refinery is a dedicated merge queue agent that handles bisecting merges, conflict resolution, flaky test retries, and max concurrency. Workers never push to main directly.

AgentTree relies on the manager to push and a CI wait stage, which is simpler but doesn't handle merge conflicts or concurrent PR landing.

**Takeaway:** As we scale to more parallel agents, a merge queue (even leveraging GitHub's built-in merge queue) becomes essential to avoid merge conflicts and broken main.

### 7. Formula Composition System

Gastown's TOML-based Formulas support inheritance (`extends`), cross-cutting concerns (`aspects`), and macro expansion. This makes workflow templates highly reusable.

AgentTree's YAML stages are simpler and more readable, but don't support composition.

**Takeaway:** Workflow composition isn't urgent, but as we add more flows beyond `default` and `quick`, having a way to share common stage definitions (via YAML anchors or similar) would reduce duplication.

### 8. Multi-Agent Support

Gastown supports a broad range of AI agents out of the box: Claude Code, GitHub Copilot, Codex, Gemini, Cursor, AMP, OpenCode, Goose, and more. Integration is configuration-based (JSON presets), not code-linked -- any CLI that runs in a terminal works at "Tier 0" with zero integration effort.

AgentTree currently supports Claude Code and Aider, with the tool configured in `.agenttree.yaml`.

**Takeaway:** A preset-based agent integration system (like Gastown's tiered approach) would make it easier to add new agent backends without code changes.

## Where AgentTree Excels

### 1. Container Isolation

AgentTree runs agents in full containers (Apple Containers, Docker, Podman) with privilege separation -- agents can't push, merge, or access the host. Gastown uses worktrees only, with no container sandboxing.

This is a real security advantage. A misbehaving agent in Gastown could run destructive commands on the host.

### 2. Simplicity

AgentTree's YAML-based configuration and flat stage system is much easier to understand and debug. Gastown has 67 internal packages and a vocabulary of metaphors (Towns, Rigs, Polecats, Beads, Molecules, Wisps, Wasteland, Refinery, Deacon, Witness, Convoy, etc.) that creates a steep learning curve.

AgentTree's "anti-slop" philosophy actively fights unnecessary complexity. This is a strength worth preserving.

### 3. Human-in-the-Loop Review Gates

AgentTree's workflow has explicit human review stages (`plan.review`, `implement.review`) with hook-based validation. The workflow won't advance without human approval at key checkpoints.

Gastown's GUPP principle prioritizes autonomy -- agents run without waiting for confirmation. This is faster but riskier.

### 4. Web Dashboard

AgentTree's FastAPI + HTMX dashboard provides a visual kanban board, live agent output streaming, and browser-based agent management. Gastown uses a Charm-based TUI, which is terminal-only.

## Concrete Suggestions for AgentTree

Based on this analysis, here are the highest-value ideas to borrow:

### 1. Add Persistent Agent Messaging (High Value, Low Effort)
Write messages to `_agenttree/issues/<id>/inbox/` as files. On agent start or restart, load and display unread messages. Simple, crash-proof, no new dependencies.

### 2. Agent Performance Tracking (High Value, Medium Effort)
Log structured events (stage transitions, completion times, revision counts) to a queryable format. Enables comparing models, identifying bottlenecks, and measuring improvement over time.

### 3. Session Handoff / Context Recovery (High Value, Medium Effort)
Before an agent exits (or on crash), write a `context.md` summarizing current state, decisions made, and next steps. On restart, inject this into the agent's prompt. Gastown's `gt handoff` / `gt seance` pattern.

### 4. Disposable Worker Mode (Medium Value, Medium Effort)
A "polecat-style" agent mode for well-scoped tasks: start, do work, submit, auto-cleanup. No long-lived state. Reduces the orphan container problem.

### 5. Watchdog Improvements (Medium Value, Low Effort)
The heartbeat system already checks for stalled agents, but Gastown's layered supervision (Deacon → Witness → Polecat) with automatic recycling is more robust. Consider: if an agent is stuck for N minutes and nudging didn't help, auto-restart it.

### 6. Merge Queue Integration (Medium Value, Future)
Not urgent now, but as agent count grows, integrate with GitHub's merge queue or build a simple queue to serialize PR merging and avoid conflicts.

## What the Community Says About Gastown

External reviews provide useful calibration on what actually matters:

- **DoltHub** (Jan 2026): "The constraint on what you can build may shift from clock time to creativity and dollars in Claude Code tokens." Positive hands-on experience, but highlights the cost dimension.

- **Maggie Appleton** (Jan 2026): Notes Gastown is "entirely vibecoded, hastily designed with off-the-cuff solutions, and inefficiently burning through thousands of dollars a month in API costs." Key insight: **when you have agents churning through code, design becomes the bottleneck**, not development time.

- **Paddo.dev** (Jan 2026): Distinguishes "org-chart multi-agent" (AI mimicking human roles) from "operational multi-agent" (Gas Town, where roles serve execution coordination). Notes that for most developers, a vanilla approach (Plan Mode, focused CLAUDE.md, verification loops) handles what's needed without an orchestration layer.

- **Aviator** (Feb 2026): "The majority of engineering teams have no business adopting agent orchestration right now... If you can't get consistent value from one agent, you'll get consistently amplified chaos from ten."

- **Goosetown** (Block/Goose team, Feb 2026): Built a Gas Town-inspired layer on Goose, deliberately more minimal, focused on research-first parallel work with phases. Validates the "simpler is better for most teams" position.

The consensus: Gastown's *direction* is right (multi-agent is the future), but the *complexity* is premature for most teams. AgentTree's lighter-weight approach with human gates may be better positioned for the current state of the art -- where agent reliability still requires human oversight.

---

*Written 2026-04-01. Based on Gastown repo at github.com/gastownhall/gastown (~13.4k stars) and AgentTree at github.com/davefowler/agenttree.*

**Sources:** [Gastown repo](https://github.com/gastownhall/gastown) | [Yegge launch post](https://steve-yegge.medium.com/welcome-to-gas-town-4f25ee16dd04) | [DoltHub review](https://www.dolthub.com/blog/2026-01-15-a-day-in-gas-town/) | [Appleton analysis](https://maggieappleton.com/gastown) | [Paddo.dev](https://paddo.dev/blog/gastown-two-kinds-of-multi-agent/) | [Aviator](https://www.aviator.co/blog/the-rise-of-coding-agent-orchestrators/) | [Goosetown](https://block.github.io/goose/blog/2026/02/19/gastown-explained-goosetown/)

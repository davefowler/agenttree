# AgentTree vs. Symphony vs. Stagent

A comparison of three approaches to orchestrating multiple coding agents against an issue tracker.

- **AgentTree** — this repo. Local, tmux + container per issue, GitHub-backed, structured stages enforced by hooks, manager agent + heartbeat loop, separate `_agenttree/` repo for workflow docs.
- **Symphony** — OpenAI's open-source spec for orchestrating Codex agents against Linear. Reference implementation in Elixir. Spec-first; ships as `SPEC.md` plus a reference runner.
- **Stagent** — the in-progress successor to AgentTree. _Stub below — fill in._

> Sources: [OpenAI Symphony announcement](https://openai.com/index/open-source-codex-orchestration-symphony/), [symphony/SPEC.md](https://github.com/openai/symphony/blob/main/SPEC.md), [Help Net Security writeup](https://www.helpnetsecurity.com/2026/04/28/openai-symphony-codex-orchestration-linear/), [Tessl summary](https://tessl.io/blog/openai-open-sources-symphony-a-spec-for-orchestrating-codex-agents/).

---

## TL;DR

All three answer the same question: *one ticket → one workspace → one agent → one PR, in parallel, without a human babysitting each step.* They differ in **what the artifact is**, **where the state lives**, **what enforces structure**, and **how much the host gets involved**.

| | AgentTree | Symphony | Stagent |
|---|---|---|---|
| **Artifact** | Running Python CLI + daemon | A spec (`SPEC.md`) + Elixir reference impl | _TBD_ |
| **Control plane** | GitHub Issues + local YAML state | Linear (ticket status = state machine) | _TBD_ |
| **Agent model** | Pluggable (Claude Code, Aider, Cursor, Gemini) | Codex app-server subprocess | _TBD_ |
| **Isolation** | git worktree + container (Apple Containers / Docker / Podman) | Per-issue workspace directory (filesystem only, by spec) | _TBD_ |
| **Stage enforcement** | First-class: stages, hooks, gates, human review checkpoints | Workflow template + handoff states; mostly agent-driven | _TBD_ |
| **Recovery model** | Heartbeat loop checks CI, stalls, merged PRs every 10s | Tracker-driven; on restart re-poll active issues. No DB | _TBD_ |
| **Persistence** | Files on disk + GitHub | Files on disk + Linear. "No persistent database" | _TBD_ |
| **Host language** | Python 3.12, Click CLI | Elixir (OTP supervisors) | _TBD_ |
| **Where the PR comes from** | Manager agent (privileged) creates/merges; agent stays sandboxed | The coding agent itself, using its own tools | _TBD_ |
| **License** | MIT | Apache 2.0 | _TBD_ |

---

## AgentTree (this repo)

**Shape:** a Python CLI + long-running daemon that supervises a fleet of containerized coding agents on your laptop. Every GitHub issue you start gets:

- A dedicated **git worktree** under `~/Projects/worktrees/`.
- A dedicated **container** (Apple Containers on macOS 26+, Docker/Podman elsewhere) with sandboxed FS/network.
- A **tmux session** the agent runs in — attachable, replayable, sendable.
- A row of state in a per-issue `issue.yaml`, plus documents in a sibling `_agenttree/` repo (`problem.md`, `spec.md`, `review.md`, etc.).

**Workflow as a state machine.** Issues progress through an explicit flow (`default` is the normal one):

```
explore.define → explore.research → plan.draft → plan.selfcheck →
plan.review (human) → implement.setup → implement.code →
implement.code_review → implement.independent_review →
implement.ci_wait → implement.review (human) → accepted
```

Stages are gated by **hooks** (`agenttree/hooks.py`) — Python callables that validate, run linters/tests, push branches, monitor CI, create PRs, etc. A stage can't advance until its hooks pass.

**Deterministic heartbeat, not a polling LLM.** A 10s loop runs *code*, not prompts: check CI, detect merged PRs, detect stalled sessions, run scheduled hooks, send notifications. The model is reserved for reasoning; status checks are just code. (Explicit design choice — see README.)

**Manager / agent split (privilege separation).** Worker agents stay inside their container. A privileged manager agent on the host pushes branches, opens PRs, merges, and notifies workers when their state changes. Workers can't escape; they don't need to.

**Pluggable coding tools.** `claude`, `aider`, `cursor-cli`, `gemini-cli`, or any subprocess. Configured per-tool in `.agenttree.yaml`.

**Docs live in a sibling repo.** `_agenttree/` is its own git repo so all the spec/plan/research/review markdown the agents generate doesn't pollute the product repo. Templates per stage; learnings accumulate over time.

**Surfaces.** CLI (`agenttree status / start / send / output / approve`), tmux attach, and a web Kanban (`agenttree server`) for drag-and-drop stage advancement and human review.

---

## Symphony

**Shape:** a *specification* (`SPEC.md`, 18 sections) for what a Codex orchestration service should do, plus an Elixir reference implementation. OpenAI's stated intent: "we don't plan to maintain it as a standalone product — it's a reference." Apache 2.0.

**Linear *is* the state machine.** No internal database. Symphony polls Linear for candidate issues, sorts them by priority + age, and dispatches up to a concurrency limit. Ticket status transitions are the workflow. A "successful" run can end at a handoff state like `Human Review` rather than `Done` — that's how human-in-the-loop is expressed.

**Per-issue workspace, per-issue lifecycle.** Each issue gets a filesystem directory under a configurable root. Lifecycle hooks (`after_create`, `before_run`, `after_run`, `before_remove`) execute around runs. A hard safety invariant: *the coding-agent subprocess must run only inside its per-issue workspace path.* (No container layer is mandated by the spec — it's "the workspace directory.")

**Run-attempt FSM.** Each attempt walks: `PreparingWorkspace → BuildingPrompt → LaunchingAgentProcess → InitializingSession → StreamingTurn → Finishing → {Succeeded | Failed | TimedOut | Stalled | CanceledByReconciliation}`. Issue-level: `Unclaimed → Claimed (Running | RetryQueued) → Released`.

**Agent runner.** Wraps workspace + prompt + Codex app-server client. Builds the prompt from a `WORKFLOW.md` template (YAML front matter + Markdown body), launches `codex app-server` as a subprocess, streams its events (token usage, approvals, errors) back to the orchestrator, and manages continuation turns up to `agent.max_turns`.

**Ticket writes are the agent's job, not the orchestrator's.** From the spec: *"Ticket writes (state transitions, comments, PR links) are typically performed by the coding agent using tools available in the workflow/runtime environment."* The orchestrator dispatches and supervises; the agent updates Linear and opens the PR.

**Recovery model.** Tracker-driven and filesystem-driven, with no DB. On restart: clean stale workspaces for terminal issues, re-poll active issues, resume. In-flight retry timers and session state don't survive a process restart — but workspaces do, so a re-run can continue incrementally. Stall detection + exponential-backoff retries are the orchestrator's responsibility.

**Elixir reference impl.** Chosen for OTP-style supervisors / concurrent process management. Reportedly Codex one-shotted the implementation.

**Reported result:** "500% increase in landed PRs" across some teams during internal deployment.

---

## Stagent _(stub — fill in)_

> This section is a stub. Replace each bullet with the actual stagent design.

**One-line pitch:** _What's stagent's elevator pitch? What does it do that AgentTree didn't?_

**What's the artifact?** _Daemon? Library? Spec? Hosted service?_

**Control plane:** _GitHub? Linear? Built-in? Multiple?_

**State machine:** _Same stages as AgentTree? Simpler? Configurable graph? Event-sourced?_

**Isolation:** _Containers? Worktrees? Remote sandboxes? Something new?_

**Agent model:** _Still multi-CLI? Locked to a single coding agent?_

**Heartbeat / supervision:** _Inherit the 10s deterministic loop, or move to event-driven?_

**Persistence:** _Files? Sqlite? Postgres? Tracker-driven like Symphony?_

**Manager / privilege model:** _Same split as AgentTree? Different?_

**Surfaces:** _CLI? Web? Mobile? API?_

**What's gone from AgentTree:** _What's being deleted in the rewrite?_

**What's new vs. AgentTree:** _Headline new capabilities._

**What's borrowed from Symphony, if anything:** _e.g. tracker-driven recovery, workflow templates, app-server protocol._

---

## Head-to-head: where the three philosophies diverge

### 1. What is the product?
- **AgentTree:** a tool you install (`uv tool install agenttree`) and run. Opinionated, batteries-included.
- **Symphony:** a spec. The Elixir impl is reference, not product. OpenAI is explicit they won't maintain it as a product.
- **Stagent:** _TBD._

### 2. Where does workflow live?
- **AgentTree:** in Python code (stages, hooks, transitions). The flow graph is part of the framework. Per-project tweaks in `.agenttree.yaml`.
- **Symphony:** in a `WORKFLOW.md` per project — YAML front matter + Markdown prompt template. The orchestrator is workflow-agnostic; the workflow file *is* the workflow.
- **Stagent:** _TBD._

### 3. Who talks to the tracker?
- **AgentTree:** the host writes to GitHub (status comments, PR creation, merge). The agent inside the container is sandboxed and goes through the manager.
- **Symphony:** the agent talks to Linear directly using whatever tools are wired into its runtime. The orchestrator only *reads* the tracker.
- **Stagent:** _TBD._

### 4. What enforces structure?
- **AgentTree:** hooks at every gate. mypy strict, pytest, CI status, independent reviewer — all are stage transitions that can fail and block advancement. Human review is a first-class stage.
- **Symphony:** the workflow template + ticket status transitions. Enforcement is largely on the agent's good behavior, plus stall/timeout supervision. Human review is a "handoff state" the workflow can land on.
- **Stagent:** _TBD._

### 5. How is failure handled?
- **AgentTree:** heartbeat detects stalls, hooks raise (not silently `return False`), the manager can restart agents and rebase worktrees. Issues persist in YAML.
- **Symphony:** orchestrator detects stalls, schedules exponential-backoff retries, releases claims. On process crash: no DB, but workspaces and tracker state are the source of truth — pick up where you left off.
- **Stagent:** _TBD._

### 6. Single-machine vs. distributed?
- **AgentTree:** local-first; remote agents over Tailscale (Phase 4). One operator's laptop is the typical deployment.
- **Symphony:** designed as a service. One orchestrator process can run many workers; Elixir/OTP makes this natural.
- **Stagent:** _TBD._

### 7. Sandboxing model
- **AgentTree:** containerized agent + worktree. The agent never touches the host repo or pushes directly.
- **Symphony:** filesystem isolation per workspace path. Containerization is not mandated by the spec.
- **Stagent:** _TBD._

---

## What AgentTree could borrow from Symphony

- **Workflow-as-template.** A `WORKFLOW.md` (YAML front matter + Markdown prompt) is a cleaner extension point than editing Python hook code for each project. Today AgentTree's stages and skill files are spread across the codebase + `_agenttree/skills/`. A single per-project file would be more legible.
- **Run-attempt FSM made explicit.** Symphony names every micro-stage of a single agent attempt (`PreparingWorkspace → BuildingPrompt → LaunchingAgentProcess → ...`). AgentTree implicitly has these; surfacing them would make the dashboard more diagnostic.
- **Tracker as source of truth.** AgentTree maintains its own YAML *and* GitHub state — drift is possible. Symphony's "tracker is the database" model is simpler. (Counterpoint: GitHub's API surface is thinner than Linear's for this.)

## What Symphony is missing that AgentTree has

- **Containerized agents + privilege separation.** Symphony's safety invariant is "stay in your workspace dir." AgentTree's is "stay in your container, and the manager pushes for you." Stronger sandbox.
- **Deterministic heartbeat.** Symphony does poll + reconcile, but AgentTree's design explicitly contrasts itself against LLM-driven self-check loops ("we use the model for reasoning, code for checking"). Worth keeping.
- **Independent reviewer stage.** AgentTree has `implement.independent_review` as a separate substage — the agent that wrote the code doesn't grade its own homework. Symphony's workflow can be configured for this, but it isn't a first-class concept.
- **Sister docs repo.** `_agenttree/` keeping all the spec/research/review markdown out of the product repo is a nice property the Symphony spec doesn't address.

---

## Open questions to answer before stagent ships

1. Tracker: stick with GitHub, switch to Linear, or be tracker-agnostic like Symphony?
2. Workflow definition: keep stages in Python, or move to `WORKFLOW.md`-style templates?
3. Heartbeat: keep the 10s deterministic loop, or move to an event-driven model (webhooks, app-server events)?
4. Agent runtime: still pluggable across CLIs, or commit to one (e.g., Claude Code via the agent SDK)?
5. Persistence: keep YAML-per-issue, or move toward "tracker is the DB"?
6. Containerization: keep the strong sandbox, or accept "workspace dir" isolation?
7. Distribution: local-first stays the default, or first-class hosted/cloud mode?

# Review: Ramp Inspect — "Why We Built Our Own Background Agent"

**Source:** [Why We Built Our Own Background Agent (Ramp Builders)](https://builders.ramp.com/post/why-we-built-our-background-agent)
**Date reviewed:** 2026-03-30

## What Ramp Built

Ramp built **Inspect**, an internal background coding agent that runs in sandboxed
VMs with full development environments. It now generates over 50% of all merged
pull requests at Ramp — with 30% adoption in the first couple months, growing
organically without mandating usage.

Inspect uses [OpenCode](https://github.com/opencode-ai/opencode) as the underlying
coding agent, hosted inside Modal Sandboxes alongside a full-stack environment:
Postgres, Redis, Temporal, RabbitMQ, VS Code server, Chromium via VNC, and all of
Ramp's internal tooling (Sentry, Datadog, GitHub, Slack, feature flags).

## Architecture

**Control plane (Cloudflare):** Durable Objects for session state management,
conversation context, and cross-client coordination.

**Data plane (Modal):** Sandboxes provide isolated containers with filesystem
snapshot support. A cron job runs every 30 minutes to clone repos, install
dependencies, run builds, and save filesystem snapshots. Sessions boot from
the latest snapshot, needing only a fast git sync to reach HEAD.

**Clients:** Slack bot, web UI (with hosted VS Code + streamed desktop), and a
Chrome extension that lets non-engineers visually select UI elements to change.
All clients feed into the same session via Modal Queues, enabling multiplayer
collaboration.

**Key design principle:** Session startup velocity should be limited only by the
model's time-to-first-token, not infrastructure overhead.

## What Makes It Interesting

### 1. Full environment, not just code generation
Inspect doesn't just write code — it runs it. The agent has access to the same
databases, CI pipelines, monitoring, and browser that a human engineer uses.
It takes before/after screenshots to visually verify frontend changes.

### 2. Filesystem snapshots as the core primitive
The 30-minute cron + snapshot approach means new sessions start in seconds rather
than minutes. Snapshots are stored as diffs from the base image, keeping them
lightweight. This is the single most important architectural decision — it turns
"spin up a dev environment" from a 5-10 minute blocker into a non-issue.

### 3. Build vs. buy argument
Ramp explicitly argues that owning the agent tooling lets you build something
"significantly more powerful than an off-the-shelf tool." Their integration depth
(Sentry alerts triggering agent sessions, Datadog context in prompts) would be
impossible with a generic tool.

### 4. Accessibility beyond engineers
The Chrome extension for visual element selection and the Slack interface mean
PMs and designers can ship code changes. This expands the addressable user base
far beyond engineering.

## Learnings for AgentTree

### What we already do well

- **Sandboxed execution:** AgentTree already runs agents in containers (Apple
  Containers / Docker). This is the same fundamental approach as Ramp's Modal
  Sandboxes.
- **Stage-based workflow:** Our explore → plan → implement → review flow provides
  the structured oversight that Ramp acknowledges is still necessary ("models
  still make mistakes, hallucinate, struggle with complex reasoning").
- **CLI-first multiplayer:** Our `agenttree send` / `agenttree output` commands
  provide similar multi-client access to agent sessions.

### What we should consider adopting

#### 1. Pre-built environment snapshots
**Priority: High.** Ramp's 30-minute cron snapshot approach is their biggest
force multiplier. AgentTree currently builds environments from scratch per
session. We should explore:
- Pre-building container images with dependencies installed on a schedule
- Using filesystem layers / overlay snapshots to make session startup near-instant
- Storing snapshots as diffs to keep storage costs low

This is especially relevant as we move toward cloud-hosted agents where startup
time directly impacts user experience.

#### 2. Visual verification loop
**Priority: Medium.** Ramp's agents take before/after screenshots using a
headless Chromium instance inside the sandbox. AgentTree has Playwright MCP
available but doesn't systematically use it for automated visual verification.
We could:
- Add a visual verification step to the `implement.code_review` stage for
  frontend changes
- Automatically screenshot affected pages before and after changes
- Include diffs in review artifacts

#### 3. Broader client surface
**Priority: Medium.** Ramp's Slack bot and Chrome extension dramatically lower
the barrier to using agents. AgentTree has a web dashboard but could expand:
- Slack/Discord integration for creating and monitoring issues
- A browser extension for "fix this" workflows triggered from the live product
- Mobile-friendly status views

#### 4. Deep tooling integration
**Priority: High.** Ramp's agents can read Sentry errors, query Datadog, and
check feature flags. This context makes agents dramatically more effective.
AgentTree's hook system is the right place for this — we should make it easy to:
- Pipe error monitoring alerts into issue creation
- Give agents access to observability data during the `explore.research` stage
- Auto-attach CI logs, test coverage data, and deployment status to agent context

#### 5. Multiplayer session support
**Priority: Low.** Ramp allows multiple people to connect to the same agent
session simultaneously. AgentTree's architecture (tmux-based sessions) already
supports this in principle via `agenttree output` and `agenttree send`, but
real-time collaborative editing (like Ramp's shared VS Code) would require
significant infrastructure work. Worth noting but not urgent.

### What we do differently (and should keep)

- **Human review gates:** Ramp's model is largely autonomous — agents create PRs
  and humans review after the fact. AgentTree's explicit `plan.review` and
  `implement.review` stages catch problems earlier. Given that models "still make
  mistakes," structured checkpoints remain valuable.
- **Staged workflow:** Ramp's agents go straight from prompt to code. AgentTree's
  explore → plan → implement pipeline produces better results for complex tasks
  by forcing research and planning before implementation. This is a feature, not
  overhead.
- **Local-first execution:** Running on the developer's machine (Apple Containers)
  avoids cloud costs and latency. Ramp's cloud-first model makes sense at their
  scale but isn't necessary for smaller teams.

### What to watch out for

- **Metric inflation:** "50% of merged PRs" is impressive but says nothing about
  the complexity distribution. If agents handle the easy 50% and humans handle
  the hard 50%, the productivity multiplier is real but smaller than the headline
  suggests.
- **Model dependency:** Ramp acknowledges they're "limited by model intelligence
  itself." The infrastructure is excellent but the ceiling is set by frontier
  model capabilities. Investing heavily in infrastructure makes sense only if you
  believe models will keep improving (which they will).
- **Build-vs-buy longevity:** Ramp's argument for building is strong today, but
  the agent tooling landscape is moving fast. Custom infrastructure is a
  competitive advantage until it becomes maintenance burden. AgentTree should
  stay modular enough to swap underlying primitives (container runtimes, model
  providers) without rewiring the whole system.

## Summary

Ramp Inspect validates the core architectural bet that AgentTree is also making:
agents need full, sandboxed development environments with real tooling access,
not just code generation in a vacuum. The two key ideas worth stealing are
**pre-built environment snapshots** for fast startup and **deep observability
tool integration** for richer agent context. The two things worth keeping are
AgentTree's **staged workflow with human checkpoints** and **local-first
execution model**.

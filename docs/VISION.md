# Vision: From Engineering to Product

**The goal isn't to be a better engineer managing AI agents. It's to become a product person who specifies and reviews.**

---

## The Pain Points

### 1. GitHub's UI is Built for Humans, Not Human-AI Collaboration

The current workflow with AI coding agents looks like this:

```
Agent creates PR
  → You scroll through GitHub to find it
  → You see code review comments
  → You ping "@cursor see the code review"
  → You wait
  → You check back later
  → You scroll past 10 code review comments to check status
  → Still not resolved
  → You ping again
  → Eventually it's green
  → You click merge
  → Repeat for next PR
```

This is tedious. You're spending engineering time on what should be automated.

### 2. Getting Lost in Issues

When you have multiple projects with many moving parts:
- Which issues are actually being worked on?
- Which PRs need your attention?
- What's blocked vs what's ready?
- What did that agent even do?

Linear helps. GitHub Projects helps. But neither is designed for the AI-agent workflow where:
- Agents need to be pinged when there's work to do
- Stage transitions need to be enforced
- CI must pass before moving forward
- Reviews need to be automatic, not manual

### 3. Agents Don't Self-Enforce Quality

Even when repeatedly reminded, agents don't reliably:
- Run CI before saying they're done
- Check that tests pass
- Follow the plan they said they'd follow
- Fill out required documentation

This isn't a prompt problem. It's an **enforcement** problem. The workflow needs gates.

### 4. The PR Ping Cycle is Soul-Crushing

The author built `agenthelper` to auto-ping agents when:
- Code review comments appear
- CI fails
- Merge conflicts occur

This was helpful—PRs started arriving with green checkmarks. But it's still reactive, still GitHub-centric, still scattered.

---

## The Insight

**If the workflow is tight enough, you don't need to review.**

```
Today:
  AI writes code → You review everything → Merge

With tight workflow:
  Problem validated → Plan validated → CI enforced → Claude reviews → You glance → Merge

Eventually:
  Problem validated → Plan validated → CI enforced → Claude reviews → Auto-merge
```

The tighter the earlier stages, the less you need to verify at the end.

### What "Tight" Means

| Stage | Enforcement |
|-------|-------------|
| Problem | Can't proceed until problem.md has required sections filled out |
| Plan | Can't proceed until plan.md specifies approach, files, tests |
| Implement | Can't proceed until CI passes (no exceptions) |
| Code Review | Claude API reviews the diff, flags issues |
| Plan Adherence | Did the agent actually do what they said? |

If all gates pass, why would you need to manually review?

---

## The Goal: Product Person, Not Engineer

The job shifts from:

**Before:** "I manage AI agents that write code"
- Review PRs
- Fix merge conflicts
- Chase down CI failures
- Ping agents about reviews
- Manually verify implementations

**After:** "I specify what I want and approve the results"
- Write problem statements
- Review plans (does this approach make sense?)
- Approve implementations (the pipeline verified quality)
- Watch features ship

Your value moves from "engineering oversight" to "product vision."

---

## The UX: Kanban + Auto-Dispatch

The interface should show **what needs your attention**, not **everything that's happening**.

```
┌─────────────────────────────────────────────────────────────────┐
│ READY TO MERGE (3)          │ NEEDS MY REVIEW (2)              │
│ ✅ #42 Fix login            │ 👀 #45 Dark mode plan            │
│ ✅ #43 Update deps          │ 👀 #47 Auth refactor plan        │
│    [Merge All]              │    [Review]                       │
│                             │                                   │
│ AGENT WORKING (2)           │ BLOCKED (1)                       │
│ 🔄 #46 Caching (impl)       │ ❌ #48 CI failing (attempt 3)    │
│ 🔄 #49 Search (research)    │    [View Errors] [Reassign]      │
└─────────────────────────────────────────────────────────────────┘
```

Key UX principles:
- **Show status at a glance** - No digging through GitHub
- **Auto-dispatch** - When you approve a plan, the agent starts automatically
- **Enforce gates** - Can't skip stages, can't bypass CI
- **Surface blockers** - If something needs human attention, make it obvious
- **Batch operations** - "Merge all green PRs" with one click

---

## The Documentation is Product Documentation

The artifacts agents produce aren't just scaffolding:

| File | What It Actually Is |
|------|---------------------|
| `problem.md` | Product requirements document |
| `plan.md` | Technical design doc |
| `review.md` | Quality assurance record |
| `commit-log.md` | Feature changelog |

These live in the agenttree repo, not cluttering your codebase. They're searchable, linkable, and form a record of how your product evolved.

When a feature ships, the system updates your product documentation automatically—linking the problem, plan, implementation, and PR together.

---

## Why Not Just Use Linear + Claude Code Skills?

You could. And for single-agent work, that's probably fine.

But this approach adds:

1. **Parallel agents** - Multiple agents working different issues simultaneously
2. **Enforcement** - Gates that agents can't bypass (CI, validation, reviews)
3. **Auto-dispatch** - Agents start working when you approve, not when you remember to ping
4. **Unified visibility** - One dashboard across all work, not scattered across GitHub/Linear/Cursor
5. **Structured handoffs** - Problem → Plan → Implementation with validated transitions

The structure IS the value. It's what gets you from "babysitting agents" to "approving features."

---

## The Progression

```
Phase 1: You review every PR manually
         (Current state for most people)

Phase 2: Automated pings reduce your overhead
         (agenthelper approach - reactive)

Phase 3: Structured workflow with gates
         (agenttree approach - proactive)

Phase 4: Trust the pipeline, spot-check only
         (Mostly automated, you review edge cases)

Phase 5: Full automation for routine work
         (You focus on product decisions, not code review)
```

This tool is about getting from Phase 1 to Phase 5.

---

## Summary

**The pain:** GitHub is tedious, agents need babysitting, you're doing engineering work when you should be doing product work.

**The insight:** Tight workflow = trusted output = no manual review needed.

**The solution:** Kanban interface with enforced stages, auto-dispatch, and automatic quality gates.

**The outcome:** You specify what you want. You approve plans. Features ship. You move from engineer to product person.

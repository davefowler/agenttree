# Research: Claude Code Enhancement Projects

**Date:** 2026-01-31
**Status:** Research Complete
**Topics:** Agent persistence, orchestration patterns, skill learning, composable prompts

## Overview

Analysis of four Claude Code enhancement projects to identify patterns and learnings applicable to AgentTree:

1. **Ralph Wiggum Plugin** - Iterative loop technique for persistent agent execution
2. **everything-claude-code** - Comprehensive configuration collection (36k+ stars)
3. **oh-my-claudecode** - Multi-agent orchestration system (3.9k stars)
4. **skill-composer** - Declarative prompt composition with stackable modes

---

## 1. Ralph Wiggum Plugin

**Source:** [anthropics/claude-code/plugins/ralph-wiggum](https://github.com/anthropics/claude-code/blob/main/plugins/ralph-wiggum/README.md)

### Concept

Ralph Wiggum is a development methodology based on **continuous AI agent loops**. Named after the Simpsons character, it embodies "persistent iteration despite setbacks."

The technique is elegantly simple: a Stop hook intercepts Claude's exit attempts and feeds the same prompt back, creating a self-referential feedback loop.

### How It Works

```bash
# You run ONCE:
/ralph-loop "Your task description" --completion-promise "DONE"

# Then Claude Code automatically:
# 1. Works on the task
# 2. Tries to exit
# 3. Stop hook blocks exit
# 4. Stop hook feeds the SAME prompt back
# 5. Repeat until completion
```

### Key Principles

| Principle | Description |
|-----------|-------------|
| **Iteration > Perfection** | Don't aim for perfect on first try - let the loop refine |
| **Failures Are Data** | "Deterministically bad" means failures are predictable and informative |
| **Operator Skill Matters** | Success depends on writing good prompts, not just having a good model |
| **Persistence Wins** | Keep trying until success; retry logic is automatic |

### Prompt Best Practices from Ralph

1. **Clear completion criteria** - Include explicit success markers like `<promise>COMPLETE</promise>`
2. **Incremental goals** - Break into phases with checkpoints
3. **Self-correction built in** - Include TDD loops in the prompt
4. **Escape hatches** - Always use `--max-iterations` as a safety net

### Real-World Results (Claimed)

- 6 repositories generated overnight in Y Combinator hackathon
- One $50k contract completed for $297 in API costs
- Entire programming language created over 3 months

### Relevance to AgentTree

This validates AgentTree's approach of keeping agents running until completion with proper verification. However, AgentTree uses external monitoring (issue #119) rather than stop-hook interception.

**Gap identified:** AgentTree doesn't prevent agents from exiting prematurely. An agent can stop mid-task without running `agenttree next`. Issue #119 addresses detection but not prevention.

---

## 2. Everything Claude Code

**Source:** [affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code) (36.2k stars)

### What It Is

A comprehensive collection of Claude Code configurations from an Anthropic hackathon winner. Battle-tested across 10+ months of daily use.

### Structure

```
everything-claude-code/
├── agents/           # 11 specialized subagents
├── skills/           # Workflow definitions and domain knowledge
├── commands/         # Slash commands (/tdd, /plan, /verify, etc.)
├── rules/            # Always-follow guidelines
├── hooks/            # Trigger-based automations
├── contexts/         # Dynamic system prompt injection
├── mcp-configs/      # MCP server configurations
```

### Notable Agent Templates

| Agent | Purpose |
|-------|---------|
| `planner.md` | Feature implementation planning |
| `architect.md` | System design decisions |
| `tdd-guide.md` | Test-driven development |
| `code-reviewer.md` | Quality and security review |
| `security-reviewer.md` | Vulnerability analysis |
| `build-error-resolver.md` | Fix build errors |
| `refactor-cleaner.md` | Dead code cleanup |

### Skills (Workflow Definitions)

| Skill | Purpose |
|-------|---------|
| `continuous-learning/` | Auto-extract patterns from sessions |
| `continuous-learning-v2/` | Instinct-based learning with confidence scoring |
| `iterative-retrieval/` | Progressive context refinement for subagents |
| `strategic-compact/` | Manual compaction suggestions |
| `verification-loop/` | Continuous verification |

### Continuous Learning System

```bash
/instinct-status        # Show learned instincts with confidence
/instinct-import <file> # Import instincts from others
/instinct-export        # Export your instincts for sharing
/evolve                 # Cluster related instincts into skills
```

This is a sophisticated pattern where the system learns from successful sessions and builds "instincts" - patterns that can be applied to future tasks.

### Context Window Management (Critical Insight)

> "Don't enable all MCPs at once. Your 200k context window can shrink to 70k with too many tools enabled."

**Rule of thumb:**
- Have 20-30 MCPs configured
- Keep under 10 enabled per project
- Under 80 tools active

### Key Learnings for AgentTree

1. **Agent specialization** - Dedicated agents for specific tasks (planning, reviewing, TDD) rather than one generalist
2. **Skill extraction** - Automatically learning patterns from successful sessions
3. **Verification loops** - Built-in self-checking mechanisms
4. **Context management** - Strategic compaction and memory persistence across sessions

---

## 3. Oh-My-ClaudeCode (OMC)

**Source:** [Yeachan-Heo/oh-my-claudecode](https://github.com/Yeachan-Heo/oh-my-claudecode) (3.9k stars)

### What It Is

Multi-agent orchestration for Claude Code with 5 execution modes. Tagline: "Don't learn Claude Code. Just use OMC."

### Execution Modes

| Mode | Speed | Use Case |
|------|-------|----------|
| **Autopilot** | Fast | Full autonomous workflows |
| **Ultrapilot** | 3-5x faster | Multi-component systems (parallel execution) |
| **Ecomode** | 30-50% cheaper | Budget-conscious projects (smart model routing) |
| **Swarm** | Coordinated | Parallel independent tasks |
| **Pipeline** | Sequential | Multi-stage processing |

### Scale

- **32 specialized agents** for architecture, research, design, testing, data science
- **31+ skills** for various workflows
- **Smart model routing** - Haiku for simple tasks, Opus for complex reasoning

### Magic Keywords

Natural language interface with optional power-user shortcuts:

| Keyword | Effect |
|---------|--------|
| `autopilot` | Full autonomous execution |
| `ralph` | Persistence mode (includes ultrawork automatically) |
| `ulw` | Maximum parallelism |
| `eco` | Token-efficient execution |
| `plan` | Planning interview |

### Notable Features

1. **HUD Statusline** - Real-time orchestration metrics in status bar
2. **Rate Limit Wait** - Auto-resume when rate limits reset (`omc wait --start`)
3. **Analytics & cost tracking** - Token usage across sessions
4. **Zero configuration** - Works out of the box with intelligent defaults

### Key Learnings for AgentTree

1. **Mode-based execution** - Different strategies for different task types
2. **Parallel orchestration** - Distributing work across multiple agents
3. **Cost optimization** - Model routing based on task complexity
4. **User experience** - Magic keywords, HUD status, zero-config defaults
5. **Rate limit handling** - Automatic recovery from API limits

---

## 4. Skill Composer

**Source:** [benegessarit/skill-composer](https://github.com/benegessarit/skill-composer)

### Concept

Skill Composer treats prompt modifiers like CSS classes - small, independent, composable units that stack at runtime. The tagline: "Like CSS for AI."

```
#pref #ver What's the best way to refactor this auth module?
```

That combines `#pref` (preflight - triple-check before acting) with `#ver` (verify - prove claims with evidence). Two thinking patterns composed at prompt-time.

### The Problem It Solves

> "Claude keeps forgetting to think carefully before acting. `#pref` forces preflight checks. `#ver` forces evidence. Stacking them (`#pref #ver`) compounds the forcing."

It's "discipline disguised as syntax."

### Available Modes

**Action Modes (WHAT to do):**

| Trigger | Mode | What It Does |
|---------|------|--------------|
| `#pref` | preflight | Triple-check before execution. Facts, completeness, consequences |
| `#ver` | verify | Prove claims with evidence. Show receipts or retract |
| `#clar` | clarify | Surface interpretations before answering |
| `#comp` | compare | Side-by-side comparison with clear criteria |
| `#teach` | teach-me | Socratic teaching. Build understanding, don't dump info |
| `#research` | research | Two-phase: survey landscape, then deep-dive |
| `#trace` | trace | Follow execution paths through code |

**Context Modes (HOW to think):**

| Trigger | Mode | What It Does |
|---------|------|--------------|
| `#qlight` | question-light | Add thoughtful questions without interrogation |
| `#qheavy` | question-heavy | Ruthless clarification. Interrogate every assumption |

**Deep Variants:** Add `*` for metacognitive audit:
```
#pref* Am I over-engineering this?
```

### Design Philosophy

- **Declarative** - Declare WHAT thinking patterns to apply, modes handle HOW
- **Composable** - Modes are independent, stack at runtime, no inheritance
- **Late binding** - Compose at prompt-time, not definition-time

### Optional: Reasoning MCP

The deep variants can use an optional `reasoning-mcp` for structured metacognition:
- **depth_probe** - Audit reasoning before starting ("where will my analysis be shallow?")
- **ensemble** - Generate personas, role-play each in separate turns
- **chaos agent** - Stress-test assumptions via perturbation
- **forced synthesis** - Track dissent, require explicit conclusion

### Key Learnings for AgentTree

This is a different axis than the other projects - not about agents or orchestration, but about **thinking quality**.

**However, AgentTree already has this capability.** Our Jinja-templated skill files can include mode content directly:

```markdown
# _agenttree/skills/implement/code_review.md

{% include '_agenttree/skills/modes/verify.md' %}
{% include '_agenttree/skills/modes/question_heavy.md' %}

## Self-Review Checklist
...
```

The difference is in *when* composition happens:

| Approach | When Composed | Who Controls |
|----------|---------------|--------------|
| **skill-composer** | Prompt-time (user types `#pref`) | User chooses per-prompt |
| **AgentTree** | Stage-time (skill file loaded) | Workflow designer chooses per-stage |

**AgentTree's structured approach is likely better for our use case** - we *want* the workflow to enforce certain thinking patterns at certain stages. We don't want agents to forget to verify in code review because they didn't type `#ver`.

Potential stage-to-mode mappings (can add directly to skill files):

| AgentTree Stage | Thinking Mode |
|-----------------|---------------|
| `define.refine` | Clarify - Surface interpretations |
| `research.explore` | Research - Survey then deep-dive |
| `plan.draft` | Compare - Side-by-side approaches |
| `implement.code` | Preflight - Triple-check before changes |
| `implement.code_review` | Verify + Question - Prove with evidence |

**No hashtag shortcuts needed** - just embed the mode instructions in stage skill templates.

---

## Comparison Table

| Feature | AgentTree | Ralph Wiggum | Everything Claude Code | OMC | Skill Composer |
|---------|-----------|--------------|----------------------|-----|----------------|
| **Primary Focus** | Issue-based workflow | Iteration loops | Config collection | Orchestration | Thinking quality |
| **Persistence** | ✅ Hooks + monitoring | ✅ Stop hook | ✅ Hooks | ✅ Autopilot | ❌ |
| **Parallel Execution** | ❌ | ❌ | ❌ | ✅ Ultrapilot/Swarm | ❌ |
| **Agent Specialization** | Partial (review agent) | ❌ | ✅ 11 agents | ✅ 32 agents | ❌ |
| **Skill Learning** | ❌ | ❌ | ✅ Continuous learning | ✅ | ❌ |
| **Model Routing** | ❌ | ❌ | ❌ | ✅ Eco mode | ❌ |
| **Composable Modes** | ❌ | ❌ | ❌ | ❌ | ✅ Hashtag stacking |
| **Metacognition** | ❌ | ❌ | ❌ | ❌ | ✅ Deep variants |
| **Container Isolation** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **GitHub Integration** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Issue Tracking** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Stall Detection** | ✅ (PR #96) | ❌ | ❌ | ❌ | ❌ |

---

## Recommendations for AgentTree

### Near-term (Low Effort, High Impact)

1. **Add more agent templates** - Following everything-claude-code's pattern:
   - `_agenttree/skills/agents/planner.md`
   - `_agenttree/skills/agents/tdd.md`
   - `_agenttree/skills/agents/security-reviewer.md`

2. **Merge issue #119** - Stall monitoring is ready and addresses the gap Ralph solves differently

3. **Document completion patterns** - Clear guidance on how agents should signal completion (run `agenttree next`)

### Medium-term

1. **Parallel agent spawning** - For independent subtasks within an issue (similar to OMC's Swarm mode)

2. **Skill extraction** - Learn patterns from successful agent sessions and save to `_agenttree/skills/learned/`

3. **Model routing** - Use cheaper/faster models for simple stages (like plan drafting), more capable models for implementation

### Long-term

1. **Execution modes** - Let users choose autopilot/eco/parallel strategies via config or CLI flag

2. **HUD/status integration** - Real-time visibility into agent orchestration (beyond web dashboard)

3. **Cross-session learning** - Build knowledge base from agent history (like everything-claude-code's continuous learning v2). **IMPLEMENTED:** Added `_agenttree/knowledge/` directory with starter files (gotchas.md, patterns.md, commands.md, workflow-tips.md) and "Knowledge for Future Agents" section in feedback.md template. TODO: Add `knowledge_update` stage after merge to incorporate learnings.

4. **Rate limit recovery** - Auto-resume agents when API rate limits reset (like OMC's `omc wait`)

5. **Thinking mode templates** - Create reusable mode files in `_agenttree/skills/modes/`:
   - `verify.md` - Prove claims with evidence
   - `preflight.md` - Triple-check before acting
   - `clarify.md` - Surface assumptions
   - Include these in stage skill files via Jinja `{% include %}` (we already have this capability)

---

## AgentTree's Unique Differentiators

Despite lacking some features from these projects, AgentTree has unique strengths:

1. **Container isolation** - Security model none of these projects have
2. **GitHub-integrated workflow** - Issues, PRs, CI feedback loop built-in
3. **Structured workflow stages** - Enforced progression through define → plan → implement → review
4. **Human-in-the-loop design** - Review stages require explicit approval
5. **Multi-agent coordination** - Different agent types (default, review, custom) with proper handoffs

---

## Related Work

- **Issue #119** - Controller agent to monitor and nudge stalled agents (PR #96 ready to merge)
- **PLAN_TASK_REENGAGEMENT.md** - Planning doc on task context persistence
- **docs/architecture/distributed-state-machine-analysis.md** - State machine formalization

---

## References

- [Ralph Wiggum Plugin README](https://github.com/anthropics/claude-code/blob/main/plugins/ralph-wiggum/README.md)
- [everything-claude-code Repository](https://github.com/affaan-m/everything-claude-code)
- [oh-my-claudecode Repository](https://github.com/Yeachan-Heo/oh-my-claudecode)
- [skill-composer Repository](https://github.com/benegessarit/skill-composer)
- [The Shorthand Guide to Everything Claude Code](https://x.com/affaanmustafa/status/2012378465664745795)
- [The Longform Guide to Everything Claude Code](https://x.com/affaanmustafa/status/2014040193557471352)

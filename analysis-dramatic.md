# BLOOD, CODE, AND BETRAYAL: The AgentTree-FormalTask Saga

### *Two friends. Two codebases. One impossible question.*

---

**NARRATOR VOICE:** *[Deep, gravelly, over sweeping orchestral strings]*

They survived the startup trenches. They survived the board meetings. They survived **her**.

But can they survive... *each other's pull requests?*

---

## ACT I: ORIGIN

They met the way all great rivalries begin -- as roommates. One, a **Jewish titan of tech investing**, a man who could read a term sheet the way Mozart read music, who could value a Series B in his sleep but had never once, not even accidentally, closed a `<div>` tag. The other, a **battle-scarred entrepreneur and champion of code**, a man who'd shipped more products than most people have downloaded, who'd learned to program before he learned that most people don't argue with compilers for fun.

They were inseparable. They co-founded together. They laughed together. They played **Risk** together -- and if you've never watched two alpha males spend nine hours fighting over Kamchatka while drinking bourbon and questioning each other's intelligence, moral character, and life choices, then you have never truly lived.

They dated. The. Same. Woman.

*[Record scratch]*

They're still friends.

**TITLE CARD:** *How?*

---

## ACT II: THE DIVERGENCE

It was February 2026. The AI agent revolution was upon us. Claude Code could write software, but running *one* agent was like hiring *one* contractor -- technically progress, practically a bottleneck.

Both men saw the same future: **multiple AI agents, working in parallel, orchestrated by a system that wouldn't let them produce garbage.** Both men, independently, in different rooms, probably on the same night, probably while the other was asleep -- *built the same thing.*

**Dave** built **AgentTree**. Containers. Web dashboards. Multi-tool support. The Swiss Army knife. The pragmatist's dream. *"Give me a workflow engine and get out of my way."*

**David** built **FormalTask**. Rules kernels. 80 specialized reviewer agents. A completion DSL. The quality zealot's manifesto. *"Nothing ships until my 22-rule gating system says it ships."*

They both chose git worktrees. They both chose tmux. They both cited **antirez**. They both wrote "anti-slop rules" into their project conventions.

*[Camera zooms in on two nearly identical CLAUDE.md files, side by side]*

**EXPERT ANALYST, adjusting glasses:** "The probability of two independent projects both implementing triple-verified worktree safety checks with fallback to `git merge-base --is-ancestor`... is... *[long pause]* ...actually kind of inevitable when you think about it, but it makes for a better story if we say it's cosmically unlikely."

---

## ACT III: THE CONFRONTATION

The differences are where it gets **personal**.

Dave, the coder, the builder, the man who *thinks in systems* -- he made AgentTree **tool-agnostic**. Claude Code, Aider, Codex, whatever comes next. Plug it in. The tool is replaceable. The workflow is forever. He added **containers** because he doesn't trust anything that runs on his machine without a security boundary. He built a **web dashboard** because he wants to *see* what's happening, across a room, on a phone, on a beach.

David, the investor, the newcomer to code, the man who learned to program *by orchestrating AI agents that program* -- he went **all in on Claude Code**. Deep hook integration. PreToolUse validators. PostToolUse logging. You can't even run `--no-verify` without his system slapping your hand. He built **80 specialized reviewer agents** because one reviewer is a single point of failure and David has never, in his life, accepted a single point of failure. He built a **rules kernel with a DSL** because when David says "done," he means *provably done, structurally verified, with receipts.*

*[Split screen: Dave's Kanban board glowing on a browser vs. David's TUI dashboard flickering in a terminal]*

**Dave:** "Why would you lock yourself into one tool?"
**David:** "Why would you half-integrate with all of them when you could fully integrate with the best one?"

**Dave:** "My agents run in containers. Yours run... on your laptop. Naked."
**David:** "My agents pass through 22 completion rules. Yours pass through... *vibes?*"

**Dave:** "I store state in YAML files you can read with `cat`."
**David:** "I store state in SQLite with WAL mode and transactional guarantees."

**Dave:** "YAML is human-readable."
**David:** *[laughing]* "So is a car crash."

---

## ACT IV: WHAT THEY'LL NEVER ADMIT

Here's what neither of them will say out loud:

**Dave's system is missing FormalTask's quality engine.** The 80 specialized reviewers. The structured findings with P0/P1/P2 priorities. The review freshness detection. The delta handoff that preserves context when Claude's memory compresses. These aren't nice-to-haves -- they're what separate "AI wrote some code" from "AI wrote code that a human can trust."

**David's system is missing AgentTree's operational muscle.** Container isolation. Remote execution over Tailscale. Multi-tool support. A web UI anyone can use. These aren't nice-to-haves -- they're what separate "works on my laptop" from "works in a team."

They're not competitors. They're **complements**.

Dave built the **body** -- the infrastructure, the containers, the networking, the visual dashboard, the tool-agnostic orchestration layer.

David built the **brain** -- the rules engine, the quality gates, the specialized reviewers, the context preservation, the completion verification.

One without the other is a soldier without a strategist. A courthouse without cops. A Risk board without anyone willing to fight over Kamchatka for nine hours.

---

## ACT V: THE QUESTION

*[Music swells. Camera pulls back to reveal both men sitting across a table, laptops open, a half-empty bottle of bourbon between them, a Risk board -- mid-game, naturally -- shoved to one side]*

They've survived roommate passive-aggression. They've survived cap table negotiations. They've survived **the same woman.** They've survived a thousand games of Risk where alliances were formed and broken before the ice melted in the glass.

But now they face the ultimate test. The one no friendship guide prepares you for. The one that has destroyed partnerships since the first caveman drew a flowchart on a cave wall:

***Do you merge the codebases?***

*[Silence]*

*[The bourbon glints in the lamplight]*

*[A tmux session blinks in the background]*

**TITLE CARD:**

# AGENTTREE x FORMALTASK

*One built the infrastructure. One built the intelligence.*

*Coming to a git repository near you.*

*Or not. They might just play Risk instead.*

---

**POST-CREDITS SCENE:**

*[Both men staring at a screen]*

**Dave:** "Your CLAUDE.md is 200 lines."
**David:** "Yours is 180."
**Dave:** "Mine's more concise."
**David:** "Mine has a rules kernel."
**Dave:** "..."
**David:** "..."

*[They both reach for the bourbon]*

**FADE TO BLACK.**

---

*Based on a true story. The names have not been changed because honestly, you can't make this up.*

*No git repositories were harmed in the making of this document. Several were force-pushed, but we don't talk about that.*

# Plan: AgentTree Cloud Service

**Product Name**: AgentTree Cloud
**Tagline**: "Cursor Agents, but powerful and self-hosted-first"

**Goal**: Offer fully-managed cloud agents with dangerous mode, Playwright browsers, and multi-AI provider support, while keeping local execution as first-class.

---

## Value Proposition

**What Cursor Agents offers:**
- ✅ Easy to use
- ✅ Integrated into IDE
- ❌ Limited to Cursor's models
- ❌ No dangerous mode / limited tool execution
- ❌ Single agent at a time
- ❌ Cloud-only, no local option

**What AgentTree Cloud offers:**
- ✅ Full dangerous mode in isolated containers
- ✅ Playwright browser automation
- ✅ Switch between Claude, GPT-4, Gemini, local models
- ✅ Multiple agents in parallel
- ✅ **Local-first**: Works 100% on your machine, cloud is optional
- ✅ Open source core, paid hosting

**Target users:**
1. **Developers** who want parallel agents but don't want to manage infrastructure
2. **Teams** who need shared agent infrastructure
3. **Power users** who want dangerous mode without risk to their machine
4. **Agencies** who run agents for clients

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      User's Machine                              │
├─────────────────────────────────────────────────────────────────┤
│  agenttree CLI                                                   │
│  ├── Local mode:  Agents run in ~/Projects/worktrees/           │
│  └── Cloud mode:  Agents run in cloud, CLI streams output       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS + WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   AgentTree Cloud (api.agenttree.dev)           │
├─────────────────────────────────────────────────────────────────┤
│  Control Plane (FastAPI)                                         │
│  ├── User accounts & billing                                    │
│  ├── Agent provisioning                                          │
│  ├── Model routing (Claude/GPT-4/Gemini)                        │
│  └── WebSocket for live streaming                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Spawn containers
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Agent Runtime Containers                      │
│                    (Modal Labs / Fly.io)                         │
├─────────────────────────────────────────────────────────────────┤
│  Container 1:                                                    │
│  ├── Git worktree (ephemeral)                                   │
│  ├── AI tool (Claude Code, Aider, etc.)                         │
│  ├── Playwright browser                                          │
│  ├── Full shell access (dangerous mode)                         │
│  └── Auto-destroyed after task                                  │
│                                                                  │
│  Container 2: ...                                                │
│  Container 3: ...                                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## User Experience

### Setup (30 seconds)

```bash
# Install CLI
npm install -g agenttree

# Login to cloud (optional - local works without account)
agenttree login

# Initialize project
cd ~/Projects/myapp
agenttree init

# Choose mode
# 1. Local (free, runs on your machine)
# 2. Cloud (paid, runs in cloud with dangerous mode)
# Mode [1]: 2

# Authenticated with AgentTree Cloud
# ✓ 3 cloud agents ready
#
# Free tier: 10 hours/month
# Current usage: 0/10 hours
```

### Dispatch to Cloud Agent

```bash
# Dispatch to cloud
agenttree dispatch cloud-1 42

# Output:
# ✓ Spawning cloud container...
# ✓ Cloning repository...
# ✓ Starting Claude Code (dangerous mode enabled)
#
# [streaming output from agent...]
#
# Agent is working on issue #42
# Live view: https://app.agenttree.dev/agents/abc123
```

### Live Dashboard

Web UI at `app.agenttree.dev`:
- 📺 Live terminal streaming
- 📊 Agent status (all agents)
- 💰 Usage & billing
- 🔧 Configuration
- 📝 Task history
- 🎛️ Model switching

### Model Switching

```bash
# Switch AI provider mid-task
agenttree config set --model gpt-4

# Or per-dispatch
agenttree dispatch cloud-1 42 --model claude-opus-4
agenttree dispatch cloud-2 43 --model gpt-4
agenttree dispatch cloud-3 44 --model gemini-2.0-flash
```

---

## Technical Implementation

### Container Platform: Modal Labs

**Why Modal:**
- ✅ Serverless containers - only pay when running
- ✅ GPU support (if we need it later)
- ✅ Simple Python API
- ✅ Fast cold starts (< 10s)
- ✅ Built-in logging & monitoring
- ✅ Auto-scaling

**Alternative considered:**
- **Fly.io**: Great for long-running apps, but more expensive for ephemeral agents
- **AWS Fargate**: Slow cold starts, complex config
- **GCP Cloud Run**: Good, but less developer-friendly than Modal

**Container lifecycle:**

```python
# agenttree-cloud/agent_runner.py
import modal

stub = modal.Stub("agenttree-agents")

# Container image with all tools
image = (
    modal.Image.debian_slim()
    .pip_install([
        "anthropic",
        "openai",
        "google-generativeai",
        "aider-chat",
        "playwright"
    ])
    .run_commands([
        "playwright install chromium",
        "apt-get update && apt-get install -y git tmux gh"
    ])
)

@stub.function(
    image=image,
    cpu=4,
    memory=8192,  # 8GB RAM
    timeout=3600,  # 1 hour max
    secrets=[
        modal.Secret.from_name("anthropic-api-key"),
        modal.Secret.from_name("openai-api-key"),
        modal.Secret.from_name("google-api-key")
    ]
)
def run_agent(
    repo_url: str,
    branch: str,
    task: str,
    model: str = "claude",
    github_token: str = None,
    dangerous: bool = True
):
    """Run an agent task in isolated container"""

    import subprocess
    import os
    from pathlib import Path

    # Setup workspace
    workspace = Path("/workspace")
    workspace.mkdir(exist_ok=True)
    os.chdir(workspace)

    # Clone repo
    subprocess.run([
        "git", "clone",
        "--depth", "1",
        "--branch", branch,
        repo_url,
        "repo"
    ], check=True)

    os.chdir("repo")

    # Create TASK.md
    Path("TASK.md").write_text(f"# Task\n\n{task}\n")

    # Configure git
    if github_token:
        subprocess.run([
            "git", "config",
            "--global", "credential.helper",
            f"!f() {{ echo username=x-access-token; echo password={github_token}; }}; f"
        ])

    # Start AI tool
    ai_cmd = {
        "claude": "claude",
        "aider": "aider",
        "gpt-4": "aider --model gpt-4-turbo",
        "claude-opus-4": "claude",  # Use ANTHROPIC_MODEL env
    }[model]

    if dangerous:
        ai_cmd += " --dangerously-skip-permissions"

    # Run with streaming
    proc = subprocess.Popen(
        ai_cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    # Stream output back to control plane
    for line in proc.stdout:
        # This gets sent to WebSocket
        yield {"type": "stdout", "data": line}

    proc.wait()

    # Return final status
    yield {
        "type": "complete",
        "exit_code": proc.returncode,
        "repo_state": get_git_status()
    }

# Control plane calls this
@stub.function()
def spawn_agent(task_config: dict):
    """Spawn agent and stream output"""

    # This returns a generator that yields stdout
    for output in run_agent.call(
        repo_url=task_config['repo_url'],
        branch=task_config['branch'],
        task=task_config['task'],
        model=task_config['model'],
        dangerous=True
    ):
        # Send to WebSocket
        websocket_send(task_config['user_id'], output)
```

**Costs:**
- Modal pricing: ~$0.10/hour for 4 CPU + 8GB RAM
- Our cost: $0.10/agent-hour
- We charge: $0.25/agent-hour (2.5x markup)

### Control Plane (FastAPI)

```python
# agenttree-cloud/api/main.py
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import stripe
import modal

app = FastAPI()

# User accounts
@app.post("/api/signup")
async def signup(email: str, password: str):
    """Create account"""
    user = create_user(email, password)
    stripe_customer = stripe.Customer.create(email=email)
    user.stripe_customer_id = stripe_customer.id
    return {"user_id": user.id, "api_key": generate_api_key(user)}

# Agent dispatch
@app.post("/api/agents/dispatch")
async def dispatch_agent(
    repo_url: str,
    task: str,
    model: str = "claude",
    api_key: str = Header(...)
):
    """Dispatch task to cloud agent"""

    user = authenticate(api_key)

    # Check quota
    usage = get_usage(user.id, current_month())
    if usage.hours >= user.quota_hours:
        raise HTTPException(402, "Quota exceeded")

    # Spawn Modal container
    task_id = generate_id()
    modal_stub = modal.Stub.lookup("agenttree-agents")

    # Start async
    modal_stub.spawn_agent.spawn(
        task_config={
            "user_id": user.id,
            "task_id": task_id,
            "repo_url": repo_url,
            "branch": "main",
            "task": task,
            "model": model
        }
    )

    return {
        "task_id": task_id,
        "status": "starting",
        "stream_url": f"wss://api.agenttree.dev/stream/{task_id}"
    }

# WebSocket for streaming
@app.websocket("/stream/{task_id}")
async def stream_task(websocket: WebSocket, task_id: str):
    """Stream agent output to client"""
    await websocket.accept()

    # Subscribe to task output
    async for message in task_stream(task_id):
        await websocket.send_json(message)
```

### CLI Integration

```python
# agenttree/cloud.py

class CloudAgent:
    """Interface to cloud agents"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.agenttree.dev"

    async def dispatch(
        self,
        agent_num: int,
        task: str,
        model: str = "claude"
    ):
        """Dispatch to cloud agent with live streaming"""

        # Get repo info
        repo = git.Repo(".")
        repo_url = repo.remotes.origin.url
        branch = repo.active_branch.name

        # Start task
        resp = requests.post(
            f"{self.base_url}/api/agents/dispatch",
            json={
                "repo_url": repo_url,
                "task": task,
                "model": model
            },
            headers={"Authorization": f"Bearer {self.api_key}"}
        )

        task_id = resp.json()["task_id"]
        stream_url = resp.json()["stream_url"]

        print(f"✓ Cloud agent started: {task_id}")
        print(f"Live view: https://app.agenttree.dev/tasks/{task_id}\n")

        # Stream output
        async with websockets.connect(stream_url) as ws:
            while True:
                msg = await ws.recv()
                data = json.loads(msg)

                if data["type"] == "stdout":
                    print(data["data"], end="")

                elif data["type"] == "complete":
                    print(f"\n✓ Task complete (exit {data['exit_code']})")
                    break

# agenttree/cli.py

@click.command()
@click.argument("agent")
@click.argument("task")
@click.option("--model", default="claude")
def dispatch(agent: str, task: str, model: str):
    """Dispatch task to agent (local or cloud)"""

    config = load_config()

    if agent.startswith("cloud-"):
        # Cloud agent
        cloud = CloudAgent(config['api_key'])
        asyncio.run(cloud.dispatch(agent, task, model))
    else:
        # Local agent
        local_dispatch(agent, task)
```

---

## Pricing Model

**Two-part pricing:** Container hours + AI model usage

### What are "cloud agent-hours"?

An **agent-hour** is 1 hour of container compute time where an agent runs. This includes:
- ✅ Container CPU/RAM (4 CPU, 8GB RAM)
- ✅ Playwright browser
- ✅ Git, tmux, dev tools
- ✅ File system and isolation

**AI model usage is billed separately** based on actual token consumption.

---

### Free Tier
- ✅ Unlimited local agents (runs on your machine, $0 forever)
- ✅ 10 cloud agent-hours/month (container time)
- ✅ $5/month free AI credits (covers ~2.5M Claude Sonnet tokens)
- ✅ All AI models available
- ✅ Dangerous mode enabled
- ✅ Community support

### Pro Tier ($29/month)
- ✅ 100 cloud agent-hours/month (container time)
- ✅ $10/month included AI credits
- ✅ Priority execution (faster container start)
- ✅ Team sharing (5 seats)
- ✅ Advanced analytics
- ✅ Email support

### Team Tier ($99/month)
- ✅ 500 cloud agent-hours/month (container time)
- ✅ $50/month included AI credits
- ✅ Dedicated containers (always hot)
- ✅ Unlimited team members
- ✅ SSO
- ✅ Priority support

### Enterprise (Custom)
- ✅ Unlimited hours
- ✅ Custom AI credit packages
- ✅ Self-hosted option
- ✅ Custom models (BYO API keys)
- ✅ SLA
- ✅ Dedicated support

**Overage pricing:**
- Container hours: $0.25/hour beyond quota
- AI credits: Pay as you go at rates below

---

## Model Routing & Costs

We act as a proxy for different AI providers:

| Model | Our Cost/1M tokens | User Cost/1M tokens | Our Markup |
|-------|-------------------|---------------------|------------|
| Claude Sonnet 4 | $3 / $15 | $4 / $20 | 33% |
| Claude Opus 4 | $15 / $75 | $20 / $100 | 33% |
| GPT-4 Turbo | $10 / $30 | $13 / $39 | 30% |
| GPT-4o | $5 / $15 | $7 / $20 | 40% |
| Gemini 2.0 Flash | $0.075 / $0.30 | $0.10 / $0.40 | 33% |

**Example bill for Pro user ($29/mo):**
- 100 hours of agent work
- Used 50 hours actual container time
- Agent made 10M tokens of Claude Sonnet API calls
  - Input: 7M tokens × $4/1M = $28
  - Output: 3M tokens × $20/1M = $60
  - Total AI: $88

**Total bill: $29 (base) + $88 (AI) = $117**

**Our costs:**
- Container: 50 hours × $0.10 = $5
- AI: 10M tokens @ our cost = $66
- Total costs: $71

**Our profit: $46 (39% margin)**

---

## Margin Breakdown

### Container Hours

| Tier | Monthly Price | Hours Included | Our Cost | Margin |
|------|--------------|----------------|----------|--------|
| Free | $0 | 10 | $1 | Loss leader |
| Pro | $29 | 100 | $10 | **65% ($19)** |
| Team | $99 | 500 | $50 | **49% ($49)** |

Modal Labs charges us ~$0.10/hour for 4 CPU + 8GB RAM containers.

### AI Model Usage

- 30-40% markup on all AI providers
- Pure pass-through with margin
- No infrastructure cost (just API calls)

**Blended margins:** Assuming average user uses 50% of container quota and $50-100 in AI:
- Container margin: 49-65%
- AI margin: 30-40%
- **Overall margin: ~45%**

This is healthy for a SaaS business (typical is 30-50%).

---

## Why Two-Part Pricing?

**Alternative considered:** Bundle everything into one price (e.g., "$99/mo unlimited")

**Why we don't:**
1. **AI costs vary wildly** - GPT-4 vs Gemini Flash is 100x difference
2. **Usage unpredictable** - Some tasks take 10M tokens, some take 100K
3. **Unit economics break** - Heavy users would destroy margins
4. **No alignment** - We want users to use efficient models when appropriate

**Two-part pricing benefits:**
1. **Transparent costs** - Users see exactly what they're paying for
2. **Flexibility** - Choose expensive models when needed, cheap when not
3. **Sustainable** - We don't subsidize heavy AI users
4. **Predictable** - Container hours are fixed, AI scales with usage

**User psychology:**
- $29/mo feels affordable for the base
- AI costs are "usage-based" and expected for API services
- Similar to AWS model (EC2 + API calls)

---

## Why This Works

**For users:**
- Pay $0 forever for local use (vs Cursor/Copilot subscriptions)
- Only pay for cloud when they need isolation/dangerous mode
- One bill for all AI providers (vs managing multiple API keys)
- Usage tracking and budget alerts included

**For us:**
- Container costs are fixed and predictable
- AI markup provides steady margin
- Free tier drives adoption (local is free!)
- Upsell path clear (local → cloud → team)

---

## Revenue Model

**Year 1 goals:**
- 1,000 free users (local + small cloud usage)
- 100 Pro users ($29/mo) = $2,900/mo
- 10 Team users ($99/mo) = $990/mo
- **Total MRR: $3,890**

**Year 2 goals:**
- 10,000 free users
- 1,000 Pro users = $29,000/mo
- 100 Team users = $9,900/mo
- 5 Enterprise deals = $10,000/mo
- **Total MRR: $48,900**

**Costs:**
- Modal compute: ~$1,000/mo (Year 1)
- AI API costs: Pass-through + 33% markup
- Infrastructure: $500/mo (hosting, monitoring)
- **Total: ~$1,500/mo (Year 1)**

**Profit margin: 62%** (healthy for SaaS)

---

## Competitive Analysis

| Feature | AgentTree Cloud | Cursor Agents | Devin | OpenHands |
|---------|----------------|---------------|-------|-----------|
| **Price** | $0-99/mo | Free (Cursor Pro) | $500/mo | Free (OSS) |
| **Local option** | ✅ Yes | ❌ No | ❌ No | ✅ Yes (Docker) |
| **Cloud option** | ✅ Yes | N/A | ✅ Yes | ❌ No |
| **Dangerous mode** | ✅ Yes | ❌ Limited | ✅ Yes | ✅ Yes |
| **Playwright** | ✅ Yes | ❌ No | ✅ Yes | ✅ Yes |
| **Multi-AI** | ✅ Yes | ❌ No | ❌ No | ✅ Yes |
| **Parallel agents** | ✅ Unlimited | ❌ 1 at a time | ❌ 1 at a time | ⚠️ Manual | | **Open source** | ✅ Core MIT | ❌ No | ❌ No | ✅ Yes |

**Our moat:**
1. **Local-first philosophy**: Cloud is optional, not required
2. **Multi-model**: Switch between Claude/GPT/Gemini/local
3. **Parallel agents**: Run 10 agents at once if you want
4. **Dangerous mode in cloud**: Safe isolation for risky tasks

---

## Go-to-Market Strategy

### Phase 1: Launch Open Source Core (Month 1-2)
- Release `agenttree` CLI as MIT license
- Focus on local-only usage
- Build community on GitHub
- **Goal: 1,000 GitHub stars**

### Phase 2: Private Beta (Month 3-4)
- Invite 50 users to cloud beta
- Gather feedback on pricing
- Iterate on UX
- **Goal: 20 paying beta users**

### Phase 3: Public Launch (Month 5)
- Launch cloud service publicly
- Product Hunt launch
- Write technical blog posts
- **Goal: 100 Pro users**

### Phase 4: Enterprise (Month 6-12)
- Self-hosted offering
- Custom integrations
- Sales outreach
- **Goal: 5 enterprise deals**

---

## Technical Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| **Modal outage** | High | Multi-cloud failover (Fly.io backup) |
| **Agent escapes container** | Critical | VM isolation (Firecracker), audit logging |
| **Expensive AI usage** | Medium | Usage caps, budget alerts |
| **Slow cold starts** | Low | Keep pool of warm containers |
| **Git access** | Medium | Ephemeral SSH keys, auto-revoke |

---

## Implementation Plan

### Month 1: Core Cloud Infrastructure
- [ ] Modal container setup
- [ ] FastAPI control plane
- [ ] WebSocket streaming
- [ ] Basic authentication

### Month 2: Model Integration
- [ ] Claude API integration
- [ ] OpenAI API integration
- [ ] Gemini API integration
- [ ] Model routing logic

### Month 3: Billing & Accounts
- [ ] Stripe integration
- [ ] Usage tracking
- [ ] Quota enforcement
- [ ] Pricing tiers

### Month 4: Dashboard
- [ ] Next.js web app
- [ ] Live terminal view
- [ ] Usage analytics
- [ ] Model switcher

### Month 5: CLI Integration
- [ ] `agenttree login`
- [ ] `agenttree dispatch cloud-N`
- [ ] Live output streaming
- [ ] Cloud config management

### Month 6: Beta Launch
- [ ] Private beta (50 users)
- [ ] Documentation
- [ ] Support system
- [ ] Monitoring & alerts

**Total timeline: 6 months to beta**

---

## Success Metrics

### Technical
- ⏱️ Container cold start: < 10 seconds
- 📊 Uptime: > 99.5%
- 💰 Compute cost/user: < $5/month (Pro tier)
- 🐛 Agent escape rate: 0%

### Business
- 👥 Month 1: 50 beta users
- 💳 Month 3: 20 paying users
- 📈 Month 6: 100 paying users
- 💰 Month 12: $50k MRR

---

## Why This Will Work

1. **Local-first is unique**: Others force you to cloud (Devin) or local-only (OpenHands). We do both.

2. **Developer trust**: Open source core = we're not trying to lock you in.

3. **Dangerous mode safely**: Developers want full power, but are scared to run `rm -rf` on their machine. We solve this.

4. **Multi-model**: Cursor locks you to their models. We let you switch.

5. **Simple pricing**: $29/month vs Devin's $500/month.

6. **Parallel agents**: Everyone else is single-threaded. We're multi-threaded from day 1.

The market is **huge** (every developer who uses AI) and **underserved** (current tools all have major limitations).

We can win by being:
- More open (vs Cursor/Devin)
- More powerful (vs Cursor)
- More affordable (vs Devin)
- More polished (vs OpenHands)

---

## Next Steps

1. **Validate demand**: Survey developers about pain points
2. **Build MVP**: Modal + FastAPI + basic CLI in 1 month
3. **Private beta**: 50 users, iterate on feedback
4. **Pricing research**: Find willingness to pay
5. **Public launch**: Product Hunt, HN, Twitter

The opportunity is now - AI coding agents are exploding in 2025, and no one has nailed the "local-first + cloud + multi-model" combo yet.

# Rate Limit Fallback: Auto-Switch to API Key Mode

## Problem

Claude Code (Max subscription) has usage limits that reset on a rolling basis. The reset time varies based on your usage pattern - it's NOT a fixed time like "midnight UTC". When an agent hits this limit, it becomes blocked and can't make progress. The output shows:

```
❯ Run 'agenttree next' to see your workflow instructions and current stage.
  ⎿  You've hit your limit · resets 3am (UTC)
```

The reset time shown (e.g., "3am UTC") is specific to YOUR account at that moment. You can also check via:
- `claude --account` in the CLI
- claude.ai Settings > Subscription/Usage

**Note**: Max subscription has ~5x Pro's allowance on a weekly rolling basis, not a strict daily reset.

Currently, all agents just sit blocked until the limit resets, wasting hours of potential work time.

## Proposed Solution

Add a config option to automatically switch blocked agents to API key mode (`ANTHROPIC_API_KEY`) until the rate limit resets, then switch back to the subscription.

### Config Option

```yaml
# .agenttree.yaml
rate_limit_fallback:
  enabled: false  # Off by default
  api_key_env: ANTHROPIC_API_KEY  # Name of env var to read (NOT the key itself!)
  model: claude-sonnet-4-20250514  # Model to use in API mode (cheaper than opus)
  switch_back_buffer_min: 5  # Minutes after reset time to wait before switching back
```

**Important**: The `api_key_env` is the *name* of the environment variable, not the key itself. The actual API key should be in your shell config (e.g., `~/.zshrc`):

```bash
# In your ~/.zshrc (NOT in git)
export ANTHROPIC_API_KEY="sk-ant-..."
```

AgentTree reads `os.environ[config.api_key_env]` at runtime to get the key. Nothing secret goes in `.agenttree.yaml`.

## Detection Strategy

### Where to Check

The heartbeat loop in `actions.py` already runs `check_stalled_agents()` every 3 minutes. This is the ideal place to add rate limit detection.

### How to Check

1. **Capture tmux pane output** for each active agent session
2. **Search for the rate limit pattern**: `You've hit your limit · resets`
3. **Parse the reset time** from the message (e.g., "3am (UTC)")

```python
import re
from datetime import datetime, timezone

RATE_LIMIT_PATTERN = re.compile(
    r"You've hit your limit · resets (\d{1,2})(am|pm) \(UTC\)"
)

def detect_rate_limit(tmux_output: str) -> datetime | None:
    """Check if output contains rate limit message, return reset time if found."""
    match = RATE_LIMIT_PATTERN.search(tmux_output)
    if not match:
        return None
    
    hour = int(match.group(1))
    ampm = match.group(2)
    
    # Convert to 24-hour format
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    
    # Calculate next reset time
    now = datetime.now(timezone.utc)
    reset_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    
    # If reset time has passed today, it's tomorrow
    if reset_time <= now:
        reset_time = reset_time.replace(day=reset_time.day + 1)
    
    return reset_time
```

### Checking Agent Output

Use existing `capture_pane()` from `tmux.py`:

```python
from agenttree.tmux import capture_pane

def check_agent_rate_limited(session_name: str) -> datetime | None:
    """Check if an agent is rate limited, return reset time if so."""
    output = capture_pane(session_name, lines=50)
    if not output:
        return None
    return detect_rate_limit(output)
```

## Switching Modes

### Current Agent Start Flow

```
agenttree start <id>
  → creates container
  → passes CLAUDE_CODE_OAUTH_TOKEN to container
  → runs `claude --model opus --dangerously-skip-permissions`
```

### API Key Mode

When switching to API key mode:

1. **Stop current claude process** (keep container running)
2. **Restart claude with API key AND `--continue`**:
   ```bash
   claude --continue --model sonnet --dangerously-skip-permissions
   ```
   With `ANTHROPIC_API_KEY` env var set (instead of oauth token).

**Note on session continuity**: Testing revealed an **asymmetry** in session access:

**oauth → API key (fallback):**
- `--continue` fails ("No conversation found to continue")
- `--resume` shows empty list (can't see oauth sessions)
- Agent starts fresh but picks up context from issue docs/worktree

**API key → oauth (recovery):**
- `--resume` CAN find and resume API key sessions!
- Conversation history IS preserved when switching back
- This means we can use `-r` when recovering to oauth

This asymmetry is useful: when rate limit lifts and we switch back to oauth, we can resume the API key session to maintain context.

### Implementation Options

**Option A: Restart tmux session (RECOMMENDED)**
- Kill tmux session (container keeps running)
- Start new tmux session with `claude --continue --model sonnet`
- `ANTHROPIC_API_KEY` is already in container (passed at startup, always available)
- Pro: Clean, predictable, uses existing restart logic
- Pro: `--continue` still works because session files persist in container
- Con: Tmux restart overhead (minimal)

**Option B: Send command to running session**
- Send `/exit` to claude in tmux (or Ctrl+C)
- Send `claude --continue --model sonnet --dangerously-skip-permissions`
- Pro: Fastest, no restart
- Con: Orchestrating commands in tmux is fragile, timing issues

**Option C: Full container restart**
- Kill container entirely, restart with different startup command
- Pro: Cleanest slate
- Con: Container restart is slow, may lose state

**Recommendation: Option A** - restart tmux only. Container stays warm, session files persist, `--continue` works, and it's predictable.

### API Key Availability

**Always pass `ANTHROPIC_API_KEY` into containers at startup** (even if not used):

```python
# In container.py, always include:
if os.environ.get("ANTHROPIC_API_KEY"):
    cmd.extend(["-e", f"ANTHROPIC_API_KEY={os.environ['ANTHROPIC_API_KEY']}"])
```

This way the key is available in the container environment whenever needed. We just don't invoke it unless switching to API mode.

### Switching ALL Agents

**Important**: Rate limits are account-wide. When ONE agent hits the limit, ALL agents on that account are blocked.

When rate limit is detected:
1. Check ALL active agent sessions for the rate limit message
2. Switch ALL of them at once (not one-by-one as they hit it)
3. Track them all in `rate_limit_state.yaml`
4. Switch them ALL back when limit resets

## Switch-Back Mechanism

### Tracking Rate Limit State

Store rate limit info in `_agenttree/rate_limit_state.yaml`:

```yaml
# Written by heartbeat when rate limit detected
rate_limited_at: "2026-02-05T00:30:00Z"
reset_time: "2026-02-05T03:00:00Z"
fallback_agents:
  - issue_id: "154"
    original_mode: "oauth"  # or "api_key"
    switched_at: "2026-02-05T00:31:00Z"
  - issue_id: "128"
    original_mode: "oauth"
    switched_at: "2026-02-05T00:31:15Z"
```

### Heartbeat Check for Switch-Back

In heartbeat (every 10s), check if:
1. Current time > reset_time + buffer
2. There are agents in `fallback_agents` list

If both true:
1. For each fallback agent, restart with original mode
2. Clear the `rate_limit_state.yaml`

```python
def check_rate_limit_recovery(agents_dir: Path) -> int:
    """Check if rate limit has reset and switch agents back."""
    state_file = agents_dir / "rate_limit_state.yaml"
    if not state_file.exists():
        return 0
    
    state = yaml.safe_load(state_file.read_text())
    reset_time = datetime.fromisoformat(state["reset_time"])
    buffer = timedelta(minutes=5)
    
    if datetime.now(timezone.utc) < reset_time + buffer:
        return 0  # Not time yet
    
    switched = 0
    for agent in state.get("fallback_agents", []):
        # Restart with original mode
        restart_agent(agent["issue_id"], mode=agent["original_mode"])
        switched += 1
    
    # Clear state
    state_file.unlink()
    console.print(f"[green]Rate limit reset - switched {switched} agents back to subscription[/green]")
    return switched
```

## New Action: `check_rate_limits`

Add to `actions.py`:

```python
@register_action("check_rate_limits")
def check_rate_limits(agents_dir: Path, **kwargs: Any) -> None:
    """Check for rate-limited agents and handle fallback/recovery.
    
    This action:
    1. Checks if any agents are showing rate limit messages
    2. If fallback is enabled, switches them to API key mode
    3. Checks if rate limit has reset and switches agents back
    """
    config = load_config()
    
    # Skip if fallback not enabled
    if not config.rate_limit_fallback.enabled:
        return
    
    # First, check for recovery (switch back to subscription)
    recovered = check_rate_limit_recovery(agents_dir)
    if recovered:
        return  # Don't check for new limits right after recovery
    
    # Check each active agent for rate limit
    for session_name in list_agent_sessions():
        reset_time = check_agent_rate_limited(session_name)
        if reset_time:
            switch_to_api_key_mode(session_name, reset_time)
```

Add to heartbeat config:

```yaml
on:
  heartbeat:
    interval_s: 10
    actions:
      - sync
      - check_rate_limits  # NEW
      - check_stalled_agents
      # ...
```

## CLI Support

### New flags on `agenttree start`

```python
@main.command(name="start")
@click.argument("issue_id", type=str)
@click.option("--api-key", is_flag=True, help="Use ANTHROPIC_API_KEY instead of subscription")
@click.option("--model", help="Model to use (default: from config, or sonnet for --api-key)")
def start_agent(issue_id: str, api_key: bool, model: Optional[str], ...):
    ...
```

### Manual override command

```bash
# Force switch an agent to API key mode (with --continue to preserve session)
agenttree start 154 --force --api-key --model sonnet --continue

# Or manually in the tmux session:
# 1. Ctrl+C to stop claude
# 2. export ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY"  # if not already set
# 3. claude --continue --model sonnet --dangerously-skip-permissions

# Check rate limit status
agenttree status --rate-limits
```

## Cost Considerations

When using API key fallback:
- **Subscription (Max)**: Fixed monthly cost, ~$200/month for unlimited* usage
- **API Key**: Pay per token
  - Opus: ~$15/M input, $75/M output
  - Sonnet: ~$3/M input, $15/M output

**Recommendation**: Use Sonnet for API key fallback to minimize costs. Most implementation work doesn't require Opus.

## Config Schema

```python
@dataclass
class RateLimitFallbackConfig:
    enabled: bool = False
    api_key_env: str = "ANTHROPIC_API_KEY"
    model: str = "claude-sonnet-4-20250514"
    switch_back_buffer_min: int = 5
    
    @classmethod
    def from_dict(cls, data: dict) -> "RateLimitFallbackConfig":
        return cls(
            enabled=data.get("enabled", False),
            api_key_env=data.get("api_key_env", "ANTHROPIC_API_KEY"),
            model=data.get("model", "claude-sonnet-4-20250514"),
            switch_back_buffer_min=data.get("switch_back_buffer_min", 5),
        )
```

## Implementation Plan

### Phase 1: Detection (Easy)
1. Add `detect_rate_limit()` function to parse tmux output
2. Add `check_agent_rate_limited()` to check individual agents
3. Test detection with current blocked agents

### Phase 2: API Key Support (Medium)
1. Always pass `ANTHROPIC_API_KEY` from host env into containers at startup
2. Add `--api-key` flag to `agenttree start` (uses API key instead of oauth)
3. Add `--continue` flag to `agenttree start` (passes `-c` to claude)
4. Test: `agenttree start 154 --force --api-key --continue` preserves session

### Phase 3: Automatic Fallback (Medium)
1. Add config schema for `rate_limit_fallback`
2. Add `check_rate_limits` action to heartbeat
3. When ANY agent hits limit, switch ALL active agents (account-wide limit)
4. Implement `switch_all_to_api_key_mode()` - restarts tmux with `--api-key --continue`
5. Write state to `rate_limit_state.yaml` (tracks all switched agents + reset time)

### Phase 4: Automatic Recovery (Easy)
1. Add `check_rate_limit_recovery()` to heartbeat
2. After reset time + buffer, switch ALL agents back to subscription mode
3. Clear `rate_limit_state.yaml`
4. Test full cycle: limit hit → switch all to API → reset → switch all back

## Manual Test Results (2026-02-05)

Successfully tested the fallback flow on agent #154:

**Steps executed:**
```bash
# 1. Exit rate-limited claude
agenttree send 154 "/exit"

# 2. Export API key in container shell (via tmux)
tmux send-keys -t agenttree-developer-154 "export ANTHROPIC_API_KEY='$ANTHROPIC_API_KEY'" Enter

# 3. Start claude with API key
tmux send-keys -t agenttree-developer-154 "claude --model sonnet --dangerously-skip-permissions" Enter

# 4. Verify agent is working
agenttree send 154 "run agenttree next to see your current task"
```

**Results:**
- ✅ Claude exited cleanly with `/exit`
- ✅ API key exported in container shell
- ✅ Claude started with Sonnet 4.5 (API key mode)
- ✅ Agent picked up task and started working
- ❌ `--continue` flag: "No conversation found to continue" (sessions are per-auth-method)
- ❌ `--resume` flag: Session picker shows empty list (can't see oauth sessions)

**Key Finding:** Sessions are stored per-auth-method. When switching from oauth to API key, you cannot resume previous sessions with either `-c` or `-r`. The agent starts fresh but successfully picks up task context from issue docs and worktree state. This is acceptable - the agent can continue meaningful work.

**Also confirmed:** You can just kill tmux - no need for graceful `/exit`. Session files persist in `.claude-sessions-{role}/` directory.

## Unit Tests

```python
def test_detect_rate_limit():
    output = "❯ Run 'agenttree next'\n  ⎿  You've hit your limit · resets 3am (UTC)"
    reset_time = detect_rate_limit(output)
    assert reset_time is not None
    assert reset_time.hour == 3

def test_detect_no_limit():
    output = "❯ I'll help you with that task..."
    assert detect_rate_limit(output) is None
```

## Open Questions

1. **What if API key also has limits?** - Should we track API key usage and warn before hitting limits?

2. **Should we notify the user?** - Send a message to manager when switching modes?

3. **Per-agent vs global switch?** - Currently proposed is per-agent. Should we switch all agents at once when any hits the limit? (The limit is account-wide, so if one hits it, all will.)

4. **What about in-progress work?** - When we restart an agent, it loses its conversation context. Claude Code does have session persistence, but we'd need to handle this carefully.

## Alternatives Considered

### A: Just wait for reset
- Pro: No extra cost, no complexity
- Con: Hours of wasted time every day

### B: Multiple Claude accounts
- Pro: More total capacity
- Con: Complex to manage, possibly against ToS

### C: Mixed fleet (some API, some subscription)
- Pro: Always have capacity
- Con: More complex config, doesn't use subscription efficiently

**Decision**: Auto-fallback to API key is the best balance of simplicity, cost, and utilization.

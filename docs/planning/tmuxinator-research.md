# Tmuxinator Research

**Date:** 2026-01-13
**Status:** Evaluated - Not needed for core functionality

## What is Tmuxinator?

Tmuxinator is a tool for managing tmux sessions via YAML config files. Instead of manually creating tmux sessions, windows, and panes, you define them declaratively:

```yaml
# ~/.tmuxinator/agenttree.yml
name: agenttree
root: ~/Projects/agenttree

windows:
  - editor:
      layout: main-vertical
      panes:
        - vim
        - uv run pytest --watch
  - agents:
      layout: tiled
      panes:
        - agenttree attach 015
        - agenttree attach 016
        - agenttree status --watch
  - logs:
      - tail -f .agenttrees/logs/agent-015.log
```

Start everything with: `tmuxinator start agenttree`

## How AgentTree Currently Uses Tmux

AgentTree programmatically creates tmux sessions for agents in `agenttree/tmux.py`:

```python
# Dynamic session creation based on issue ID
tmux new-session -d -s agenttree-issue-015 -c /path/to/worktree
```

Key functions:
- `create_session()` - Creates new tmux session for an agent
- `send_keys()` - Sends commands to agent sessions
- `attach_session()` - Attaches user to agent session
- `list_sessions()` - Lists active agent sessions

## Evaluation

### Why Tmuxinator Doesn't Fit

| Requirement | Tmuxinator | AgentTree Current |
|-------------|------------|-------------------|
| Dynamic session creation | ❌ Static YAML configs | ✅ Created on-demand per issue |
| Ephemeral sessions | ❌ Designed for persistent layouts | ✅ Agents come and go |
| Programmatic control | ❌ CLI-based | ✅ Full Python API |
| Issue-specific sessions | ❌ Pre-defined | ✅ Named by issue ID |

### Potential Use Cases (Limited)

1. **Developer Workflow** - A tmuxinator config for development setup:
   ```yaml
   name: agenttree-dev
   windows:
     - code: vim
     - tests: uv run pytest --watch
     - agents: agenttree agents
     - web: uv run agenttree web
   ```

2. **Monitoring Dashboard** - Static layout to watch agents (but requires manual updates as agents change)

## Conclusion

**Not adopting tmuxinator because:**

1. AgentTree needs **dynamic** session creation - agents spawn based on issues
2. Sessions are **ephemeral** - they come and go as work progresses
3. Current `tmux.py` provides **programmatic control** that tmuxinator can't match
4. No benefit over existing implementation

**Alternative considered:** Could add an `agenttree dev` command that generates a tmuxinator-style layout showing all active agents, but `agenttree attach` already serves this purpose.

## References

- [Tmuxinator GitHub](https://github.com/tmuxinator/tmuxinator)
- [Tmux documentation](https://github.com/tmux/tmux/wiki)
- AgentTree tmux implementation: `agenttree/tmux.py`

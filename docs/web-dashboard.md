# AgentTree Web Dashboard

The AgentTree web dashboard provides a real-time view of all agents, their tmux sessions, and allows you to start tasks and chat with agents through a browser interface.

## Features

- **Real-time Agent Status**: See all agents and their current state
- **Live Tmux Output**: View tmux sessions updating in real-time via WebSocket
- **Send Commands**: Type commands directly to agents via tmux
- **Task Start**: Assign GitHub issues or ad-hoc tasks to agents
- **HTMX-Powered**: Dynamic updates without JavaScript framework overhead
- **Optional Authentication**: Secure your dashboard if exposing publicly

## Quick Start

### 1. Install Dependencies

The web dashboard requires FastAPI and its dependencies:

```bash
pip install fastapi uvicorn websockets jinja2
```

Or install from the project root:

```bash
pip install -e ".[web]"
```

### 2. Run the Server

```bash
# From Python
python -m agenttree.web.app

# Or using the run_server function
python -c "from agenttree.web.app import run_server; run_server()"
```

By default, the server runs on `http://127.0.0.1:8080`.

### 3. Access the Dashboard

Open your browser to:
```
http://127.0.0.1:8080
```

## Configuration

### Bind Address and Port

```bash
# Custom host and port
python -c "from agenttree.web.app import run_server; run_server(host='0.0.0.0', port=3000)"
```

### Tailscale Access (Recommended)

By default, the dashboard has **no authentication** because it's designed to run on Tailscale, which provides network-level security.

**Setup:**
1. Install Tailscale on your machine: https://tailscale.com/download
2. Start the web dashboard bound to your Tailscale IP:
   ```bash
   python -c "from agenttree.web.app import run_server; run_server(host='100.x.x.x', port=8080)"
   ```
3. Access from any device on your Tailscale network: `http://100.x.x.x:8080`

**Benefits:**
- No authentication needed (Tailscale handles it)
- Secure encrypted connection
- Access from anywhere (phone, laptop, other computers)
- No port forwarding or firewall configuration

## Optional Authentication

If you need to expose the dashboard publicly (not recommended), you can enable HTTP Basic Authentication.

### Enable Auth

Set the following environment variables:

```bash
export AGENTTREE_WEB_AUTH=true
export AGENTTREE_WEB_USERNAME=your_username
export AGENTTREE_WEB_PASSWORD=your_secure_password

python -m agenttree.web.app
```

### Docker Example

```bash
docker run -e AGENTTREE_WEB_AUTH=true \
           -e AGENTTREE_WEB_USERNAME=admin \
           -e AGENTTREE_WEB_PASSWORD=mysecretpassword \
           -p 8080:8080 \
           agenttree-web
```

### .env File

Create a `.env` file:

```bash
AGENTTREE_WEB_AUTH=true
AGENTTREE_WEB_USERNAME=admin
AGENTTREE_WEB_PASSWORD=changeme123
```

Then load it:

```bash
set -a
source .env
set +a
python -m agenttree.web.app
```

### Security Notes

- **Default:** Auth is **disabled** (assumes Tailscale security)
- **When enabled:** Uses HTTP Basic Auth (username + password)
- **HTTPS recommended:** If exposing publicly, use HTTPS (nginx, Caddy, or Cloudflare Tunnel)
- **Strong passwords:** Use a password manager to generate secure passwords
- **Timing-attack protection:** Uses `secrets.compare_digest()` for credential comparison

## Usage

### Viewing Agents

The dashboard shows all configured agents with:
- Agent number
- Status (idle, working, error)
- Current task
- Tmux session active status
- Last activity timestamp

### Viewing Tmux Output

Click "Tmux Output" on any agent card to expand the tmux session view. The output refreshes every 2 seconds via HTMX.

For live streaming (1-second updates), the WebSocket connection is automatically established.

### Sending Commands

1. Expand the "Tmux Output" section
2. Type your command in the input box
3. Click "Send"
4. The command is sent to the agent's tmux session

**Examples:**
- `git status`
- `pytest`
- `Read TASK.md`

### Starting Tasks

1. Expand the "Start Task" section
2. Either:
   - Enter a GitHub issue number (e.g., `42`)
   - OR write an ad-hoc task description
3. Click "Start Task"

This will create a TASK.md file in the agent's worktree and notify the agent.

## Architecture

### Technology Stack

- **FastAPI**: Modern Python web framework
- **HTMX**: Dynamic HTML without heavy JavaScript
- **WebSocket**: Real-time tmux streaming
- **Jinja2**: Server-side HTML templates

### Endpoints

**HTML Pages:**
- `GET /` - Main dashboard
- `GET /health` - Health check

**HTMX Endpoints:**
- `GET /agents` - Agent list (updates every 5s)
- `GET /agent/{num}/tmux` - Tmux output (updates every 2s)
- `POST /agent/{num}/send` - Send command to agent
- `POST /agent/{num}/start` - Start task on agent

**WebSocket:**
- `WS /ws/agent/{num}/tmux` - Live tmux streaming (updates every 1s)

### File Structure

```
agenttree/web/
├── app.py                          # FastAPI application
├── templates/
│   ├── dashboard.html              # Main page
│   └── partials/
│       ├── agents_list.html        # Agent cards (HTMX partial)
│       ├── tmux_output.html        # Tmux display (HTMX partial)
│       ├── send_status.html        # Send confirmation
│       └── start_status.html       # Start confirmation
└── static/                         # CSS/JS (future)
```

## Customization

### Styling

The dashboard uses embedded CSS with a dark GitHub-inspired theme. To customize:

1. Edit `templates/dashboard.html`
2. Modify the `<style>` section
3. Or create `static/custom.css` and link it

### Agent Status

Currently, agent status is mocked. To integrate with real worktree manager:

```python
# In app.py
from agenttree.worktree import WorktreeManager

class AgentManager:
    def __init__(self, config):
        self.worktree_manager = WorktreeManager(config)

    def get_agent_status(self, agent_num: int) -> dict:
        status = self.worktree_manager.get_agent_status(agent_num)
        return {
            "agent_num": agent_num,
            "status": "working" if status.is_busy else "idle",
            "current_task": status.current_branch,
            "tmux_active": status.tmux_active,
            "last_activity": status.last_commit_time.isoformat() if status.last_commit_time else None
        }
```

## Troubleshooting

### "Could not capture tmux output"

**Cause:** Tmux session not running or wrong session name

**Fix:**
1. Check tmux sessions: `tmux list-sessions`
2. Ensure agent sessions are named: `agent-1`, `agent-2`, etc.
3. Start agents with: `agenttree start --agents 3`

### WebSocket Connection Failed

**Cause:** Browser blocked WebSocket or server not running

**Fix:**
1. Check browser console for errors
2. Ensure server is running on expected port
3. Try disabling browser extensions (ad blockers)

### Authentication Not Working

**Cause:** Environment variables not set or incorrect

**Fix:**
1. Verify env vars: `echo $AGENTTREE_WEB_AUTH`
2. Restart server after setting env vars
3. Check credentials match exactly

### HTMX Not Updating

**Cause:** HTMX library not loaded or network issue

**Fix:**
1. Check browser console for HTMX errors
2. Verify internet connection (HTMX loaded from CDN)
3. Try refreshing the page

## Future Enhancements

- [ ] Static file serving for custom CSS/JS
- [ ] Agent performance metrics (task completion time, success rate)
- [ ] Task history and logs
- [ ] Multi-project support
- [ ] Dark/light theme toggle
- [ ] Mobile-responsive design improvements
- [ ] WebSocket reconnection logic
- [ ] Agent configuration UI
- [ ] Knowledge base browser (Phase 6)

## See Also

- [AgentTree Documentation](../README.md)
- [Tailscale Setup Guide](https://tailscale.com/kb/1017/install/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [HTMX Documentation](https://htmx.org/)

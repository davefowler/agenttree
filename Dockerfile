# AgentTree Agent Runtime
# Container image for running AI coding agents in isolation

FROM node:20-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    python3-pip \
    python3-venv \
    sudo \
    expect \
    gh \
    && rm -rf /var/lib/apt/lists/*

# Install Claude CLI
RUN npm install -g @anthropic-ai/claude-code

# Create non-root user (Claude CLI refuses --dangerously-skip-permissions as root)
RUN useradd -m -s /bin/bash agent && \
    echo "agent ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Set up git config for agent user
USER agent
RUN git config --global user.email "agent@agenttree.dev" && \
    git config --global user.name "AgentTree Agent"

# Create workspace directory
WORKDIR /workspace

# Pre-create Claude config to skip onboarding wizard
RUN mkdir -p /home/agent/.claude && \
    echo '{"hasCompletedOnboarding":true}' > /home/agent/.claude.json && \
    echo '{"theme":"dark"}' > /home/agent/.claude/settings.json

# Create entrypoint script that sets up environment
RUN cat > /home/agent/entrypoint.sh << 'EOF'
#!/bin/bash

# If host .claude directory is mounted, copy .claude.json if it exists there
# (User can place their .claude.json in ~/.claude/ for sharing with containers)
if [ -f /home/agent/.claude-host/.claude.json ]; then
    cp /home/agent/.claude-host/.claude.json /home/agent/.claude.json
fi

# Copy settings.json from host if available
if [ -f /home/agent/.claude-host/settings.json ]; then
    cp /home/agent/.claude-host/settings.json /home/agent/.claude/settings.json
fi

# Set up agenttree - only do editable install if workspace IS agenttree
# (for self-development). Other projects would need agenttree from PyPI.
if [ -f /workspace/pyproject.toml ] && grep -q 'name = "agenttree"' /workspace/pyproject.toml; then
    # Working on agenttree itself - install from workspace (editable)
    if [ ! -d /home/agent/.agenttree-venv ]; then
        python3 -m venv /home/agent/.agenttree-venv
    fi
    /home/agent/.agenttree-venv/bin/pip install -q -e "/workspace[dev]"
    export PATH="/home/agent/.agenttree-venv/bin:$PATH"
fi

exec "$@"
EOF
RUN chmod +x /home/agent/entrypoint.sh

ENTRYPOINT ["/home/agent/entrypoint.sh"]

# Default command
CMD ["claude", "--dangerously-skip-permissions"]

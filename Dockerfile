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
    gh \
    && rm -rf /var/lib/apt/lists/*

# Install Claude CLI
RUN npm install -g @anthropic-ai/claude-code

# Install uv (fast Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install agenttree runtime dependencies (for dogfooding - symlink approach)
RUN pip install --break-system-packages \
    click>=8.1.0 \
    pyyaml>=6.0 \
    pydantic>=2.0.0 \
    rich>=13.0.0 \
    filelock>=3.0.0 \
    jinja2>=3.1.0

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

# Create agenttree wrapper script (avoids slow pip install for dogfooding)
COPY --chown=agent:agent <<'EOF' /home/agent/agenttree-wrapper.sh
#!/bin/bash
# Wrapper for agenttree CLI when working on agenttree itself
# Uses PYTHONPATH instead of pip install -e for instant startup
PYTHONPATH=/workspace exec python3 -c "import sys; sys.argv[0]='agenttree'; from agenttree.cli import main; main()" "$@"
EOF
RUN chmod +x /home/agent/agenttree-wrapper.sh

# Create entrypoint script that sets up environment
COPY --chown=agent:agent <<'EOF' /home/agent/entrypoint.sh
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

# Set up agenttree - use symlink approach for instant startup when dogfooding
AGENTTREE_PATH=""
if [ -f /workspace/pyproject.toml ] && grep -q 'name = "agenttree"' /workspace/pyproject.toml; then
    # Working on agenttree itself - symlink wrapper to PATH instead of pip install
    mkdir -p /home/agent/bin
    ln -sf /home/agent/agenttree-wrapper.sh /home/agent/bin/agenttree
    AGENTTREE_PATH="/home/agent/bin:"
fi

# Use exec env to ensure PATH persists to child processes
exec env PATH="${AGENTTREE_PATH}${PATH}" "$@"
EOF
RUN chmod +x /home/agent/entrypoint.sh

ENTRYPOINT ["/home/agent/entrypoint.sh"]

# Default command
CMD ["claude", "--dangerously-skip-permissions"]

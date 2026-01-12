# AgentTree Agent Runtime
# Container image for running AI coding agents in isolation

FROM node:20-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Claude CLI
RUN npm install -g @anthropic-ai/claude-code

# Create workspace directory
WORKDIR /workspace

# Set up git config (agents need this for commits)
RUN git config --global user.email "agent@agenttree.dev" && \
    git config --global user.name "AgentTree Agent"

# Default command
CMD ["claude"]


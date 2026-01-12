# AgentTree Agent Runtime
# Container image for running AI coding agents in isolation

FROM node:20-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    python3-pip \
    sudo \
    expect \
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

# Create expect script to automate Claude first-run wizard
RUN cat > /home/agent/claude-init.exp << 'EXPECT_EOF'
#!/usr/bin/expect -f
set timeout 30
spawn claude --dangerously-skip-permissions

# Handle theme selection (select dark mode - option 1)
expect {
    "Choose the text style" {
        send "\r"
        exp_continue
    }
    "Select login method" {
        # Select option 2 (API key auth)
        send "\033\[B"
        sleep 0.5
        send "\r"
        exp_continue
    }
    "bypass permissions" {
        # Select "Yes, I accept" (option 2)
        send "\033\[B"
        sleep 0.5
        send "\r"
        exp_continue
    }
    "OAuth error" {
        send "\r"
        exp_continue
    }
    -re "❯.*" {
        # We're at the prompt - ready!
        interact
    }
    timeout {
        puts "Timeout - trying to continue"
        interact
    }
}
EXPECT_EOF
RUN chmod +x /home/agent/claude-init.exp

# Create entrypoint script
RUN echo '#!/bin/bash\n\
exec "$@"' > /home/agent/entrypoint.sh && chmod +x /home/agent/entrypoint.sh

ENTRYPOINT ["/home/agent/entrypoint.sh"]

# Default command - use expect script for interactive mode
CMD ["/home/agent/claude-init.exp"]

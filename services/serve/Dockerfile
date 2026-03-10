FROM harbor.server.unarmedpuppy.com/docker-hub/library/python:3.12-slim

# Install Node.js 20 (required for Claude Code CLI) + system tools
RUN apt-get update && apt-get install -y curl git && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[serve]"

COPY services/serve/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8013

ENTRYPOINT ["/entrypoint.sh"]

FROM harbor.server.unarmedpuppy.com/docker-hub/library/python:3.12-slim

# Install Node.js 20 (required for Claude Code CLI) + system tools
RUN apt-get update && apt-get install -y curl git gosu && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appuser && useradd -r -g appuser -m appuser

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[serve]"

COPY services/serve/entrypoint.sh /entrypoint.sh
COPY services/serve/bootstrap/ /app/bootstrap/
RUN chmod +x /entrypoint.sh

EXPOSE 8013

ENTRYPOINT ["/entrypoint.sh"]

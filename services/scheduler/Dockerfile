FROM python:3.12-slim

WORKDIR /app

# Install innie-engine from source
COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir -e "."

COPY services/scheduler/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[serve]"

COPY services/serve/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8013

ENTRYPOINT ["/entrypoint.sh"]

FROM python:3.12-slim

WORKDIR /app

# Install CPU-only torch first to keep image smaller
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV CACHE_DIR=/app/cache
ENV PORT=8766

EXPOSE 8766

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8766/health || exit 1

CMD ["python", "server.py"]

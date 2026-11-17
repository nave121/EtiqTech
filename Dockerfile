FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS base

# Prevent Python from writing .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY gunicorn.conf.py .
COPY src/ src/
COPY server/ server/
COPY llm/ llm/
COPY resources/ resources/
COPY examples/known-good/ examples/known-good/
COPY examples/head-to-head/ examples/head-to-head/

# Non-root user for security
RUN addgroup --system --gid 1000 app && adduser --system --uid 1000 --gid 1000 app \
    && mkdir -p /app/output && chown -R app:app /app/output
USER app

EXPOSE 4242

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:4242/api/health')"

CMD ["gunicorn", "-c", "gunicorn.conf.py", "server.app:app"]

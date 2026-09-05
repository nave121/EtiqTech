FROM python:3.13-slim@sha256:eefe082c4b73082d83b8e7705ed999bc8a1dae57fe1ea723f907a0fc4b90f088 AS base

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
RUN addgroup --system app && adduser --system --group app \
    && mkdir -p /app/output && chown -R app:app /app/output
USER app

EXPOSE 4242

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:4242/api/health')"

CMD ["gunicorn", "-c", "gunicorn.conf.py", "server.app:app"]

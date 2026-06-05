# server.monitor — container image
# NVML (libnvidia-ml) is injected at runtime by the NVIDIA Container Toolkit,
# so a plain slim image is enough. No CUDA base image required.
FROM python:3.12-slim

# Don't write .pyc files; flush stdout/stderr immediately for clean logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY config.py monitor.py stats.py ./
COPY static ./static

# Run as a non-root user.
RUN useradd --create-home --uid 1001 monitor
USER monitor

EXPOSE 8000

# Defaults; override via docker-compose env or -e flags.
ENV BIND_HOST=0.0.0.0 \
    BIND_PORT=8000 \
    POLL_INTERVAL=2.0 \
    LOG_LEVEL=INFO

# Liveness probe using stdlib only (no curl/wget in slim).
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)" || exit 1

# Single worker — the stats collector caches state per process.
CMD ["uvicorn", "monitor:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

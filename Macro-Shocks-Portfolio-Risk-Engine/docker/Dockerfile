# docker/Dockerfile
# Production Docker image for the MSRE Pipeline and API server.
# Multi-stage build: builder stage installs deps, runtime stage is lean.
#
# Build: docker build -t msre-pipeline:latest -f docker/Dockerfile .
# Run:   docker run -p 8000:8000 --env-file .env msre-pipeline:latest

# ============================================================
# Stage 1: Builder — install Python dependencies
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first (maximise layer cache hits)
COPY requirements.txt requirements-dev.txt pyproject.toml ./

# Install Python dependencies into a prefix directory
RUN pip install --upgrade pip && \
    pip install --prefix=/install \
    pydantic>=2.5 \
    numpy>=1.26 \
    pandas>=2.1 \
    structlog>=24.1 \
    pyyaml>=6.0 \
    python-dotenv>=1.0 \
    requests>=2.31 \
    aiohttp>=3.9 \
    fastapi>=0.110 \
    uvicorn[standard]>=0.27 \
    httpx>=0.27

# ============================================================
# Stage 2: Runtime — lean production image
# ============================================================
FROM python:3.11-slim AS runtime

LABEL maintainer="Quantitative Research & Risk Engineering"
LABEL version="1.0.0"
LABEL description="Macro Shock Risk Engine — Pipeline and API Server"

# Non-root user for security
RUN groupadd -r msre && useradd -r -g msre -m msre

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY python/src/ ./python/src/
COPY python/configs/ ./python/configs/
COPY examples/ ./examples/
COPY pyproject.toml ./

# Set PYTHONPATH so macro_shock package is importable
ENV PYTHONPATH=/app/python/src
ENV MSRE_ENVIRONMENT=production
ENV MSRE_LOG_LEVEL=WARNING

# Health check (liveness probe for orchestrators)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1

# Switch to non-root user
USER msre

EXPOSE 8000

# Default: run the API server
# Override CMD to run: python -m macro_shock.orchestration.pipeline --mode monitor
CMD ["uvicorn", "macro_shock.orchestration.api:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--log-level", "warning"]

# ── Stage 1: Builder ───────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build deps for asyncpg / cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Production ────────────────────────────────────────────────────────
FROM python:3.12-slim AS production

# Security: non-root user
RUN groupadd -r darkatlas && useradd -r -g darkatlas -d /app darkatlas

WORKDIR /app

# Runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY --chown=darkatlas:darkatlas app/ ./app/
COPY --chown=darkatlas:darkatlas alembic/ ./alembic/
COPY --chown=darkatlas:darkatlas alembic.ini ./
COPY --chown=darkatlas:darkatlas data/ ./data/

USER darkatlas

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

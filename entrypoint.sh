#!/bin/sh
set -e

echo "[entrypoint] Running Alembic migrations..."
alembic upgrade head

echo "[entrypoint] Starting Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log

#!/usr/bin/env bash
# Container entrypoint: run DB migrations (Postgres only), then start the server.
#
# Referenced by:
#   - Dockerfile    -> CMD ["./scripts/docker-entrypoint.sh"]
#   - docker-compose.yml -> command: ["./scripts/docker-entrypoint.sh"]
#
# Migrations:
#   Run `alembic upgrade head` ONLY when DATABASE_URL points at Postgres.
#   For local sqlite dev (the default in cpa_first/config.py) we skip alembic
#   and just echo, since the app creates/uses the sqlite file directly and the
#   Postgres-targeted migrations may not be meaningful there.
#
# Driver scheme:
#   The app depends on psycopg v3 (psycopg[binary]) — NOT psycopg2. Managed
#   PaaS Postgres hands out bare `postgres://` / `postgresql://` URLs, which
#   SQLAlchemy 2.x would try to load via the (uninstalled) psycopg2 dialect.
#   We normalize the scheme to `postgresql+psycopg://` here, and export it so
#   both alembic AND the app process inherit the corrected URL. (Python source
#   is intentionally not modified.)
#
# Concurrency:
#   Render/Fly may start more than one instance at once, so every container
#   could call `alembic upgrade head` simultaneously and race on
#   alembic_version. PREFERRED fix: run migrations exactly once via the
#   platform release phase — fly.toml's [deploy].release_command and Render's
#   preDeployCommand both already invoke `alembic upgrade head` BEFORE any web
#   instance boots. When that runs first, the per-container call below is a
#   true no-op (alembic compares to head and exits).
#
#   For the case where instances still boot concurrently (e.g. release phase
#   disabled), set RUN_MIGRATIONS_ON_BOOT=0 on all but a dedicated migrator,
#   or rely on the release phase. We keep the on-boot call by default because
#   alembic wraps each step in a transaction; the realistic remaining race is
#   only during a brand-new revision applied with the release phase disabled.

set -euo pipefail

# --- Server tunables (overridable via env) -------------------------------
PORT="${PORT:-8000}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-2}"

# --- Database migrations --------------------------------------------------
DATABASE_URL="${DATABASE_URL:-}"
RUN_MIGRATIONS_ON_BOOT="${RUN_MIGRATIONS_ON_BOOT:-1}"

# Normalize bare Postgres schemes to the psycopg v3 dialect SQLAlchemy expects.
# Managed PaaS Postgres emits postgres:// or postgresql://; without this the
# app/alembic would try the uninstalled psycopg2 dialect and fail to connect.
case "${DATABASE_URL}" in
  postgres://*)
    DATABASE_URL="postgresql+psycopg://${DATABASE_URL#postgres://}"
    ;;
  postgresql://*)
    DATABASE_URL="postgresql+psycopg://${DATABASE_URL#postgresql://}"
    ;;
  postgresql+psycopg2://*)
    DATABASE_URL="postgresql+psycopg://${DATABASE_URL#postgresql+psycopg2://}"
    ;;
esac
# Export the corrected URL so both alembic and the gunicorn app inherit it.
export DATABASE_URL

case "${DATABASE_URL}" in
  postgresql+psycopg://*)
    if [ "${RUN_MIGRATIONS_ON_BOOT}" = "1" ]; then
      echo "[entrypoint] Postgres detected — running 'alembic upgrade head'..."
      alembic upgrade head
      echo "[entrypoint] migrations complete."
    else
      echo "[entrypoint] RUN_MIGRATIONS_ON_BOOT=0 — skipping on-boot migrations (handled by release phase)."
    fi
    ;;
  "")
    echo "[entrypoint] DATABASE_URL not set — skipping migrations (dev default)."
    ;;
  sqlite*)
    echo "[entrypoint] sqlite DATABASE_URL detected — skipping migrations (dev)."
    ;;
  *)
    echo "[entrypoint] Non-Postgres DATABASE_URL ('${DATABASE_URL%%:*}:...') — skipping migrations."
    ;;
esac

# --- Start the application ------------------------------------------------
# Gunicorn process manager + Uvicorn ASGI workers (production-grade for FastAPI).
echo "[entrypoint] starting gunicorn on 0.0.0.0:${PORT} with ${WEB_CONCURRENCY} worker(s)..."
exec gunicorn cpa_first.api.main:app \
  -k uvicorn.workers.UvicornWorker \
  -b "0.0.0.0:${PORT}" \
  --workers "${WEB_CONCURRENCY}" \
  --timeout 60 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile -

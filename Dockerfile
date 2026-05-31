# syntax=docker/dockerfile:1
# Multi-stage build for the cpa-first FastAPI app.
# Target: Docker-portable managed PaaS (Render / Fly / Railway).
# Python pinned to 3.12 (matches .python-version).

# ---------------------------------------------------------------------------
# Stage 1: builder — install the project into an isolated virtualenv.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps for native wheels (argon2-cffi, psycopg builds, etc.).
# psycopg[binary] ships wheels, but keep build-essential for safety on cffi.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create the venv that the runtime stage will copy verbatim.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

# Copy only what pip needs to build/install the project (better layer caching).
COPY pyproject.toml README.md ./
COPY cpa_first ./cpa_first

# Install the project itself plus the observability extra (Sentry + Prometheus).
# These are wired in cpa_first/api/main.py and are optional at runtime, so a
# missing extra would not crash boot — but we include it for prod observability.
RUN pip install --no-cache-dir ".[observability]"

# ---------------------------------------------------------------------------
# Stage 2: runtime — slim image with only the venv + app artifacts.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# libpq runtime is bundled in psycopg[binary] wheels; no extra apt deps needed.

# Non-root user (PaaS best practice; uid/gid fixed for predictable perms).
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Copy the prebuilt virtualenv from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Copy application code and runtime data.
# (Source tree is authoritative; the installed package in the venv is fine too,
#  but copying cpa_first keeps `gunicorn cpa_first.api.main:app` and alembic env
#  resolution working against the on-disk tree.)
COPY cpa_first ./cpa_first
COPY data/seeds ./data/seeds
COPY data/schemas ./data/schemas
COPY prototype ./prototype
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY pyproject.toml ./pyproject.toml
COPY scripts/docker-entrypoint.sh ./scripts/docker-entrypoint.sh

# Make the entrypoint executable, then keep ALL code/assets root-owned and
# read-only to the runtime user (defense in depth: a path-traversal / upload
# bug cannot rewrite cpa_first/, alembic/, or prototype/ at runtime).
# Only data/runtime needs to be writable by the app user.
RUN chmod +x ./scripts/docker-entrypoint.sh \
    && mkdir -p /app/data/runtime \
    && chown -R root:root /app \
    && chown -R app:app /app/data/runtime \
    && chmod -R o-w /app

# Verify gunicorn + the uvicorn worker class are importable at build time.
# Fails the build early if deps are missing, rather than at container start.
RUN python -c "import gunicorn, uvicorn; from uvicorn.workers import UvicornWorker; print('gunicorn', gunicorn.__version__, '/ uvicorn', uvicorn.__version__)"

USER app

EXPOSE 8000

# Entrypoint runs `alembic upgrade head` (Postgres only) then execs gunicorn.
CMD ["./scripts/docker-entrypoint.sh"]

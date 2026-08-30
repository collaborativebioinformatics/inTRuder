# syntax=docker/dockerfile:1

# inTRuder backend — FastAPI + LangGraph + DuckDB.
#
#   docker compose up backend                                  # from the repo root
#   docker build -f docker/backend.Dockerfile -t intruder-backend .
#
# The build context is the REPOSITORY ROOT, not backend/, so that one
# .dockerignore governs both images. Nothing under data/ is copied in: the
# dataset registry is bind-mounted at runtime, which is what lets someone drop
# in their own callset without rebuilding. See docker/README.md.

ARG PYTHON_VERSION=3.13
ARG UV_VERSION=0.9

# Who the service runs as. Uploads are written into the bind-mounted ./data, so
# on Linux — where bind-mount ownership is NOT virtualized the way it is under
# Docker Desktop — the container user has to be one that can write your data
# directory:
#
#   docker compose build --build-arg UID=$(id -u) --build-arg GID=$(id -g) backend
ARG UID=10001
ARG GID=10001


# --------------------------------------------------------------------------- #
# Builder — resolve the locked dependency set into a self-contained venv.
# --------------------------------------------------------------------------- #
FROM ghcr.io/astral-sh/uv:${UV_VERSION}-python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Only the lockfile and the project metadata, so this layer is cached across
# every source edit. `package = false` in backend/pyproject.toml means the
# project itself is never built — only its dependencies are installed.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project


# --------------------------------------------------------------------------- #
# Runtime — the venv plus the application source, nothing else.
# --------------------------------------------------------------------------- #
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    INTRUDER_DATA_DIR=/data \
    INTRUDER_REGISTRY_DIR=/data/web

# Unprivileged: agent-authored SQL runs in this process. The DuckDB connection
# is already read-only with external access disabled (app/registry.py), and a
# non-root user is the second layer of that.
ARG UID
ARG GID
RUN groupadd --gid ${GID} intruder 2>/dev/null || true \
 && useradd --create-home --uid ${UID} --gid ${GID} intruder

WORKDIR /app

COPY --from=builder --chown=intruder:intruder /app/.venv ./.venv
COPY --chown=intruder:intruder backend/app ./app
COPY --chown=intruder:intruder backend/scripts ./scripts

# The registry materializes every dataset into a DuckDB file under .cache at
# startup, so this has to be writable by the unprivileged user.
RUN install -d -o intruder -g intruder /app/.cache /data /data/uploads

USER intruder
EXPOSE 8000

# /api/health reports which datasets loaded and whether a model credential is
# present; the frontend waits on this before starting.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

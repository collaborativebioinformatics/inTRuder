# novelTRs task runner.  `just` with no arguments lists everything.
#
# The backend and the repository root are two INDEPENDENT uv projects: the root
# manages the research pipeline under src/python, backend/ manages the web
# service. They do not share a lockfile or an environment.

default:
    @just --list

# One-time setup for the whole repo.
setup: setup-pipeline setup-backend setup-frontend
    @echo ""
    @echo "Ready. Add a model credential to backend/.env, then run: just dev"

setup-pipeline:
    uv sync

setup-backend:
    cd backend && uv sync
    cd backend && test -f .env || cp .env.example .env
    cd backend && uv run python scripts/make_demo_data.py

setup-frontend:
    cd frontend && npm install
    cd frontend && test -f .env.local || cp .env.local.example .env.local

# Run backend and frontend together.
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT
    (cd backend && uv run uvicorn app.main:app --reload --port 8000) &
    (cd frontend && npm run dev) &
    wait

backend:
    cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend:
    cd frontend && npm run dev

# Regenerate the synthetic demo dataset in data/web/demo.
demo-data:
    cd backend && uv run python scripts/make_demo_data.py

lint:
    cd backend && uv run ruff check app scripts
    cd frontend && npx tsc --noEmit

build:
    cd frontend && npm run build

test:
    cd backend && uv run pytest

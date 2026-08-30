# inTRuder task runner.  `just` with no arguments lists everything.
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

# Fetch the STRchive disease-locus catalog into data/web/strchive.
strchive-data:
    cd backend && uv run python scripts/fetch_strchive.py

# Cache data/plots/*.tsv as parquet in data/plots/parquet. Needed by web-data,
# and worth it on its own: 05_hprc_multisample.tsv is 586 MB of text.
plot-parquet *args:
    cd backend && uv run python scripts/plots_to_parquet.py {{args}}

# Rebuild the real loci/segments tables from the gene-annotated callsets.
# Needs `just plot-data && just plot-parquet` first, and `just strchive-data`
# or the strchive_* columns come out empty. Pass a cohort to build just one.
web-data *cohorts:
    cd backend && uv run python scripts/build_web_tables.py {{cohorts}}

# Download the shared Drive tables (750 MiB) into data/plots. `--list` first to
# see what is missing; `--only 02_` for just the novelty-filtered pair.
plot-data *args:
    scripts/fetch_plot_data.sh {{args}}

# Rent a DNAnexus box, work on it, terminate on exit. See docs/scripts/DNANexus.md.
dx-terminal time="1h":
    scripts/dnanexus/dx-instance-cpu.sh --time {{time}}

# The same on a GPU box (1x L4). Costs several times as much per hour.
dx-terminal-gpu time="1h":
    scripts/dnanexus/dx-instance-gpu.sh --time {{time}}

# Run a program on a CPU box, fetch $OUT, terminate -- nothing left billing.
dx-run command time="2h":
    scripts/dnanexus/dx-batch-cpu.sh --time {{time}} -- {{command}}

# The same on a GPU box.
dx-run-gpu command time="2h":
    scripts/dnanexus/dx-batch-gpu.sh --time {{time}} -- {{command}}

# What this project can launch, and what each type is for. Filter: `... gpu`.
dx-instances pattern="":
    scripts/dnanexus/dx-instance.sh --list-instances {{pattern}}

# Everything CI runs, in the same order. Run this before pushing.
check: lint test

lint:
    uv run ruff check src/python tests/python
    cd backend && uv run ruff check app scripts
    cd frontend && npx tsc --noEmit

build:
    cd frontend && npm run build

test:
    uv run pytest -q
    cd backend && uv run pytest -q

#!/usr/bin/env bash
# Build this project's environment on a fresh DNAnexus worker (or any bare
# Ubuntu box). Idempotent -- safe to re-run.
#
#     uv run dx ssh "$JOB" -T "bash -s" < scripts/setup-worker.sh
#     BRANCH=main REPO_DIR=. bash scripts/setup-worker.sh   # a checkout you have
#
# `scripts/dx-instance.sh` runs this for you, over stdin, before your command.
# It installs uv, clones the branch from GitHub -- nothing on a workstation
# survives the session, and the box has no copy of your laptop -- and syncs the
# locked environment into .venv.
#
# Pass extras and groups through SYNC_ARGS:
#
#     SYNC_ARGS="--group dx" bash scripts/setup-worker.sh
#
# Afterwards call `.venv/bin/...` directly rather than `uv run`: `uv run`
# resyncs to uv.lock first, which removes anything you installed on top of it.
set -uo pipefail

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "[$(date +%H:%M:%S)] FATAL: $*" >&2; exit 1; }

BRANCH="${BRANCH:-main}"
REPO_URL="${REPO_URL:-https://github.com/collaborativebioinformatics/novelTRs.git}"
REPO_DIR="${REPO_DIR:-$HOME/novelTRs}"
SYNC_ARGS="${SYNC_ARGS:-}"

# --- uv -----------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    log "installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || die "uv install failed"
fi
# The installer puts uv in ~/.local/bin, which a non-interactive shell does not
# have on PATH yet -- it writes an env file for exactly this.
# shellcheck disable=SC1091
. "$HOME/.local/bin/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null 2>&1 || die "uv still not on PATH"
log "uv $(uv --version)"

# --- checkout -----------------------------------------------------------
if [ ! -d "$REPO_DIR/.git" ]; then
    log "cloning $BRANCH into $REPO_DIR"
    git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$REPO_DIR" >/dev/null 2>&1 \
        || die "clone failed (is $BRANCH pushed to $REPO_URL?)"
fi
cd "$REPO_DIR" || die "no $REPO_DIR"
log "at $(git log --oneline -1)"

# --- dependencies -------------------------------------------------------
# uv fetches the interpreter named in .python-version itself, so the box's own
# python does not matter. Every locked dependency has a manylinux wheel, so this
# needs no compiler -- and these workers have none.
log "uv sync ${SYNC_ARGS:-(default groups)}"
# shellcheck disable=SC2086
uv sync $SYNC_ARGS 2>&1 | tail -3 || die "uv sync failed"

PY=.venv/bin/python
[ -x "$PY" ] || die "no $PY after sync"
"$PY" -c 'import novelty' 2>/dev/null || die "the project did not import after sync"

cat <<EOF

[$(date +%H:%M:%S)] === READY ===

  $("$PY" --version) at $REPO_DIR/.venv

  Use the venv binaries, NOT 'uv run' -- it resyncs to uv.lock and undoes
  anything you installed on top of it:

    cd $REPO_DIR
    .venv/bin/novelty --help
    .venv/bin/python -m pytest -q

  Nothing here survives the session: 'dx upload' anything you want to keep, or
  leave it in \$OUT and dx-instance.sh fetches it for you.
EOF

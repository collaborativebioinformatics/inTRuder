#!/usr/bin/env bash
# Build this project's environment on a fresh DNAnexus worker (or any bare
# Ubuntu box). Idempotent -- safe to re-run.
#
#     uv run dx ssh "$JOB" -T "bash -s" < scripts/dnanexus/dx-worker-setup.sh
#     BRANCH=main REPO_DIR=. bash scripts/dnanexus/dx-worker-setup.sh
#         # ... against a checkout you already have
#
# `scripts/dnanexus/dx-instance.sh` runs this for you, over stdin, before your
# command. It installs uv, clones the branch from GitHub -- nothing on a
# workstation survives the session, and the box has no copy of your laptop --
# and syncs the locked environment into .venv.
#
# Everything is configured by environment variable, because that is all that
# survives `dx ssh JOB -T "... bash -s" < this-file`: there is no argv on the
# far side of that pipe, stdin is already the script.
#
#     BRANCH      branch to check out                          [main]
#     REPO_URL    where to clone it from                        [novelTRs]
#     REPO_DIR    where to put it                               [$HOME/novelTRs]
#     SYNC_ARGS   extra flags for `uv sync`, e.g. "--group dx"  [none]
#
# Every one of them is validated below and echoed back before any work starts,
# and the READY banner reports what was actually built. The driver has no other
# way to tell a worker that quietly ignored it from one that obeyed.
#
# Afterwards call `.venv/bin/...` directly rather than `uv run`: `uv run`
# resyncs to uv.lock first, which removes anything you installed on top of it.
set -uo pipefail

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "[$(date +%H:%M:%S)] FATAL: $*" >&2; exit 1; }

# `-` rather than `:-` throughout: unset means "nobody told us, take the
# default", but set-and-empty means the driver did try to tell us and the value
# was lost on the way. Collapsing those two to the same default would hide the
# one failure the checks below exist to catch.
BRANCH="${BRANCH-main}"
REPO_URL="${REPO_URL-https://github.com/collaborativebioinformatics/novelTRs.git}"
REPO_DIR="${REPO_DIR-$HOME/novelTRs}"
SYNC_ARGS="${SYNC_ARGS-}"

# --- what did we actually receive? --------------------------------------
# The driver interpolates these into a remote command string, so a mangled
# handoff arrives as a plausible-looking wrong value rather than as an error:
# an empty BRANCH clones the default branch, a REPO_DIR that lost half its
# quoting becomes a directory named after the first word. Both then fail much
# later, on the far side of a boot nobody wants to pay for twice. Check the
# shapes here, where the message can still say which variable was wrong.
log "received:"
log "  BRANCH    ${BRANCH:-(empty)}"
log "  REPO_URL  ${REPO_URL:-(empty)}"
log "  REPO_DIR  ${REPO_DIR:-(empty)}"
log "  SYNC_ARGS ${SYNC_ARGS:-(none)}"

[ -n "$BRANCH" ] || die "BRANCH is empty. The driver did not pass it through."
[ -n "$REPO_URL" ] || die "REPO_URL is empty. The driver did not pass it through."
[ -n "$REPO_DIR" ] || die "REPO_DIR is empty. The driver did not pass it through."
# A branch name cannot contain whitespace; if one arrived with any, the quoting
# broke in transit and $BRANCH now holds a fragment of the next variable.
case "$BRANCH" in
    *[[:space:]]*) die "BRANCH '$BRANCH' contains whitespace -- the handoff was mangled." ;;
esac
case "$REPO_DIR" in
    *[[:space:]]*) die "REPO_DIR '$REPO_DIR' contains whitespace -- the handoff was mangled." ;;
esac
case "$REPO_URL" in
    http://*|https://*|git@*|ssh://*|/*|.|./*) ;;
    *) die "REPO_URL '$REPO_URL' is not a URL or a path -- the handoff was mangled." ;;
esac

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
log "$(uv --version)"

# --- checkout -----------------------------------------------------------
# The interesting case is the second run. A workstation you have attached to
# twice, or any `--job` re-attach, already has a checkout -- and the old code
# here stopped at `cd`, so it silently ran whatever branch happened to be on
# disk. Asking for `--branch fix-x` and getting `main` is the one failure this
# script must never produce: it is invisible, and every result it goes on to
# compute is quietly attributed to the wrong commit. So an existing checkout is
# MADE to match the request rather than trusted to already.
if [ ! -d "$REPO_DIR/.git" ]; then
    log "cloning $BRANCH from $REPO_URL into $REPO_DIR"
    git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$REPO_DIR" >/dev/null 2>&1 \
        || die "clone of '$BRANCH' failed (is it pushed to $REPO_URL?)"
    cd "$REPO_DIR" || die "no $REPO_DIR"
else
    cd "$REPO_DIR" || die "no $REPO_DIR"
    have_url="$(git remote get-url origin 2>/dev/null)"
    if [ "$have_url" != "$REPO_URL" ]; then
        # A different repo entirely under the directory we were told to use.
        # Repointing someone else's checkout is not ours to do.
        die "$REPO_DIR already holds a clone of '$have_url', not '$REPO_URL'.
       Pass a different REPO_DIR, or remove that directory on the worker."
    fi
    log "existing checkout in $REPO_DIR; making it match '$BRANCH'"
    # --depth 1 above means the branch we now want may not be in this clone at
    # all, so fetch it by name and check out the FETCH_HEAD it produced.
    git fetch --depth 1 origin "$BRANCH" >/dev/null 2>&1 \
        || die "could not fetch '$BRANCH' from $REPO_URL"
    git checkout -q -B "$BRANCH" FETCH_HEAD \
        || die "could not check out '$BRANCH'"
fi

# The branch was asked for by name; report the commit it resolved to, because
# that is the thing a result is actually attributable to.
HEAD_SHA="$(git rev-parse --short HEAD 2>/dev/null)"
HEAD_REF="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
log "at $HEAD_SHA on ${HEAD_REF} -- $(git log --oneline -1)"
# `git checkout -B` above cannot leave us anywhere else, and a fresh clone is
# on the branch it asked for, so a mismatch here means git did something we do
# not understand -- worth saying out loud rather than proceeding.
if [ "$HEAD_REF" != "$BRANCH" ] && [ "$HEAD_REF" != "HEAD" ]; then
    die "checked out '$HEAD_REF' but '$BRANCH' was requested."
fi

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

# If extra groups were asked for, say whether they arrived. `uv sync --group dx`
# that silently no-ops leaves an import error an hour into the run.
if [ -n "$SYNC_ARGS" ]; then
    log "synced with: $SYNC_ARGS"
    case "$SYNC_ARGS" in
        *"--group dx"*|*"--all-groups"*)
            if "$PY" -c 'import dxpy' 2>/dev/null; then
                log "  dxpy importable"
            else
                log "  WARNING: dxpy still not importable after '$SYNC_ARGS'"
            fi ;;
    esac
fi

cat <<EOF

[$(date +%H:%M:%S)] === READY ===

  $("$PY" --version) at $REPO_DIR/.venv
  $HEAD_SHA on $BRANCH from $REPO_URL
  uv sync ${SYNC_ARGS:-(default groups)}

  Use the venv binaries, NOT 'uv run' -- it resyncs to uv.lock and undoes
  anything you installed on top of it:

    cd $REPO_DIR
    .venv/bin/novelty --help
    .venv/bin/python -m pytest -q

  Nothing here survives the session: 'dx upload' anything you want to keep, or
  leave it in \$OUT and dx-instance.sh fetches it for you.
EOF

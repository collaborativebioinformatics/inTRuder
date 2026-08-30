#!/usr/bin/env bash
# Set up Evo 2 extraction on a fresh GPU worker (DNAnexus cloud_workstation or
# any bare CUDA box). Idempotent -- safe to re-run.
#
#     bash scripts/setup-gpu-worker.sh            # clone into $HOME and set up
#     REPO_DIR=. bash scripts/setup-gpu-worker.sh # set up a checkout you have
#
# Four things here are not obvious, and each one cost a debugging round trip on
# 2026-08-27. See docs/DNANexus.md "Running Evo 2 on a worker".
#
#   1. Python 3.12, not the repo's pinned 3.13. `evo2` caps itself below 3.13,
#      so uv.lock gates it on `python_full_version < '3.13'` -- a 3.13 sync
#      succeeds and silently omits evo2.
#   2. flash-attn is REQUIRED, not optional. vortex imports `flash_attn_2_cuda`
#      at module import time, so `import evo2` raises without it.
#   3. It must be installed AFTER the sync, from a PREBUILT wheel. The wheel is
#      specific to (python, torch, cuda, cxx11-abi), so torch has to exist first
#      to choose it -- and DNAnexus GPU workers ship no `nvcc`, so the
#      `--no-build-isolation` source build cannot work at all.
#   4. Afterwards, invoke the venv directly (`.venv/bin/evo-embed`). flash-attn
#      is not in uv.lock, so any `uv run`/`uv sync` resyncs to the lock and
#      uninstalls it. `uv run` with no extras is worse: it removes torch too.
set -uo pipefail

log() { echo "[$(date +%H:%M:%S)] $*"; }
die() { echo "[$(date +%H:%M:%S)] FATAL: $*" >&2; exit 1; }

BRANCH="${BRANCH:-feature/evo-embeds}"
REPO_URL="${REPO_URL:-https://github.com/collaborativebioinformatics/novelTRs.git}"
REPO_DIR="${REPO_DIR:-$HOME/novelTRs}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
TORCH_EXTRA="${TORCH_EXTRA:-cu128}"
FA_VERSION="${FA_VERSION:-2.8.3.post1}"

# --- uv -----------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    log "installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || die "uv install failed"
fi
# shellcheck disable=SC1091
. "$HOME/.local/bin/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null 2>&1 || die "uv still not on PATH"
log "uv $(uv --version)"

# --- checkout -----------------------------------------------------------
if [ ! -d "$REPO_DIR/.git" ]; then
    log "cloning $BRANCH into $REPO_DIR"
    git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$REPO_DIR" >/dev/null 2>&1 \
        || die "clone failed (is $BRANCH pushed?)"
fi
cd "$REPO_DIR" || die "no $REPO_DIR"
log "at $(git log --oneline -1)"

# --- dependencies -------------------------------------------------------
EXTRAS=(--extra "$TORCH_EXTRA" --extra embed)
log "uv sync (python $PYTHON_VERSION, $TORCH_EXTRA + embed)"
uv sync --python "$PYTHON_VERSION" "${EXTRAS[@]}" 2>&1 | tail -3 \
    || die "uv sync failed"

PY=.venv/bin/python
[ -x "$PY" ] || die "no $PY after sync"

# evo2 present? If the sync resolved on 3.13 it will not be.
"$PY" -c 'import vortex' 2>/dev/null \
    || die "vortex missing after sync -- did it resolve on Python >=3.13?"

# --- flash-attn ---------------------------------------------------------
# Chosen from the interpreter that will actually run it, never hardcoded: the
# wheel must match python tag, torch major.minor and the C++11 ABI exactly.
read -r PYTAG TORCH_MM ABI < <("$PY" - <<'PY'
import sys, torch
mm = ".".join(torch.__version__.split("+")[0].split(".")[:2])
abi = "TRUE" if torch._C._GLIBCXX_USE_CXX11_ABI else "FALSE"
print(f"cp{sys.version_info.major}{sys.version_info.minor}", mm, abi)
PY
) || die "could not probe torch"
log "target: $PYTAG / torch $TORCH_MM / cxx11abi $ABI"

if "$PY" -c 'import flash_attn' 2>/dev/null; then
    log "flash-attn already present ($("$PY" -c 'import flash_attn;print(flash_attn.__version__)'))"
else
    WHEEL="flash_attn-${FA_VERSION}+cu12torch${TORCH_MM}cxx11abi${ABI}-${PYTAG}-${PYTAG}-linux_x86_64.whl"
    URL="https://github.com/Dao-AILab/flash-attention/releases/download/v${FA_VERSION}/${WHEEL}"
    log "installing prebuilt $WHEEL"
    uv pip install "$URL" 2>&1 | tail -2 || die "flash-attn install failed: $URL"
fi

# --- verify -------------------------------------------------------------
log "verifying (via $PY -- deliberately not 'uv run')"
"$PY" - <<'PY' || die "verification failed"
import torch, flash_attn, vortex, evo2
from evo2 import Evo2
assert torch.cuda.is_available(), "CUDA not available"
cc = torch.cuda.get_device_capability(0)
assert cc >= (8, 0), f"compute capability {cc} is below flash-attn's sm_80 floor"
print(f"  torch      {torch.__version__}")
print(f"  gpu        {torch.cuda.get_device_name(0)}  sm_{cc[0]}{cc[1]}")
print(f"  flash_attn {flash_attn.__version__}")
print(f"  evo2       ok")
PY

cat <<EOF

[$(date +%H:%M:%S)] === READY ===

  Run extraction with the venv binaries, NOT 'uv run':

    cd $REPO_DIR
    .venv/bin/python -m evo.embeddings <calls.vcf> <hg38.fasta> out/  # both alleles
    .venv/bin/evo-embed <calls.vcf> <hg38.fasta> out.npz              # one allele

  scripts/dx-gpu-instance.sh runs this script for you, then the command, then
  fetches the results and terminates the box.

  'uv run' resyncs to uv.lock and uninstalls flash-attn; with no extras it
  removes torch as well. If that happens, re-run this script -- it is idempotent.
EOF

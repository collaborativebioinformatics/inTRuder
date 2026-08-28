#!/usr/bin/env bash
# Run one program on a DNAnexus GPU box and come straight back. Sets the
# machine up, runs what you asked for, saves the results, and terminates the
# box -- no shell, nobody attached, nothing left billing.
#
#     scripts/dx-batch-gpu.sh -- nvidia-smi
#     scripts/dx-batch-gpu.sh -t 6h -o data/dx/evo2 -- \
#         .venv/bin/python src/python/evo2_extract.py --out '$OUT'
#
# Everything after `--` is the program. It runs in the checkout with the venv
# first on PATH, so `novelty` and `python -m ...` resolve there.
#
# Write results to $OUT. Anything left there is uploaded to the project and
# then downloaded to --output-dir (data/dx/<run> by default); nothing else on
# the worker survives. Quote it as '$OUT' so your own shell leaves it alone.
#
# The box is mem2_ssd2_gpu1_v2_x8 -- one L4 with 24 GB, 8 cores -- unless you
# pass -i or set DX_GPU_INSTANCE. This is the expensive one: it bills for
# wall-clock time whether or not the GPU is busy, which is the whole reason to
# run unattended rather than leaving a terminal open. Have the program print
# nvidia-smi first if it needs to prove the card was there.
#
# --time is not a budget, it is the dead-man's switch: the box normally dies as
# soon as the program is done, and --time is what kills it if this script is
# itself killed. Set it above the run's worst case.
#
# A command is required, and --shell and --keep are refused: both would leave
# you attached to, or paying for, a box this script promises to shut down. For
# a terminal, use scripts/dx-instance-gpu.sh.
DX_WRAP_MODE="batch"
DX_WRAP_ARCH="gpu"
# shellcheck source=scripts/dx-wrapper.sh
. "$(dirname "${BASH_SOURCE[0]:-$0}")/dx-wrapper.sh"

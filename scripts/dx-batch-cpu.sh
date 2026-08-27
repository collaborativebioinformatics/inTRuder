#!/usr/bin/env bash
# Run one program on a DNAnexus CPU box and come straight back. Sets the
# machine up, runs what you asked for, saves the results, and terminates the
# box -- no shell, nobody attached, nothing left billing.
#
#     scripts/dx-batch-cpu.sh -- .venv/bin/python -m pytest -q
#     scripts/dx-batch-cpu.sh -t 4h -o data/dx/screen1 \
#         -f /survivor/HPRC_SV.survivor.vcf -- \
#         novelty screen /home/dnanexus/HPRC_SV.survivor.vcf '$OUT/hits.tsv'
#
# Everything after `--` is the program. It runs in the checkout with the venv
# first on PATH, so `novelty` and `python -m ...` resolve there.
#
# Write results to $OUT. Anything left there is uploaded to the project and
# then downloaded to --output-dir (data/dx/<run> by default); nothing else on
# the worker survives. Quote it as '$OUT' so your own shell leaves it alone.
#
# The box is mem1_ssd1_v2_x4 (4 cores, ~8 GB) unless you pass -i or set
# DX_INSTANCE. --time is not a budget, it is the dead-man's switch: the box
# normally dies as soon as the program is done, and --time is what kills it if
# this script is itself killed. Set it above the run's worst case.
#
# A command is required, and --shell and --keep are refused: both would leave
# you attached to, or paying for, a box this script promises to shut down. For
# a terminal, use scripts/dx-instance-cpu.sh.
DX_WRAP_MODE="batch"
DX_WRAP_ARCH="cpu"
# shellcheck source=scripts/dx-wrapper.sh
. "$(dirname "${BASH_SOURCE[0]:-$0}")/dx-wrapper.sh"

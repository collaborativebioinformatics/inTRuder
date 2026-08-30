#!/usr/bin/env bash
# A terminal on a DNAnexus CPU box. Sets the machine up, drops you into a shell
# on it, brings back anything you left in $OUT, and terminates it when you exit.
#
#     scripts/dnanexus/dx-instance-cpu.sh                    # a shell, for 2h at most
#     scripts/dnanexus/dx-instance-cpu.sh --time 30m
#     scripts/dnanexus/dx-instance-cpu.sh -f /survivor/HPRC_SV.survivor.vcf
#
# The box is mem1_ssd1_v2_x4 (4 cores, ~8 GB) unless you pass -i or set
# DX_INSTANCE. The repo is cloned to /home/dnanexus/inTRuder with its venv
# built; use .venv/bin/... there, never `uv run`.
#
# This one takes no command -- it is the interactive half of the pair. To run a
# program and come straight back, use scripts/dnanexus/dx-batch-cpu.sh.
#
# Exiting the shell TERMINATES the box and stops the billing. Answer `n` to
# dx's own "Terminate now?" prompt on the way out; the script does that itself,
# and confirms the state afterwards.
DX_WRAP_MODE="interactive"
DX_WRAP_ARCH="cpu"
# shellcheck source=scripts/dnanexus/dx-wrapper.sh
. "$(dirname "${BASH_SOURCE[0]:-$0}")/dx-wrapper.sh"

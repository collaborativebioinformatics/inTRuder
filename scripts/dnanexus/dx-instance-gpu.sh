#!/usr/bin/env bash
# A terminal on a DNAnexus GPU box. Sets the machine up, drops you into a shell
# on it, brings back anything you left in $OUT, and terminates it when you exit.
#
#     scripts/dnanexus/dx-instance-gpu.sh                    # a shell, for 2h at most
#     scripts/dnanexus/dx-instance-gpu.sh --time 4h
#     scripts/dnanexus/dx-instance-gpu.sh --sync-args "--group dx"
#
# The box is mem2_ssd2_gpu1_v2_x8 -- one L4 with 24 GB, 8 cores -- unless you
# pass -i or set DX_GPU_INSTANCE. It is one of only two GPU types this project
# can actually launch; `scripts/dnanexus/dx-instance.sh --list-instances gpu` is the
# live list. Check the card is there with nvidia-smi before you trust a run.
#
# A GPU box costs several times what the CPU one does per hour and bills for
# wall-clock time whether or not the GPU is busy, so --time matters more here.
#
# This one takes no command -- it is the interactive half of the pair. To run a
# program and come straight back, use scripts/dnanexus/dx-batch-gpu.sh.
#
# Exiting the shell TERMINATES the box and stops the billing. Answer `n` to
# dx's own "Terminate now?" prompt on the way out; the script does that itself,
# and confirms the state afterwards.
DX_WRAP_MODE="interactive"
DX_WRAP_ARCH="gpu"
# shellcheck source=scripts/dnanexus/dx-wrapper.sh
. "$(dirname "${BASH_SOURCE[0]:-$0}")/dx-wrapper.sh"

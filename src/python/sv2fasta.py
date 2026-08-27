#! /usr/bin/env python3

# Usage: python sv2fasta.py <input.vcf> <output.fa>
# Usage with merged SV: python sv2fasta.py HPRC_SV.survivor.ins.vcf HPRC_SV.survivor.ins.fa
# Usage with example merged SV: python sv2fasta.py .././data/sv_output/survivor_multisample_vcf/first_500_INS.vcf ./data/sv_output/survivor_multisample_vcf/first_500_INS.fa

import sys
import os

import pytrf
import parasail

from cyvcf2 import VCF
from tqdm   import tqdm
from contextlib import contextmanager

import numpy as np

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

matrix = parasail.matrix_create("ACGT", 2, -1)

vcf     = VCF(sys.argv[1])
out     = open(sys.argv[2], 'w')
samples = vcf.samples

sv_repeats = {}

@contextmanager
def suppress_pysam_output():
    # Save original file descriptors
    original_stdout_fd = sys.stdout.fileno()
    original_stderr_fd = sys.stderr.fileno()

    # Duplicate original file descriptors so they can be restored later
    save_stdout_fd = os.dup(original_stdout_fd)
    save_stderr_fd = os.dup(original_stderr_fd)

    # Open devnull
    devnull_fd = os.open(os.devnull, os.O_WRONLY)

    # Flush standard Python buffers
    sys.stdout.flush()
    sys.stderr.flush()

    # Overwrite original descriptors with devnull
    os.dup2(devnull_fd, original_stdout_fd)
    os.dup2(devnull_fd, original_stderr_fd)

    # Close the extra devnull handle
    os.close(devnull_fd)

    try:
        yield
    finally:
        # Flush again before restoring
        sys.stdout.flush()
        sys.stderr.flush()

        # Restore original descriptors
        os.dup2(save_stdout_fd, original_stdout_fd)
        os.dup2(save_stderr_fd, original_stderr_fd)

        # Close duplicated handles
        os.close(save_stdout_fd)
        os.close(save_stderr_fd)


for variant in tqdm(vcf, ncols=80, smoothing=0.1, unit='variants'):
    if variant.is_sv and variant.INFO.get("SVTYPE") == "INS":
        ID  = variant.format('ID')
        RAL = variant.format('RAL')
        AAL = variant.format('AAL')
        DR    = variant.format('DR')
        LEN   = variant.format('LN')

        for s, sample in enumerate(samples):
            if ID[s] == 'NaN': continue
            depth = DR[s][0]
            insert_size = LEN[s][0] if (type(LEN[s]) == list or type(LEN[s]) == np.ndarray) else LEN[s]
            ALT = AAL[s][len(RAL):]
            if ALT is None or ALT == '': continue
            print(f'>{ID[s]}_{sample}_{variant.CHROM}_{variant.POS}_{depth}_{len(ALT)}', file=out)
            print(ALT, file=out)

out.close()
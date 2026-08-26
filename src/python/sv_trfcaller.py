#! /usr/bin/env python3

# Usage: python sv_trfcaller.py <input.vcf> <output.tsv>
# Usage with merged SV: python sv_trfcaller.py HPRC_SV.survivor.ins.vcf HPRC_SV.survivor.ins.trf.tsv
# Usage with example merged SV: python sv_trfcaller.py ./data/sv_output/survivor_multisample_vcf/first_500_INS.vcf ./data/sv_output/survivor_multisample_vcf/first_500_INS.trf.tsv

import sys
import os

import pytrf
import parasail

from cyvcf2 import VCF
from tqdm   import tqdm
from contextlib import contextmanager

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

matrix = parasail.matrix_create("ACGT", 2, -1)

vcf     = VCF(sys.argv[1])
out     = open(sys.argv[2], 'w')
print('sample', 'SVID', 'rep_start', 'rep_end', 'motif', 'purity', 'motif_length', 'rep_length', 'rep_units', sep='\t', file=out)
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

        for s, sample in enumerate(samples):
            if ID[s] == 'NaN': continue
            ALT = AAL[s][len(RAL):]

            n_trf = 0
            trf_repeats    = []

            with suppress_pysam_output():
                for repeat in pytrf.ATRFinder(sample, ALT, min_motif=1, max_motif=100, min_identity=0.8):
                    repeat    = repeat.as_string().split('\t')
                    rep_start = int(repeat[1]) - 1
                    rep_end   = int(repeat[2])
                    motif     = repeat[3]
                    motif_length = len(motif)

                    rep_length = rep_end - rep_start
                    rep_units  = rep_length // motif_length + 2
                    query      = motif*(rep_units)

                    result = parasail.sg_trace_scan_16(ALT[rep_start:rep_end], query, 5, 1, matrix)

                    cigar_bytes  = result.cigar.decode
                    cigar_str    = cigar_bytes.decode()
                    cigar_simple = cigar_str.replace('=', 'M')
                    purity       = float(repeat[15])/100

                    trf_repeats.append([sample, ID[s], rep_start, rep_end, motif, round(purity, 3), motif_length, rep_length, rep_units])
                    n_trf += 1

            for rep in trf_repeats:
                print(*rep, sep='\t', file=out)

out.close()

#!/usr/bin/env python3

# Usage: python sv_trfcaller.py <input.vcf> <output.tsv>
# Usage with merged SV: python sv_trfcaller.py HPRC_SV.survivor.ins.vcf HPRC_SV.survivor.ins.trf.tsv
# Usage with example merged SV: python sv_trfcaller.py ../../data/sv_output/survivor_multisample_vcf/first_500_INS.vcf ../../data/sv_output/survivor_multisample_vcf/first_500_INS.trf.tsv

import os
import sys
from contextlib import contextmanager

import parasail
import pytrf
from cyvcf2 import VCF
from tqdm import tqdm

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

matrix = parasail.matrix_create("ACGT", 2, -1)


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


def main():
    with VCF(sys.argv[1]) as vcf, open(sys.argv[2], "w") as out:
        print(
            "chrom",
            "ins_coord",
            "SVID",
            "depth",
            "insert_size",
            "sample",
            "rep_start",
            "rep_end",
            "motif",
            "purity",
            "motif_length",
            "rep_length",
            "rep_units",
            sep="\t",
            file=out,
        )
        samples = vcf.samples

        for variant in tqdm(vcf, ncols=80, smoothing=0.1, unit="variants"):
            if variant.is_sv and variant.INFO.get("SVTYPE") == "INS":
                ID = variant.format("ID")
                RAL = variant.format("RAL")
                AAL = variant.format("AAL")
                DR = variant.format("DR")
                LEN = variant.format("LN")

                for s, sample in enumerate(samples):
                    if ID[s] == "NaN":
                        continue
                    ALT = AAL[s][len(RAL) :]
                    depth = DR[s]
                    insert_size = LEN[s]

                    trf_repeats = []

                    with suppress_pysam_output():
                        for repeat in pytrf.ATRFinder(
                            sample,
                            ALT,
                            min_motif=1,
                            max_motif=100,
                            min_identity=0.8,
                        ):
                            repeat = repeat.as_string().split("\t")
                            rep_start = int(repeat[1]) - 1
                            rep_end = int(repeat[2])
                            motif = repeat[3]
                            motif_length = len(motif)

                            rep_length = rep_end - rep_start
                            # How many copies of the motif the repeat actually spans --
                            # this is a reported column, and `novelty --min-rep-units`
                            # thresholds on it.
                            rep_units = rep_length // motif_length
                            # The alignment target is padded by two extra copies so a
                            # semi-global alignment has somewhere to run off the end;
                            # that padding must not leak into the reported copy number.
                            query = motif * (rep_units + 2)

                            parasail.sg_trace_scan_16(
                                ALT[rep_start:rep_end], query, 5, 1, matrix
                            )

                            purity = float(repeat[15]) / 100

                            trf_repeats.append([
                                variant.CHROM,
                                variant.POS,
                                ID[s],
                                depth,
                                insert_size,
                                sample,
                                rep_start,
                                rep_end,
                                motif,
                                round(purity, 3),
                                motif_length,
                                rep_length,
                                rep_units,
                            ])

                    for rep in trf_repeats:
                        print(*rep, sep="\t", file=out)


if __name__ == "__main__":
    main()
